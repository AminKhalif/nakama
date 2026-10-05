# SPDX-License-Identifier: Apache-2.0
"""Tests for the independent verifier (verify_receipts.py). No gateway,
no network.

- The verifier script must never import gateway code (it is the second
  opinion; sharing code with the attested party would void it).
- A valid offline-built chain verifies with exit 0.
- A tampered chain exits non-zero and names the failing receipt.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "packages", "python"))

import verify_receipts  # noqa: E402
from gwclient import crypto  # noqa: E402
from gwclient.receipts import (receipt_hash,  # noqa: E402
                               receipt_signing_bytes)

GW_PRIV, GW_PUB = crypto.generate_keypair()
AUD_PRIV, AUD_PUB = crypto.generate_keypair()
SESSION = "sess_abc123def456"


def _sign(body, priv):
    body = dict(body)
    body["gw_sig"] = None
    body["auditor_sig"] = None
    msg = receipt_signing_bytes(body)
    body["gw_sig"] = "ed25519:" + crypto.sign(GW_PRIV, msg).hex()
    body["auditor_sig"] = "ed25519:" + crypto.sign(AUD_PRIV, msg).hex()
    return body


def _commit(side):
    return "%02x" % side * 32


def build_chain():
    """A 3-round a-wins chain with real signatures (match-1 layout)."""
    r1 = _sign({
        "session": SESSION, "round": 1,
        "commitments": {"a": _commit(1), "b": _commit(2)},
        "reveals": {"a": {"cell": "r0c0"}, "b": {"cell": "r0c1"}},
        "board_after": ["a", "b", None, None, None, None, None, None,
                        None],
        "result": "draw", "game_over": False,
        "prev_hash": "0" * 64,
        "schema_versions": {"ttt": "ttt/1"},
    }, GW_PRIV)
    r2 = _sign({
        "session": SESSION, "round": 2,
        "commitments": {"a": _commit(3), "b": _commit(4)},
        "reveals": {"a": {"cell": "r1c1"}, "b": {"cell": "r2c0"}},
        "board_after": ["a", "b", None, None, "a", None, "b", None,
                        None],
        "result": "draw", "game_over": False,
        "prev_hash": receipt_hash(r1),
        "schema_versions": {"ttt": "ttt/1"},
    }, GW_PRIV)
    r3 = _sign({
        "session": SESSION, "round": 3,
        "commitments": {"a": _commit(5), "b": _commit(6)},
        "reveals": {"a": {"cell": "r2c2"}, "b": {"cell": "r0c2"}},
        # b's r0c2 recorded but not applied: a won on its move.
        "board_after": ["a", "b", None, None, "a", None, "b", None,
                        "a"],
        "result": "a", "game_over": True,
        "prev_hash": receipt_hash(r2),
        "schema_versions": {"ttt": "ttt/1"},
    }, GW_PRIV)
    game = _sign({
        "session": SESSION, "rounds_played": 3,
        "final_board": ["a", "b", None, None, "a", None, "b", None,
                        "a"],
        "result": "a",
        "prev_hash": receipt_hash(r3),
        "schema_versions": {"ttt": "ttt/1"},
    }, GW_PRIV)
    return [r1, r2, r3, game]


class FakeClient:
    def __init__(self, chain):
        self._chain = chain

    def agent_card(self):
        return {"gwPubkey": "ed25519:" + GW_PUB}

    def receipts(self, session):
        assert session == SESSION
        return self._chain


class VerifierTests(unittest.TestCase):
    def run_verifier(self, chain):
        real_new = verify_receipts.GWClient.new
        verify_receipts.GWClient.new = staticmethod(
            lambda *a, **k: FakeClient(chain))
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = verify_receipts.main([
                    "--base-url", "http://127.0.0.1:9",
                    "--auditor-pubkey", "ed25519:" + AUD_PUB,
                    SESSION])
        finally:
            verify_receipts.GWClient.new = real_new
        return code, buf.getvalue()

    def test_valid_chain_exit_zero(self):
        code, out = self.run_verifier(build_chain())
        self.assertEqual(code, 0)
        self.assertIn("VALID", out)
        self.assertIn("1/1 chains valid", out)

    def test_tampered_chain_names_receipt(self):
        chain = build_chain()
        chain[1]["board_after"][4] = "b"  # flip a's mark, keep the sigs
        code, out = self.run_verifier(chain)
        self.assertEqual(code, 1)
        self.assertIn("round 2", out)
        self.assertIn("0/1 chains valid", out)

    def test_broken_signature_names_receipt(self):
        chain = build_chain()
        chain[2]["gw_sig"] = "ed25519:" + "00" * 64
        code, out = self.run_verifier(chain)
        self.assertEqual(code, 1)
        self.assertIn("round 3", out)

    def test_no_gateway_imports(self):
        src = open(os.path.join(HERE, "verify_receipts.py")).read()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or \
                    stripped.startswith("from "):
                self.assertNotIn("gateway", stripped.split("#")[0],
                                 "verify_receipts.py must not import "
                                 "gateway code: %r" % line)


if __name__ == "__main__":
    unittest.main()
