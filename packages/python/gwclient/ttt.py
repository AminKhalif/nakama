# SPDX-License-Identifier: Apache-2.0
"""Pure tic-tac-toe rules (schema ttt/1), shared by the auditor helpers
and the independent receipt verifier.

Spec model (spec/ttt-v1.md): sides are "a" (first) and "b"; the board is
a flat 9-list of None/"a"/"b", cumulative across rounds of one game;
each round both sides commit simultaneously, then reveal; revealed cells
apply in deterministic order, side a first, with a terminal check after
each application.

Cell: "r<row>c<col>", zero-based, e.g. "r0c2" is top-right.
"""

import re

CELL_RE = re.compile(r"^r([0-2])c([0-2])$")
SIDES = ("a", "b")

_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
          (0, 3, 6), (1, 4, 7), (2, 5, 8),   # columns
          (0, 4, 8), (2, 4, 6))              # diagonals


class IllegalMove(ValueError):
    """A move breaks the rules: bad cell format, or the cell is taken."""


def parse_cell(cell):
    """'r0c2' -> (0, 2). Raises IllegalMove on bad format."""
    if not isinstance(cell, str):
        raise IllegalMove("cell must be a string like 'r0c2', got %r"
                          % (cell,))
    m = CELL_RE.match(cell)
    if not m:
        raise IllegalMove("cell %r is not of the form 'r<0-2>c<0-2>'"
                          % (cell,))
    return int(m.group(1)), int(m.group(2))


def cell_index(cell):
    """'r0c2' -> 2. Raises IllegalMove on bad format."""
    row, col = parse_cell(cell)
    return row * 3 + col


def new_board():
    """Fresh empty board: [None] * 9."""
    return [None] * 9


def check_move(board, cell):
    """Legality check: returns (row, col) if the cell is free on this
    board, raises IllegalMove otherwise. Does not mutate anything."""
    row, col = parse_cell(cell)
    if not isinstance(board, list) or len(board) != 9:
        raise IllegalMove("board must be a 9-list of None/'a'/'b'")
    if board[row * 3 + col] is not None:
        raise IllegalMove("cell %r is already occupied" % (cell,))
    return row, col


def apply_move(board, cell, side):
    """New board with side's mark at cell. Raises IllegalMove if taken."""
    if side not in SIDES:
        raise IllegalMove("side must be 'a' or 'b', got %r" % (side,))
    check_move(board, cell)
    out = list(board)
    row, col = parse_cell(cell)
    out[row * 3 + col] = side
    return out


def has_line(board, side):
    """True when side has three in a row on the board."""
    for x, y, z in _LINES:
        if board[x] == board[y] == board[z] == side:
            return True
    return False


def check_win(board):
    """'a' or 'b' on three in a row, else None."""
    for x, y, z in _LINES:
        if board[x] is not None and board[x] == board[y] == board[z]:
            return board[x]
    return None


def is_full(board):
    """True when no empty cells remain."""
    return all(cell is not None for cell in board)


def outcome(board):
    """(result, game_over) for a board. result is 'a', 'b', or 'draw';
    game_over is true exactly when a side has three in a row or the
    board is full. A position with lines for both sides is a draw
    (the double-win rule, ttt-v1.md section 7)."""
    lines = {side: has_line(board, side) for side in SIDES}
    if lines["a"] and not lines["b"]:
        return "a", True
    if lines["b"] and not lines["a"]:
        return "b", True
    if lines["a"] or lines["b"] or is_full(board):
        return "draw", True
    return "draw", False
