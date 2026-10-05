# SPDX-License-Identifier: Apache-2.0
"""Ed25519 key generation, signing, and verification — stdlib only.

Python's standard library has no Ed25519, so this module vendors a compact
pure-Python implementation of the Ed25519 algorithm as specified in
RFC 8032 (Edwards-Curve Digital Signature Algorithm).

Attribution: the field/point arithmetic below follows the classic compact
public-domain reference implementation of Ed25519 (the widely-copied
"ed25519.py" in the style of Daniel J. Bernstein's reference code, as
popularized by Frank Braun's public-domain version). The algorithm is
implemented directly from RFC 8032 section 5.1. Correctness is
established by the RFC 8032 section 7.1 test vectors in
tests/test_crypto.py, cross-checked against PyNaCl (libsodium) during
development.

Swap point: the public surface of this module is only
    generate_keypair() -> (private_key_hex, public_key_hex)
    public_key_from_private(private_key_hex) -> public_key_hex
    sign(private_key_hex, message: bytes) -> signature bytes (64)
    verify(public_key_hex, message: bytes, signature: bytes) -> bool
A future backend using libsodium or the `cryptography` package can replace
everything below the "Public interface" marker as long as it keeps those
four functions and their exact semantics (keys as lowercase hex strings,
private key = 32-byte seed, signature = 64 bytes).

Security notes:
  * Key generation uses os.urandom.
  * verify() is written to avoid secret-dependent branches on attacker
    controlled data where cheap to do so; this is a reference
    implementation, not a hardened constant-time build. For production
    deployments handling high-value keys, swap in libsodium.
  * Signatures are deterministic per RFC 8032 (no per-signature randomness
    needed, which removes a whole class of RNG-failure bugs).
"""

import hashlib
import os

# ---------------------------------------------------------------------------
# Curve parameters (RFC 8032, section 5.1)
# ---------------------------------------------------------------------------

_B = 256                      # bits per field element encoding
_Q = 2 ** 255 - 19            # the prime defining GF(q)


def _inv(x):
    # Fermat inverse (q is prime).
    return pow(x, _Q - 2, _Q)


_D = (-121665 * _inv(121666)) % _Q   # Edwards curve constant d
_L = 2 ** 252 + 27742317777372353535851937790883648493  # order of base point


def _xrecover(y):
    # RFC 8032 5.1.3.
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * pow(2, (_Q - 1) // 4, _Q)) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


def _edwards_add(p, q_):
    """Add two points in extended coordinates (X, Y, Z, T)."""
    (x1, y1, z1, t1) = p
    (x2, y2, z2, t2) = q_
    a = (y1 - x1) * (y2 - x2) % _Q
    b = (y1 + x1) * (y2 + x2) % _Q
    c = t1 * 2 * _D * t2 % _Q
    d = z1 * 2 * z2 % _Q
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return ((e * f) % _Q, (g * h) % _Q, (f * g) % _Q, (e * h) % _Q)


def _edwards_double(p):
    return _edwards_add(p, p)


_IDENT = (0, 1, 1, 0)  # neutral element (0, 1) in extended coordinates


def _scalarmult(p, e):
    # Double-and-add. Simple and obviously correct; fast enough for a
    # client library (a handful of signatures per game).
    if e == 0:
        return _IDENT
    q_ = _scalarmult(p, e // 2)
    q_ = _edwards_double(q_)
    if e & 1:
        q_ = _edwards_add(q_, p)
    return q_


# Base point B (RFC 8032 5.1): y = 4/5, x recovered.
_Bx = _xrecover(4 * _inv(5) % _Q)
_By = 4 * _inv(5) % _Q
_BASE = (_Bx, _By, 1, (_Bx * _By) % _Q)


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(p):
    (x, y, z, t) = p
    zi = _inv(z)
    x = (x * zi) % _Q
    y = (y * zi) % _Q
    bits = (y & ((1 << 255) - 1)) | ((x & 1) << 255)
    return bits.to_bytes(32, "little")


def _decodeint(s):
    return int.from_bytes(s, "little")


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _decodepoint(s):
    """Decode a 32-byte point encoding; raises ValueError if invalid."""
    y = _decodeint(s) & ((1 << 255) - 1)
    sign = (_decodeint(s) >> 255) & 1
    x = _xrecover(y)
    if (x & 1) != sign:
        x = _Q - x
    p = (x, y, 1, (x * y) % _Q)
    (px, py, pz, pt) = p
    if pz % _Q == 0:
        raise ValueError("decoded point has zero Z")
    if (px * py - pz * pt) % _Q != 0:
        raise ValueError("decoded point failed T check")
    if (py * py - px * px - pz * pz - _D * pt * pt) % _Q != 0:
        raise ValueError("decoded point not on curve")
    return p


def _hint(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _secret_scalar(seed):
    """Clamp the hashed seed to the Ed25519 secret scalar (RFC 8032 5.1.5)."""
    h = hashlib.sha512(seed).digest()
    return 2 ** (_B - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _B - 2))


def _publickey_bytes(seed):
    a = _secret_scalar(seed)
    return _encodepoint(_scalarmult(_BASE, a))


def _signature_bytes(message, seed):
    h = hashlib.sha512(seed).digest()
    a = _secret_scalar(seed)
    prefix = h[32:]
    r = _hint(prefix + message)
    big_r = _scalarmult(_BASE, r)
    enc_r = _encodepoint(big_r)
    enc_a = _publickey_bytes(seed)
    s = (r + _hint(enc_r + enc_a + message) * a) % _L
    return enc_r + _encodeint(s)


def _checkvalid(signature, message, public_key):
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        r_point = _decodepoint(signature[:32])
        a_point = _decodepoint(public_key)
    except ValueError:
        return False
    s = _decodeint(signature[32:])
    if s >= _L:
        return False
    h = _hint(_encodepoint(r_point) + public_key + message)
    # [S]B == R + [h]A, compared in projective coordinates.
    p1 = _scalarmult(_BASE, s)
    p2 = _edwards_add(r_point, _scalarmult(a_point, h))
    return ((p1[0] * p2[2] - p2[0] * p1[2]) % _Q == 0
            and (p1[1] * p2[2] - p2[1] * p1[2]) % _Q == 0)


# ---------------------------------------------------------------------------
# Public interface (the swap point for libsodium / cryptography backends)
# ---------------------------------------------------------------------------

def generate_keypair():
    """Generate a fresh Ed25519 keypair.

    Returns (private_key_hex, public_key_hex): the private key is the
    32-byte seed as 64 lowercase hex chars; the public key is the 32-byte
    encoded point as 64 lowercase hex chars. Uses os.urandom.
    """
    seed = os.urandom(32)
    return seed.hex(), _publickey_bytes(seed).hex()


def public_key_from_private(private_key_hex):
    """Derive the public key hex from a private key hex (32-byte seed)."""
    seed = bytes.fromhex(private_key_hex)
    if len(seed) != 32:
        raise ValueError("private key must be 32 bytes (64 hex chars)")
    return _publickey_bytes(seed).hex()


def sign(private_key_hex, message):
    """Sign message bytes; returns the 64-byte signature.

    Deterministic per RFC 8032: signing the same message with the same
    key always yields the same signature.
    """
    seed = bytes.fromhex(private_key_hex)
    if len(seed) != 32:
        raise ValueError("private key must be 32 bytes (64 hex chars)")
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    return _signature_bytes(bytes(message), seed)


def verify(public_key_hex, message, signature):
    """Verify a signature; returns True/False (never raises on bad input)."""
    try:
        public_key = bytes.fromhex(public_key_hex)
    except (ValueError, TypeError):
        return False
    if not isinstance(message, (bytes, bytearray)):
        return False
    signature = bytes(signature)
    return _checkvalid(signature, bytes(message), public_key)
