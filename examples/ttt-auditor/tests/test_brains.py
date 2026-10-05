# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the ttt-auditor brains. No gateway, no network.

Covers the Brain interface contract, scripted determinism, the LLM
fallback paths (no key, failed call, illegal output -- none of these may
touch the network), and an offline simulation of run_demo.py's three
scripted match layouts proving they produce exactly a-win, b-win, and
draw (the draw via the last-cell rule).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brains import parse_brain_spec
from brains.scripted import CenterFirst, RandomSeeded, Scripted
from brains.llm import LLMBrain

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "packages", "python"))
from gwclient.ttt import apply_move, new_board, outcome  # noqa: E402


def sim_round(board, ca, cb):
    """One simultaneous round per spec/ttt-v1.md section 7. Returns
    (board_after, result, game_over)."""
    empties = [i for i, c in enumerate(board) if c is None]
    if ca == cb:
        idx = int(ca[1]) * 3 + int(ca[3])
        if empties == [idx]:  # last-cell rule: side a claims it
            claimed = apply_move(board, ca, "a")
            result, over = outcome(claimed)
            return claimed, result, True
        return list(board), "draw", False  # same-cell collision
    after_a = apply_move(board, ca, "a")
    result, over = outcome(after_a)
    if over:  # b's cell recorded but not applied
        return after_a, result, True
    after_b = apply_move(after_a, cb, "b")
    result, over = outcome(after_b)
    return after_b, result, over


def play_out(a_brain, b_brain):
    """Play scripted brains against each other offline. Returns
    (result, rounds, boards)."""
    board, rounds, boards = new_board(), 0, []
    while True:
        rounds += 1
        if rounds > 9:
            raise AssertionError("game did not terminate")
        ca = a_brain.choose_move(list(board), "a")
        cb = b_brain.choose_move(list(board), "b")
        board, result, over = sim_round(board, ca, cb)
        boards.append(list(board))
        if over:
            return result, rounds, boards


class BrainContract(unittest.TestCase):
    def check(self, brain):
        board = new_board()
        for _ in range(9):
            cell = brain.choose_move(list(board), "a")
            self.assertRegex(cell, r"^r[0-2]c[0-2]$")
            idx = int(cell[1]) * 3 + int(cell[3])
            self.assertIsNone(board[idx])
            board[idx] = "a"
        with self.assertRaises(ValueError):
            brain.choose_move(board, "a")

    def test_center_first(self):
        self.assertEqual(CenterFirst().choose_move(new_board(), "a"),
                         "r1c1")
        self.check(CenterFirst())

    def test_scripted(self):
        b = Scripted(["r0c0", "r2c2"], name="t")
        self.assertEqual(b.choose_move(new_board(), "b"), "r0c0")
        board = new_board()
        board[0] = "a"
        self.assertEqual(b.choose_move(board, "b"), "r2c2")
        self.check(Scripted(["r%dc%d" % (i // 3, i % 3)
                             for i in range(9)]))

    def test_scripted_rejects_bad_cells(self):
        with self.assertRaises(ValueError):
            Scripted(["r9c9"])

    def test_random_seeded_deterministic(self):
        boards = [new_board(), new_board()]
        boards[1][4] = "b"
        first = [RandomSeeded(7).choose_move(list(b), "a") for b in boards]
        second = [RandomSeeded(7).choose_move(list(b), "a") for b in boards]
        self.assertEqual(first, second)
        self.check(RandomSeeded(123))

    def test_parse_brain_spec(self):
        self.assertIsInstance(parse_brain_spec("center"), CenterFirst)
        self.assertIsInstance(parse_brain_spec("seed:42"), RandomSeeded)
        self.assertIsInstance(parse_brain_spec("list:r0c0,r1c1"),
                              Scripted)
        with self.assertRaises(ValueError):
            parse_brain_spec("bogus")


class ScriptedMatchLayouts(unittest.TestCase):
    """The exact layouts run_demo.py plays, simulated offline."""

    def test_match1_a_wins_diagonal(self):
        a = Scripted(["r0c0", "r1c1", "r2c2",
                      "r0c1", "r0c2", "r1c0", "r1c2", "r2c0", "r2c1"])
        b = Scripted(["r0c1", "r2c0", "r0c2",
                      "r1c0", "r1c2", "r2c1", "r0c0", "r1c1", "r2c2"])
        result, rounds, boards = play_out(a, b)
        self.assertEqual(result, "a")
        self.assertEqual(rounds, 3)
        # a's diagonal is on the board; b's last cell was not applied
        self.assertEqual([boards[-1][i] for i in (0, 4, 8)],
                         ["a", "a", "a"])

    def test_match2_b_wins_bottom_row(self):
        a = Scripted(["r0c0", "r0c2", "r1c1",
                      "r1c0", "r1c2", "r0c1", "r2c0", "r2c1", "r2c2"])
        b = Scripted(["r2c0", "r2c1", "r2c2",
                      "r0c1", "r1c0", "r1c2", "r0c0", "r0c2", "r1c1"])
        result, rounds, boards = play_out(a, b)
        self.assertEqual(result, "b")
        self.assertEqual(rounds, 3)
        self.assertEqual([boards[-1][i] for i in (6, 7, 8)],
                         ["b", "b", "b"])

    def test_match3_draw_last_cell_rule(self):
        a = Scripted(["r0c0", "r0c2", "r1c0", "r2c1", "r2c2",
                      "r0c1", "r1c1", "r1c2", "r2c0"])
        b = Scripted(["r0c1", "r1c1", "r1c2", "r2c0", "r2c2",
                      "r0c0", "r0c2", "r1c0", "r2c1"])
        result, rounds, boards = play_out(a, b)
        self.assertEqual(result, "draw")
        self.assertEqual(rounds, 5)
        final = boards[-1]
        self.assertNotIn(None, final)  # board full
        self.assertEqual(final, ["a", "b", "a",
                                 "a", "b", "b",
                                 "b", "a", "a"])
        # no three-in-a-row for either side
        self.assertEqual(outcome(final), ("draw", True))


class LLMFallback(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("NVIDIA_API_KEY", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["NVIDIA_API_KEY"] = self._saved

    def test_no_key_uses_fallback(self):
        brain = LLMBrain(fallback=CenterFirst())
        self.assertFalse(LLMBrain.available())
        self.assertEqual(brain.choose_move(new_board(), "a"), "r1c1")

    def test_failed_call_uses_fallback(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key-not-real"
        brain = LLMBrain(fallback=CenterFirst())
        self.assertTrue(LLMBrain.available())
        brain._query = lambda board, me, key: (_ for _ in ()).throw(
            RuntimeError("boom"))
        self.assertEqual(brain.choose_move(new_board(), "a"), "r1c1")

    def test_illegal_output_uses_fallback(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key-not-real"
        brain = LLMBrain(fallback=CenterFirst())
        board = new_board()
        board[4] = "b"  # center taken
        brain._query = lambda board, me, key: "r1c1"  # illegal now
        move = brain.choose_move(board, "a")
        self.assertNotEqual(move, "r1c1")
        self.assertRegex(move, r"^r[0-2]c[0-2]$")

    def test_legal_output_is_used(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key-not-real"
        brain = LLMBrain(fallback=CenterFirst())
        # _query extracts the cell from model chatter; here it returns the
        # extracted cell directly.
        brain._query = lambda board, me, key: "r0c2"
        self.assertEqual(brain.choose_move(new_board(), "a"), "r0c2")

    def test_query_parses_cell_from_chatter(self):
        import io
        import json
        import urllib.request
        from brains import llm as llm_mod

        os.environ["NVIDIA_API_KEY"] = "nvapi-test-key-not-real"
        brain = LLMBrain(fallback=CenterFirst())

        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{"message": {
                        "content": "My move is r2c0. Good luck!"}}]
                }).encode()

        def fake_urlopen(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            captured["url"] = req.full_url
            return FakeResp()

        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            cell = brain._query(new_board(), "b",
                                os.environ["NVIDIA_API_KEY"])
        finally:
            urllib.request.urlopen = real
        self.assertEqual(cell, "r2c0")
        self.assertTrue(captured["auth"].startswith("Bearer "))
        self.assertNotIn(os.environ["NVIDIA_API_KEY"],
                         captured["url"])
        self.assertTrue(captured["url"].endswith("/chat/completions"))


if __name__ == "__main__":
    unittest.main()
