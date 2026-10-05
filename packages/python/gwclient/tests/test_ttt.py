# SPDX-License-Identifier: Apache-2.0
"""Pure tic-tac-toe rules."""

import unittest

from gwclient import ttt
from gwclient.ttt import IllegalMove


class TestTtt(unittest.TestCase):
    def test_parse_cell(self):
        self.assertEqual(ttt.parse_cell("r0c2"), (0, 2))
        self.assertEqual(ttt.parse_cell("r2c0"), (2, 0))
        for bad in ("r3c0", "r0c3", "a1", "r0", "", None, "R0C1"):
            with self.subTest(cell=bad):
                with self.assertRaises(IllegalMove):
                    ttt.parse_cell(bad)

    def test_apply_and_win(self):
        board = ttt.new_board()
        for cell in ("r0c0", "r0c1"):
            board = ttt.apply_move(board, cell, "a")
        self.assertIsNone(ttt.check_win(board))
        board = ttt.apply_move(board, "r0c2", "a")
        self.assertEqual(ttt.check_win(board), "a")
        self.assertEqual(ttt.outcome(board)[0], "a")

    def test_taken_cell_rejected(self):
        board = ttt.apply_move(ttt.new_board(), "r1c1", "b")
        with self.assertRaises(IllegalMove):
            ttt.check_move(board, "r1c1")
        with self.assertRaises(IllegalMove):
            ttt.apply_move(board, "r1c1", "a")

    def test_draw(self):
        board = ttt.new_board()
        moves = [("r0c0", "a"), ("r0c1", "b"), ("r0c2", "a"),
                 ("r1c0", "a"), ("r1c1", "b"), ("r1c2", "b"),
                 ("r2c0", "b"), ("r2c1", "a"), ("r2c2", "a")]
        for cell, side in moves:
            board = ttt.apply_move(board, cell, side)
        self.assertIsNone(ttt.check_win(board))
        self.assertEqual(ttt.outcome(board)[0], "draw")

    def test_diagonal_win(self):
        board = ttt.new_board()
        for cell in ("r0c0", "r1c1", "r2c2"):
            board = ttt.apply_move(board, cell, "b")
        self.assertEqual(ttt.check_win(board), "b")



    def test_outcome_game_over(self):
        self.assertEqual(ttt.outcome(ttt.new_board()), ("draw", False))
        board = ttt.new_board()
        for cell in ("r0c0", "r0c1"):
            board = ttt.apply_move(board, cell, "a")
        self.assertEqual(ttt.outcome(board), ("draw", False))
        board = ttt.apply_move(board, "r0c2", "a")
        self.assertEqual(ttt.outcome(board), ("a", True))
        full = ["a", "b", "a", "a", "b", "b", "b", "a", "a"]
        self.assertEqual(ttt.outcome(full), ("draw", True))
        self.assertTrue(ttt.is_full(full))
        self.assertFalse(ttt.is_full(ttt.new_board()))

    def test_outcome_double_win_is_draw(self):
        board = ["a", "a", None, "b", "b", None, None, None, None]
        board = ttt.apply_move(board, "r0c2", "a")
        board = ttt.apply_move(board, "r1c2", "b")
        self.assertEqual(ttt.outcome(board), ("draw", True))


if __name__ == "__main__":
    unittest.main()
