# SPDX-License-Identifier: Apache-2.0
"""Ed25519 via PyNaCl/libsodium. Keys are 32-byte seeds encoded as hex."""
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


def generate_keypair():
    key = SigningKey.generate()
    return key.encode().hex(), key.verify_key.encode().hex()


def public_key_from_private(private_key_hex):
    return SigningKey(bytes.fromhex(private_key_hex)).verify_key.encode().hex()


def sign(private_key_hex, message):
    """Return a detached 64-byte signature; never implement curve arithmetic here."""
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError('message must be bytes')
    return SigningKey(bytes.fromhex(private_key_hex)).sign(bytes(message)).signature


def verify(public_key_hex, message, signature):
    """Verify a detached signature. Malformed input returns False."""
    try:
        if not isinstance(message, (bytes, bytearray)) or not isinstance(signature, (bytes, bytearray)):
            return False
        VerifyKey(bytes.fromhex(public_key_hex)).verify(bytes(message), bytes(signature))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
