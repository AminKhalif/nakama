# SPDX-License-Identifier: Apache-2.0
"""Deterministic scripted brains. The default: no network, no keys, no
surprises. Integration tests and run_demo.py use these exclusively."""

import random

# Local cell helpers are defined here on purpose: brains must not depend
# on the gateway or on networking, and this keeps them importable without
# sys.path tricks from the tests.
CELL_RE_PARTS = ("r", "c")


def _cell_index(cell):
    """'r0c2' -> 2. Raises ValueError on bad format."""
    if (not isinstance(cell, str) or len(cell) != 4
            or cell[0] != "r" or cell[2] != "c"
            or not cell[1].isdigit() or not cell[3].isdigit()):
        raise ValueError("bad cell %r: want 'r<0-2>c<0-2>'" % (cell,))
    row, col = int(cell[1]), int(cell[3])
    if row > 2 or col > 2:
        raise ValueError("bad cell %r: rows/cols are 0..2" % (cell,))
    return row * 3 + col


def _cell_name(index):
    return "r%dc%d" % (index // 3, index % 3)


def _check_board(board):
    if (not isinstance(board, list) or len(board) != 9
            or any(c not in ("a", "b", None) for c in board)):
        raise ValueError("board must be a 9-list of 'a'/'b'/None")
    return board


class ScriptedBrain:
    """Take the first empty cell from a fixed priority list.

    Deterministic, side-agnostic: the same list always yields the same
    move on the same board. Two players with *disjoint* lists never
    collide; that is how run_demo.py scripts exact win/draw layouts.
    """

    def __init__(self, priority, name=None):
        self.priority = list(priority)
        if not self.priority:
            raise ValueError("priority list must not be empty")
        for cell in self.priority:
            _cell_index(cell)  # validate format now, not mid-game
        self.name = name or "scripted"

    def choose_move(self, board, me):
        _check_board(board)
        if me not in ("a", "b"):
            raise ValueError("me must be 'a' or 'b', got %r" % (me,))
        for cell in self.priority:
            if board[_cell_index(cell)] is None:
                return cell
        raise ValueError("no legal move: board is full")


# Backwards-friendly alias used across the demo scripts.
Scripted = ScriptedBrain


class CenterFirst(ScriptedBrain):
    """The classic opener: center, then corners, then edges."""

    def __init__(self):
        super(CenterFirst, self).__init__(
            ["r1c1",
             "r0c0", "r0c2", "r2c0", "r2c2",
             "r0c1", "r1c0", "r1c2", "r2c1"],
            name="center-first")


class RandomSeeded:
    """Uniform random legal move from a seeded PRNG. Deterministic for a
    given seed and board sequence: same seed + same boards = same moves."""

    def __init__(self, seed, name=None):
        self._rng = random.Random(seed)
        self.name = name or "random-seeded(%r)" % (seed,)

    def choose_move(self, board, me):
        _check_board(board)
        if me not in ("a", "b"):
            raise ValueError("me must be 'a' or 'b', got %r" % (me,))
        empties = [_cell_name(i) for i, c in enumerate(board) if c is None]
        if not empties:
            raise ValueError("no legal move: board is full")
        return self._rng.choice(empties)
