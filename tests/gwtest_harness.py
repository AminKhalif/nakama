#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shared harness for the agent-interop live-gateway test suites.

Spawns a real gateway (packages/python/gateway/server.py) on 127.0.0.1
with a throwaway sqlite db and drives it only through public surfaces:
the JSON-RPC API via gwclient, the operator console over HTTP, and the
sqlite file for test-controlled setup (invite-code reads, grant-expiry
tweaks). Gateway internals are never imported.
"""

import http.client
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, "..", "packages", "python"))
sys.path.insert(0, PKG)
SERVER = os.path.join(PKG, "gateway", "server.py")

from gwclient.client import GWClient, GatewayError  # noqa: E402
from gwclient import auditor as auditor_mod  # noqa: E402
from gwclient import crypto as crypto_mod  # noqa: E402
from gwclient import envelope as envelope_mod  # noqa: E402
from gwclient.receipts import verify_chain, ReceiptChainError  # noqa: E402
from gwclient import ttt as ttt_mod  # noqa: E402


# ---------------------------------------------------------------------------
# check framework: PASS/FAIL per check, fail-fast, final ALL N CHECKS PASSED
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self):
        self.results = []

    def __call__(self, name, cond, detail=""):
        cond = bool(cond)
        self.results.append((name, cond))
        print(("PASS " if cond else "FAIL ") + name
              + ((" -- " + str(detail)) if detail and not cond else ""),
              flush=True)
        if not cond:
            raise AssertionError("FAILED: " + name + " " + str(detail))

    def evidence(self, name, text):
        print("EVIDENCE %s: %s" % (name, text), flush=True)

    def summary(self):
        ok = sum(1 for _, c in self.results if c)
        total = len(self.results)
        print("ALL %d CHECKS PASSED" % total if ok == total
              else "%d/%d CHECKS PASSED" % (ok, total), flush=True)
        return ok == total


def expect_error(check, name, fn, code, typed):
    """fn must raise GatewayError with the exact HTTP class and typed code."""
    try:
        result = fn()
    except GatewayError as exc:
        good = exc.code == code and typed in str(exc)
        check.evidence(name, "GatewayError %s: %s"
                       % (exc.code, str(exc).split(": ", 1)[-1]))
        check(name, good, "want %s/%s, got %s/%s"
              % (code, typed, exc.code, str(exc)))
        return exc
    check(name, False, "want %s/%s, call unexpectedly succeeded: %r"
          % (code, typed, result))


# ---------------------------------------------------------------------------
# gateway lifecycle
# ---------------------------------------------------------------------------

def spawn_gateway():
    tmp = tempfile.mkdtemp(prefix="gwtest_")
    db = os.path.join(tmp, "gw.db")
    token = "testop_" + secrets.token_urlsafe(16)
    env = dict(os.environ, GW_CONSOLE_TOKEN=token)
    proc = subprocess.Popen(
        [sys.executable, SERVER, "--port", "0", "--db", db,
         "--host", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env)
    try:
        line = proc.stdout.readline()
        port = int(line.strip().rsplit(":", 1)[-1].split()[0])
    except Exception as exc:
        proc.terminate()
        raise RuntimeError("could not read gateway port: %r" % exc)
    base = "http://127.0.0.1:%d" % port
    for _ in range(200):
        try:
            with urllib.request.urlopen(base + "/healthz",
                                        timeout=2) as resp:
                if resp.status == 200 and os.path.exists(db):
                    break
        except Exception:
            pass
        time.sleep(0.05)
    else:
        proc.terminate()
        raise RuntimeError("gateway did not become healthy")
    return proc, base, db, token


def shutdown(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def healthz(base):
    with urllib.request.urlopen(base + "/healthz", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def rpc_raw(base, method, envelope, cookie=None):
    """One raw JSON-RPC call. Returns result or raises GatewayError."""
    body = json.dumps({"jsonrpc": "2.0", "id": "t1",
                       "method": method, "params": envelope}).encode()
    req = urllib.request.Request(
        base + "/rpc", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            reply = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            reply = json.loads(exc.read().decode("utf-8"))
        except Exception:
            reply = None
        if isinstance(reply, dict) and "error" in reply:
            err = reply["error"] or {}
            raise GatewayError(err.get("code"), err.get("message"),
                               err.get("data"))
        raise AssertionError("HTTP %s without JSON-RPC error" % exc.code)
    if "error" in reply:
        err = reply["error"] or {}
        raise GatewayError(err.get("code"), err.get("message"),
                           err.get("data"))
    return reply.get("result")


# ---------------------------------------------------------------------------
# operator console (separate auth domain: operator token cookie)
# ---------------------------------------------------------------------------

class Console:
    def __init__(self, base, token):
        self.base = base
        self.cookie = None
        self.login(token)

    def _http(self, method, path, body=None, headers=None):
        parts = urllib.parse.urlsplit(self.base)
        conn = http.client.HTTPConnection(parts.hostname, parts.port,
                                          timeout=10)
        h = dict(headers or {})
        if self.cookie:
            h["Cookie"] = self.cookie
        conn.request(method, path, body=body, headers=h)
        resp = conn.getresponse()
        data = resp.read()
        headers = dict(resp.getheaders())
        status = resp.status
        conn.close()
        return status, headers, data

    def login(self, token):
        body = urllib.parse.urlencode({"token": token}).encode()
        status, headers, _ = self._http(
            "POST", "/console/login", body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert status == 303, "console login failed: %s" % status
        match = re.search(r"gw_console=([^;]+)",
                          headers.get("Set-Cookie", ""))
        assert match, "no gw_console cookie on login"
        self.cookie = "gw_console=" + match.group(1)

    def action(self, path, form=None):
        """POST a console form action; 303 means it ran."""
        body = urllib.parse.urlencode(form or {}).encode()
        status, _, _ = self._http(
            "POST", path, body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert status == 303, "console action %s -> %s" % (path, status)

    def mint_invite(self, db, agent_id):
        self.action("/console/invite/%s/mint" % agent_id)
        rows = db.q("SELECT code, expires_at FROM invite_codes "
                    "WHERE agent_id=? AND used=0 ORDER BY created_at DESC "
                    "LIMIT 1", (agent_id,))
        assert rows, "no invite code minted"
        return rows[0]["code"], rows[0]["expires_at"]

    def friend_decide(self, decider_cli, request_id, decision):
        """The console API path: gw.friend_decide on /rpc with the
        operator cookie (agent keys alone get 403 console_only)."""
        env = envelope_mod.build_envelope(
            decider_cli.agent_id, "gateway", "gw.friend_decide", "gw/1",
            None, {"request_id": request_id, "decision": decision},
            decider_cli.private_key_hex)
        return rpc_raw(self.base, "gw.friend_decide", env,
                       cookie=self.cookie)


# ---------------------------------------------------------------------------
# sqlite: test-controlled setup only (invite reads, grant-expiry tweaks)
# ---------------------------------------------------------------------------

class DB:
    def __init__(self, path):
        self.path = path

    def q(self, sql, args=()):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def w(self, sql, args=()):
        con = sqlite3.connect(self.path)
        try:
            con.execute(sql, args)
            con.commit()
        finally:
            con.close()

    def grants(self, agent_id, scope="game.ttt:play"):
        return self.q("SELECT * FROM grants WHERE agent_id=? AND scope=?",
                      (agent_id, scope))

    def set_grant_expiry(self, agent_id, scope, expires_at):
        self.w("UPDATE grants SET expires_at=? WHERE agent_id=? AND scope=?",
               (expires_at, agent_id, scope))

    def friendship_id(self, a_id, b_id):
        rows = self.q("SELECT id FROM friendships WHERE "
                      "((a_id=? AND b_id=?) OR (a_id=? AND b_id=?)) "
                      "ORDER BY created_at DESC LIMIT 1",
                      (a_id, b_id, b_id, a_id))
        return rows[0]["id"] if rows else None


# ---------------------------------------------------------------------------
# agent-level flows (gwclient only)
# ---------------------------------------------------------------------------

def new_agent(base, name, owner=None, vendor="muse-test"):
    cli = GWClient.new(base)
    cli.register(name, owner_display_name=owner or (name + "-owner"),
                 vendor=vendor)
    assert cli.agent_id, "registration returned no agent_id"
    return cli


def befriend(console, db, a_cli, b_cli):
    """Invite-code request from b to a, approved in the console.
    Returns the request/friendship id."""
    code, _ = console.mint_invite(db, a_cli.agent_id)
    request_id = b_cli.friend_request(invite_code=code)
    result = console.friend_decide(a_cli, request_id, "accept")
    assert result["status"] == "accepted", result
    return request_id


def _receipt_notifications(cli, session, msg_type, rnd=None):
    notes = cli.session_state(session).get("notifications", [])
    out = [n["payload"] for n in notes if n.get("type") == msg_type]
    if rnd is not None:
        out = [p for p in out if p.get("round") == rnd]
    return out


def countersign_round(aud_cli, session, rnd):
    cands = _receipt_notifications(aud_cli, session, "ttt.round_receipt",
                                   rnd)
    assert cands, "no round receipt #%d to countersign" % rnd
    sig = auditor_mod.countersign(cands[-1], aud_cli.private_key_hex)
    return aud_cli.countersign(session, rnd, sig)


def countersign_game(aud_cli, session, rnd):
    cands = _receipt_notifications(aud_cli, session, "ttt.game_receipt")
    assert cands, "no game receipt to countersign"
    sig = auditor_mod.countersign(cands[-1], aud_cli.private_key_hex)
    return aud_cli.countersign(session, rnd, sig, kind="game")


def round_receipt(cli, session, rnd):
    receipts = cli.receipts(session)
    matches = [r for r in receipts if r.get("round") == rnd]
    assert matches, "round %d receipt not published" % rnd
    return matches[-1]


def commits_published_payload(cli, session, rnd):
    """The gateway's shuffled commit hashes for a round (from the
    player's own session-state notifications)."""
    notes = cli.session_state(session).get("notifications", [])
    cands = [n["payload"] for n in notes
             if n.get("type") == "ttt.commits_published"
             and n["payload"].get("round") == rnd]
    assert cands, "no commits_published for round %d" % rnd
    return cands[-1]


def play_round(a_cli, b_cli, aud_cli, session, rnd, cell_a, sec_a,
               cell_b, sec_b):
    """One full round: commits, reveals, auditor countersign.
    Returns (round receipt, commits_published payload)."""
    a_cli.commit(session, rnd, cell_a, sec_a)
    state_b = b_cli.commit(session, rnd, cell_b, sec_b)
    pubs = [n["payload"] for n in state_b.get("notifications", [])
            if n.get("type") == "ttt.commits_published"
            and n["payload"].get("round") == rnd]
    a_cli.reveal(session, rnd, cell_a, sec_a)
    b_cli.reveal(session, rnd, cell_b, sec_b)
    countersign_round(aud_cli, session, rnd)
    return round_receipt(a_cli, session, rnd), (pubs[0] if pubs else None)


def gw_pubkey(base):
    return healthz(base)["gw_pubkey"]
