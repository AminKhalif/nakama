# SPDX-License-Identifier: Apache-2.0
"""RFC 8032 section 7.1 Ed25519 test vectors plus rejection checks."""

import unittest

from gwclient import crypto

# (secret_key_hex, public_key_hex, message_hex, signature_hex)
VECTORS = [
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
    ("833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
     "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
     "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
     "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
     "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
     "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"),
]


class TestRFC8032(unittest.TestCase):
    def test_vectors(self):
        for i, (sk, pk, msg_hex, sig_hex) in enumerate(VECTORS):
            with self.subTest(vector=i + 1):
                msg = bytes.fromhex(msg_hex)
                sig = bytes.fromhex(sig_hex)
                self.assertEqual(crypto.public_key_from_private(sk), pk)
                self.assertEqual(crypto.sign(sk, msg).hex(), sig_hex)
                self.assertTrue(crypto.verify(pk, msg, sig))

    def test_sign_is_deterministic(self):
        sk = VECTORS[0][0]
        self.assertEqual(crypto.sign(sk, b"abc"), crypto.sign(sk, b"abc"))

    def test_tampered_signature_rejected(self):
        _, pk, msg_hex, sig_hex = VECTORS[2]
        bad = bytearray.fromhex(sig_hex)
        bad[10] ^= 1
        self.assertFalse(crypto.verify(pk, bytes.fromhex(msg_hex),
                                       bytes(bad)))

    def test_wrong_message_rejected(self):
        _, pk, _, sig_hex = VECTORS[1]
        self.assertFalse(crypto.verify(pk, b"\x73",
                                       bytes.fromhex(sig_hex)))

    def test_wrong_key_rejected(self):
        _, _, msg_hex, sig_hex = VECTORS[1]
        _, other_pub = crypto.generate_keypair()
        self.assertFalse(crypto.verify(other_pub, bytes.fromhex(msg_hex),
                                       bytes.fromhex(sig_hex)))

    def test_malformed_inputs_rejected_not_raised(self):
        _, pk, msg_hex, sig_hex = VECTORS[0]
        msg, sig = bytes.fromhex(msg_hex), bytes.fromhex(sig_hex)
        self.assertFalse(crypto.verify("zz", msg, sig))
        self.assertFalse(crypto.verify(pk, msg, sig[:-1]))
        self.assertFalse(crypto.verify(pk, msg, sig + b"\x00"))

    def test_keygen_roundtrip(self):
        priv, pub = crypto.generate_keypair()
        self.assertEqual(len(priv), 64)
        self.assertEqual(len(pub), 64)
        self.assertEqual(crypto.public_key_from_private(priv), pub)
        sig = crypto.sign(priv, b"hello gateway")
        self.assertTrue(crypto.verify(pub, b"hello gateway", sig))


if __name__ == "__main__":
    unittest.main()
