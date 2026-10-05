#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Conformance suite for the agent-interop gateway (M2/M4).

Every check runs end-to-end against a LIVE gateway spawned on 127.0.0.1
with a throwaway sqlite db (mirror of the bridge test pattern). The only
client is gwclient; the console is driven over HTTP with the operator
token; the sqlite file is touched only for test-controlled setup
(invite-code reads, grant-expiry tweaks). No gateway internals imported.

Flow: register (proof-of-possession) -> invite code -> console-approved
friendship -> expiring scoped grant -> session_open with auditor ->
complete games (won / draw with last-cell rule / forfeit) -> receipts ->
independent verify_chain -> spectator page -> Agent Card -> key rotation
-> revocation list -> console-only friend_decide.

Style: check(name, cond) prints PASS/FAIL; the final line is
"ALL N CHECKS PASSED"; any failure exits non-zero.
"""

import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import gwtest_harness as H  # noqa: E402
from gwtest_harness import Checker, expect_error  # noqa: E402


def _sig_ok(pubkey_spec, body_dict, sig_spec):
    body = {k: v for k, v in body_dict.items() if k != "gw_sig"}
    pub_hex = pubkey_spec[len("ed25519:"):]
    sig_hex = sig_spec[len("ed25519:"):]
    return H.crypto_mod.verify(pub_hex, H.envelope_mod.canonical(body),
                               bytes.fromhex(sig_hex))


def run(check, base, db, token):
    # -- boot ---------------------------------------------------------
    hz = H.healthz(base)
    check("gateway boots: /healthz ok, gw/1, pubkey present",
          hz.get("ok") is True and hz.get("gw") == "gw/1"
          and re.fullmatch(r"ed25519:[0-9a-f]{64}", hz.get("gw_pubkey") or ""))
    gw_pub = hz["gw_pubkey"]

    console = H.Console(base, token)
    check("console operator login issues gw_console cookie",
          bool(console.cookie))

    # -- register (proof-of-possession) --------------------------------
    A = H.new_agent(base, "ALICE")
    check("register returns agent_id + identity document",
          A.agent_id.startswith("agent_") and isinstance(A.identity, dict))
    check("identity document gw_sig verifies independently against card key",
          _sig_ok(gw_pub, A.identity, A.identity["gw_sig"]))
    check("identity document binds the registered pubkey",
          A.identity["pubkey"] == "ed25519:" + A.public_key_hex
          and A.identity["id"] == A.agent_id)
    dup = H.GWClient.new(base)
    expect_error(check, "duplicate display name -> 409 name_taken",
                 lambda: dup.register("ALICE", owner_display_name="x",
                                      vendor="muse-test"),
                 409, "name_taken")
    B = H.new_agent(base, "AHMED")
    C = H.new_agent(base, "AUDITOR")
    R = H.new_agent(base, "ROTATOR")
    check("register AHMED, AUDITOR, ROTATOR",
          all(c.agent_id.startswith("agent_") for c in (B, C, R)))

    # -- friendship via invite code + console approval ------------------
    code, code_exp = console.mint_invite(db, A.agent_id)
    check("console mints invite code (single-use, ~24h)",
          re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", code or "") is not None
          and code_exp > time.time() + 23 * 3600)
    req_id = B.friend_request(invite_code=code)
    check("friend_request with invite code -> pending request",
          req_id.startswith("fr_"))
    expect_error(check, "self-friend -> 400 bad_request",
                 lambda: A.friend_request(to_agent_id=A.agent_id),
                 400, "bad_request")
    expect_error(check, "agent-key gw.friend_decide -> 403 console_only",
                 lambda: B.friend_decide(req_id, "accept"),
                 403, "console_only")
    res = console.friend_decide(A, req_id, "accept")
    check("console gw.friend_decide approves (operator token)",
          res["status"] == "accepted" and "game.ttt:play" in res["scopes"])
    ga, gb = db.grants(A.agent_id), db.grants(B.agent_id)
    check("accept mints directional expiring game.ttt:play grants",
          len(ga) == 1 and len(gb) == 1
          and not ga[0]["revoked"] and not gb[0]["revoked"]
          and ga[0]["expires_at"] > time.time() + 300 * 86400
          and ga[0]["peer_id"] == B.agent_id
          and gb[0]["peer_id"] == A.agent_id)
    expect_error(check, "duplicate friend_request after accept -> 409",
                 lambda: B.friend_request(to_agent_id=A.agent_id),
                 409, "duplicate_request")

    # -- session open ----------------------------------------------------
    st = A.session_open(B.agent_id, C.agent_id,
                        commit_timeout_s=30, reveal_timeout_s=30)
    sess = st["session"]
    check("session_open: players a/b, auditor, commit phase round 1",
          st["players"] == {"a": A.agent_id, "b": B.agent_id}
          and st["auditor_id"] == C.agent_id
          and st["phase"] == "commit" and st["round"] == 1
          and st["status"] == "active" and st["board"] == [None] * 9)
    expect_error(check, "second session_open while live -> 409 session_active",
                 lambda: A.session_open(B.agent_id, C.agent_id),
                 409, "session_active")
    expect_error(check, "auditor must be a third party -> 400 bad_request",
                 lambda: B.session_open(A.agent_id, A.agent_id),
                 400, "bad_request")

    # -- game 1: a wins, mid-game same-cell collision --------------------
    secrets_used = []

    def sec(tag):
        s = "sec-%s-%s" % (tag, os.urandom(4).hex())
        secrets_used.append(s)
        return s

    sA1, sB1 = sec("g1r1a"), sec("g1r1b")
    A.commit(sess, 1, "r0c0", sA1)
    stB = B.commit(sess, 1, "r0c1", sB1)
    check("R1 commits accepted; reveal phase opens",
          stB["phase"] == "reveal")
    pubs = [n["payload"] for n in stB.get("notifications", [])
            if n.get("type") == "ttt.commits_published"]
    blob = json.dumps(pubs)
    check("commits_published: both hashes, no moves leak",
          len(pubs) == 1 and len(pubs[0]["commits"]) == 2
          and "cell" not in blob and "secret" not in blob
          and sA1 not in blob and sB1 not in blob)
    A.reveal(sess, 1, "r0c0", sA1)
    B.reveal(sess, 1, "r0c1", sB1)
    H.countersign_round(C, sess, 1)
    r1 = H.round_receipt(A, sess, 1)
    check("R1 receipt published with both signatures",
          bool(r1.get("gw_sig")) and bool(r1.get("auditor_sig"))
          and r1["result"] == "draw" and not r1["game_over"])

    sA2, sB2 = sec("g1r2a"), sec("g1r2b")
    A.commit(sess, 2, "r2c2", sA2)
    B.commit(sess, 2, "r2c2", sB2)
    A.reveal(sess, 2, "r2c2", sA2)
    B.reveal(sess, 2, "r2c2", sB2)
    H.countersign_round(C, sess, 2)
    r2 = H.round_receipt(A, sess, 2)
    check("R2 same-cell collision: drawn round, board unchanged",
          r2["result"] == "draw" and not r2["game_over"]
          and r2["reveals"]["a"]["cell"] == "r2c2"
          and r2["reveals"]["b"]["cell"] == "r2c2"
          and r2["board_after"] == r1["board_after"])

    sA3, sB3 = sec("g1r3a"), sec("g1r3b")
    A.commit(sess, 3, "r1c0", sA3)
    B.commit(sess, 3, "r0c2", sB3)
    A.reveal(sess, 3, "r1c0", sA3)
    B.reveal(sess, 3, "r0c2", sB3)
    H.countersign_round(C, sess, 3)

    sA4, sB4 = sec("g1r4a"), sec("g1r4b")
    A.commit(sess, 4, "r2c0", sA4)
    B.commit(sess, 4, "r1c2", sB4)
    A.reveal(sess, 4, "r2c0", sA4)
    B.reveal(sess, 4, "r1c2", sB4)
    H.countersign_round(C, sess, 4)
    r4 = H.round_receipt(A, sess, 4)
    check("R4 a wins col 0: result a, game over, b's cell recorded not applied",
          r4["result"] == "a" and r4["game_over"]
          and r4["reveals"]["b"]["cell"] == "r1c2"
          and r4["board_after"][5] is None
          and r4["board_after"][6] == "a")

    H.countersign_game(C, sess, 4)
    fin = A.session_state(sess)
    check("game receipt countersigned: session finished",
          fin["status"] == "finished" and fin["phase"] == "done")
    receipts = A.receipts(sess)
    rounds = [r for r in receipts if "rounds_played" not in r]
    games = [r for r in receipts if "rounds_played" in r]
    check("gw.receipts: 4 round receipts + game receipt, in order",
          len(rounds) == 4 and len(games) == 1
          and [r["round"] for r in rounds] == [1, 2, 3, 4]
          and receipts[-1] is games[0]
          and games[0]["rounds_played"] == 4
          and games[0]["result"] == "a")
    try:
        vok, vdetail = H.verify_chain(receipts, gw_pub,
                                      C.public_key_hex), ""
    except H.ReceiptChainError as exc:
        vok, vdetail = False, str(exc)
    check("independent verify_chain(game1) -> True", vok, vdetail)
    check("every receipt carries gw_sig and auditor_sig",
          all(r.get("gw_sig") and r.get("auditor_sig") for r in receipts))
    blob = json.dumps(receipts)
    check("secrets never appear in receipts (verify-then-discard)",
          all(s not in blob for s in secrets_used))

    # -- game 2: draw exercising the last-cell rule ----------------------
    st2 = A.session_open(B.agent_id, C.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=30)
    sess2 = st2["session"]
    check("session_open #2 after game 1 finished",
          st2["status"] == "active" and st2["round"] == 1)
    for rnd, ca, cb in ((1, "r0c0", "r0c1"), (2, "r0c2", "r1c1"),
                        (3, "r1c0", "r1c2"), (4, "r2c1", "r2c0"),
                        (5, "r2c2", "r2c2")):
        sa, sb = sec("g2r%da" % rnd), sec("g2r%db" % rnd)
        A.commit(sess2, rnd, ca, sa)
        B.commit(sess2, rnd, cb, sb)
        A.reveal(sess2, rnd, ca, sa)
        B.reveal(sess2, rnd, cb, sb)
        H.countersign_round(C, sess2, rnd)
    r5 = H.round_receipt(A, sess2, 5)
    check("R5 last-cell rule: both reveal final cell, a claims it, draw, over",
          r5["reveals"]["a"]["cell"] == "r2c2"
          and r5["reveals"]["b"]["cell"] == "r2c2"
          and r5["board_after"][8] == "a"
          and r5["result"] == "draw" and r5["game_over"]
          and all(c is not None for c in r5["board_after"]))
    H.countersign_game(C, sess2, 5)
    receipts2 = A.receipts(sess2)
    g2 = [r for r in receipts2 if "rounds_played" in r][0]
    check("game2 receipt: draw, 5 rounds, full board",
          g2["result"] == "draw" and g2["rounds_played"] == 5
          and all(c is not None for c in g2["final_board"]))
    try:
        vok2, vdetail2 = H.verify_chain(receipts2, gw_pub,
                                         C.public_key_hex), ""
    except H.ReceiptChainError as exc:
        vok2, vdetail2 = False, str(exc)
    check("independent verify_chain(game2 draw) -> True", vok2, vdetail2)

    # -- game 3: illegal_move + reveal-timeout forfeit -------------------
    st3 = A.session_open(B.agent_id, C.agent_id,
                         commit_timeout_s=2, reveal_timeout_s=3)
    sess3 = st3["session"]
    check("session_open #3 with short per-session timeouts",
          st3["status"] == "active")
    sA, sB = sec("g3a-alpha"), sec("g3b-unrevealed-xyz")
    A.commit(sess3, 1, "r0c0", sA)
    with urllib.request.urlopen(base + "/g/" + sess3,
                                timeout=5) as resp:
        page = resp.read().decode("utf-8")
    check("spectator page renders; unrevealed move hidden",
          resp.status == 200 and sess3 in page
          and "r0c0" not in page and sA not in page
          and "unrevealed moves never appear here" in page)
    B.commit(sess3, 1, "r1c1", sB)
    A.reveal(sess3, 1, "r0c0", sA)
    B.reveal(sess3, 1, "r1c1", sB)
    H.countersign_round(C, sess3, 1)
    # R2: B commits a cell taken in R1 -> illegal_move at reveal time.
    sA2, sB2 = sec("g3r2a"), sec("g3r2b")
    A.commit(sess3, 2, "r0c1", sA2)
    B.commit(sess3, 2, "r0c0", sB2)  # r0c0 taken by a in R1
    A.reveal(sess3, 2, "r0c1", sA2)
    expect_error(check, "reveal of taken cell -> 400 illegal_move",
                 lambda: B.reveal(sess3, 2, "r0c0", sB2),
                 400, "illegal_move")
    expect_error(check, "illegal_move retry stays bound -> 400 illegal_move",
                 lambda: B.reveal(sess3, 2, "r0c0", sB2),
                 400, "illegal_move")
    time.sleep(4.0)  # pass the 3s reveal deadline
    A.session_state(sess3)  # fires apply_timeouts -> forfeit receipt
    H.countersign_round(C, sess3, 2)
    rf = H.round_receipt(A, sess3, 2)
    check("reveal-timeout forfeit: b forfeits, a's cell applied, draw, not over",
          rf.get("forfeit") == "b"
          and rf["reveals"]["a"]["cell"] == "r0c1"
          and rf["reveals"]["b"] is None
          and rf["board_after"][0] == "a"
          and rf["board_after"][1] == "a"
          and rf["result"] == "draw" and not rf["game_over"])
    check("forfeit receipt carries both signatures",
          bool(rf.get("gw_sig")) and bool(rf.get("auditor_sig")))
    st3c = A.session_state(sess3)
    check("game continues after forfeit: round 3 commit phase",
          st3c["round"] == 3 and st3c["phase"] == "commit"
          and st3c["status"] == "active")

    # -- Agent Card -------------------------------------------------------
    with urllib.request.urlopen(base + "/.well-known/agent-card.json",
                                timeout=5) as resp:
        card = json.loads(resp.read().decode("utf-8"))
        card_status = resp.status
    check("Agent Card: A2A fields + gwPubkey",
          card_status == 200 and card.get("name") and card.get("version")
          and card.get("url") and card.get("protocolVersion") == "1.0.1"
          and card.get("gwPubkey") == gw_pub
          and re.fullmatch(r"ed25519:[0-9a-f]{64}",
                            card.get("gwPubkey") or ""))

    # -- key rotation -----------------------------------------------------
    new_priv, new_pub = H.crypto_mod.generate_keypair()
    console.action("/console/keys/rotate",
                   {"agent_id": R.agent_id,
                    "new_pubkey": "ed25519:" + new_pub})
    expect_error(check, "rotated-out key rejected on authenticated call",
                 lambda: R.friend_request(to_agent_id=A.agent_id),
                 401, "bad_signature")
    Rnew = H.GWClient(base, private_key_hex=new_priv,
                      public_key_hex=new_pub, agent_id=R.agent_id)
    row = db.q("SELECT identity_doc FROM agents WHERE id=?",
               (R.agent_id,))[0]
    doc2 = json.loads(row["identity_doc"])
    check("rotation: new key works, same id, reissued doc verifies",
          Rnew.session_state(sess)["session"] == sess
          and doc2["id"] == R.agent_id
          and doc2["pubkey"] == "ed25519:" + new_pub
          and _sig_ok(gw_pub, doc2, doc2["gw_sig"]))

    # -- revocation list ---------------------------------------------------
    console.action("/console/keys/revoke",
                   {"pubkey": "ed25519:" + new_pub, "reason": "conformance"})
    with urllib.request.urlopen(base + "/.well-known/revocations.json",
                                timeout=5) as resp:
        rev = json.loads(resp.read().decode("utf-8"))
    check("revocation list names the key and is gateway-signed",
          ("ed25519:" + new_pub) in rev.get("revoked", [])
          and _sig_ok(gw_pub, rev, rev["gw_sig"]))
    expect_error(check, "revoked key -> 403 revoked",
                 lambda: Rnew.session_state(sess), 403, "revoked")

    # -- forfeit board persistence (gateway bug, reported not patched) ----
    # ttt-v1.md section 5: the non-forfeiting side's revealed cell IS
    # applied to the board. The game-3 R2 forfeit receipt's board_after
    # has a's r0c1 applied; the gateway never persists it to the live
    # session row, so the session board diverges from its own receipt
    # (later rounds then build on stale state). This check is last-but-one
    # so the deviation cannot abort the live checks above; it is NOT
    # weakened -- the gateway is wrong here.
    check("live session board matches forfeit receipt board_after",
          st3c["board"] == rf["board_after"],
          "session board %s vs receipt board_after %s"
          % (st3c["board"], rf["board_after"]))

    # -- Agent Card spec-MUSTs (runs last; documents a gateway deviation) --
    # spec/a2a-extension.md: the card MUST serve, at minimum, name,
    # description, url, provider, version, plus a skills entry for the
    # tic-tac-toe referee with id "game.ttt". The gateway serves neither
    # `provider` nor a `game.ttt` skill id (skill ids served are the
    # method-style gw.* / ttt.* names). This check is intentionally last
    # so the deviation cannot abort the remaining live checks; it is NOT
    # weakened -- the gateway is wrong here, reported not patched.
    check("Agent Card carries provider + game.ttt referee skill (spec MUST)",
          card.get("provider") and any(s.get("id") == "game.ttt"
                                       for s in card.get("skills", [])),
          "skill ids served: %s; provider field: %r"
          % ([s.get("id") for s in card.get("skills", [])],
             card.get("provider")))


def main():
    check = Checker()
    proc, base, db_path, token = H.spawn_gateway()
    db = H.DB(db_path)
    try:
        run(check, base, db, token)
    finally:
        H.shutdown(proc)
    if not check.summary():
        sys.exit(1)


if __name__ == "__main__":
    main()
