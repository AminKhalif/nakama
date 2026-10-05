"""Gateway compatibility interface over the shared PyNaCl/libsodium backend."""
from nacl.bindings import crypto_core_ed25519_is_valid_point
from gwclient.crypto import generate_keypair, public_key_from_private, sign as _sign, verify as _verify


def pubkey_from_priv(priv_hex):
    return public_key_from_private(priv_hex)


def sign(priv_hex, msg):
    """Gateway callers historically use detached signatures encoded as hex."""
    return _sign(priv_hex, msg).hex()


def verify(pub_hex, msg, sig_hex):
    try:
        return _verify(pub_hex, msg, bytes.fromhex(sig_hex))
    except (ValueError, TypeError):
        return False


def is_valid_pubkey(pub_hex):
    """Check canonical 32-byte hex encoding; not proof of subgroup membership."""
    try:
        raw = bytes.fromhex(pub_hex)
        return len(raw) == 32 and pub_hex == raw.hex()
    except (ValueError, TypeError):
        return False


def is_prime_order_pubkey(pub_hex):
    """Require a canonical main-subgroup point; libsodium rejects small-order keys."""
    try:
        return is_valid_pubkey(pub_hex) and crypto_core_ed25519_is_valid_point(bytes.fromhex(pub_hex))
    except (ValueError, TypeError):
        return False
