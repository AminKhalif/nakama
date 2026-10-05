#!/usr/bin/env python3
"""RFC 8032 section 7.1 Ed25519 test vectors for gateway.crypto.

Vectors copied from RFC 8032 (primary source). For each vector:
  * derived public key matches byte-for-byte
  * signature matches byte-for-byte (deterministic signing)
  * verification of the valid signature passes
  * a bit-flipped signature is rejected
  * a wrong message is rejected
Plus a random keypair round-trip and cross-key rejection.
Run: python3 selftest_crypto.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto  # noqa: E402

VECTORS = [
    # (secret_hex, pubkey_hex, message_hex, signature_hex)
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + detail) if detail and not cond else ""))
    if not cond:
        raise AssertionError("FAILED: " + name + " " + detail)


def flip(sig_hex):
    b = bytearray.fromhex(sig_hex)
    b[0] ^= 1
    return bytes(b).hex()


def main():
    for i, (sk, pk, msg_hex, sig) in enumerate(VECTORS, 1):
        msg = bytes.fromhex(msg_hex)
        check("TEST%d pubkey matches" % i, crypto.pubkey_from_priv(sk) == pk)
        check("TEST%d signature matches byte-for-byte" % i, crypto.sign(sk, msg) == sig)
        check("TEST%d valid signature verifies" % i, crypto.verify(pk, msg, sig))
        check("TEST%d flipped signature rejected" % i, not crypto.verify(pk, msg, flip(sig)))
        check("TEST%d wrong message rejected" % i,
              not crypto.verify(pk, msg + b"x", sig))
        check("TEST%d is_valid_pubkey" % i, crypto.is_valid_pubkey(pk))

    # round-trip on a fresh random keypair, plus negative controls
    sk, pk = crypto.generate_keypair()
    check("keygen sizes", len(sk) == 64 and len(pk) == 64)
    m = b'{"gw":"gw/1","msg_id":"msg_abc"}'
    s = crypto.sign(sk, m)
    check("round-trip verifies", crypto.verify(pk, m, s))
    sk2, pk2 = crypto.generate_keypair()
    check("wrong-key signature rejected", not crypto.verify(pk2, m, s))
    check("malformed sig rejected", not crypto.verify(pk, m, "zz"))
    check("malformed pubkey rejected", not crypto.verify("00" * 32, m, s))
    check("zero pubkey is on-curve torsion (accepted syntactically)",
          crypto.is_valid_pubkey("00" * 32))
    check("zero pubkey rejected as non-prime-order",
          not crypto.is_prime_order_pubkey("00" * 32))
    check("real pubkey is prime-order",
          crypto.is_prime_order_pubkey(crypto.pubkey_from_priv(VECTORS[0][0])))
    print("\nALL %d CRYPTO CHECKS PASSED" % len(RESULTS))


if __name__ == "__main__":
    main()
