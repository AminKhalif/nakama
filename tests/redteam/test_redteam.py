#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Red-team suite for the agent-interop gateway (M2/M4).

Ten adversarial checks, each against a LIVE gateway on 127.0.0.1 with a
throwaway db, each required to FAIL CLOSED. The exact typed error (or
receipt evidence) is logged per check via EVIDENCE lines. gwclient is the
only client; raw envelopes are built with gwclient's own envelope module
(forgery = attacker's key signing as a victim).

Style: check(name, cond) prints PASS/FAIL; the final line is
"ALL N CHECKS PASSED"; any failure exits non-zero.
"""

import copy
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import gwtest_harness as H  # noqa: E402
from gwtest_harness import Checker, expect_error  # noqa: E402
from gwclient import commit as commit_mod  # noqa: E402
from gwclient import envelope as env_mod  # noqa: E402


def expect_chain_error(check, name, receipts, gw_pub, aud_pub, needle):
    """verify_chain must reject the tampered chain, naming the receipt."""
    try:
        H.verify_chain(receipts, gw_pub, aud_pub)
    except H.ReceiptChainError as exc:
        check.evidence(name, "ReceiptChainError: %s" % exc)
        check(name, needle in str(exc),
              "want failure naming %r" % needle)
        return
    check(name, False, "tampered chain verified: NOT rejected")


def auto_finish(a, b, aud, session, start_rnd):
    """Play arbitrary legal rounds (with countersigns) until the session
    finishes. Board truth comes from the last published receipt, not the
    session state: after a reveal-timeout forfeit the gateway's live
    board goes stale (the receipt's board_after is correct; the session
    row is not -- see bug report), so the session board could offer a
    taken cell as empty."""
    rnd = start_rnd
    while True:
        st = a.session_state(session)
        if st["status"] != "active":
            return
        assert st["phase"] == "commit" and st["round"] == rnd, st
        receipts = a.receipts(session)
        rounds = [r for r in receipts if "rounds_played" not in r]
        board = rounds[-1]["board_after"] if rounds else st["board"]
        empties = ["r%dc%d" % (i // 3, i % 3)
                   for i, c in enumerate(board) if c is None]
        ca = empties[0]
        cb = empties[1] if len(empties) > 1 else empties[0]
        sa, sb = "auto-%d-a" % rnd, "auto-%d-b" % rnd
        a.commit(session, rnd, ca, sa)
        b.commit(session, rnd, cb, sb)
        a.reveal(session, rnd, ca, sa)
        b.reveal(session, rnd, cb, sb)
        H.countersign_round(aud, session, rnd)
        if H.round_receipt(a, session, rnd)["game_over"]:
            H.countersign_game(aud, session, rnd)
            return
        rnd += 1


def run(check, base, db, token):
    gw_pub = H.gw_pubkey(base)
    console = H.Console(base, token)
    check("red-team setup: console login", bool(console.cookie))

    P1 = H.new_agent(base, "P1")
    P2 = H.new_agent(base, "P2")
    Q1 = H.new_agent(base, "Q1")
    Q2 = H.new_agent(base, "Q2")
    AUD = H.new_agent(base, "AUD")
    STR = H.new_agent(base, "STRANGER")
    check("red-team setup: six agents registered",
          all(c.agent_id for c in (P1, P2, Q1, Q2, AUD, STR)))
    H.befriend(console, db, P1, P2)
    H.befriend(console, db, Q1, Q2)
    check("red-team setup: P1-P2 and Q1-Q2 befriended", True)

    attacker = H.GWClient.new(base)  # keypair only, never registered

    def raw_commit(cli, session, rnd, commit_hex):
        env = env_mod.build_envelope(
            cli.agent_id, "gateway", "ttt.commit", "ttt/1", session,
            {"session": session, "round": rnd, "commit": commit_hex},
            cli.private_key_hex)
        return H.rpc_raw(base, "gw.commit", env)

    def forge(victim_cli, method, msg_type, schema, session, payload):
        env = env_mod.build_envelope(
            victim_cli.agent_id, "gateway", msg_type, schema, session,
            payload, attacker.private_key_hex)
        return H.rpc_raw(base, method, env)

    # -- S1: tampered reveal, double commit, double reveal ----------------
    s1 = P1.session_open(P2.agent_id, AUD.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=30)["session"]
    s1a_sec = "rt1-secA"
    P1.commit(s1, 1, "r0c0", s1a_sec)
    s1a_hash = commit_mod.make_commit(s1, 1, P1.agent_id, "r0c0", s1a_sec)
    expect_error(check, "10a double-commit same round -> 409 "
                 "already_committed",
                 lambda: P1.commit(s1, 1, "r0c0", s1a_sec),
                 409, "already_committed")
    P2.commit(s1, 1, "r1c1", "rt1-secB")
    expect_error(check, "1a tampered reveal (wrong secret) -> 400 "
                 "commitment_mismatch",
                 lambda: P1.reveal(s1, 1, "r0c0", "wrong-secret"),
                 400, "commitment_mismatch")
    stA = P1.reveal(s1, 1, "r0c0", s1a_sec)
    check("1b retry with correct secret accepted",
          stA["phase"] == "reveal")
    expect_error(check, "10b double-reveal same round -> 409 already_revealed",
                 lambda: P1.reveal(s1, 1, "r0c0", s1a_sec),
                 409, "already_revealed")
    P2.reveal(s1, 1, "r1c1", "rt1-secB")
    H.countersign_round(AUD, s1, 1)
    # finish S1: P1 takes row 0 -> chain for check 9
    for rnd, ca, cb in ((2, "r0c1", "r2c2"), (3, "r0c2", "r1c2")):
        P1.commit(s1, rnd, ca, "s1-%d-a" % rnd)
        P2.commit(s1, rnd, cb, "s1-%d-b" % rnd)
        P1.reveal(s1, rnd, ca, "s1-%d-a" % rnd)
        P2.reveal(s1, rnd, cb, "s1-%d-b" % rnd)
        H.countersign_round(AUD, s1, rnd)
    H.countersign_game(AUD, s1, 3)
    check("S1 finished (chain available for tamper checks)",
          P1.session_state(s1)["status"] == "finished")
    s1_chain = P1.receipts(s1)

    # -- Q session: cross-round commitment replay -------------------------
    q = Q1.session_open(Q2.agent_id, AUD.agent_id,
                        commit_timeout_s=30, reveal_timeout_s=6)["session"]
    q1a_sec = "rt2-secA"
    Q1.commit(q, 1, "r0c0", q1a_sec)
    Q2.commit(q, 1, "r1c1", "rt2-secB")
    Q1.reveal(q, 1, "r0c0", q1a_sec)
    Q2.reveal(q, 1, "r1c1", "rt2-secB")
    H.countersign_round(AUD, q, 1)
    q1_hash = commit_mod.make_commit(q, 1, Q1.agent_id, "r0c0", q1a_sec)
    raw_commit(Q1, q, 2, q1_hash)  # replay of Q1's own round-1 commitment
    Q2.commit(q, 2, "r2c2", "rt2-r2-secB")
    expect_error(check, "2 cross-round commitment replay -> 400 "
                 "commitment_mismatch",
                 lambda: Q1.reveal(q, 2, "r0c0", q1a_sec),
                 400, "commitment_mismatch")
    Q2.reveal(q, 2, "r2c2", "rt2-r2-secB")
    time.sleep(7)  # reveal deadline: Q1 forfeits, session recovers
    Q1.session_state(q)
    H.countersign_round(AUD, q, 2)
    auto_finish(Q1, Q2, AUD, q, 3)
    check("Q session recovered via forfeit and finished",
          Q1.session_state(q)["status"] == "finished")

    # -- S2: player B replays A's commitment as its own -------------------
    s2 = P1.session_open(P2.agent_id, AUD.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=6)["session"]
    cellX, secX = "r1c0", "rt4-secX"
    evil = commit_mod.make_commit(s2, 1, P1.agent_id, cellX, secX)
    P1.commit(s2, 1, "r0c0", "rt4-secA")
    raw_commit(P2, s2, 1, evil)  # bound to P1's id, submitted by P2
    P1.reveal(s2, 1, "r0c0", "rt4-secA")
    expect_error(check, "4 B replays A's commitment as its own -> 400 "
                 "commitment_mismatch (agent binding)",
                 lambda: P2.reveal(s2, 1, cellX, secX),
                 400, "commitment_mismatch")
    time.sleep(7)
    P1.session_state(s2)
    H.countersign_round(AUD, s2, 1)
    auto_finish(P1, P2, AUD, s2, 2)
    check("S2 recovered via forfeit and finished",
          P1.session_state(s2)["status"] == "finished")

    # -- S3: cross-session commitment replay -------------------------------
    s3 = P1.session_open(P2.agent_id, AUD.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=6)["session"]
    P1.commit(s3, 1, "r2c2", "rt3-secA")
    raw_commit(P2, s3, 1, s1a_hash)  # P1's S1 round-1 commitment, new session
    P1.reveal(s3, 1, "r2c2", "rt3-secA")
    expect_error(check, "3 cross-session commitment replay -> 400 "
                 "commitment_mismatch",
                 lambda: P2.reveal(s3, 1, "r0c0", s1a_sec),
                 400, "commitment_mismatch")
    time.sleep(7)
    P1.session_state(s3)
    H.countersign_round(AUD, s3, 1)
    auto_finish(P1, P2, AUD, s3, 2)
    check("S3 recovered via forfeit and finished",
          P1.session_state(s3)["status"] == "finished")

    # -- S4: forged Ed25519 signatures on every method ----------------------
    s4 = P1.session_open(P2.agent_id, AUD.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=30)["session"]
    f_priv, f_pub = H.crypto_mod.generate_keypair()
    reg_env = env_mod.build_envelope(
        "agent_unregistered", "gateway", "gw.register", "gw/1", None,
        {"name": "FORGE", "pubkey": "ed25519:" + f_pub,
         "owner_display_name": "x", "vendor": "muse-test", "endpoints": {},
         "capabilities": [], "schemas": ["ttt/1", "gw/1"]},
        attacker.private_key_hex)
    expect_error(check, "8a forged gw.register -> 401 bad_signature "
                 "(never a field error)",
                 lambda: H.rpc_raw(base, "gw.register", reg_env),
                 401, "bad_signature")
    expect_error(check, "8b forged gw.friend_request -> 401 bad_signature",
                 lambda: forge(P1, "gw.friend_request", "gw.friend_request",
                               "gw/1", None, {"to": STR.agent_id}),
                 401, "bad_signature")
    expect_error(check, "8c forged gw.session_open -> 401 bad_signature",
                 lambda: forge(P1, "gw.session_open", "gw.session_open",
                               "gw/1", None,
                               {"friend_id": P2.agent_id, "app": "ttt",
                                "schema": "ttt/1", "auditor_id": AUD.agent_id}),
                 401, "bad_signature")
    expect_error(check, "8d forged gw.commit -> 401 bad_signature",
                 lambda: forge(P1, "gw.commit", "ttt.commit", "ttt/1", s4,
                               {"session": s4, "round": 1,
                                "commit": "ab" * 32}),
                 401, "bad_signature")
    expect_error(check, "8e forged ttt.commit alias -> 401 bad_signature",
                 lambda: forge(P1, "ttt.commit", "ttt.commit", "ttt/1", s4,
                               {"session": s4, "round": 1,
                                "commit": "ab" * 32}),
                 401, "bad_signature")
    expect_error(check, "8f forged gw.reveal -> 401 bad_signature",
                 lambda: forge(P1, "gw.reveal", "ttt.reveal", "ttt/1", s4,
                               {"session": s4, "round": 1, "cell": "r0c0",
                                "secret": "x"}),
                 401, "bad_signature")
    expect_error(check, "8g forged ttt.reveal alias -> 401 bad_signature",
                 lambda: forge(P1, "ttt.reveal", "ttt.reveal", "ttt/1", s4,
                               {"session": s4, "round": 1, "cell": "r0c0",
                                "secret": "x"}),
                 401, "bad_signature")
    expect_error(check, "8h forged gw.countersign (as auditor) -> 401 "
                 "bad_signature",
                 lambda: forge(AUD, "gw.countersign", "gw.countersign",
                               "gw/1", s4,
                               {"session": s4, "round": 1,
                                "auditor_sig": "ed25519:" + "ab" * 64}),
                 401, "bad_signature")
    res_state = forge(P1, "gw.session_state", "gw.session_state", "gw/1",
                      s4, {"session": s4})
    check("8i forged gw.session_state fails closed: public view, no board",
          "board" not in res_state and "notifications" not in res_state)
    unsigned = env_mod.build_envelope(
        P1.agent_id, "gateway", "gw.session_state", "gw/1", s4,
        {"session": s4}, attacker.private_key_hex)
    unsigned["sig"] = ""
    res_unsigned = H.rpc_raw(base, "gw.session_state", unsigned)
    check("8j unsigned gw.session_state: public view, no board",
          "board" not in res_unsigned
          and "notifications" not in res_unsigned)
    res_rcpt = forge(P1, "gw.receipts", "gw.receipts", "gw/1", s4,
                     {"session": s4})
    check("8k forged gw.receipts: receipts are public by design",
          isinstance(res_rcpt.get("receipts"), list))
    expect_error(check, "8l forged gw.friend_decide without console cookie "
                 "-> 403 console_only",
                 lambda: forge(P1, "gw.friend_decide", "gw.friend_decide",
                               "gw/1", None,
                               {"request_id": "fr_x", "decision": "accept"}),
                 403, "console_only")
    auto_finish(P1, P2, AUD, s4, 1)
    check("S4 unaffected by forgeries, finished clean",
          P1.session_state(s4)["status"] == "finished")

    # -- 5: stranger cannot open a session ----------------------------------
    expect_error(check, "5 non-friend opens session -> 403 not_friends",
                 lambda: STR.session_open(P1.agent_id, AUD.agent_id),
                 403, "not_friends")

    # -- 6: expired grant ----------------------------------------------------
    db.set_grant_expiry(P1.agent_id, "game.ttt:play", time.time() - 10)
    expect_error(check, "6 expired grant -> 403 grant_expired",
                 lambda: P1.session_open(P2.agent_id, AUD.agent_id),
                 403, "grant_expired")
    db.set_grant_expiry(P1.agent_id, "game.ttt:play",
                        time.time() + 365 * 86400)

    # -- 9: auditor alters a revealed move -> chain replay catches it --------
    t1 = copy.deepcopy(s1_chain)
    t1[1]["reveals"]["a"]["cell"] = "r0c2"
    expect_chain_error(check, "9a altered revealed move fails chain "
                       "naming round 2", t1, gw_pub, AUD.public_key_hex,
                       "round 2")
    t2 = copy.deepcopy(s1_chain)
    t2[1]["board_after"][0] = "b"
    expect_chain_error(check, "9b altered board_after fails chain naming "
                       "round 2", t2, gw_pub, AUD.public_key_hex, "round 2")
    t3 = copy.deepcopy(s1_chain)
    t3[-1]["result"] = "b"
    expect_chain_error(check, "9c altered game receipt fails chain naming "
                       "the game receipt", t3, gw_pub, AUD.public_key_hex,
                       "game receipt")

    # -- 7: friendship revoked mid-game (LAST: destroys the pair) ------------
    s5 = P1.session_open(P2.agent_id, AUD.agent_id,
                         commit_timeout_s=30, reveal_timeout_s=30)["session"]
    P1.commit(s5, 1, "r0c0", "rt7-secA")
    fr_id = db.friendship_id(P1.agent_id, P2.agent_id)
    console.action("/console/friendships/%s/unfriend" % fr_id)
    st5 = P1.session_state(s5)
    check("7a session frozen after mid-game unfriend",
          st5["status"] == "frozen")
    expect_error(check, "7b commit on frozen session rejected",
                 lambda: P2.commit(s5, 1, "r1c1", "rt7-secB"),
                 403, "forbidden")
    expect_error(check, "7c reveal on frozen session rejected",
                 lambda: P1.reveal(s5, 1, "r0c0", "rt7-secA"),
                 403, "forbidden")
    rc = P1.receipts(s5)
    check("7d receipt chain stays queryable after freeze",
          isinstance(rc, list))


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
