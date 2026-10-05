# SPDX-License-Identifier: Apache-2.0
"""Identity document verification (spec/identity.md)."""

import copy
import unittest

from gwclient import crypto
from gwclient.envelope import canonical
from gwclient.identity import (IdentityError, document_signing_bytes,
                               verify_identity_document)


def make_doc(gw_priv, **overrides):
    doc = {"id": "agent_7f2c1a", "agent_name": "AliceAgent",
           "owner_display_name": "Alice", "vendor": "muse",
           "pubkey": "ed25519:" + "ab" * 32,
           "endpoints": {}, "capabilities": ["game.ttt:play"],
           "schemas": ["ttt/1", "gw/1"], "accepts": ["gw/1"],
           "certification": {}, "issued_at": "2026-10-04T12:00:00Z",
           "expires_at": "2027-10-04T12:00:00Z", "did": None,
           "deprecated_schemas": []}
    doc.update(overrides)
    doc["gw_sig"] = "ed25519:" + crypto.sign(
        gw_priv, document_signing_bytes(doc)).hex()
    return doc


class TestIdentityDocument(unittest.TestCase):
    def setUp(self):
        self.gw_priv, self.gw_pub = crypto.generate_keypair()

    def verify(self, doc):
        return verify_identity_document(doc, "ed25519:" + self.gw_pub)

    def test_valid_document(self):
        doc = make_doc(self.gw_priv)
        self.assertEqual(self.verify(doc)["agent_name"], "AliceAgent")

    def test_bare_hex_gateway_key(self):
        doc = make_doc(self.gw_priv)
        self.assertEqual(verify_identity_document(doc, self.gw_pub)["id"],
                         "agent_7f2c1a")

    def test_tampered_field_rejected(self):
        doc = make_doc(self.gw_priv)
        doc["agent_name"] = "MALLORY"
        with self.assertRaises(IdentityError):
            self.verify(doc)

    def test_missing_field_rejected(self):
        doc = make_doc(self.gw_priv)
        del doc["pubkey"]
        with self.assertRaises(IdentityError):
            self.verify(doc)

    def test_bad_pubkey_format_rejected(self):
        doc = make_doc(self.gw_priv, pubkey="ab" * 32)
        with self.assertRaises(IdentityError):
            self.verify(doc)

    def test_non_null_did_rejected(self):
        doc = make_doc(self.gw_priv, did="did:example:123")
        with self.assertRaises(IdentityError):
            self.verify(doc)

    def test_wrong_gateway_key_rejected(self):
        doc = make_doc(self.gw_priv)
        _, other_pub = crypto.generate_keypair()
        with self.assertRaises(IdentityError):
            verify_identity_document(doc, other_pub)

    def test_signing_bytes_exclude_gw_sig(self):
        doc = make_doc(self.gw_priv)
        raw = canonical({k: v for k, v in doc.items() if k != "gw_sig"})
        self.assertEqual(document_signing_bytes(doc), raw)


if __name__ == "__main__":
    unittest.main()
