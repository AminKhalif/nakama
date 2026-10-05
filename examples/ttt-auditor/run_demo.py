#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Zero-human-action end-to-end demo: two player agents + a deterministic
auditor play >=3 full tic-tac-toe matches (including a draw) on a live
gateway, every receipt countersigned, every chain verified.

What it does:
1. spawns the gateway in a subprocess (temp sqlite db, ephemeral port,
   random console token),
2. registers two players (Amber, Blaise) and the auditor (Referee),
3. sends a friend request and approves it through the operator console
   (the human tap, automated here with the console token),
4. plays three scripted matches -- side-a win, side-b win, and a draw via
   the last-cell rule -- with simultaneous commit/reveal every round,
5. the auditor independently verifies and countersigns every round and
   game receipt,
6. verifies each match's receipt chain with gwclient.verify_chain,
7. prints per-match results and receipt counts, and exits non-zero on ANY
   failure (wrong result, timeout, refusal, bad chain).

Brains: --brains scripted (default, deterministic, zero network) or
--brains llm (LLMBrain with the scripted lists as fallback; needs
NVIDIA_API_KEY, see README.md; outcomes are not asserted in llm mode).

No external network calls in the default path. The only HTTP traffic is
to the gateway on 127.0.0.1.
"""

import argparse
import http.cookiejar
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKGS = os.path.join(HERE, "..", "..", "packages", "python")
sys.path.insert(0, PKGS)
sys.path.insert(0, HERE)

from gwclient import (GWClient, ReceiptChainError,  # noqa: E402
                      verify_chain)
from player import Player  # noqa: E402
from auditor_bot import AuditorBot  # noqa: E402
from brains.scripted import Scripted  # noqa: E402
from brains.llm import LLMBrain  # noqa: E402

GATEWAY_CWD = os.path.join(PKGS)

# The three scripted matches. Disjoint priority lists per side: no two
# sides ever want the same cell in the same round (except match 3's final
# round, which exercises the last-cell rule on purpose).
MATCHES = [
    {
        "name": "match 1: side a wins (diagonal r0c0/r1c1/r2c2)",
        "a": ["r0c0", "r1c1", "r2c2",
              "r0c1", "r0c2", "r1c0", "r1c2", "r2c0", "r2c1"],
        "b": ["r0c1", "r2c0", "r0c2",
              "r1c0", "r1c2", "r2c1", "r0c0", "r1c1", "r2c2"],
        "expect": "a",
    },
    {
        "name": "match 2: side b wins (bottom row)",
        "a": ["r0c0", "r0c2", "r1c1",
              "r1c0", "r1c2", "r0c1", "r2c0", "r2c1", "r2c2"],
        "b": ["r2c0", "r2c1", "r2c2",
              "r0c1", "r1c0", "r1c2", "r0c0", "r0c2", "r1c1"],
        "expect": "b",
    },
    {
        "name": "match 3: draw (full board; last-cell rule on r2c2)",
        "a": ["r0c0", "r0c2", "r1c0", "r2c1", "r2c2",
              "r0c1", "r1c1", "r1c2", "r2c0"],
        "b": ["r0c1", "r1c1", "r1c2", "r2c0", "r2c2",
              "r0c0", "r0c2", "r1c0", "r2c1"],
        "expect": "draw",
    },
]


def spawn_gateway():
    tmp = tempfile.mkdtemp(prefix="ttt-demo-")
    token = "demo_" + secrets.token_urlsafe(24)
    env = dict(os.environ, GW_CONSOLE_TOKEN=token)
    srv = subprocess.Popen(
        [sys.executable, "-m", "gateway.server", "--port", "0",
         "--db", os.path.join(tmp, "demo.db"), "--host", "127.0.0.1"],
        cwd=GATEWAY_CWD, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    first = srv.stdout.readline()
    m = re.search(r"http://127\.0\.0\.1:(\d+)", first)
    if not m:
        srv.kill()
        raise RuntimeError("gateway did not print a port: %r" % (first,))
    base = "http://127.0.0.1:%s" % m.group(1)
    for _ in range(200):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=2).read()
            break
        except OSError:
            time.sleep(0.05)
    else:
        srv.kill()
        raise RuntimeError("gateway never became healthy")
    return srv, base, token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def console_accept(base, token, request_id):
    """The human tap, automated: log in to the console and accept."""
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPCookieProcessor(jar))

    def post(url, data):
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            op.open(req, timeout=5)
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise

    post(base + "/console/login", ("token=%s" % token).encode())
    post(base + "/console/requests/%s/accept" % request_id,
         b"scope=game.ttt%3Aplay&scope=game.ttt%3Aspectate")


def render(board):
    mark = {"a": "X", "b": "O", None: "."}
    return "\n".join(
        " ".join(mark[c] for c in board[i:i + 3]) for i in (0, 3, 6))


def main(argv=None):
    ap = argparse.ArgumentParser(description="ttt + auditor end-to-end demo")
    ap.add_argument("--brains", default="scripted", choices=["scripted", "llm"],
                    help="scripted (default, deterministic) or llm "
                         "(NVIDIA NIM with scripted fallback)")
    ap.add_argument("--match-timeout", type=int, default=180)
    args = ap.parse_args(argv)

    srv, base, token = spawn_gateway()
    print("gateway up at %s" % base, flush=True)
    failures = []
    try:
        amber = Player(base, "Amber")
        blaise = Player(base, "Blaise")
        auditor = AuditorBot(base, name="Referee")
        amber.register()
        blaise.register()
        auditor.register()
        print("registered: Amber=%s Blaise=%s Referee=%s"
              % (amber.client.agent_id, blaise.client.agent_id,
                 auditor.client.agent_id), flush=True)
        print("auditor pubkey for verify_receipts.py: ed25519:%s"
              % auditor.client.public_key_hex, flush=True)

        req = amber.request_friend(to_agent_id=blaise.client.agent_id)
        console_accept(base, token, req)
        print("friendship approved via console", flush=True)

        card = GWClient.new(base).agent_card()
        gw_pubkey = card["gwPubkey"]
        auditor_pubkey = "ed25519:" + auditor.client.public_key_hex

        sessions = []
        watch_errors = {}

        def watch_target():
            try:
                auditor.watch(sessions, timeout=900, expect=len(MATCHES))
            except Exception as exc:  # noqa: BLE001 -- surfaced below
                watch_errors["error"] = exc

        watcher = threading.Thread(target=watch_target, daemon=True)
        watcher.start()

        results = []
        for match in MATCHES:
            a_brain = Scripted(match["a"], name="A")
            b_brain = Scripted(match["b"], name="B")
            if args.brains == "llm":
                a_brain = LLMBrain(fallback=a_brain)
                b_brain = LLMBrain(fallback=b_brain)
            amber.brain, blaise.brain = a_brain, b_brain

            session = amber.open_match(blaise.client.agent_id,
                                       auditor.client.agent_id)
            sessions.append(session)
            print("\n=== %s ===\n  session %s\n  spectator %s/g/%s"
                  % (match["name"], session, base, session), flush=True)

            outcome = {}

            def play(player, key):
                try:
                    outcome[key] = player.play_match(
                        session, timeout=args.match_timeout)
                except Exception as exc:  # noqa: BLE001
                    outcome[key] = exc

            ta = threading.Thread(target=play, args=(amber, "a"),
                                  daemon=True)
            tb = threading.Thread(target=play, args=(blaise, "b"),
                                  daemon=True)
            ta.start()
            tb.start()
            ta.join(args.match_timeout + 30)
            tb.join(30)
            if ta.is_alive() or tb.is_alive():
                failures.append("%s: player threads hung" % match["name"])
                break
            for key in ("a", "b"):
                if isinstance(outcome.get(key), Exception):
                    failures.append("%s: player %s failed: %s"
                                    % (match["name"], key, outcome[key]))
            if failures:
                break
            result_a = outcome["a"][0]
            if outcome["b"][0] != result_a:
                failures.append("%s: players disagree (%r vs %r)"
                                % (match["name"], result_a, outcome["b"][0]))
                break

            chain = amber.client.receipts(session)
            n_rounds = len([r for r in chain if "rounds_played" not in r])
            try:
                verify_chain(chain, gw_pubkey, auditor_pubkey)
                chain_ok = True
            except ReceiptChainError as exc:
                chain_ok = False
                failures.append("%s: receipt chain INVALID: %s"
                                % (match["name"], exc))
            game = [r for r in chain if "rounds_played" in r][0]
            results.append((match["name"], result_a, n_rounds,
                            len(chain), chain_ok, session,
                            game["final_board"]))
            print("  result=%s rounds=%d receipts=%d chain=%s\n%s"
                  % (result_a, n_rounds, len(chain),
                     "VALID" if chain_ok else "INVALID",
                     render(game["final_board"])), flush=True)

            if args.brains == "scripted" and result_a != match["expect"]:
                failures.append(
                    "%s: expected %r, got %r (scripted demo must be "
                    "deterministic)" % (match["name"], match["expect"],
                                        result_a))
                break

        watcher.join(60)
        if watch_errors.get("error"):
            failures.append("auditor watcher failed: %s"
                            % watch_errors["error"])
        if auditor.refusals:
            failures.append("auditor refused: %r" % (auditor.refusals,))

        # Independent verification, as a separate process, against the
        # live gateway: the exact documented verify_receipts.py command.
        if results:
            print("\n----- independent verifier (separate process) -----",
                  flush=True)
            vproc = subprocess.run(
                [sys.executable, os.path.join(HERE, "verify_receipts.py"),
                 "--base-url", base,
                 "--auditor-pubkey", auditor_pubkey]
                + [session for _, _, _, _, _, session, _ in results])
            if vproc.returncode != 0:
                failures.append("verify_receipts.py exited %d"
                                % vproc.returncode)
    finally:
        srv.kill()

    print("\n----- demo summary -----")
    for name, result, n_rounds, n_receipts, chain_ok, session, _board in results:
        print("%-46s result=%-5s rounds=%d receipts=%d chain=%s  %s/g/%s"
              % (name, result, n_rounds, n_receipts,
                 "VALID" if chain_ok else "INVALID", base, session))
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("  - %s" % failure)
        return 1
    print("\nAll %d matches played, attested, and verified."
          % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
