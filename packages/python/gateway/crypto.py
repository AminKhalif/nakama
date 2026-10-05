"""Ed25519 behind a small interface: keygen / sign / verify.

Python's stdlib has no Ed25519, so this module vendors a compact,
well-known pure-Python implementation: Daniel J. Bernstein's Ed25519
reference code ("ref.py", SUPERCOP ref10), which he released into the
public domain ("This is free and unencumbered software released into the
public domain."). The implementation below is a faithful transcription
with private names; the public interface is generate_keypair(),
sign(), verify(), and pubkey_from_priv(). It is verified against the
RFC 8032 section 7.1 test vectors (see selftest_crypto.py).

This is intentionally slow (~0.1s per sign/verify on CPython) but has no
dependencies and no platform-specific code. A production deployment would
swap this module for libsodium/cryptography behind the same interface --
the rest of the gateway only touches the four public functions.
"""

import hashlib
import secrets

# ---------------------------------------------------------------------------
# Vendored Ed25519 reference implementation (public domain, D. J. Bernstein).
# Private names below; do not import them elsewhere -- use the interface
# at the bottom of this file.
# ---------------------------------------------------------------------------

_b = 256
_q = (1 << 255) - 19
_l = 2 ** 252 + 27742317777372353535851937790883648493  # group order


def _H(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, _q - 2, _q)


_d = (-121665 * _inv(121666)) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1) % _q
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = (4 * _inv(5)) % _q
_Bx = _xrecover(_By)
_B = [_Bx, _By]


def _edwards(P, Q):
    # Complete addition law for the twisted Edwards curve
    # -x^2 + y^2 = 1 + d*x^2*y^2 (i.e. a = -1). Per the Explicit Formulas
    # Database ("twisted Edwards" addition): the y-numerator is
    # (y1*y2 - a*x1*x2), which for a = -1 is (y1*y2 + x1*x2).
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return [x3 % _q, y3 % _q]


def _scalarmult(P, e):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _encodeint(y):
    bits = [(y >> i) & 1 for i in range(_b)]
    return bytes(
        sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8))


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(_b - 1)] + [x & 1]
    return bytes(
        sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8))


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _publickey(sk):
    h = _H(sk)
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    A = _scalarmult(_B, a)
    return _encodepoint(A)


def _Hint(m):
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * _b))


def _signature(m, sk, pk):
    h = _H(sk)
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    r = _Hint(bytes(h[i] for i in range(_b // 8, _b // 4)) + m)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % _l
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _decodeint(s):
    return sum(2 ** i * _bit(s, i) for i in range(_b))


def _decodepoint(s):
    y = sum(2 ** i * _bit(s, i) for i in range(_b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def _checkvalid(s, m, pk):
    if len(s) != _b // 4:  # signatures are 64 bytes, pubkeys 32
        raise ValueError("signature length is wrong")
    if len(pk) != _b // 8:
        raise ValueError("public-key length is wrong")
    R = _decodepoint(s[0:_b // 8])
    A = _decodepoint(pk)
    S = _decodeint(s[_b // 8:_b // 4])
    h = _Hint(_encodepoint(R) + pk + m)
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))


# ---------------------------------------------------------------------------
# Public interface. Everything else in the gateway uses only these.
# Keys and signatures are lowercase hex strings (32 / 64 bytes).
# ---------------------------------------------------------------------------

def generate_keypair():
    """Return (priv_hex, pub_hex). Uses os randomness; private key never leaves
    the caller's host -- the gateway only ever sees pubkeys."""
    sk = secrets.token_bytes(32)
    return sk.hex(), _publickey(sk).hex()


def pubkey_from_priv(priv_hex):
    """Derive the public key hex for a private key hex."""
    sk = bytes.fromhex(priv_hex)
    if len(sk) != 32:
        raise ValueError("private key must be 32 bytes hex")
    return _publickey(sk).hex()


def sign(priv_hex, msg):
    """Sign bytes, return 128-char hex signature. Deterministic (RFC 8032)."""
    sk = bytes.fromhex(priv_hex)
    if len(sk) != 32:
        raise ValueError("private key must be 32 bytes hex")
    if not isinstance(msg, (bytes, bytearray)):
        raise TypeError("msg must be bytes")
    pk = _publickey(sk)
    return _signature(bytes(msg), sk, pk).hex()


def verify(pub_hex, msg, sig_hex):
    """Return True iff sig is a valid Ed25519 signature of msg under pub.
    Never raises on malformed input -- returns False."""
    try:
        pk = bytes.fromhex(pub_hex)
        sig = bytes.fromhex(sig_hex)
        if not isinstance(msg, (bytes, bytearray)):
            return False
        return bool(_checkvalid(sig, bytes(msg), pk))
    except Exception:
        return False


def is_valid_pubkey(pub_hex):
    """Cheap syntactic check: 64 lowercase hex chars decoding to a curve point."""
    try:
        raw = bytes.fromhex(pub_hex)
    except Exception:
        return False
    if len(raw) != 32 or pub_hex != raw.hex():
        return False
    try:
        _decodepoint(raw)
        return True
    except Exception:
        return False


def is_prime_order_pubkey(pub_hex):
    """True iff the key decodes to a point in the prime-order subgroup
    (l*P == identity). Rejects torsion points: a registered torsion key
    would weaken the non-repudiation the receipt chain relies on, since
    small-order public keys admit signature malleability."""
    try:
        raw = bytes.fromhex(pub_hex)
        if len(raw) != 32:
            return False
        P = _decodepoint(raw)  # raises if not on the curve
        return _scalarmult(P, _l) == [0, 1]
    except Exception:
        return False
