#!/usr/bin/env python3
"""End-to-end self-test against a LIVE gateway instance (subprocess + urllib).

Full flows per spec/: register -> invite code -> friend request -> console
accept -> grant -> session open -> simultaneous commit/reveal rounds ->
auditor countersigns -> receipts -> independent chain verification.
Plus deadline forfeits, revocation, key rotation, and adversarial rejects.

NOT unit tests: every check below goes through HTTP to a real server.
Unit-level checks (crypto vectors) live in selftest_crypto.py.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway import crypto, identity, sessions as ttt, wire  # noqa: E402
from gateway.receipts import signing_bytes, published_hash  # noqa: E402

BASE = "http://127.0.0.1:18301"
CONSOLE_TOKEN = "test-operator-token"
FAILS = []
PASSES = [0]


def check(name, cond, detail=""):
    if cond:
        PASSES[0] += 1
        print("PASS " + name)
    else:
        FAILS.append(name)
        print("FAIL " + name + " " + str(detail)[:200])


def rpc(method, params, cookie=None):
    body = json.dumps({"jsonrpc": "2.0", "id": "t1", "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(BASE + "/rpc", data=body,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        raw = urllib.request.urlopen(req, timeout=20).read()
        return 200, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(path, cookie=None):
    req = urllib.request.Request(BASE + path)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post_form(path, fields, cookie=None):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Agent:
    def __init__(self, name, owner, vendor="test", schemas=None):
        self.name = name
        self.priv, self.pub = crypto.generate_keypair()
        self.pub_w = "ed25519:" + self.pub
        self.id = None
        self.owner = owner
        self.vendor = vendor
        self.schemas = schemas or ["ttt/1", "gw/1"]

    def register(self):
        env = wire.make_envelope(
            self.priv, wire.REGISTER_FROM, "gw.register",
            {"name": self.name, "pubkey": self.pub_w,
             "owner_display_name": self.owner, "vendor": self.vendor,
             "endpoints": {}, "capabilities": ["game.ttt:play"],
             "schemas": self.schemas})
        return rpc("gw.register", env)

    def call(self, method, type_, payload, session=None, schema="gw/1"):
        env = wire.make_envelope(self.priv, self.id, type_, payload,
                                 schema, session)
        return rpc(method, env)

    def commit(self, sid, rnd, cell, secret):
        h = ttt.commitment_hash(sid, rnd, self.id, cell, secret)
        return self.call("gw.commit", "ttt.commit",
                         {"round": rnd, "commit": h}, session=sid,
                         schema="ttt/1")

    def reveal(self, sid, rnd, cell, secret):
        return self.call("gw.reveal", "ttt.reveal",
                         {"round": rnd, "cell": cell, "secret": secret},
                         session=sid, schema="ttt/1")

    def state(self, sid):
        return self.call("gw.session_state", "gw.session_state",
                         {"session": sid}, session=sid)

    def countersign(self, sid, rnd, body, kind="round"):
        sig = crypto.sign(self.priv, signing_bytes(body))
        payload = {"session": sid, "round": rnd, "auditor_sig": "ed25519:" + sig}
        if kind != "round":
            payload["kind"] = kind
        return self.call("gw.countersign", "gw.countersign", payload,
                         session=sid)


def console_cookie():
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", 18301, timeout=20)
    body = urllib.parse.urlencode({"token": CONSOLE_TOKEN}).encode()
    c.request("POST", "/console/login", body,
              {"Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    r.read()
    cookie = r.getheader("Set-Cookie", "")
    c.close()
    check("console login sets cookie", r.status == 303 and bool(cookie),
          "status=%s" % r.status)
    return cookie.split(";")[0]


def notifications_for(agent, sid, mtype):
    code, res = agent.state(sid)
    if code != 200:
        return []
    return [n for n in res["result"].get("notifications", [])
            if n["type"] == mtype]


def auditor_countersign_round(auditor, sid, rnd, gw_pub):
    """The auditor's independent verification, then countersign."""
    notes = notifications_for(auditor, sid, "ttt.round_receipt")
    check("auditor got round receipt push (round %d)" % rnd, len(notes) > 0)
    body = notes[-1]["payload"]
    # verify gateway signature
    sig = wire.split_sig(body["gw_sig"])
    ok = crypto.verify(gw_pub, signing_bytes(body), sig)
    check("round %d receipt gw_sig verifies" % rnd, ok)
    # recompute board transition from the previous published receipt
    code, res = rpc("gw.receipts", wire.make_envelope(
        auditor.priv, auditor.id, "gw.receipts", {"session": sid},
        "gw/1", sid))
    prev_board = [None] * 9
    if rnd > 1:
        prev = [r for r in res["result"]["receipts"] if r.get("round") == rnd - 1]
        if prev:
            prev_board = prev[0]["board_after"]
    ca = body["reveals"]["a"]["cell"] if body["reveals"]["a"] else None
    cb = body["reveals"]["b"]["cell"] if body["reveals"]["b"] else None
    if body.get("forfeit") and (ca, cb) != (None, None):
        # reveal-deadline forfeit: the revealed cell was applied
        exp_board = list(prev_board)
        exp_board[ttt.cell_index(ca or cb)] = "a" if ca else "b"
        exp_over, exp_result = ttt.terminal(exp_board)
    elif ca and cb:
        exp_board, exp_result, exp_over = ttt.apply_moves(prev_board, ca, cb)
    else:
        exp_board, exp_result, exp_over = prev_board, "draw", False
    check("round %d board recomputes" % rnd, body["board_after"] == exp_board)
    check("round %d outcome recomputes" % rnd,
          body["result"] == exp_result and body["game_over"] == exp_over)
    code, res = auditor.countersign(sid, rnd, body)
    check("auditor countersigns round %d" % rnd,
          code == 200 and res["result"]["countersigned"], str(res)[:120])
    return body


def verify_chain(sid, gw_pub, auditor_pub, expect_rounds, expect_result):
    """receipts.md §3 verification, independently reimplemented."""
    env = {"gw": "gw/1", "msg_id": "msg_" + "ab" * 8, "from": "spectator",
           "to": "gateway", "type": "gw.receipts", "schema": "gw/1",
           "session": sid, "payload": {"session": sid}, "sig": ""}
    code, res = rpc("gw.receipts", env)
    check("receipts exported for chain check", code == 200)
    rs = res["result"]["receipts"]
    rounds = [r for r in rs if "round" in r]
    games = [r for r in rs if "round" not in r]
    check("chain has %d round receipts + 1 game receipt" % expect_rounds,
          len(rounds) == expect_rounds and len(games) == 1,
          "got %d+%d" % (len(rounds), len(games)))
    if not (len(rounds) == expect_rounds and len(games) == 1):
        return False
    ok = True
    for i, r in enumerate(rounds):
        if r["round"] != i + 1:
            ok = False
        for key, keyhex in (("gw_sig", gw_pub), ("auditor_sig", auditor_pub)):
            s = wire.split_sig(r[key])
            if not s or not crypto.verify(keyhex, signing_bytes(r), s):
                ok = False
        want_prev = "0" * 64 if i == 0 else published_hash(rounds[i - 1])
        if r["prev_hash"] != want_prev:
            ok = False
        if r["schema_versions"] != {"ttt": "ttt/1"}:
            ok = False
        if not r["game_over"] and r["result"] != "draw":
            ok = False
    check("chain links, sigs, rounds 1..N all valid", ok)
    g = games[0]
    check("game receipt rounds_played matches",
          g["rounds_played"] == expect_rounds)
    check("game receipt chains from last round",
          g["prev_hash"] == published_hash(rounds[-1]))
    check("game receipt result matches", g["result"] == expect_result,
          g["result"])
    check("game final_board matches last round",
          g["final_board"] == rounds[-1]["board_after"])
    for key, keyhex in (("gw_sig", gw_pub), ("auditor_sig", auditor_pub)):
        s = wire.split_sig(g[key])
        check("game receipt " + key + " verifies",
              bool(s) and crypto.verify(keyhex, signing_bytes(g), s))
    # secrets must never appear in any receipt
    blob = json.dumps(rs)
    check("no secret material in receipts", "secret" not in blob.lower())
    return ok


def main():
    db = tempfile.mktemp(suffix=".db")
    env = dict(os.environ, GW_CONSOLE_TOKEN=CONSOLE_TOKEN)
    srv = subprocess.Popen(
        [sys.executable, "server.py", "--port", "18301", "--db", db,
         "--host", "127.0.0.1"], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(4)
        run(db)
    finally:
        srv.terminate()
        srv.wait(timeout=10)
    print()
    if FAILS:
        print("FAILURES: %d  (%s)" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("ALL %d CHECKS PASSED" % PASSES[0])


def run(db):
    # -- discovery -------------------------------------------------------
    code, raw = get("/healthz")
    check("healthz", code == 200 and json.loads(raw)["ok"])
    code, raw = get("/.well-known/agent-card.json")
    card = json.loads(raw)
    check("agent card", code == 200 and card["protocolVersion"] == "1.0.1")
    gw_pub_w = card["gwPubkey"]
    check("card carries gwPubkey", gw_pub_w.startswith("ed25519:"))
    gw_pub = gw_pub_w[len("ed25519:"):]
    code, raw = get("/.well-known/revocations.json")
    rev = json.loads(raw)
    check("revocation list empty + signed", code == 200 and rev["revoked"] == []
          and crypto.verify(gw_pub, wire.canonical_bytes(
              {k: v for k, v in rev.items() if k != "gw_sig"}),
              wire.split_sig(rev["gw_sig"])))

    # -- registration ------------------------------------------------------
    A = Agent("ALICE", "Alex")
    code, res = A.register()
    check("ALICE registers", code == 200, str(res)[:120])
    A.id = res["result"]["agent_id"]
    doc = res["result"]["identity_document"]
    check("identity doc verifies offline",
          identity.verify_identity_doc(doc, gw_pub))
    check("doc pubkey prefixed", doc["pubkey"] == A.pub_w)
    check("doc has deprecated_schemas", doc["deprecated_schemas"] == [])

    B = Agent("Ahmed", "Ahmed")
    code, res = B.register()
    check("Ahmed registers", code == 200)
    B.id = res["result"]["agent_id"]
    C = Agent("Ref", "Ops")
    code, res = C.register()
    check("auditor registers", code == 200)
    C.id = res["result"]["agent_id"]

    evil = Agent("Evil", "X")
    bad = wire.make_envelope(evil.priv, wire.REGISTER_FROM, "gw.register",
                             {"name": "Evil", "pubkey": evil.pub_w,
                              "owner_display_name": "X", "vendor": "x",
                              "endpoints": {}, "capabilities": [],
                              "schemas": ["ttt/1"]})
    bad["sig"] = "ed25519:" + "00" * 64
    code, res = rpc("gw.register", bad)
    check("bad envelope signature rejected",
          code == 401 and res["error"]["message"] == "bad_signature",
          str(res)[:100])
    bad2 = wire.make_envelope(evil.priv, "agent_someone", "gw.register",
                              {"name": "Evil2", "pubkey": evil.pub_w,
                               "owner_display_name": "X", "vendor": "x",
                               "endpoints": {}, "capabilities": [],
                               "schemas": ["ttt/1"]})
    code, res = rpc("gw.register", bad2)
    check("register from wrong sender rejected",
          code == 400 and res["error"]["message"] == "bad_envelope",
          str(res)[:100])
    # forged signature must yield bad_signature even when fields are also bad
    forged = wire.make_envelope(evil.priv, wire.REGISTER_FROM, "gw.register",
                                {"name": "Evil3", "pubkey": evil.pub_w,
                                 "owner_display_name": "X",
                                 "endpoints": {}, "capabilities": [],
                                 "schemas": ["ttt/1"]})
    forged["sig"] = "ed25519:" + "ff" * 64
    code, res = rpc("gw.register", forged)
    check("forged register sig -> 401 bad_signature (not field error)",
          code == 401 and res["error"]["message"] == "bad_signature",
          str(res)[:120])
    dup = Agent("ALICE", "Clone")
    code, res = dup.register()
    check("duplicate name rejected",
          code == 409 and res["error"]["message"] == "name_taken",
          str(res)[:100])

    # -- console + friendship ----------------------------------------------
    ccode, craw = get("/console")
    check("console needs login", ccode == 200 and b"operator token" in craw)
    cookie = console_cookie()
    check("console login works", bool(cookie), str(cookie)[:40])

    code, _ = post_form("/console/invite/%s/mint" % A.id, {}, cookie)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    row = con.execute("SELECT code FROM invite_codes WHERE agent_id=? AND used=0"
                      " ORDER BY created_at DESC LIMIT 1", (A.id,)).fetchone()
    icode = row["code"]
    check("invite code minted", bool(icode))

    code, res = B.call("gw.friend_request", "gw.friend_request",
                       {"invite_code": icode})
    check("friend request via invite code", code == 200, str(res)[:120])
    req_id = res["result"]["request_id"]
    code, res = B.call("gw.friend_request", "gw.friend_request",
                       {"invite_code": icode})
    check("single-use code rejected on reuse",
          code == 400, str(res)[:100])

    # agents cannot approve: 403 console_only
    env = wire.make_envelope(A.priv, A.id, "gw.friend_decide",
                             {"request_id": req_id, "decision": "accept"})
    code, res = rpc("gw.friend_decide", env)
    check("agent-key friend_decide -> 403 console_only",
          code == 403 and res["error"]["message"] == "console_only",
          str(res)[:120])

    # human accepts via the JSON-RPC console path
    env = {"gw": "gw/1", "msg_id": "msg_" + "cd" * 8, "from": B.id,
           "to": "gateway", "type": "gw.friend_decide", "schema": "gw/1",
           "session": None,
           "payload": {"request_id": req_id, "decision": "accept"}, "sig": ""}
    code, res = rpc("gw.friend_decide", env, cookie)
    check("console accepts via gw.friend_decide",
          code == 200 and res["result"]["status"] == "accepted",
          str(res)[:150])
    rows = con.execute("SELECT scope FROM grants WHERE agent_id=?", (A.id,)).fetchall()
    check("grants minted both sides",
          {r["scope"] for r in rows} == {"game.ttt:play", "game.ttt:spectate"})
    n = con.execute("SELECT COUNT(*) c FROM outbox WHERE msg_type='friends.update'").fetchone()["c"]
    check("friends.update pushed to both agents", n == 2, str(n))

    # -- session open ---------------------------------------------------------
    D = Agent("Stranger", "S")
    code, res = D.register()
    D.id = res["result"]["agent_id"]
    code, res = D.call("gw.session_open", "gw.session_open",
                       {"friend_id": A.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    check("non-friend session blocked (403 not_friends)",
          code == 403 and res["error"]["message"] == "not_friends",
          str(res)[:100])

    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": A.id})
    check("self-auditor rejected", code == 400, str(res)[:100])

    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    check("session opens", code == 200, str(res)[:150])
    sid = res["result"]["session"]
    check("open returns active/commit state",
          res["result"]["status"] == "active" and res["result"]["phase"] == "commit")
    check("players keyed a/b",
          res["result"]["players"] == {"a": A.id, "b": B.id})
    notes = notifications_for(A, sid, "ttt.session_open")
    check("session_open pushed to player", len(notes) == 1
          and notes[0]["from"] == "gateway")

    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    check("second live session -> 409 session_active",
          code == 409 and res["error"]["message"] == "session_active",
          str(res)[:100])

    # -- round 1: full simultaneous flow ---------------------------------------
    s1, s2, s3 = "s3cr3t-one-0001", "s3cr3t-two-0002", "s3cr3t-tre-0003"
    code, res = A.commit(sid, 1, "r0c0", s1)
    check("A commits round 1", code == 200)
    code, res = A.commit(sid, 1, "r0c0", s1)
    check("duplicate commit -> 409 already_committed",
          code == 409 and res["error"]["message"] == "already_committed",
          str(res)[:100])
    code, res = B.commit(sid, 1, "r1c0", s2)
    check("B commits round 1", code == 200)
    pubs = notifications_for(A, sid, "ttt.commits_published")
    check("commits_published pushed", len(pubs) == 1)
    commits = pubs[0]["payload"]["commits"]
    check("published commits shuffled, no cells",
          {c["player"] for c in commits} == {"a", "b"}
          and all(len(c["commit"]) == 64 for c in commits))

    code, res = A.reveal(sid, 1, "r0c0", "wrong-secret")
    check("tampered reveal -> 400 commitment_mismatch",
          code == 400 and res["error"]["message"] == "commitment_mismatch",
          str(res)[:100])
    code, res = A.reveal(sid, 1, "r0c0", s1)
    check("A reveals round 1", code == 200)
    code, res = A.reveal(sid, 1, "r0c0", s1)
    check("duplicate reveal -> 409 already_revealed",
          code == 409 and res["error"]["message"] == "already_revealed",
          str(res)[:100])
    code, res = B.reveal(sid, 1, "r1c0", s2)
    check("B reveals round 1", code == 200)
    body = auditor_countersign_round(C, sid, 1, gw_pub)
    check("round 1 board correct",
          body["board_after"] == ["a", None, None, "b", None, None,
                                  None, None, None])
    check("round 1 not game over",
          body["game_over"] is False and body["result"] == "draw")
    check("round 1 prev is genesis", body["prev_hash"] == "0" * 64)
    check("reveals carry cells not secrets",
          body["reveals"] == {"a": {"cell": "r0c0"}, "b": {"cell": "r1c0"}})

    # -- rounds 2-3: A wins -------------------------------------------------------
    code, _ = A.commit(sid, 2, "r0c1", s1)
    code, _ = B.commit(sid, 2, "r1c1", s2)
    code, _ = A.reveal(sid, 2, "r0c1", s1)
    code, _ = B.reveal(sid, 2, "r1c1", s2)
    auditor_countersign_round(C, sid, 2, gw_pub)
    code, _ = A.commit(sid, 3, "r0c2", s1)
    code, _ = B.commit(sid, 3, "r2c2", s2)
    code, _ = A.reveal(sid, 3, "r0c2", s1)
    code, _ = B.reveal(sid, 3, "r2c2", s2)
    body3 = auditor_countersign_round(C, sid, 3, gw_pub)
    check("round 3 ends the game for a",
          body3["game_over"] is True and body3["result"] == "a")
    check("b's late cell recorded not applied",
          body3["board_after"][8] is None
          and body3["reveals"]["b"] == {"cell": "r2c2"})

    # game receipt
    notes = notifications_for(C, sid, "ttt.game_receipt")
    check("game receipt pushed to auditor", len(notes) == 1)
    gbody = notes[-1]["payload"]
    check("game receipt gw_sig verifies",
          crypto.verify(gw_pub, signing_bytes(gbody),
                        wire.split_sig(gbody["gw_sig"])))
    code, res = C.countersign(sid, 3, gbody, kind="game")
    check("auditor countersigns game receipt",
          code == 200 and res["result"]["countersigned"], str(res)[:120])
    code, res = A.state(sid)
    check("session finished", code == 200
          and res["result"]["status"] == "finished"
          and res["result"]["phase"] == "done")
    verify_chain(sid, gw_pub, C.pub, 3, "a")

    # -- draw game with last-cell rule -----------------------------------------------------
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id,
                        "commit_timeout_s": 600, "reveal_timeout_s": 600})
    sid3 = res["result"]["session"]
    draw_moves = [("r0c0", "r0c2"), ("r0c1", "r1c0"), ("r1c2", "r1c1"),
                  ("r2c0", "r2c1")]
    for i, (ca, cb) in enumerate(draw_moves, 1):
        A.commit(sid3, i, ca, "da%d" % i)
        B.commit(sid3, i, cb, "db%d" % i)
        A.reveal(sid3, i, ca, "da%d" % i)
        B.reveal(sid3, i, cb, "db%d" % i)
        auditor_countersign_round(C, sid3, i, gw_pub)
    A.commit(sid3, 5, "r2c2", "da5")
    B.commit(sid3, 5, "r2c2", "db5")
    A.reveal(sid3, 5, "r2c2", "da5")
    B.reveal(sid3, 5, "r2c2", "db5")
    body5 = auditor_countersign_round(C, sid3, 5, gw_pub)
    check("last-cell rule: a claims the final cell",
          body5["board_after"][8] == "a")
    check("full board with no line is a draw",
          body5["game_over"] is True and body5["result"] == "draw")
    notes = notifications_for(C, sid3, "ttt.game_receipt")
    C.countersign(sid3, 5, notes[-1]["payload"], kind="game")
    verify_chain(sid3, gw_pub, C.pub, 5, "draw")

    # -- A2A message/send ----------------------------------------------------------------------
    a2a_env = wire.make_envelope(A.priv, A.id, "gw.session_state",
                                 {"session": sid3}, "gw/1", sid3)
    a2a_params = {"message": {"role": "user", "parts": [
        {"kind": "text", "text": json.dumps(a2a_env)}]}}
    code, res = rpc("message/send", a2a_params)
    check("A2A message/send works",
          code == 200 and "result" in res, str(res)[:120])

    # -- commit-deadline forfeit ------------------------------------------------------------------
    # Generous reveal_timeout_s: the test auditor's pure-Python crypto is
    # slow, and the countersign deadline runs on reveal_timeout_s.
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id,
                        "commit_timeout_s": 3, "reveal_timeout_s": 12})
    sid4 = res["result"]["session"]
    A.commit(sid4, 1, "r0c0", "fa1")
    time.sleep(3.6)
    code, res = A.state(sid4)  # read applies the timeout
    check("commit deadline fired", code == 200
          and res["result"]["phase"] == "awaiting_countersign")
    body = auditor_countersign_round(C, sid4, 1, gw_pub)
    check("forfeit recorded: b missed commit",
          body["forfeit"] == "b" and body["result"] == "draw"
          and body["board_after"] == [None] * 9)
    check("game continues after forfeit round",
          C.countersign(sid4, 1, body)[0] == 200)
    code, res = A.state(sid4)
    check("round 2 opened", res["result"]["round"] == 2
          and res["result"]["phase"] == "commit")

    # -- reveal-deadline forfeit --------------------------------------------------------------------
    A.commit(sid4, 2, "r1c1", "fb1")
    B.commit(sid4, 2, "r2c2", "fb2")
    A.reveal(sid4, 2, "r1c1", "fb1")
    time.sleep(12.6)
    B.state(sid4)
    body = auditor_countersign_round(C, sid4, 2, gw_pub)
    check("forfeit recorded: b missed reveal; a's cell applied",
          body["forfeit"] == "b" and body["board_after"][4] == "a"
          and body["reveals"]["b"] is None)

    # -- countersign timeout freezes ------------------------------------------------------------------
    code, res = A.state(sid4)
    check("round 3 open", res["result"]["round"] == 3)
    A.commit(sid4, 3, "r0c1", "fc1")
    B.commit(sid4, 3, "r0c2", "fc2")
    A.reveal(sid4, 3, "r0c1", "fc1")
    B.reveal(sid4, 3, "r0c2", "fc2")
    time.sleep(12.6)  # auditor never countersigns
    code, res = A.state(sid4)
    check("missing countersign freezes session",
          res["result"]["status"] == "frozen", str(res["result"])[:120])
    code, res = C.countersign(sid4, 3, notifications_for(
        C, sid4, "ttt.round_receipt")[-1]["payload"])
    check("countersign on frozen session rejected", code == 403,
          str(res)[:80])

    # -- grant revoke freezes ---------------------------------------------------------------------------
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    sid5 = res["result"]["session"]
    A.commit(sid5, 1, "r0c0", "g1")
    grant = con.execute("SELECT id FROM grants WHERE agent_id=? AND scope=?",
                        (A.id, "game.ttt:play")).fetchone()
    code, _ = post_form("/console/grants/%s/revoke" % grant["id"], {}, cookie)
    code, res = A.state(sid5)
    check("revoke freezes live session", res["result"]["status"] == "frozen")
    code, res = B.commit(sid5, 1, "r1c1", "g2")
    check("commit on frozen session rejected", code == 403, str(res)[:80])
    code, _ = post_form("/console/grants/%s/restore" % grant["id"], {}, cookie)
    con.execute("UPDATE grants SET expires_at=? WHERE id=?",
                (time.time() - 10, grant["id"]))
    con.commit()
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    check("expired grant blocks open (403 grant_expired)",
          code == 403 and res["error"]["message"] == "grant_expired",
          str(res)[:100])
    con.execute("UPDATE grants SET expires_at=? WHERE id=?",
                (time.time() + 365 * 86400, grant["id"]))
    con.commit()

    # -- adversarial session: collision, illegal move, replay, envelopes ----
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id,
                        "commit_timeout_s": 3, "reveal_timeout_s": 8})
    check("adversarial session opens", code == 200, str(res)[:100])
    sid6 = res["result"]["session"]

    code, res = A.commit(sid, 1, "r0c0", s1)
    check("commit on finished session rejected", code == 409, str(res)[:60])

    A.commit(sid6, 1, "r0c0", s1)
    B.commit(sid6, 1, "r2c2", s2)
    A.reveal(sid6, 1, "r0c0", s1)
    B.reveal(sid6, 1, "r2c2", s2)
    auditor_countersign_round(C, sid6, 1, gw_pub)

    # same-cell collision -> drawn round, board unchanged
    A.commit(sid6, 2, "r1c1", s1)
    B.commit(sid6, 2, "r1c1", s2)
    A.reveal(sid6, 2, "r1c1", s1)
    B.reveal(sid6, 2, "r1c1", s2)
    body = auditor_countersign_round(C, sid6, 2, gw_pub)
    check("collision round drawn, board unchanged",
          body["result"] == "draw" and body["game_over"] is False
          and body["board_after"][0] == "a"
          and body["board_after"][8] == "b"
          and body["board_after"][4] is None)

    # illegal move: r0c0 is taken since round 1
    A.commit(sid6, 3, "r0c0", "stuck-secret-1")
    B.commit(sid6, 3, "r1c2", s2)
    code, res = A.reveal(sid6, 3, "r0c0", "stuck-secret-1")
    check("reveal of taken cell -> 400 illegal_move",
          code == 400 and res["error"]["message"] == "illegal_move",
          str(res)[:100])
    time.sleep(8.6)  # reveal deadline: nobody revealed legally
    B.state(sid6)
    body = auditor_countersign_round(C, sid6, 3, gw_pub)
    check("double-missed reveal -> drawn round",
          body["forfeit"] is None and body["result"] == "draw"
          and body["board_after"][0] == "a")

    # cross-session replay: game-1 commitment smuggled into this game
    stale = ttt.commitment_hash(sid, 1, A.id, "r0c0", s1)
    code, res = A.call("gw.commit", "ttt.commit",
                       {"round": 4, "commit": stale}, session=sid6,
                       schema="ttt/1")
    check("stale commit stored (binding checked at reveal)", code == 200,
          str(res)[:60])

    # replay: B's commit envelope delivered twice
    env = wire.make_envelope(B.priv, B.id, "ttt.commit",
                             {"round": 4, "commit": "cd" * 32}, "ttt/1", sid6)
    code1, r1 = rpc("gw.commit", env)
    check("B commit stored", code1 == 200, str(r1)[:80])
    code, res = rpc("gw.commit", env)  # exact replay
    check("replayed msg_id -> 409 duplicate",
          code == 409 and res["error"]["message"] == "duplicate",
          str(res)[:80])

    code, res = A.reveal(sid6, 4, "r0c0", s1)
    check("cross-session reveal -> 400 commitment_mismatch",
          code == 400 and res["error"]["message"] == "commitment_mismatch",
          str(res)[:80])

    # envelope attacks: all rejected before any state change
    env = wire.make_envelope(A.priv, A.id, "ttt.commit",
                             {"round": 4, "commit": "ab" * 32}, "ttt/1", sid6)
    env["to"] = "someone-else"
    code, res = rpc("gw.commit", env)
    check("wrong to -> 400 bad_envelope",
          code == 400 and res["error"]["message"] == "bad_envelope",
          str(res)[:80])
    env = wire.make_envelope(A.priv, A.id, "ttt.commit",
                             {"round": 4, "commit": "ab" * 32}, "ttt/1", sid6)
    env["msg_id"] = "not-a-valid-id"
    code, res = rpc("gw.commit", env)
    check("bad msg_id -> 400 bad_envelope",
          code == 400 and res["error"]["message"] == "bad_envelope",
          str(res)[:80])
    env = wire.make_envelope(A.priv, A.id, "ttt.commit",
                             {"round": 4, "commit": "ab" * 32,
                              "session": "sess_other"}, "ttt/1", sid6)
    code, res = rpc("gw.commit", env)
    check("payload/session mismatch -> 400 bad_envelope",
          code == 400 and res["error"]["message"] == "bad_envelope",
          str(res)[:80])
    env = wire.make_envelope(A.priv, A.id, "ttt.commit",
                             {"round": 4, "commit": "ab" * 32}, "ttt/1", sid6)
    env["sig"] = "ed25519:" + "ff" * 64
    code, res = rpc("gw.commit", env)
    check("bad signature -> 401", code == 401, str(res)[:80])
    env = wire.make_envelope(A.priv, A.id, "ttt.commit",
                             {"round": 4, "commit": "ab" * 32}, "ttt/1", sid6)
    del env["sig"]
    code, res = rpc("gw.commit", env)
    check("missing signature -> 401", code == 401, str(res)[:80])
    code, res = C.commit(sid6, 4, "r0c0", "x")
    check("non-player commit -> 403 forbidden",
          code == 403 and res["error"]["message"] == "forbidden",
          str(res)[:80])
    code, res = rpc("gw.commit", wire.make_envelope(
        A.priv, A.id, "gw.commit", {"round": 4, "commit": "ab" * 32},
        "ttt/1", sid6))
    check("method/type mismatch rejected",
          code == 400 and res["error"]["message"] == "bad_envelope",
          str(res)[:80])

    # -- unfriend blocks new sessions ----------------------------------------------------------------------
    fr = con.execute("SELECT id FROM friendships WHERE "
                     "((a_id=? AND b_id=?) OR (a_id=? AND b_id=?))",
                     (A.id, B.id, B.id, A.id)).fetchone()
    code, _ = post_form("/console/friendships/%s/unfriend" % fr["id"], {},
                        cookie)
    code, res = A.call("gw.session_open", "gw.session_open",
                       {"friend_id": B.id, "app": "ttt", "schema": "ttt/1",
                        "auditor_id": C.id})
    check("session after unfriend blocked (403 not_friends)",
          code == 403 and res["error"]["message"] == "not_friends",
          str(res)[:100])

    # -- key revocation ----------------------------------------------------------------------------------------
    code, _ = post_form("/console/keys/revoke",
                        {"pubkey": B.pub_w, "reason": "test"}, cookie)
    code, res = B.call("gw.session_state", "gw.session_state",
                       {"session": sid3}, session=sid3)
    check("revoked key rejected (403 revoked)",
          code == 403 and res["error"]["message"] == "revoked",
          str(res)[:100])
    code, raw = get("/.well-known/revocations.json")
    rev = json.loads(raw)
    check("revocation list carries the key",
          B.pub_w in rev["revoked"]
          and crypto.verify(gw_pub, wire.canonical_bytes(
              {k: v for k, v in rev.items() if k != "gw_sig"}),
              wire.split_sig(rev["gw_sig"])))

    # -- expired identity -------------------------------------------------------------------------------------------
    E = Agent("Old", "O")
    code, res = E.register()
    E.id = res["result"]["agent_id"]
    row = con.execute("SELECT identity_doc FROM agents WHERE id=?",
                      (E.id,)).fetchone()
    doc = json.loads(row["identity_doc"])
    doc["expires_at"] = "2000-01-01T00:00:00+00:00"
    con.execute("UPDATE agents SET identity_doc=?, expires_at=? WHERE id=?",
                (json.dumps(doc), doc["expires_at"], E.id))
    con.commit()
    code, res = E.call("gw.friend_request", "gw.friend_request",
                       {"to": A.id})
    check("expired identity rejected (403 revoked)",
          code == 403 and res["error"]["message"] == "revoked",
          str(res)[:100])

    # -- key rotation ---------------------------------------------------------------------------------------------------
    code, _ = post_form("/console/keys/rotate",
                        {"agent_id": E.id, "new_pubkey": E.pub_w}, cookie)
    row = con.execute("SELECT pubkey FROM agents WHERE id=?",
                      (E.id,)).fetchone()
    check("rotation with same key changes nothing", row["pubkey"] == E.pub)
    E2priv, E2pub = crypto.generate_keypair()
    code, _ = post_form("/console/keys/rotate",
                        {"agent_id": E.id,
                         "new_pubkey": "ed25519:" + E2pub}, cookie)
    row = con.execute("SELECT pubkey FROM agents WHERE id=?",
                      (E.id,)).fetchone()
    check("key rotated", row["pubkey"] == E2pub)
    row = con.execute("SELECT 1 FROM revocations WHERE pubkey=?",
                      (E.pub,)).fetchone()
    check("old key revoked on rotation", bool(row))

    # -- spectator page ----------------------------------------------------------------------------------------------------
    code, raw = get("/g/" + sid3)
    check("spectator page renders", code == 200 and b"board" in raw)
    check("no secrets in spectator html", b"da5" not in raw and b"db5" not in raw)

    # -- console auth boundary -----------------------------------------------------------------------------------------------
    code, raw = post_form("/console/requests/x/accept", {})
    check("console action without login shows login",
          code == 200 and b"operator token" in raw)

    con.close()


if __name__ == "__main__":
    main()
