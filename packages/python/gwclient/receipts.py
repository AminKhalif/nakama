# SPDX-License-Identifier: Apache-2.0
"""Independent receipt-chain verifier (spec/receipts.md).

Takes a list of receipts plus the gateway's and auditor's public keys
and verifies the whole chain, implementing the chain verification
algorithm in receipts.md section 3 step by step:

1. order and completeness (rounds 1..N, N == rounds_played),
2. both Ed25519 signatures on every receipt,
3. hash links (genesis "0"*64, then sha256 over as-published bytes),
4. commitment publication (against an optional message log),
5. board transitions (simultaneous-round replay, a-first application),
6. outcome (win/draw recomputed from the 8 lines),
7. schema pinning.

Imports nothing but gwclient's own crypto/envelope/ttt helpers: any
agent can run this offline on receipts plus this spec. Returns True on
success; raises ReceiptChainError naming the exact failing receipt
otherwise.

What this proves and does not prove is stated in receipts.md: the
commitment-to-(cell, secret) binding is NOT recheckable by a third
party (secrets are excluded by design); the chain is the gateway's and
auditor's signed attestation that reveal-time verification happened.
"""

import hashlib
import re

from . import crypto
from .envelope import canonical
from . import ttt

GENESIS_PREV_HASH = "0" * 64
_SIG_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SESSION_RE = re.compile(r"^sess_[0-9a-f]+$")
_RESULT_RE = re.compile(r"^(a|b|draw)$")


class ReceiptChainError(ValueError):
    """A receipt chain failed verification. The message names the exact
    receipt (round number or the game receipt) and the failed check."""


def receipt_signing_bytes(receipt):
    """The bytes both signatures cover: canonical JSON of the receipt
    with gw_sig and auditor_sig removed (receipts.md section 1)."""
    unsigned = {k: v for k, v in receipt.items()
                if k not in ("gw_sig", "auditor_sig")}
    return canonical(unsigned)


def receipt_hash(receipt):
    """SHA-256 hex of the canonical bytes of the receipt AS PUBLISHED,
    both signature fields included (receipts.md section 3, step 3)."""
    return hashlib.sha256(canonical(receipt)).hexdigest()


def _key_hex(key):
    """Normalize a public key to bare 64 hex chars. Accepts the spec's
    "ed25519:<64 hex>" form or bare hex."""
    if key.startswith("ed25519:"):
        key = key[len("ed25519:"):]
    try:
        raw = bytes.fromhex(key)
    except (ValueError, TypeError):
        raise ReceiptChainError("public key is not hex")
    if len(raw) != 32:
        raise ReceiptChainError("public key is not 32 bytes")
    return key


def _fail(where, message):
    raise ReceiptChainError("%s: %s" % (where, message))


def _check_sig_format(where, receipt):
    for field in ("gw_sig", "auditor_sig"):
        sig = receipt.get(field)
        if not isinstance(sig, str) or not _SIG_RE.match(sig):
            _fail(where, "field %r must be 'ed25519:' + 128 hex chars"
                  % (field,))


def _check_round_shape(pos, r):
    where = "round receipt #%d" % pos
    if not isinstance(r.get("round"), int) or r["round"] < 1:
        _fail(where, "'round' must be an integer >= 1")
    where = "round %d" % r["round"]
    if not isinstance(r.get("session"), str) or \
            not _SESSION_RE.match(r["session"]):
        _fail(where, "'session' must match ^sess_[0-9a-f]+$")
    for side in ("a", "b"):
        commits = r.get("commitments")
        if not isinstance(commits, dict):
            _fail(where, "'commitments' must be an object keyed by side")
        commit = commits.get(side)
        if commit is not None and not _HASH_RE.match(commit):
            _fail(where, "commitments.%s must be 64 hex or null" % side)
        reveals = r.get("reveals")
        if not isinstance(reveals, dict):
            _fail(where, "'reveals' must be an object keyed by side")
        reveal = reveals.get(side)
        if reveal is not None:
            if not isinstance(reveal, dict):
                _fail(where, "reveals.%s must be an object or null" % side)
            cell = reveal.get("cell")
            try:
                ttt.parse_cell(cell)
            except ttt.IllegalMove as exc:
                _fail(where, "reveals.%s.cell invalid: %s" % (side, exc))
    board = r.get("board_after")
    if not isinstance(board, list) or len(board) != 9 or \
            any(c not in ("a", "b", None) for c in board):
        _fail(where, "'board_after' must be 9 cells of 'a'/'b'/null")
    if not isinstance(r.get("result"), str) or \
            not _RESULT_RE.match(r["result"]):
        _fail(where, "'result' must be 'a', 'b', or 'draw'")
    if not isinstance(r.get("game_over"), bool):
        _fail(where, "'game_over' must be a boolean")
    if not _HASH_RE.match(r.get("prev_hash") or ""):
        _fail(where, "'prev_hash' must be 64 hex chars")
    forfeit = r.get("forfeit")
    if forfeit not in (None, "a", "b"):
        _fail(where, "'forfeit' must be null, 'a', or 'b'")
    _check_sig_format(where, r)
    return where


def _check_game_shape(r):
    where = "game receipt"
    if not isinstance(r.get("rounds_played"), int) or \
            not 1 <= r["rounds_played"] <= 5:
        _fail(where, "'rounds_played' must be an integer 1..5")
    board = r.get("final_board")
    if not isinstance(board, list) or len(board) != 9 or \
            any(c not in ("a", "b", None) for c in board):
        _fail(where, "'final_board' must be 9 cells of 'a'/'b'/null")
    if not isinstance(r.get("result"), str) or \
            not _RESULT_RE.match(r["result"]):
        _fail(where, "'result' must be 'a', 'b', or 'draw'")
    if not isinstance(r.get("session"), str) or \
            not _SESSION_RE.match(r["session"]):
        _fail(where, "'session' must match ^sess_[0-9a-f]+$")
    if not _HASH_RE.match(r.get("prev_hash") or ""):
        _fail(where, "'prev_hash' must be 64 hex chars")
    _check_sig_format(where, r)


def _replay_round(board, r):
    """Apply one round receipt's reveals to the board per receipts.md
    section 3 step 5 and ttt-v1.md section 7.

    Returns (board_after, result, game_over). Raises ReceiptChainError
    naming the round on any inconsistency.
    """
    where = "round %s" % r["round"]
    ca = r["reveals"]["a"]["cell"] if r["reveals"]["a"] else None
    cb = r["reveals"]["b"]["cell"] if r["reveals"]["b"] else None
    ka = r["commitments"]["a"]
    kb = r["commitments"]["b"]
    forfeit = r.get("forfeit")

    # Forfeit-shape consistency (ttt-v1.md section 5).
    a_no_commit = ka is None
    b_no_commit = kb is None
    a_no_reveal = ka is not None and ca is None
    b_no_reveal = kb is not None and cb is None
    if a_no_commit and b_no_commit:
        if forfeit is not None:
            _fail(where, "no side committed, 'forfeit' must be null")
    elif a_no_commit or b_no_commit:
        want = "a" if a_no_commit else "b"
        if forfeit != want:
            _fail(where, "commit-timeout forfeit, 'forfeit' must be %r"
                  % (want,))
        if ca is not None or cb is not None:
            _fail(where, "commit-timeout round must have no reveals")
    elif a_no_reveal and b_no_reveal:
        if forfeit is not None:
            _fail(where, "no side revealed, 'forfeit' must be null")
    elif a_no_reveal or b_no_reveal:
        want = "a" if a_no_reveal else "b"
        if forfeit != want:
            _fail(where, "reveal-timeout forfeit, 'forfeit' must be %r"
                  % (want,))
    elif forfeit is not None:
        _fail(where, "clean round must not name a forfeit")

    if ca is None and cb is None:
        # Double forfeit: the board is unchanged.
        return list(board), "draw", False

    if ca is not None and ca == cb:
        # Same-cell collision: drawn round, board unchanged — except
        # the last-cell rule, where side a claims the final cell.
        idx = ttt.cell_index(ca)
        if board[idx] is not None:
            _fail(where, "revealed cell %r is not empty" % (ca,))
        if all(c is not None for i, c in enumerate(board) if i != idx):
            claimed = list(board)
            claimed[idx] = "a"
            result, game_over = ttt.outcome(claimed)
            return claimed, result, game_over
        return list(board), "draw", False

    after_a = list(board)
    if ca is not None:
        idx = ttt.cell_index(ca)
        if after_a[idx] is not None:
            _fail(where, "side a revealed taken cell %r" % (ca,))
        after_a[idx] = "a"
    a_wins = ttt.has_line(after_a, "a")
    a_full = ttt.is_full(after_a)

    if cb is not None:
        # Simultaneous reveals: b's legality is judged against the
        # board as b saw it, i.e. before a's application.
        idx = ttt.cell_index(cb)
        if board[idx] is not None:
            _fail(where, "side b revealed taken cell %r" % (cb,))

    after_b = list(after_a)
    if cb is not None:
        after_b[ttt.cell_index(cb)] = "b"
    b_wins = ttt.has_line(after_b, "b")

    if a_wins and b_wins:
        # Double win (ttt-v1.md section 7): both lines complete — a draw.
        return after_b, "draw", True
    if a_wins:
        # The game ended on a's move; b's cell is recorded but not
        # applied.
        return after_a, "a", True
    if a_full:
        return after_a, "draw", True
    if b_wins:
        return after_b, "b", True
    if ttt.is_full(after_b):
        return after_b, "draw", True
    return after_b, "draw", False


def verify_chain(receipts, gw_pubkey, auditor_pubkey,
                 commits_published=None):
    """Verify a receipt chain per receipts.md section 3. Returns True.

    receipts: the ordered list from gw.receipts (round receipts, then
    the game receipt). gw_pubkey / auditor_pubkey: 32-byte keys as
    "ed25519:<64 hex>" (spec form) or bare 64 hex. commits_published:
    optional message log {round: {"a": hex|None, "b": hex|None}} from
    the session's ttt.commits_published messages, re-checked per
    algorithm step 4 when provided.
    """
    if not isinstance(receipts, list) or not receipts or \
            not all(isinstance(r, dict) for r in receipts):
        raise ReceiptChainError("receipts must be a non-empty list of "
                                "receipt dicts")

    rounds = [r for r in receipts if "rounds_played" not in r]
    games = [r for r in receipts if "rounds_played" in r]
    if len(games) != 1:
        raise ReceiptChainError("chain must hold exactly one game "
                                "receipt, found %d" % len(games))
    game = games[0]
    if receipts[-1] is not game:
        raise ReceiptChainError("the game receipt must close the chain")
    _check_game_shape(game)

    # Step 1: order and completeness.
    for pos, r in enumerate(rounds):
        _check_round_shape(pos, r)
    ordered = sorted(rounds, key=lambda r: r["round"])
    want_rounds = list(range(1, len(ordered) + 1))
    got_rounds = [r["round"] for r in ordered]
    if got_rounds != want_rounds:
        raise ReceiptChainError("round receipts must be exactly 1..%d "
                                "with no gaps or duplicates, got %r"
                                % (len(ordered), got_rounds))
    if game["rounds_played"] != len(ordered):
        raise ReceiptChainError("game receipt rounds_played=%d != %d "
                                "round receipts"
                                % (game["rounds_played"], len(ordered)))

    sessions = {r["session"] for r in ordered} | {game["session"]}
    if len(sessions) != 1:
        raise ReceiptChainError("receipts span sessions: %r" % sessions)

    # Step 7 (early): schema pinning — present and consistent.
    versions = [r.get("schema_versions") for r in ordered] + \
               [game.get("schema_versions")]
    if any(not isinstance(v, dict) or not v for v in versions):
        raise ReceiptChainError("'schema_versions' must be a non-empty "
                                "object on every receipt")
    if any(v != versions[0] for v in versions):
        raise ReceiptChainError("'schema_versions' differs across "
                                "receipts")

    gw_key = _key_hex(gw_pubkey)
    auditor_key = _key_hex(auditor_pubkey)

    # Step 2: signatures, every receipt.
    for r in ordered + [game]:
        where = ("round %s" % r["round"]) if r is not game \
            else "game receipt"
        msg = receipt_signing_bytes(r)
        for field, key in (("gw_sig", gw_key),
                           ("auditor_sig", auditor_key)):
            sig = bytes.fromhex(r[field][len("ed25519:"):])
            if not crypto.verify(key, msg, sig):
                _fail(where, "%s is not a valid signature" % (field,))

    # Step 3: hash links, as-published bytes (signatures included).
    if ordered[0]["prev_hash"] != GENESIS_PREV_HASH:
        _fail("round 1", "prev_hash must be the genesis marker %r"
              % (GENESIS_PREV_HASH,))
    prev = ordered[0]
    for r in ordered[1:] + [game]:
        where = ("round %s" % r["round"]) if r is not game \
            else "game receipt"
        if r["prev_hash"] != receipt_hash(prev):
            _fail(where, "prev_hash does not match the previous "
                         "receipt's hash")
        prev = r

    # Step 4: commitment publication, when the message log is provided.
    if commits_published is not None:
        for r in ordered:
            published = commits_published.get(r["round"])
            if published != {"a": r["commitments"]["a"],
                             "b": r["commitments"]["b"]}:
                _fail("round %s" % r["round"],
                      "commitments differ from the published "
                      "ttt.commits_published message")

    # Steps 5+6: replay the boards, recompute the outcomes.
    board = ttt.new_board()
    for i, r in enumerate(ordered):
        board_after, result, game_over = _replay_round(board, r)
        where = "round %s" % r["round"]
        if board_after != r["board_after"]:
            _fail(where, "board_after != recomputed board")
        if result != r["result"]:
            _fail(where, "result %r != recomputed %r"
                  % (r["result"], result))
        if game_over != r["game_over"]:
            _fail(where, "game_over %r != recomputed %r"
                  % (r["game_over"], game_over))
        if not game_over and result != "draw":
            _fail(where, "result must be 'draw' while the game continues")
        if game_over and i != len(ordered) - 1:
            _fail(where, "the game ended here; no further round may "
                         "follow")
        board = board_after

    last = ordered[-1]
    if game["final_board"] != last["board_after"]:
        _fail("game receipt", "final_board != last round's board_after")
    if game["result"] != last["result"]:
        _fail("game receipt", "result != last round's result")
    return True
