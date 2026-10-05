# SPDX-License-Identifier: Apache-2.0
"""The auditor (referee) agent for the tic-tac-toe demo.

DELIBERATE DESIGN DECISION (flagged per the build brief): the auditor is
NOT LLM-driven. Its entire job is deterministic re-checking:

1. receive every session envelope (session_open, commits_published, round
   and game receipts),
2. independently verify each round receipt *before* countersigning --
   commitments match what was published, reveals name legal empty cells,
   board math and outcome recompute correctly (receipts.md section 3
   minus the secret-dependent check, which no third party can redo),
3. countersign via gw.countersign (auditor.countersign over the canonical
   receipt bytes with signature fields removed).

Why deterministic: a referee must be replayable and blameless. If the
auditor countersigned a bogus receipt, anyone can re-run this exact code
on the published chain and prove it. An LLM referee could neither be
replayed nor held to the spec. The interop proof is in the *players*:
their brains are pluggable (scripted or LLM). The auditor proves the
game was fair, whatever the players were thinking with.

The auditor never sees moves before reveal (only commitments), never
learns secrets (verify-then-discard at the gateway), and refuses to
countersign anything it cannot verify -- in which case the gateway
freezes the session per spec/ttt-v1.md section 6 and the demo fails
loudly instead of attesting a lie.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "packages", "python"))

from gwclient import (GWClient, GatewayError, countersign as make_sig)  # noqa: E402
from gwclient import crypto  # noqa: E402
from gwclient.receipts import (GENESIS_PREV_HASH, ReceiptChainError,  # noqa: E402
                               _replay_round, receipt_hash,
                               receipt_signing_bytes)
from gwclient.ttt import new_board  # noqa: E402

POLL_S = 0.25


class AuditRefusal(Exception):
    """The auditor will not countersign this receipt."""


class AuditorBot:
    def __init__(self, base_url, name="Referee", timeout=10):
        self.client = GWClient.new(base_url, timeout=timeout)
        self.name = name
        self.gw_pubkey = None  # "ed25519:<hex>", from the Agent Card
        self.tracking = {}     # session -> tracking dict
        self.refusals = []     # (session, round/kind, reason)

    # -- identity --------------------------------------------------------

    def register(self):
        self.client.register(
            self.name, owner_display_name="ttt-auditor demo",
            vendor="ttt-auditor-demo",
            schemas=["ttt/1", "gw/1", "friends/1", "receipts/1"])
        card = self.client.agent_card()
        self.gw_pubkey = card["gwPubkey"]
        return self.client.agent_id

    # -- watching --------------------------------------------------------

    def _track(self, session):
        tr = self.tracking.get(session)
        if tr is None:
            tr = {"seen": set(), "published_commits": {},
                  "board": new_board(), "next_round": 1,
                  "rounds_verified": 0, "game_over": False,
                  "game_verified": False, "done": False,
                  "init": False}
            self.tracking[session] = tr
        return tr

    def watch(self, sessions, timeout=300, expect=None):
        """Watch sessions until each is finished and its game receipt is
        countersigned. `sessions` may be a list that grows while watching:
        new ids are picked up on the next poll. `expect` is the total
        number of sessions to wait for (needed when sessions are appended
        over time: without it the watcher would exit as soon as the
        sessions known *so far* are all done). Returns the tracking dict.
        Any refusal is recorded in self.refusals (and the session will
        freeze server-side)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for session in list(sessions):
                tr = self._track(session)
                if tr["done"]:
                    continue
                try:
                    self._pump(session, tr)
                except Exception as exc:
                    # A failed poll must never kill the watcher: log and
                    # retry on the next pass.
                    print("[auditor] pump error on %s: %s: %s"
                          % (session[:14], type(exc).__name__, exc),
                          flush=True)
            if expect is not None:
                if len(sessions) >= expect and all(
                        self.tracking[s]["done"] for s in sessions):
                    break
            elif sessions and all(self.tracking[s]["done"]
                                  for s in sessions):
                break
            time.sleep(POLL_S)
        pending = [s for s in sessions if not self.tracking[s]["done"]]
        if pending:
            raise TimeoutError("auditor timed out on %r" % (pending,))
        return self.tracking

    def _pump(self, session, tr):
        state = self.client.session_state(session)
        if not tr["init"]:
            if state["auditor_id"] != self.client.agent_id:
                raise AuditRefusal("not the appointed auditor of %s"
                                   % session)
            tr["init"] = True
        for env in state.get("notifications", []):
            msg_id = env.get("msg_id")
            if msg_id in tr["seen"]:
                continue
            tr["seen"].add(msg_id)
            msg_type, payload = env.get("type"), env.get("payload") or {}
            try:
                if msg_type == "ttt.commits_published":
                    self._note_commits(tr, payload)
                    continue
                if msg_type == "ttt.round_receipt":
                    sig = self._check_round(session, tr, payload)
                    self._submit(session, tr, payload.get("round"),
                                 sig, kind="round")
                elif msg_type == "ttt.game_receipt":
                    sig = self._check_game(session, tr, payload)
                    self._submit(session, tr,
                                 payload.get("rounds_played"), sig,
                                 kind="game")
            except AuditRefusal as exc:
                self.refusals.append(
                    (session, payload.get("round", "game"), str(exc)))
            except Exception as exc:  # malformed receipt: refuse, never crash
                self.refusals.append(
                    (session, payload.get("round", "game"),
                     "malformed receipt: %s: %s"
                     % (type(exc).__name__, exc)))
        if state["status"] == "finished":
            tr["done"] = True
        elif state["status"] == "frozen":
            # Attestation failed upstream (e.g. a refusal froze it, or the
            # countersign deadline fired). Nothing more to attest.
            print("[auditor] session %s frozen; stopping watch"
                  % session[:14], flush=True)
            tr["done"] = True

    # -- verification -----------------------------------------------------

    def _note_commits(self, tr, payload):
        rnd = payload.get("round")
        commits = {c["player"]: c["commit"]
                   for c in payload.get("commits", [])}
        if set(commits) != {"a", "b"}:
            raise AuditRefusal("round %r: commits_published must name both "
                               "sides" % (rnd,))
        tr["published_commits"][rnd] = commits

    def _check_gw_sig(self, receipt, where):
        sig = receipt.get("gw_sig") or ""
        if not sig.startswith("ed25519:"):
            raise AuditRefusal("%s: missing gateway signature" % where)
        key = self.gw_pubkey[len("ed25519:"):] \
            if self.gw_pubkey.startswith("ed25519:") else self.gw_pubkey
        if not crypto.verify(key, receipt_signing_bytes(receipt),
                             bytes.fromhex(sig[len("ed25519:"):])):
            raise AuditRefusal("%s: gateway signature does not verify"
                               % where)

    def _published_rounds(self, session):
        return [r for r in self.client.receipts(session)
                if "rounds_played" not in r]

    def _submit(self, session, tr, round_n, sig, kind):
        """Submit a countersignature. Transport failures retry (the
        receipt was already verified); verification failures never get
        here."""
        for attempt in range(30):
            try:
                res = self.client.countersign(session, round_n, sig,
                                              kind=kind if kind != "round"
                                              else None)
            except GatewayError as exc:
                if exc.message == "bad_signature":
                    raise AuditRefusal("gateway rejected our countersignature"
                                       ": %s" % exc)
                time.sleep(1.0)
                continue
            except Exception:
                time.sleep(1.0)
                continue
            if res.get("countersigned"):
                print("[auditor] countersigned %s %r of %s"
                      % (kind, round_n, session[:14]), flush=True)
                return
            time.sleep(1.0)
        raise AuditRefusal("countersign for %s %r never acknowledged"
                           % (kind, round_n))

    def _check_round(self, session, tr, receipt):
        rnd = receipt.get("round")
        where = "round %r of %s" % (rnd, session)
        if rnd != tr["next_round"]:
            raise AuditRefusal("%s: expected round %d (continuity break)"
                               % (where, tr["next_round"]))
        if receipt.get("session") != session:
            raise AuditRefusal("%s: wrong session id" % where)
        self._check_gw_sig(receipt, where)

        published = tr["published_commits"].get(rnd)
        if published != {"a": receipt["commitments"]["a"],
                         "b": receipt["commitments"]["b"]}:
            raise AuditRefusal("%s: commitments differ from the published "
                               "ttt.commits_published" % where)

        if rnd == 1:
            if receipt.get("prev_hash") != GENESIS_PREV_HASH:
                raise AuditRefusal("%s: round 1 prev_hash must be genesis"
                                   % where)
        else:
            prev = [r for r in self._published_rounds(session)
                    if r["round"] == rnd - 1]
            if not prev:
                raise AuditRefusal("%s: previous round receipt not "
                                   "published yet" % where)
            if receipt.get("prev_hash") != receipt_hash(prev[0]):
                raise AuditRefusal("%s: prev_hash does not match the "
                                   "published round %d receipt"
                                   % (where, rnd - 1))

        try:
            board_after, result, game_over = _replay_round(tr["board"],
                                                           receipt)
        except ReceiptChainError as exc:
            raise AuditRefusal("%s: %s" % (where, exc))
        if board_after != receipt.get("board_after"):
            raise AuditRefusal("%s: board_after != recomputed board" % where)
        if result != receipt.get("result"):
            raise AuditRefusal("%s: result %r != recomputed %r"
                               % (where, receipt.get("result"), result))
        if game_over != receipt.get("game_over"):
            raise AuditRefusal("%s: game_over != recomputed" % where)

        sig = make_sig(receipt, self.client.private_key_hex)

        tr["board"] = board_after
        tr["next_round"] = rnd + 1
        tr["rounds_verified"] += 1
        tr["game_over"] = game_over
        print("[auditor] verified round %d of %s (result=%s game_over=%s)"
              % (rnd, session[:14], result, game_over), flush=True)
        return sig

    def _check_game(self, session, tr, receipt):
        where = "game receipt of %s" % session
        self._check_gw_sig(receipt, where)
        rounds = self._published_rounds(session)
        if not rounds:
            raise AuditRefusal("%s: no published round receipts" % where)
        last = max(rounds, key=lambda r: r["round"])
        if receipt.get("rounds_played") != tr["rounds_verified"]:
            raise AuditRefusal("%s: rounds_played=%r != %d verified rounds"
                               % (where, receipt.get("rounds_played"),
                                  tr["rounds_verified"]))
        if receipt.get("final_board") != tr["board"]:
            raise AuditRefusal("%s: final_board != auditor's board" % where)
        if receipt.get("result") != last["result"]:
            raise AuditRefusal("%s: result != last round's result" % where)
        if receipt.get("prev_hash") != receipt_hash(last):
            raise AuditRefusal("%s: prev_hash != last round receipt's hash"
                               % where)

        sig = make_sig(receipt, self.client.private_key_hex)
        tr["game_verified"] = True
        print("[auditor] verified game receipt of %s (result=%s rounds=%d)"
              % (session[:14], receipt["result"],
                 receipt["rounds_played"]), flush=True)
        return sig


def main(argv=None):
    ap = argparse.ArgumentParser(description="deterministic ttt auditor")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--name", default="Referee")
    ap.add_argument("--session", action="append", required=True,
                    help="session id to watch (repeatable)")
    args = ap.parse_args(argv)

    bot = AuditorBot(args.base_url, name=args.name)
    agent_id = bot.register()
    print("auditor %s registered as %s" % (bot.name, agent_id), flush=True)
    bot.watch(args.session, expect=len(args.session))
    if bot.refusals:
        print("REFUSALS: %r" % (bot.refusals,), flush=True)
        return 1
    print("all sessions finished and attested", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
