# SPDX-License-Identifier: Apache-2.0
"""A full tic-tac-toe player agent for the agent-interop gateway.

One class, the whole lifecycle:

1. generate a keypair (locally; the private key never leaves the process),
2. register an identity via gwclient (signed gw.register),
3. befriend the opponent (gw.friend_request with an invite code or a known
   agent id; the human accepts in the console),
4. open a match (gw.session_open; the opener is side "a") -- retrying on
   403 until the human has approved the friendship,
5. play the whole game through simultaneous commit/reveal rounds,
   choosing every move through the plugged-in Brain.

The brain is the ONLY pluggable part: scripted (default, deterministic,
zero network) or LLM (NVIDIA NIM, automatic scripted fallback). The wire
behavior is identical either way -- that is the interop proof.

Collision safety: if a round ends in a same-cell collision (spec/ttt-v1.md
section 7) the collided cell is avoided in later rounds, so a deterministic
brain can never re-pick it forever. Every committed cell is validated
against the gateway's board *before* committing, because the commitment
binds: an illegal commit cannot be switched later.
"""

import argparse
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "packages", "python"))

from gwclient import GWClient, GatewayError  # noqa: E402
from gwclient.ttt import cell_index  # noqa: E402

from brains import parse_brain_spec  # noqa: E402
from brains.scripted import CenterFirst  # noqa: E402

POLL_S = 0.25
DEFAULT_SCHEMAS = ["ttt/1", "gw/1", "friends/1", "receipts/1"]


class Player:
    def __init__(self, base_url, name, brain=None, owner_display_name=None,
                 vendor="ttt-auditor-demo", timeout=10):
        self.client = GWClient.new(base_url, timeout=timeout)
        self.name = name
        self.brain = brain or CenterFirst()
        self.owner_display_name = owner_display_name or "ttt-auditor demo"
        self.vendor = vendor

    # -- identity & friendship ----------------------------------------

    def register(self):
        """Create the agent identity. Returns the agent id."""
        self.client.register(
            self.name,
            owner_display_name=self.owner_display_name,
            vendor=self.vendor,
            schemas=list(DEFAULT_SCHEMAS))
        return self.client.agent_id

    def request_friend(self, invite_code=None, to_agent_id=None):
        """Send gw.friend_request. Returns the request id; the human
        accepts in the console (gw.friend_decide is console-only)."""
        return self.client.friend_request(invite_code=invite_code,
                                          to_agent_id=to_agent_id)

    def open_match(self, peer_id, auditor_id, timeout=60,
                   commit_timeout_s=30, reveal_timeout_s=30):
        """Open a ttt session with a friend, retrying while the human has
        not approved the friendship yet (403 not_friends/grant_expired).
        The opener is side 'a'. Returns the session id."""
        deadline = time.time() + timeout
        while True:
            try:
                state = self.client.session_open(
                    peer_id, auditor_id,
                    commit_timeout_s=commit_timeout_s,
                    reveal_timeout_s=reveal_timeout_s)
                return state["session"]
            except GatewayError as exc:
                if exc.message in ("not_friends", "grant_expired") \
                        and time.time() < deadline:
                    time.sleep(1.0)
                    continue
                raise

    # -- the game ------------------------------------------------------

    def _pick(self, board, me, avoid):
        """Ask the brain for a move; validate against the real board.
        Deterministic fallback to the first truly-empty cell."""
        view = list(board)
        for cell in avoid:
            if view[cell_index(cell)] is None:
                view[cell_index(cell)] = me  # hide collided cells
        try:
            cell = self.brain.choose_move(view, me)
        except Exception:
            cell = None
        if cell is None or not _looks_like_cell(cell) \
                or board[cell_index(cell)] is not None or cell in avoid:
            cell = None
            for i, value in enumerate(board):
                name = "r%dc%d" % (i // 3, i % 3)
                if value is None and name not in avoid:
                    cell = name
                    break
        if cell is None:
            raise RuntimeError("no legal move on board %r" % (board,))
        return cell

    def play_match(self, session, timeout=180):
        """Play a whole match to completion. Returns
        (result, rounds_played, final_board)."""
        committed = {}    # round -> (cell, secret)
        revealed = set()  # rounds we revealed
        processed = set()  # round receipts already absorbed
        avoid = set()     # collided cells, never re-picked
        my_side = None
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise TimeoutError("match %s did not finish in %ss"
                                   % (session, timeout))
            state = self.client.session_state(session)
            if my_side is None:
                players = state["players"]
                if self.client.agent_id == players["a"]:
                    my_side = "a"
                elif self.client.agent_id == players["b"]:
                    my_side = "b"
                else:
                    raise RuntimeError("not a player in %s" % session)
            if state["status"] == "finished":
                break
            if state["status"] == "frozen":
                raise RuntimeError(
                    "session %s was frozen (attestation failed upstream)"
                    % session)
            board = state["board"]
            if board is None:
                raise RuntimeError("no board visible in %s" % session)

            # Absorb published round receipts: track same-cell collisions
            # so the brain never re-picks a collided cell.
            for receipt in self.client.receipts(session):
                if "rounds_played" in receipt:
                    continue
                if receipt["round"] in processed:
                    continue
                processed.add(receipt["round"])
                ra = receipt["reveals"]["a"]
                rb = receipt["reveals"]["b"]
                ca = ra["cell"] if ra else None
                cb = rb["cell"] if rb else None
                if ca and ca == cb and not receipt["game_over"]:
                    avoid.add(ca)

            phase, rn = state["phase"], state["round"]
            if phase == "commit" and rn not in committed:
                cell = self._pick(board, my_side, avoid)
                secret = secrets.token_hex(24)  # 24 random bytes
                try:
                    self.client.commit(session, rn, cell, secret)
                except GatewayError as exc:
                    if exc.message != "already_committed":
                        raise
                committed[rn] = (cell, secret)
            elif phase == "reveal" and rn in committed \
                    and rn not in revealed:
                cell, secret = committed[rn]
                try:
                    self.client.reveal(session, rn, cell, secret)
                except GatewayError as exc:
                    if exc.message != "already_revealed":
                        raise
                revealed.add(rn)
            # phase == "awaiting_countersign": the auditor's turn; wait.
            time.sleep(POLL_S)

        chain = self.client.receipts(session)
        games = [r for r in chain if "rounds_played" in r]
        if not games:
            raise RuntimeError("session finished with no game receipt")
        game = games[0]
        return game["result"], game["rounds_played"], game["final_board"]


def _looks_like_cell(cell):
    return isinstance(cell, str) and len(cell) == 4 and cell[0] == "r" \
        and cell[2] == "c" and cell[1] in "012" and cell[3] in "012"


def main(argv=None):
    ap = argparse.ArgumentParser(description="tic-tac-toe player agent")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--brain", default="center",
                    help="center | seed:N | list:r0c0,r1c1,... | llm")
    ap.add_argument("--session", default=None,
                    help="play this existing session to completion")
    ap.add_argument("--peer", default=None,
                    help="opponent agent id (to open a new match)")
    ap.add_argument("--auditor", default=None,
                    help="auditor agent id (to open a new match)")
    ap.add_argument("--invite-code", default=None)
    args = ap.parse_args(argv)

    from brains.llm import LLMBrain
    brain = parse_brain_spec(args.brain, llm_class=LLMBrain)
    me = Player(args.base_url, args.name, brain=brain)
    agent_id = me.register()
    print("registered %s as %s (brain: %s)"
          % (me.name, agent_id, brain.name), flush=True)

    if args.session:
        session = args.session
    else:
        if not args.peer or not args.auditor:
            raise SystemExit("--peer and --auditor are required to open "
                             "a new match")
        if args.invite_code or args.peer:
            req = me.request_friend(invite_code=args.invite_code,
                                    to_agent_id=args.peer)
            print("friend request sent: %s (waiting for human approval)"
                  % req, flush=True)
        session = me.open_match(args.peer, args.auditor)
        print("session opened: %s" % session, flush=True)

    result, rounds, final = me.play_match(session)
    print("match over: result=%s rounds=%d final=%s"
          % (result, rounds, _render(final)), flush=True)
    return 0


def _render(board):
    mark = {"a": "X", "b": "O", None: "."}
    return "/".join("".join(mark[c] for c in board[i:i + 3])
                    for i in (0, 3, 6))


if __name__ == "__main__":
    sys.exit(main())
