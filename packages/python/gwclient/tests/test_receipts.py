# SPDX-License-Identifier: Apache-2.0
"""Independent verifier: hand-built spec-format chains, valid and tampered.

The builder below emits receipts exactly per spec/receipts.md (flat
receipts, genesis "0"*64, hashes over as-published bytes, game receipt
closing the chain). Every tamper case must fail naming the exact receipt.
"""

import copy
import hashlib
import unittest

from gwclient import auditor as auditor_mod
from gwclient import crypto
from gwclient import ttt
from gwclient.commit import make_commit
from gwclient.envelope import canonical
from gwclient.receipts import (GENESIS_PREV_HASH, ReceiptChainError,
                               receipt_hash, receipt_signing_bytes,
                               verify_chain)

SESSION = "sess_abc123"
AGENT_A = "agent_aaa111"
AGENT_B = "agent_bbb222"
SCHEMA_VERSIONS = {"ttt": "ttt/1"}


def _sign(priv, receipt):
    return "ed25519:" + crypto.sign(
        priv, receipt_signing_bytes(receipt)).hex()


def _commit(agent, cell, secret, round_n):
    if cell is None:
        return None
    return make_commit(SESSION, round_n, agent, cell, secret)


def _expected(board, ca, cb, ka, kb):
    """Independent round-outcome computation for the fixture builder."""
    a_nc = ka is None
    b_nc = kb is None
    a_nr = ka is not None and ca is None
    b_nr = kb is not None and cb is None
    if a_nc and b_nc:
        forfeit = None
    elif a_nc or b_nc:
        forfeit = "a" if a_nc else "b"
    elif a_nr and b_nr:
        forfeit = None
    elif a_nr or b_nr:
        forfeit = "a" if a_nr else "b"
    else:
        forfeit = None

    if ca is None and cb is None:
        return list(board), "draw", False, forfeit
    if ca is not None and ca == cb:
        idx = ttt.cell_index(ca)
        assert board[idx] is None
        if all(c is not None for i, c in enumerate(board) if i != idx):
            nb = list(board)
            nb[idx] = "a"
            res, over = ttt.outcome(nb)
            return nb, res, over, forfeit
        return list(board), "draw", False, forfeit
    after_a = list(board)
    if ca is not None:
        after_a[ttt.cell_index(ca)] = "a"
    a_wins = ttt.has_line(after_a, "a")
    after_b = list(after_a)
    if cb is not None:
        after_b[ttt.cell_index(cb)] = "b"
    b_wins = ttt.has_line(after_b, "b")
    if a_wins and b_wins:
        return after_b, "draw", True, forfeit
    if a_wins:
        return after_a, "a", True, forfeit
    if ttt.is_full(after_a):
        return after_a, "draw", True, forfeit
    if b_wins:
        return after_b, "b", True, forfeit
    if ttt.is_full(after_b):
        return after_b, "draw", True, forfeit
    return after_b, "draw", False, forfeit


def build_chain(gw_priv, aud_priv, moves, session=SESSION, forfeit_rounds=None):
    """moves: [(cell_a, cell_b)] per round, None = no reveal.
    forfeit_rounds: {round: side} forcing that side's commit to null.
    Returns the full chain ending with the game receipt."""
    forfeit_rounds = forfeit_rounds or {}
    receipts = []
    prev_hash = GENESIS_PREV_HASH
    board = ttt.new_board()
    for n, (ca, cb) in enumerate(moves, start=1):
        fa = forfeit_rounds.get(n)
        ka = None if fa == "a" else _commit(AGENT_A, ca, "sec-a-%d" % n, n)
        kb = None if fa == "b" else _commit(AGENT_B, cb, "sec-b-%d" % n, n)
        if fa:
            ca, cb = None, None  # commit-timeout: no reveal phase
        board_after, result, game_over, forfeit = _expected(
            board, ca, cb, ka, kb)
        r = {"session": session, "round": n,
             "commitments": {"a": ka, "b": kb},
             "reveals": {"a": {"cell": ca} if ca else None,
                         "b": {"cell": cb} if cb else None},
             "board_after": board_after, "result": result,
             "game_over": game_over, "prev_hash": prev_hash,
             "schema_versions": dict(SCHEMA_VERSIONS)}
        if forfeit:
            r["forfeit"] = forfeit
        r["gw_sig"] = _sign(gw_priv, r)
        r["auditor_sig"] = _sign(aud_priv, r)
        receipts.append(r)
        prev_hash = receipt_hash(r)
        board = board_after
    game = {"session": session, "rounds_played": len(moves),
            "final_board": board, "result": receipts[-1]["result"],
            "prev_hash": prev_hash,
            "schema_versions": dict(SCHEMA_VERSIONS)}
    game["gw_sig"] = _sign(gw_priv, game)
    game["auditor_sig"] = _sign(aud_priv, game)
    receipts.append(game)
    return receipts


# A 3-round game: a wins on round 3 (r0c0, r1c0, r2c0).
WIN_MOVES = [("r0c0", "r1c1"), ("r1c0", "r2c2"), ("r2c0", "r0c2")]
# A 5-round draw ending in a same-cell collision on the last cell,
# which side a claims (last-cell rule, ttt-v1.md section 7).
DRAW_MOVES = [("r0c0", "r0c1"), ("r0c2", "r1c1"), ("r1c0", "r1c2"),
              ("r2c1", "r2c0"), ("r2c2", "r2c2")]


def _check_draw(moves):
    board = ttt.new_board()
    for ca, cb in moves:
        if ca is not None and ca == cb:
            # Collision: only side a's mark lands (last-cell rule).
            board = ttt.apply_move(board, ca, "a")
            continue
        for cell, side in ((ca, "a"), (cb, "b")):
            if cell is not None:
                board = ttt.apply_move(board, cell, side)
    assert ttt.outcome(board) == ("draw", True), board


_check_draw(DRAW_MOVES)


class TestVerifyChain(unittest.TestCase):
    def setUp(self):
        self.gw_priv, self.gw_pub = crypto.generate_keypair()
        self.aud_priv, self.aud_pub = crypto.generate_keypair()
        self.gw_pubkey = "ed25519:" + self.gw_pub
        self.aud_pubkey = "ed25519:" + self.aud_pub

    def verify(self, chain, **kw):
        return verify_chain(chain, self.gw_pubkey, self.aud_pubkey, **kw)

    def test_valid_win_chain(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        self.assertTrue(self.verify(chain))
        self.assertEqual(chain[-1]["result"], "a")
        self.assertEqual(chain[2]["board_after"][0], "a")
        self.assertEqual(chain[2]["board_after"][3], "a")
        self.assertEqual(chain[2]["board_after"][6], "a")

    def test_valid_draw_chain(self):
        chain = build_chain(self.gw_priv, self.aud_priv, DRAW_MOVES)
        self.assertTrue(self.verify(chain))
        self.assertEqual(chain[-1]["result"], "draw")
        self.assertTrue(all(c is not None
                            for c in chain[-1]["final_board"]))

    def test_mid_game_chain_rejected_without_game_receipt(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        with self.assertRaises(ReceiptChainError):
            self.verify(chain[:-1])

    def test_bare_hex_pubkeys_accepted(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        self.assertTrue(verify_chain(chain, self.gw_pub, self.aud_pub))

    # -- tamper matrix: each must name the exact receipt --------------

    def _tampered(self, chain, pos, mutate):
        bad = copy.deepcopy(chain)
        mutate(bad[pos])
        return bad

    def test_tampered_board_after(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 1,
                             lambda r: r["board_after"].__setitem__(0, "b"))
        # board_after edit breaks gw_sig first (signatures checked
        # before replay).
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 2", str(ctx.exception))

    def test_tampered_result_with_resign(self):
        # Resign after editing so the failure lands in the replay step.
        chain = build_chain(self.gw_priv, self.aud_priv, DRAW_MOVES)
        bad = copy.deepcopy(chain)
        bad[0]["result"] = "a"
        bad[0]["gw_sig"] = _sign(self.gw_priv, bad[0])
        bad[0]["auditor_sig"] = _sign(self.aud_priv, bad[0])
        # Rechain so only the replay check fires.
        prev = receipt_hash(bad[0])
        for r in bad[1:]:
            r["prev_hash"] = prev
            r["gw_sig"] = _sign(self.gw_priv, r)
            r["auditor_sig"] = _sign(self.aud_priv, r)
            prev = receipt_hash(r)
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))
        self.assertIn("result", str(ctx.exception))

    def test_flipped_game_over_with_resign(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = copy.deepcopy(chain)
        bad[1]["game_over"] = True
        bad[1]["gw_sig"] = _sign(self.gw_priv, bad[1])
        bad[1]["auditor_sig"] = _sign(self.aud_priv, bad[1])
        prev = receipt_hash(bad[1])
        for r in bad[2:]:
            r["prev_hash"] = prev
            r["gw_sig"] = _sign(self.gw_priv, r)
            r["auditor_sig"] = _sign(self.aud_priv, r)
            prev = receipt_hash(r)
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 2", str(ctx.exception))

    def test_bad_gw_sig(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 0,
                             lambda r: r.update(gw_sig="ed25519:" + "ff" * 64))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))
        self.assertIn("gw_sig", str(ctx.exception))

    def test_bad_auditor_sig(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(
            chain, 2, lambda r: r.update(auditor_sig="ed25519:" + "ff" * 64))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 3", str(ctx.exception))

    def test_missing_auditor_sig_rejected(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 0, lambda r: r.pop("auditor_sig"))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))

    def test_wrong_auditor_key(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        _, other_pub = crypto.generate_keypair()
        with self.assertRaises(ReceiptChainError) as ctx:
            verify_chain(chain, self.gw_pubkey, "ed25519:" + other_pub)
        self.assertIn("round 1", str(ctx.exception))

    def test_broken_prev_hash_link(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 2,
                             lambda r: r.update(prev_hash="ab" * 32))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 3", str(ctx.exception))

    def test_non_genesis_first_prev_hash(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 0,
                             lambda r: r.update(prev_hash="ab" * 32))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))

    def test_reordered_rounds_still_verify(self):
        # Spec step 1 sorts by round: out-of-order delivery is fine.
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        reordered = [chain[1], chain[0], chain[2], chain[3]]
        self.assertTrue(self.verify(reordered))

    def test_duplicate_round_rejected(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = [chain[0], chain[1], copy.deepcopy(chain[1]), chain[3]]
        with self.assertRaises(ReceiptChainError):
            self.verify(bad)

    def test_round_after_game_over_rejected(self):
        # A round receipt after a game-ending round is malformed: the
        # game receipt must close the game instead (ttt-v1.md section 4).
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = copy.deepcopy(chain)
        extra = {"session": SESSION, "round": 4,
                 "commitments": {"a": None, "b": None},
                 "reveals": {"a": None, "b": None},
                 "board_after": bad[2]["board_after"], "result": "draw",
                 "game_over": False, "prev_hash": bad[3]["prev_hash"],
                 "schema_versions": dict(SCHEMA_VERSIONS)}
        extra["gw_sig"] = _sign(self.gw_priv, extra)
        extra["auditor_sig"] = _sign(self.aud_priv, extra)
        bad[3]["prev_hash"] = receipt_hash(extra)
        bad[3]["rounds_played"] = 4
        bad[3]["gw_sig"] = _sign(self.gw_priv, bad[3])
        bad[3]["auditor_sig"] = _sign(self.aud_priv, bad[3])
        bad.insert(3, extra)
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 3", str(ctx.exception))

    def test_rounds_played_mismatch(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = self._tampered(chain, 3,
                             lambda r: r.update(rounds_played=2))
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("rounds_played", str(ctx.exception))

    def test_reveal_on_taken_cell(self):
        # b reveals a's cell from round 1: the replay must catch it.
        chain = build_chain(self.gw_priv, self.aud_priv,
                            [("r0c0", "r1c1"), ("r1c0", "r0c0")])
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(chain)
        self.assertIn("round 2", str(ctx.exception))

    def test_game_receipt_final_board_mismatch(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = copy.deepcopy(chain)
        bad[-1]["final_board"] = list(reversed(bad[-1]["final_board"]))
        bad[-1]["gw_sig"] = _sign(self.gw_priv, bad[-1])
        bad[-1]["auditor_sig"] = _sign(self.aud_priv, bad[-1])
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("game receipt", str(ctx.exception))

    def test_schema_versions_inconsistent(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = copy.deepcopy(chain)
        bad[1]["schema_versions"] = {"ttt": "ttt/2"}
        bad[1]["gw_sig"] = _sign(self.gw_priv, bad[1])
        bad[1]["auditor_sig"] = _sign(self.aud_priv, bad[1])
        prev = receipt_hash(bad[1])
        for r in bad[2:]:
            r["prev_hash"] = prev
            r["gw_sig"] = _sign(self.gw_priv, r)
            r["auditor_sig"] = _sign(self.aud_priv, r)
            prev = receipt_hash(r)
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("schema_versions", str(ctx.exception))

    def test_wrong_forfeit_side(self):
        chain = build_chain(self.gw_priv, self.aud_priv, [("r0c0", "r1c1")],
                            forfeit_rounds={1: "b"})
        bad = copy.deepcopy(chain)
        bad[0]["forfeit"] = "a"
        bad[0]["gw_sig"] = _sign(self.gw_priv, bad[0])
        bad[0]["auditor_sig"] = _sign(self.aud_priv, bad[0])
        bad[1]["prev_hash"] = receipt_hash(bad[0])
        bad[1]["gw_sig"] = _sign(self.gw_priv, bad[1])
        bad[1]["auditor_sig"] = _sign(self.aud_priv, bad[1])
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))

    def test_spurious_forfeit_on_clean_round(self):
        chain = build_chain(self.gw_priv, self.aud_priv, [("r0c0", "r1c1")])
        bad = copy.deepcopy(chain)
        bad[0]["forfeit"] = "b"
        bad[0]["gw_sig"] = _sign(self.gw_priv, bad[0])
        bad[0]["auditor_sig"] = _sign(self.aud_priv, bad[0])
        bad[1]["prev_hash"] = receipt_hash(bad[0])
        bad[1]["gw_sig"] = _sign(self.gw_priv, bad[1])
        bad[1]["auditor_sig"] = _sign(self.aud_priv, bad[1])
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(bad)
        self.assertIn("round 1", str(ctx.exception))

    def test_round_after_game_receipt_rejected(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = chain + [copy.deepcopy(chain[0])]
        with self.assertRaises(ReceiptChainError):
            self.verify(bad)

    def test_two_game_receipts_rejected(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = chain + [copy.deepcopy(chain[-1])]
        with self.assertRaises(ReceiptChainError):
            self.verify(bad)

    def test_gap_in_rounds_rejected(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        bad = [chain[0], chain[2], chain[3]]
        with self.assertRaises(ReceiptChainError):
            self.verify(bad)

    def test_empty_chain_rejected(self):
        with self.assertRaises(ReceiptChainError):
            self.verify([])

    # -- edge cases from ttt-v1.md section 7 ---------------------------

    def test_same_cell_collision_is_draw(self):
        chain = build_chain(self.gw_priv, self.aud_priv,
                            [("r1c1", "r1c1")])
        self.assertTrue(self.verify(chain))
        self.assertEqual(chain[0]["board_after"], [None] * 9)
        self.assertEqual(chain[0]["result"], "draw")
        self.assertFalse(chain[0]["game_over"])

    def test_last_cell_rule_a_claims(self):
        chain = build_chain(self.gw_priv, self.aud_priv, DRAW_MOVES)
        self.assertTrue(self.verify(chain))
        # Round 5: both sides revealed r2c2, the only empty cell; side a
        # claims it. No line completes, so the full board is a draw.
        self.assertEqual(chain[4]["board_after"][8], "a")
        self.assertEqual(chain[4]["result"], "draw")
        self.assertTrue(chain[4]["game_over"])
        self.assertEqual(chain[-1]["result"], "draw")

    def test_double_win_is_draw(self):
        # a completes the top row, b the middle row, same round.
        moves = [("r0c0", "r1c0"), ("r0c1", "r1c1"), ("r0c2", "r1c2")]
        chain = build_chain(self.gw_priv, self.aud_priv, moves)
        self.assertTrue(self.verify(chain))
        self.assertEqual(chain[2]["result"], "draw")
        self.assertTrue(chain[2]["game_over"])

    def test_a_wins_b_recorded_not_applied(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        # Round 3: a took r2c0 and won; b's r0c2 must be recorded but
        # the board must not carry it.
        self.assertEqual(chain[2]["reveals"]["b"], {"cell": "r0c2"})
        self.assertIsNone(chain[2]["board_after"][2])
        self.assertTrue(self.verify(chain))

    # -- forfeits (ttt-v1.md section 5) ---------------------------------

    def test_commit_timeout_forfeit(self):
        chain = build_chain(self.gw_priv, self.aud_priv, [("r0c0", "r1c1")],
                            forfeit_rounds={1: "b"})
        self.assertTrue(self.verify(chain))
        r = chain[0]
        self.assertEqual(r["forfeit"], "b")
        self.assertIsNone(r["commitments"]["b"])
        self.assertIsNone(r["reveals"]["a"])
        self.assertIsNone(r["reveals"]["b"])
        self.assertEqual(r["board_after"], [None] * 9)
        self.assertEqual(r["result"], "draw")
        self.assertFalse(r["game_over"])

    def test_reveal_timeout_forfeit(self):
        # b commits but never reveals: a's cell is applied, b forfeits.
        gw_priv, aud_priv = self.gw_priv, self.aud_priv
        receipts = []
        prev = GENESIS_PREV_HASH
        kb = _commit(AGENT_B, "r1c1", "sec-b-1", 1)
        r = {"session": SESSION, "round": 1,
             "commitments": {"a": _commit(AGENT_A, "r0c0", "sec-a-1", 1),
                             "b": kb},
             "reveals": {"a": {"cell": "r0c0"}, "b": None},
             "board_after": ["a"] + [None] * 8, "result": "draw",
             "game_over": False, "prev_hash": prev,
             "schema_versions": dict(SCHEMA_VERSIONS), "forfeit": "b"}
        r["gw_sig"] = _sign(gw_priv, r)
        r["auditor_sig"] = _sign(aud_priv, r)
        receipts.append(r)
        game = {"session": SESSION, "rounds_played": 1,
                "final_board": ["a"] + [None] * 8, "result": "draw",
                "prev_hash": receipt_hash(r),
                "schema_versions": dict(SCHEMA_VERSIONS)}
        game["gw_sig"] = _sign(gw_priv, game)
        game["auditor_sig"] = _sign(aud_priv, game)
        receipts.append(game)
        self.assertTrue(self.verify(receipts))

    # -- step 4: commitment publication ----------------------------------

    def test_commits_published_match(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        log = {r["round"]: {"a": r["commitments"]["a"],
                            "b": r["commitments"]["b"]}
               for r in chain if "round" in r}
        self.assertTrue(self.verify(chain, commits_published=log))

    def test_commits_published_mismatch(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        log = {r["round"]: {"a": r["commitments"]["a"],
                            "b": r["commitments"]["b"]}
               for r in chain if "round" in r}
        log[2]["a"] = "cc" * 32
        with self.assertRaises(ReceiptChainError) as ctx:
            self.verify(chain, commits_published=log)
        self.assertIn("round 2", str(ctx.exception))

    # -- auditor helper ---------------------------------------------------

    def test_auditor_countersign_verifies(self):
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        unsigned = copy.deepcopy(chain[0])
        unsigned.pop("auditor_sig")
        sig = auditor_mod.countersign(unsigned, self.aud_priv)
        self.assertTrue(sig.startswith("ed25519:"))
        msg = receipt_signing_bytes(unsigned)
        self.assertTrue(crypto.verify(
            self.aud_pub, msg, bytes.fromhex(sig[len("ed25519:"):])))
        # And it equals the signature on the built chain.
        self.assertEqual(sig, chain[0]["auditor_sig"])

    def test_receipt_hash_covers_sigs(self):
        # Spec: prev_hash is over as-published bytes, sigs included.
        chain = build_chain(self.gw_priv, self.aud_priv, WIN_MOVES)
        self.assertEqual(chain[1]["prev_hash"], receipt_hash(chain[0]))
        self.assertEqual(receipt_hash(chain[0]),
                         hashlib.sha256(canonical(chain[0])).hexdigest())
        # Changing a signature changes the hash.
        altered = copy.deepcopy(chain[0])
        altered["gw_sig"] = "ed25519:" + "aa" * 64
        self.assertNotEqual(receipt_hash(altered), receipt_hash(chain[0]))


if __name__ == "__main__":
    unittest.main()
