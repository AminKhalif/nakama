# SPDX-License-Identifier: Apache-2.0
"""Envelope build/parse/verify: round-trip, tamper detection, errors."""

import json
import unittest

from gwclient import crypto
from gwclient import envelope as env_mod
from gwclient.envelope import (BadEnvelope, BadSignature, build_envelope,
                               canonical, parse_envelope, verify_envelope)


def make_env(priv=None, **kw):
    priv = priv or crypto.generate_keypair()[0]
    args = {"from_id": "agent_a", "to_id": "gateway", "msg_type": "ttt.commit",
            "schema": "ttt/1", "session": "sess_1",
            "payload": {"round": 1, "commit": "ab" * 32}}
    args.update(kw)
    return build_envelope(private_key_hex=priv, **args), priv


class TestEnvelope(unittest.TestCase):
    def test_round_trip(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        out = verify_envelope(env, pub)
        self.assertEqual(out["payload"]["round"], 1)
        self.assertTrue(out["sig"].startswith("ed25519:"))
        self.assertEqual(len(out["sig"]), len("ed25519:") + 128)

    def test_canonical_is_key_order_independent(self):
        a = canonical({"z": 1, "a": [1, 2], "m": {"y": 2, "x": 1}})
        b = canonical({"a": [1, 2], "m": {"x": 1, "y": 2}, "z": 1})
        self.assertEqual(a, b)
        self.assertEqual(a, b'{"a":[1,2],"m":{"x":1,"y":2},"z":1}')

    def test_tampered_payload_rejected(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        env["payload"]["round"] = 2
        with self.assertRaises(BadSignature):
            verify_envelope(env, pub)

    def test_tampered_type_rejected(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        env["type"] = "ttt.reveal"
        with self.assertRaises(BadSignature):
            verify_envelope(env, pub)

    def test_wrong_key_rejected(self):
        env, _ = make_env()
        _, other_pub = crypto.generate_keypair()
        with self.assertRaises(BadSignature):
            verify_envelope(env, other_pub)

    def test_resolver_callable(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        out = verify_envelope(env, lambda from_id: pub
                              if from_id == "agent_a" else None)
        self.assertEqual(out["from"], "agent_a")

    def test_missing_sig_rejected(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        del env["sig"]
        with self.assertRaises(BadSignature):
            verify_envelope(env, pub)

    def test_malformed_sig_rejected(self):
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        env["sig"] = "ed25519:zzzz"
        with self.assertRaises(BadSignature):
            verify_envelope(env, pub)

    def test_missing_field_rejected(self):
        env, _ = make_env()
        del env["session"]
        with self.assertRaises(BadEnvelope):
            parse_envelope(env)

    def test_bad_version_rejected(self):
        env, _ = make_env()
        env["gw"] = "gw/2"
        with self.assertRaises(BadEnvelope):
            parse_envelope(env)

    def test_not_json_rejected(self):
        with self.assertRaises(BadEnvelope):
            parse_envelope("{not json")

    def test_unknown_fields_ignored(self):
        # Additive schema evolution: a newer sender signs an envelope
        # carrying a field this verifier never heard of; verification
        # must still succeed and the field must survive parsing.
        env, priv = make_env()
        pub = crypto.public_key_from_private(priv)
        env["future_field"] = {"new": "stuff"}
        sig = crypto.sign(priv, env_mod.signing_bytes(env))
        env["sig"] = "ed25519:" + sig.hex()
        out = verify_envelope(env, pub)  # must not raise
        self.assertEqual(out["future_field"], {"new": "stuff"})

    def test_parse_from_json_text(self):
        env, _ = make_env()
        parsed = parse_envelope(json.dumps(env))
        self.assertEqual(parsed["msg_id"], env["msg_id"])

    def test_null_session_allowed_for_sessionless(self):
        env, priv = make_env(msg_type="gw.register", schema="gw/1",
                             session=None,
                             payload={"name": "AMIN",
                                      "pubkey": "ed25519:" + "ab" * 32})
        pub = crypto.public_key_from_private(priv)
        out = verify_envelope(env, pub)
        self.assertIsNone(out["session"])

    def test_session_scoped_type_with_null_session_rejected(self):
        env, _ = make_env(session=None)
        with self.assertRaises(BadEnvelope):
            parse_envelope(env)

    def test_sessionless_type_with_session_rejected(self):
        env, _ = make_env(msg_type="gw.register", schema="gw/1",
                           session="sess_1", payload={"name": "x"})
        with self.assertRaises(BadEnvelope):
            parse_envelope(env)

    def test_bad_msg_id_rejected(self):
        env, _ = make_env()
        env["msg_id"] = "too-short"
        with self.assertRaises(BadEnvelope):
            parse_envelope(env)

    def test_register_from_unregistered(self):
        # envelope.md section 6: from MUST be "agent_unregistered".
        env, priv = make_env(from_id="agent_unregistered",
                             msg_type="gw.register", schema="gw/1",
                             session=None,
                             payload={"name": "AMIN",
                                      "pubkey": "ed25519:" + "ab" * 32})
        pub = crypto.public_key_from_private(priv)
        out = verify_envelope(env, pub)
        self.assertEqual(out["from"], "agent_unregistered")


if __name__ == "__main__":
    unittest.main()
