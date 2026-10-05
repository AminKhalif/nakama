# SPDX-License-Identifier: Apache-2.0
"""Commit/reveal helpers: formula, verification, cross-context rejection."""

import hashlib
import unittest

from gwclient import commit as commit_mod
from gwclient.commit import make_commit, verify_commit


class TestCommit(unittest.TestCase):
    def test_formula(self):
        # sha256("gw/1|sess_9|r3|agent_a|r0c2|hunter2")
        preimage = "gw/1|sess_9|r3|agent_a|r0c2|hunter2"
        self.assertEqual(commit_mod.commitment_input("sess_9", 3, "agent_a",
                                                     "r0c2", "hunter2"),
                         preimage)
        self.assertEqual(make_commit("sess_9", 3, "agent_a", "r0c2",
                                     "hunter2"),
                         hashlib.sha256(preimage.encode()).hexdigest())
        self.assertEqual(len(make_commit("s", 1, "a", "r0c0", "x")), 64)

    def test_verify_ok(self):
        c = make_commit("sess_1", 1, "agent_a", "r1c1", "secret!")
        self.assertTrue(verify_commit(c, "sess_1", 1, "agent_a", "r1c1",
                                       "secret!"))

    def test_wrong_secret_rejected(self):
        c = make_commit("sess_1", 1, "agent_a", "r1c1", "secret!")
        self.assertFalse(verify_commit(c, "sess_1", 1, "agent_a", "r1c1",
                                        "secret?"))

    def test_cross_context_rejected(self):
        # A commitment is bound to session, round, agent, and cell: reuse
        # in any other context must fail verification.
        c = make_commit("sess_1", 1, "agent_a", "r1c1", "s")
        cases = [
            ("sess_2", 1, "agent_a", "r1c1", "s"),   # other session
            ("sess_1", 2, "agent_a", "r1c1", "s"),   # other round
            ("sess_1", 1, "agent_b", "r1c1", "s"),   # other player
            ("sess_1", 1, "agent_a", "r1c2", "s"),   # other cell
        ]
        for session, rnd, agent, cell, secret in cases:
            with self.subTest(case=(session, rnd, agent, cell)):
                self.assertFalse(verify_commit(c, session, rnd, agent,
                                               cell, secret))

    def test_case_insensitive_hex(self):
        c = make_commit("s", 1, "a", "r0c0", "x")
        self.assertTrue(verify_commit(c.upper(), "s", 1, "a", "r0c0", "x"))

    def test_garbage_rejected(self):
        self.assertFalse(verify_commit("zz", "s", 1, "a", "r0c0", "x"))
        self.assertFalse(verify_commit(None, "s", 1, "a", "r0c0", "x"))


if __name__ == "__main__":
    unittest.main()
