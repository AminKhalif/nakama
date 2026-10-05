"""Tic-tac-toe sessions (schema ttt/1), refereed live by the gateway.

One session is one game. Rounds are simultaneous: both sides commit
sha256("gw/1|<session>|r<round>|<agent_id>|<cell>|<secret>"), the gateway
publishes the shuffled hashes, both sides reveal, and the gateway applies
side a's cell then side b's cell, checking for a terminal position after
each. See spec/ttt-v1.md.

Deadlines cost the round, never the game. Missed commit/reveal deadlines
produce a forfeit round receipt; a missing auditor countersignature freezes
the session. Secrets are verify-then-discard: never stored, never logged,
never in receipts.
"""

import hashlib
import random
import time
import uuid
from datetime import datetime, timezone

from . import friends, receipts, wire

APP = "ttt"
SCHEMA = "ttt/1"
DEFAULT_TIMEOUT_S = 600
TIMEOUT_MIN = 1
TIMEOUT_MAX = 86400

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
         (0, 3, 6), (1, 4, 7), (2, 5, 8),
         (0, 4, 8), (2, 4, 6))


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _aname(store, agent_id):
    a = store.get_agent(agent_id)
    return a["name"] if a else agent_id


def _clamp_timeout(value, default=DEFAULT_TIMEOUT_S):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(TIMEOUT_MIN, min(TIMEOUT_MAX, v))


def _side(session, agent_id):
    if agent_id == session["a_id"]:
        return "a"
    if agent_id == session["b_id"]:
        return "b"
    return None


def parse_cell(cell):
    """'r1c2' -> (row, col), or None."""
    if not isinstance(cell, str) or len(cell) != 4:
        return None
    if cell[0] != "r" or cell[2] != "c":
        return None
    if cell[1] not in "012" or cell[3] not in "012":
        return None
    return int(cell[1]), int(cell[3])


def cell_index(cell):
    rc = parse_cell(cell)
    return rc[0] * 3 + rc[1] if rc else None


def commitment_hash(session_id, round_n, agent_id, cell, secret):
    return hashlib.sha256(
        ("gw/1|%s|r%s|%s|%s|%s" % (session_id, round_n, agent_id, cell,
                                   secret)).encode("utf-8")).hexdigest()


def winners(board):
    """Sides with 3 in a row on this board."""
    return {side for side in ("a", "b")
            if any(all(board[i] == side for i in line) for line in LINES)}


def terminal(board):
    """(game_over, result) from a board: result in a/b/draw."""
    w = winners(board)
    if "a" in w and "b" in w:
        return True, "draw"  # defensive; unreachable via the engine
    if "a" in w:
        return True, "a"
    if "b" in w:
        return True, "b"
    if all(c is not None for c in board):
        return True, "draw"
    return False, "draw"


def apply_moves(board, cell_a, cell_b):
    """Apply a round's revealed cells (a first, then b) per ttt-v1.md §7.

    Returns (board_after, result, game_over). Cells were verified legal
    (empty, in range) at reveal time.
    """
    b = list(board)
    if cell_a == cell_b:
        empties = [i for i, c in enumerate(b) if c is None]
        idx = cell_index(cell_a)
        if len(empties) == 1 and empties[0] == idx:
            b[idx] = "a"  # last-cell rule: side a claims it
            over, result = terminal(b)
            return b, result, True
        return b, "draw", False  # same-cell collision: drawn round
    b[cell_index(cell_a)] = "a"
    over, result = terminal(b)
    if over:
        return b, result, True  # b's cell recorded but not applied
    b[cell_index(cell_b)] = "b"
    over, result = terminal(b)
    return b, result, over


# ---------------------------------------------------------------------------
# gateway-originated pushes
# ---------------------------------------------------------------------------

def _push(store, gw_keys, recipients, msg_type, payload, session_id,
          schema=SCHEMA):
    gw_priv, _gw_pub = gw_keys
    for rid in recipients:
        env = wire.make_gateway_envelope(gw_priv, rid, msg_type, payload,
                                         schema=schema, session=session_id)
        store.push_envelope(rid, session_id, msg_type, env)


def _participants(session):
    return [session["a_id"], session["b_id"], session["auditor_id"]]


# ---------------------------------------------------------------------------
# session open
# ---------------------------------------------------------------------------

def _negotiate_schema(store, caller_id, friend_id, want):
    """Both players must advertise a common ttt major; pick the highest."""
    if not want or "/" not in want:
        return None
    name, major = want.split("/", 1)
    if not major.isdigit():
        return None
    majors = set()
    for aid in (caller_id, friend_id):
        agent = store.get_agent(aid)
        if not agent:
            return None
        for s in agent["schemas"]:
            if "/" in s:
                n, m = s.split("/", 1)
                if n == name and m.isdigit():
                    majors.add(int(m))
    if not majors:
        return None
    return "%s/%d" % (name, max(majors))


def open_session(store, gw_keys, caller_id, payload):
    """gw.session_open {friend_id, app, schema, auditor_id, ...}."""
    if payload.get("app") != APP:
        return None, wire.AppError("bad_request", 'app must be "%s"' % APP)
    friend_id = payload.get("friend_id")
    friend = store.get_agent(friend_id)
    if not friend:
        return None, wire.AppError("not_found", "unknown friend_id", 404)
    if friend_id == caller_id:
        return None, wire.AppError("bad_request", "you cannot play yourself")
    fr = store.get_friendship_between(caller_id, friend_id)
    if not fr or fr["status"] != "accepted":
        return None, wire.AppError("not_friends",
                                   "you can only play friends", 403)
    ok, _grant = friends.grant_active(store, fr["id"], caller_id,
                                       "game.ttt:play")
    if not ok:
        return None, wire.AppError("grant_expired",
                                   "no live game.ttt:play grant", 403)
    auditor_id = payload.get("auditor_id")
    auditor = store.get_agent(auditor_id)
    if not auditor:
        return None, wire.AppError("not_found", "unknown auditor_id", 404)
    if auditor_id in (caller_id, friend_id):
        return None, wire.AppError("bad_request",
                                   "the auditor must be a third party")
    schema = _negotiate_schema(store, caller_id, friend_id,
                               payload.get("schema"))
    if not schema:
        return None, wire.AppError(
            "bad_request", "no common ttt schema version advertised by both "
                           "players (want %s)" % (payload.get("schema"),))
    if store.active_session_between(caller_id, friend_id, APP):
        return None, wire.AppError("session_active",
                                   "there is already a live ttt session "
                                   "between you", 409)

    commit_timeout = _clamp_timeout(payload.get("commit_timeout_s"))
    reveal_timeout = _clamp_timeout(payload.get("reveal_timeout_s"))
    sid = "sess_" + uuid.uuid4().hex[:12]
    store.create_session({
        "id": sid, "a_id": caller_id, "b_id": friend_id,
        "auditor_id": auditor_id, "app": APP, "schema": schema,
        "status": "active", "phase": "commit", "round": 1,
        "board": [None] * 9,
        "commit_timeout_s": commit_timeout, "reveal_timeout_s": reveal_timeout,
        "commit_deadline": None, "reveal_deadline": None,
        "countersign_deadline": None, "created_at": _now_iso(),
    })
    store.create_round({"session_id": sid, "n": 1})
    _push(store, gw_keys, _participants(store.get_session(sid)),
          "ttt.session_open",
          {"session": sid, "players": {"a": caller_id, "b": friend_id},
           "auditor_id": auditor_id, "schema": schema,
           "commit_timeout_s": commit_timeout,
           "reveal_timeout_s": reveal_timeout,
           "issued_at": _now_iso()},
          sid)
    store.log_event("session.opened",
                    "%s opened ttt session with %s (auditor %s)"
                    % (_aname(store, caller_id), friend["name"],
                       auditor["name"]),
                    agent_id=caller_id, session_id=sid)
    return get_state(store, gw_keys, sid, caller_id, True), None


# ---------------------------------------------------------------------------
# live-session guard + timeouts
# ---------------------------------------------------------------------------

def _get_live_session(store, session_id, agent_id):
    s = store.get_session(session_id)
    if not s:
        return None, None, wire.AppError("not_found", "unknown session", 404)
    side = _side(s, agent_id)
    if not side:
        return None, None, wire.AppError("forbidden",
                                         "only the two players may play", 403)
    if s["status"] == "frozen":
        return None, None, wire.AppError("forbidden",
                                         "session frozen by human revoke", 403)
    if s["status"] == "finished":
        return None, None, wire.AppError("round_not_open",
                                         "session is finished", 409)
    return s, side, None


def freeze_session(store, session_id, reason):
    s = store.get_session(session_id)
    if not s or s["status"] != "active":
        return
    store.update_session(session_id, {"status": "frozen"})
    store.log_event("session.frozen", "Session %s frozen: %s" % (session_id,
                                                                 reason),
                    session_id=session_id)


def freeze_pair(store, a_id, b_id, reason):
    for s in (store.live_sessions_for(a_id) or []):
        if {s["a_id"], s["b_id"]} == {a_id, b_id}:
            freeze_session(store, s["id"], reason)


def _issue_round_receipt(store, gw_keys, session_id, round_n, board_after,
                         result, game_over, forfeit, reason):
    """Emit the round receipt (gateway-signed, awaiting countersignature),
    push it to the participants, and park the session in
    awaiting_countersign."""
    body = receipts.emit_round_receipt(store, gw_keys, session_id, round_n,
                                       board_after, result, game_over,
                                       forfeit, reason)
    s = store.get_session(session_id)
    store.update_session(session_id, {
        "board": board_after,
        "phase": "awaiting_countersign",
        "commit_deadline": None, "reveal_deadline": None,
        "countersign_deadline": time.time() + s["reveal_timeout_s"],
    })
    _push(store, gw_keys, _participants(s), "ttt.round_receipt", body,
          session_id, schema="receipts/1")
    return body


def apply_timeouts(store, gw_keys, session_id):
    """Enforce commit/reveal/countersign deadlines, idempotently."""
    s = store.get_session(session_id)
    if not s or s["status"] != "active":
        return
    now = time.time()
    n = s["round"]

    if s["phase"] == "commit" and s["commit_deadline"] \
            and now >= s["commit_deadline"]:
        rnd = store.get_round(session_id, n)
        ca, cb = bool(rnd["commit_a"]), bool(rnd["commit_b"])
        if ca and cb:
            return  # both in; reveal phase should have opened already
        forfeit = "b" if ca and not cb else "a" if cb and not ca else None
        reason = ("commit deadline passed: %s never committed"
                  % ("b" if forfeit == "b" else "a" if forfeit == "a"
                     else "neither side"))
        _issue_round_receipt(store, gw_keys, session_id, n, s["board"],
                             "draw", False, forfeit, reason)
        store.log_event("round.forfeit", "Round %d forfeit (%s)" % (n, reason),
                        session_id=session_id)

    elif s["phase"] == "reveal" and s["reveal_deadline"] \
            and now >= s["reveal_deadline"]:
        rnd = store.get_round(session_id, n)
        ca, cb = rnd["cell_a"], rnd["cell_b"]
        board = list(s["board"])
        if ca and not cb:
            forfeit, board_after = "b", board
            board_after[cell_index(ca)] = "a"
            over, result = terminal(board_after)
        elif cb and not ca:
            forfeit, board_after = "a", board
            board_after[cell_index(cb)] = "b"
            over, result = terminal(board_after)
        else:
            forfeit, board_after, over, result = None, board, False, "draw"
        reason = ("reveal deadline passed: %s never revealed"
                  % ("b" if forfeit == "b" else "a" if forfeit == "a"
                     else "neither side"))
        _issue_round_receipt(store, gw_keys, session_id, n, board_after,
                             result, over, forfeit, reason)
        store.log_event("round.forfeit", "Round %d forfeit (%s)" % (n, reason),
                        session_id=session_id)

    elif s["phase"] == "awaiting_countersign" and s["countersign_deadline"] \
            and now >= s["countersign_deadline"]:
        freeze_session(store, session_id,
                       "auditor did not countersign in time")
        store.log_event("session.frozen",
                        "Auditor %s missed the countersign deadline; session "
                        "frozen, game result stands"
                        % _aname(store, s["auditor_id"]),
                        session_id=session_id)


# ---------------------------------------------------------------------------
# commit / reveal
# ---------------------------------------------------------------------------

def commit(store, gw_keys, agent_id, session_id, payload):
    """gw.commit / ttt.commit {round, commit}: both sides commit, then the
    gateway publishes the shuffled hashes and opens the reveal phase."""
    apply_timeouts(store, gw_keys, session_id)
    s, side, err = _get_live_session(store, session_id, agent_id)
    if err:
        return None, err
    if s["phase"] != "commit":
        return None, wire.AppError("round_not_open",
                                   "round is not in commit phase", 409)
    if payload.get("round") != s["round"]:
        return None, wire.AppError("round_not_open",
                                   "round must be %d" % s["round"], 409)
    digest = (payload.get("commit") or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return None, wire.AppError("bad_envelope",
                                   "commit must be a 64-char sha256 hex string")
    rnd = store.get_round(session_id, s["round"])
    if rnd["commit_" + side]:
        return None, wire.AppError("already_committed",
                                   "you already committed this round", 409)
    store.update_round(session_id, s["round"], {"commit_" + side: digest})
    rnd = store.get_round(session_id, s["round"])
    if not rnd["commit_a"] or not rnd["commit_b"]:
        # First commit of the round starts the commit deadline.
        if not s["commit_deadline"]:
            store.update_session(session_id, {
                "commit_deadline": time.time() + s["commit_timeout_s"]})
        return get_state(store, gw_keys, session_id, agent_id, True), None
    commits = [{"player": p, "commit": rnd["commit_" + p]} for p in ("a", "b")]
    random.shuffle(commits)
    _push(store, gw_keys, _participants(s), "ttt.commits_published",
          {"session": session_id, "round": s["round"], "commits": commits},
          session_id)
    store.update_session(session_id, {
        "phase": "reveal", "commit_deadline": None,
        "reveal_deadline": time.time() + s["reveal_timeout_s"],
    })
    return get_state(store, gw_keys, session_id, agent_id, True), None


def reveal(store, gw_keys, agent_id, session_id, payload):
    """gw.reveal / ttt.reveal {round, cell, secret}: binding verified
    (verify-then-discard), legality checked; both reveals resolve the round."""
    apply_timeouts(store, gw_keys, session_id)
    s, side, err = _get_live_session(store, session_id, agent_id)
    if err:
        return None, err
    if s["phase"] != "reveal":
        return None, wire.AppError("round_not_open",
                                   "round is not in reveal phase", 409)
    if payload.get("round") != s["round"]:
        return None, wire.AppError("round_not_open",
                                   "round must be %d" % s["round"], 409)
    rnd = store.get_round(session_id, s["round"])
    if rnd["cell_" + side]:
        return None, wire.AppError("already_revealed",
                                   "you already revealed this round", 409)
    cell = payload.get("cell")
    secret = payload.get("secret")
    if parse_cell(cell) is None:
        return None, wire.AppError("bad_request",
                                   'cell must look like "r1c2" (rows/cols 0..2)')
    if not isinstance(secret, str) or not secret:
        return None, wire.AppError("bad_request",
                                   "secret must be a non-empty string")
    expect = commitment_hash(session_id, s["round"], agent_id, cell, secret)
    if expect != (rnd["commit_" + side] or "").lower():
        return None, wire.AppError(
            "commitment_mismatch",
            "reveal does not match your commitment; retry with the true "
            "cell and secret before the deadline")
    if s["board"][cell_index(cell)] is not None:
        return None, wire.AppError(
            "illegal_move", "cell %s is already taken; the commitment still "
                            "binds you to it" % cell)
    # Binding verified. The secret is discarded here: never stored.
    store.update_round(session_id, s["round"], {"cell_" + side: cell})
    rnd = store.get_round(session_id, s["round"])
    if rnd["cell_a"] and rnd["cell_b"]:
        _resolve_round(store, gw_keys, session_id)
    return get_state(store, gw_keys, session_id, agent_id, True), None


def _resolve_round(store, gw_keys, session_id):
    s = store.get_session(session_id)
    rnd = store.get_round(session_id, s["round"])
    board_after, result, game_over = apply_moves(s["board"], rnd["cell_a"],
                                                rnd["cell_b"])
    _issue_round_receipt(store, gw_keys, session_id, s["round"], board_after,
                         result, game_over, None, None)
    store.log_event("round.resolved",
                    "Round %d resolved: %s%s"
                    % (s["round"], result,
                       " (game over)" if game_over else ""),
                    session_id=session_id)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def get_state(store, gw_keys, session_id, viewer_id=None,
              viewer_verified=False):
    """gw.session_state. Unrevealed moves never appear. Non-participants get
    no board and no notifications."""
    apply_timeouts(store, gw_keys, session_id)
    s = store.get_session(session_id)
    if not s:
        return None
    state = {
        "session": s["id"], "status": s["status"],
        "players": {"a": s["a_id"], "b": s["b_id"]},
        "auditor_id": s["auditor_id"], "round": s["round"],
        "phase": "done" if s["status"] == "finished" else s["phase"],
        "commit_deadline": s["commit_deadline"],
        "reveal_deadline": s["reveal_deadline"],
    }
    if viewer_verified and viewer_id in _participants(s):
        state["board"] = list(s["board"])
        state["notifications"] = store.recent_for_recipient(
            viewer_id, session_id, 20)
    return state
