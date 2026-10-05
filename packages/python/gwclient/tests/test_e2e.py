# SPDX-License-Identifier: Apache-2.0
"""Live spec-conformance end to end.

A full game against a LIVE gateway spawned in-process: register three
agents (two players, one auditor), friend + console accept, open a
session, play simultaneous commit/reveal rounds, countersign every
receipt as the auditor via gw.countersign, then fetch gw.receipts and
verify the whole chain with the independent verifier. No fixtures,
no stubs: every step goes over real HTTP against the real gateway.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
import http.cookiejar

from gwclient import (GWClient, verify_chain, verify_identity_document,
                      countersign)
from gwclient.client import GatewayError

GATEWAY_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                           "gateway")
CONSOLE_TOKEN = "e2e-console-token"


def spawn_gateway():
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, GW_CONSOLE_TOKEN=CONSOLE_TOKEN)
    srv = subprocess.Popen(
        [sys.executable, "-m", "gateway.server", "--port", "0",
         "--db", os.path.join(tmp, "e2e.db"), "--host", "127.0.0.1"],
        cwd=os.path.join(GATEWAY_DIR, ".."), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    first = srv.stdout.readline()
    m = re.search(r":(\d+)", first)
    if not m:
        srv.kill()
        raise RuntimeError("gateway did not print a port: %r" % (first,))
    base = "http://127.0.0.1:%s" % m.group(1)
    for _ in range(200):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read()
            break
        except OSError:
            time.sleep(0.05)
    return srv, base


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def console_accept(base, request_id):
    """The human tap: log in to the console and accept the request."""
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPCookieProcessor(jar))

    def post(url, data):
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            op.open(req, timeout=5)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise

    post(base + "/console/login",
         ("token=%s" % CONSOLE_TOKEN).encode())
    post(base + "/console/requests/%s/accept" % request_id, b"")


def wait_for_notification(aud, session, msg_type, timeout=10, round=None):
    """Poll the auditor's session_state until a notification of the
    given type (and round, when given) arrives; return its payload.
    Notifications accumulate, so the round filter skips stale ones."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = aud.session_state(session)
        for env in state.get("notifications", []):
            if env.get("type") != msg_type:
                continue
            payload = env["payload"]
            if round is not None and payload.get("round") != round:
                continue
            return payload
        time.sleep(0.1)
    raise AssertionError("timed out waiting for %s" % (msg_type,))


class SpecRequestShape(unittest.TestCase):
    """The client's wire construction matches the spec. No gateway
    needed: these inspect the envelopes the client builds."""

    def test_register_envelope_shape(self):
        client = GWClient.new("http://127.0.0.1:9")
        env = client._envelope("gw.register", "gw.register", "gw/1", None,
                               {"name": "AliceAgent",
                                "pubkey": "ed25519:" + "ab" * 32})
        self.assertEqual(env["from"], "agent_unregistered")
        self.assertEqual(env["to"], "gateway")
        self.assertIsNone(env["session"])
        self.assertEqual(env["type"], "gw.register")
        self.assertEqual(env["schema"], "gw/1")
        self.assertTrue(env["sig"].startswith("ed25519:"))

    def test_rpc_target_is_slash_rpc(self):
        client = GWClient.new("http://127.0.0.1:9/")
        self.assertEqual(client.rpc_url, "http://127.0.0.1:9/rpc")

    def test_commit_envelope_pairs_gw_method_with_ttt_type(self):
        client = GWClient.new("http://127.0.0.1:9")
        client.agent_id = "agent_aaa111"
        env = client._envelope(
            "gw.commit", "ttt.commit", "ttt/1", "sess_abc",
            client._session_payload("sess_abc", {"round": 1,
                                                 "commit": "ab" * 32}))
        self.assertEqual(env["type"], "ttt.commit")
        self.assertEqual(env["session"], "sess_abc")
        self.assertEqual(env["payload"]["session"], "sess_abc")
        self.assertEqual(env["to"], "gateway")


class FullGameLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = spawn_gateway()

    @classmethod
    def tearDownClass(cls):
        cls.srv.kill()

    def test_register_identity_documents_verify(self):
        card = GWClient.new(self.base).agent_card()
        gw_pubkey = card["gwPubkey"]
        self.assertTrue(gw_pubkey.startswith("ed25519:"))
        alice = GWClient.new(self.base)
        alice.register("LiveA", owner_display_name="probe",
                       vendor="gwclient")
        doc = verify_identity_document(alice.identity, gw_pubkey)
        self.assertEqual(doc["id"], alice.agent_id)
        self.assertEqual(doc["pubkey"], "ed25519:" + alice.public_key_hex)

    def test_full_game_with_countersigning(self):
        base = self.base
        alice = GWClient.new(base)
        bob = GWClient.new(base)
        aud = GWClient.new(base)
        alice.register("LiveB", owner_display_name="probe",
                       vendor="gwclient")
        bob.register("LiveC", owner_display_name="probe",
                     vendor="gwclient")
        aud.register("LiveD", owner_display_name="probe",
                     vendor="gwclient")

        req = alice.friend_request(to_agent_id=bob.agent_id)
        console_accept(base, req)

        state = alice.session_open(bob.agent_id, aud.agent_id)
        session = state["session"]
        self.assertEqual(state["players"]["a"], alice.agent_id)
        self.assertEqual(state["players"]["b"], bob.agent_id)
        self.assertEqual(state["phase"], "commit")

        # a wins on round 3 with the left column.
        moves = [("r0c0", "r1c1"), ("r1c0", "r2c2"), ("r2c0", "r0c2")]
        for n, (ca, cb) in enumerate(moves, start=1):
            alice.commit(session, n, ca, "sec-a-%d" % n)
            bob.commit(session, n, cb, "sec-b-%d" % n)
            alice.reveal(session, n, ca, "sec-a-%d" % n)
            bob.reveal(session, n, cb, "sec-b-%d" % n)
            receipt = wait_for_notification(aud, session,
                                            "ttt.round_receipt", round=n)
            self.assertEqual(receipt["round"], n)
            sig = countersign(receipt, aud.private_key_hex)
            res = aud.countersign(session, n, sig)
            self.assertTrue(res["countersigned"])

        self.assertTrue(receipt["game_over"])
        self.assertEqual(receipt["result"], "a")

        # The game receipt is issued once the final round is
        # countersigned; countersign it too, then verify everything.
        game_receipt = wait_for_notification(aud, session,
                                             "ttt.game_receipt")
        gsig = countersign(game_receipt, aud.private_key_hex)
        res = aud.countersign(session, len(moves), gsig, kind="game")
        self.assertTrue(res["countersigned"])

        chain = alice.receipts(session)
        self.assertEqual(len(chain), len(moves) + 1)
        card = alice.agent_card()
        self.assertTrue(verify_chain(chain, card["gwPubkey"],
                                     "ed25519:" + aud.public_key_hex))
        # Both signatures present on every published receipt.
        for r in chain:
            self.assertTrue(r["gw_sig"].startswith("ed25519:"))
            self.assertTrue(r["auditor_sig"].startswith("ed25519:"))

    def test_wrong_secret_reveal_rejected(self):
        base = self.base
        alice = GWClient.new(base)
        bob = GWClient.new(base)
        aud = GWClient.new(base)
        alice.register("LiveE", owner_display_name="probe",
                       vendor="gwclient")
        bob.register("LiveF", owner_display_name="probe",
                     vendor="gwclient")
        aud.register("LiveG", owner_display_name="probe",
                     vendor="gwclient")
        req = alice.friend_request(to_agent_id=bob.agent_id)
        console_accept(base, req)
        session = alice.session_open(bob.agent_id,
                                     aud.agent_id)["session"]
        alice.commit(session, 1, "r0c0", "real-secret")
        bob.commit(session, 1, "r1c1", "sec-b")
        with self.assertRaises(GatewayError) as ctx:
            alice.reveal(session, 1, "r0c0", "wrong-secret")
        self.assertIn("commitment_mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
