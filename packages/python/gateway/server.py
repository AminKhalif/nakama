#!/usr/bin/env python3
"""Agent Interop Gateway -- HTTP entry point.

Run: python3 server.py --port 8080 --db gw.db --host 127.0.0.1

Agents talk A2A JSON-RPC 2.0 to POST /rpc; every call's params is one
signed envelope (spec/envelope.md). Also serves the A2A Agent Card, the
signed revocation list, spectator pages, and the human console.

Game logic never touches HTTP: this file parses requests, authenticates
envelopes (fail closed), and calls the domain modules, which return
plain dicts.
"""

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Allow `python3 server.py` from inside the package directory as well as
# `python3 -m gateway.server` from packages/python.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway import console as console_mod  # noqa: E402
from gateway import crypto  # noqa: E402
from gateway import friends, identity, receipts  # noqa: E402
from gateway import sessions as ttt  # noqa: E402
from gateway import spectator, sqlite_store, wire  # noqa: E402
from gateway import __version__  # noqa: E402

MAX_BODY = 65536


class Ctx:
    def __init__(self, store, gw_keys):
        self.store = store
        self.gw_keys = gw_keys


# ---------------------------------------------------------------------------
# JSON-RPC dispatch. params is always exactly one envelope (envelope.md §3).
# ---------------------------------------------------------------------------

def _bad_envelope(detail):
    return wire.AppError("bad_envelope", detail, 400)


def _check_envelope(ctx, method, env):
    """Structural envelope checks. Returns None or raises bad_envelope."""
    reason = wire.validate_envelope_shape(env)
    if reason:
        raise _bad_envelope(reason)
    if env["to"] != wire.GATEWAY_ID:
        raise _bad_envelope('envelope "to" must be "gateway"')
    want_type, want_schema = wire.METHOD_TYPE_PAIRS[method]
    if env["type"] != want_type:
        raise _bad_envelope("method/type mismatch: %s needs type %s"
                            % (method, want_type))
    if env["schema"] != want_schema:
        raise _bad_envelope("method/schema mismatch: %s needs schema %s"
                            % (method, want_schema))
    payload = env["payload"]
    if method == "gw.register":
        if env["from"] != wire.REGISTER_FROM:
            raise _bad_envelope('gw.register needs from "%s"'
                                % wire.REGISTER_FROM)
        if env["session"] is not None:
            raise _bad_envelope("gw.register takes no session")
    else:
        session_scoped = method in ("gw.commit", "ttt.commit", "gw.reveal",
                                    "ttt.reveal", "gw.countersign",
                                    "gw.session_state", "gw.receipts")
        if session_scoped and not env["session"]:
            raise _bad_envelope(method + " needs a session")
        if not session_scoped and env["session"] is not None:
            raise _bad_envelope(method + " takes no session")
        if payload.get("session") is not None \
                and payload["session"] != env["session"]:
            raise _bad_envelope("payload.session must equal envelope session")
    return payload


def _verify_caller(ctx, env):
    """Fail-closed authentication for one signed envelope.

    Returns the agent_id. Raises 401 unauthorized / bad_signature, or
    403 revoked for revoked/expired keys.
    """
    agent = ctx.store.get_agent(env["from"])
    if not agent:
        raise wire.AppError("unauthorized", "unknown sender id", 401)
    if ctx.store.is_revoked(agent["pubkey"]):
        raise wire.AppError("revoked", "this key was revoked", 403)
    if identity.doc_expired(agent["identity_doc"]):
        raise wire.AppError("revoked", "identity document expired", 403)
    sig_hex = wire.split_sig(env.get("sig"))
    if not sig_hex:
        raise wire.AppError("bad_signature",
                            "missing or malformed sig (want ed25519:<128 hex>)",
                            401)
    body = {k: v for k, v in env.items() if k != "sig"}
    if not crypto.verify(agent["pubkey"], wire.canonical_bytes(body), sig_hex):
        raise wire.AppError("bad_signature", "bad signature", 401)
    if not ctx.store.note_message(env["msg_id"], env["from"]):
        raise wire.AppError("duplicate", "msg_id already seen", 409)
    return agent["id"]


def _optional_caller(ctx, env):
    """For public reads: return the agent_id iff the envelope carries a
    valid signature from a registered, live key, else None. A revoked or
    expired key is rejected outright (403), even on public reads."""
    agent = ctx.store.get_agent(env.get("from"))
    if not agent:
        return None
    if ctx.store.is_revoked(agent["pubkey"]):
        raise wire.AppError("revoked", "this key was revoked", 403)
    if identity.doc_expired(agent["identity_doc"]):
        raise wire.AppError("revoked", "identity document expired", 403)
    sig_hex = wire.split_sig(env.get("sig"))
    if not sig_hex:
        return None
    body = {k: v for k, v in env.items() if k != "sig"}
    if not crypto.verify(agent["pubkey"], wire.canonical_bytes(body), sig_hex):
        return None
    return agent["id"]


def dispatch(ctx, method, params, console_authed=False):
    """Route one JSON-RPC call. Returns the result dict."""
    if method == "message/send":
        return _dispatch_a2a(ctx, params)
    if method not in wire.METHOD_TYPE_PAIRS:
        raise wire.WireError(wire.METHOD_NOT_FOUND, "unknown method: " + method)
    if not isinstance(params, dict):
        raise _bad_envelope("params must be exactly one envelope object")
    env = params
    payload = _check_envelope(ctx, method, env)

    if method == "gw.register":
        result, err = identity.register(ctx.store, ctx.gw_keys, env)
        if err:
            raise err
        return result

    if method == "gw.friend_decide":
        # Console auth domain only: agent keys get 403 console_only.
        if not console_authed:
            raise wire.AppError("console_only",
                                "gw.friend_decide needs the human console "
                                "session; agent keys cannot approve", 403)
        result, err = friends.human_decide(
            ctx.store, ctx.gw_keys, payload.get("request_id"),
            (payload.get("decision") or "") == "accept")
        if err:
            raise err
        return result

    if method in wire.PUBLIC_METHODS:
        viewer_id = _optional_caller(ctx, env)
        if method == "gw.session_state":
            state = ttt.get_state(ctx.store, ctx.gw_keys, env["session"],
                                  viewer_id, viewer_id is not None)
            if not state:
                raise wire.AppError("not_found", "unknown session", 404)
            return state
        if method == "gw.receipts":
            if not ctx.store.get_session(env["session"]):
                raise wire.AppError("not_found", "unknown session", 404)
            return receipts.export(ctx.store, env["session"])
        raise wire.WireError(wire.METHOD_NOT_FOUND, "unknown method: " + method)

    agent_id = _verify_caller(ctx, env)
    if method == "gw.friend_request":
        result, err = friends.friend_request(ctx.store, agent_id, payload)
    elif method == "gw.session_open":
        result, err = ttt.open_session(ctx.store, ctx.gw_keys, agent_id, payload)
    elif method in ("gw.commit", "ttt.commit"):
        result, err = ttt.commit(ctx.store, ctx.gw_keys, agent_id,
                                 env["session"], payload)
    elif method in ("gw.reveal", "ttt.reveal"):
        result, err = ttt.reveal(ctx.store, ctx.gw_keys, agent_id,
                                 env["session"], payload)
    elif method == "gw.countersign":
        result, err = receipts.countersign(ctx.store, ctx.gw_keys, agent_id,
                                           env["session"], payload)
    else:  # pragma: no cover -- pairing table is exhaustive
        raise wire.WireError(wire.METHOD_NOT_FOUND, "unknown method: " + method)
    if err:
        raise err
    return result


def _dispatch_a2a(ctx, params):
    """A2A message/send: the envelope rides as a TextPart. Pure-A2A clients
    can carry envelopes; acting still needs a valid signature."""
    inner = wire.unwrap_a2a_message(params)
    if not isinstance(inner, dict) or not inner.get("type"):
        raise wire.WireError(wire.INVALID_PARAMS,
                             "text part must carry the envelope with a type")
    msg_type = inner["type"]
    method = {"ttt.commit": "gw.commit",
              "ttt.reveal": "gw.reveal"}.get(msg_type, msg_type)
    if method not in wire.METHOD_TYPE_PAIRS:
        raise wire.WireError(wire.METHOD_NOT_FOUND, "unknown type: " + msg_type)
    result = dispatch(ctx, method, inner)
    return wire.wrap_a2a_result(result)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "AgentGateway/" + __version__
    ctx = None            # set by main()
    console_app = None    # set by main()

    def log_message(self, *a):
        sys.stderr.write("[gw] %s\n" % " ".join(str(x) for x in a))

    # -- small responders ------------------------------------------------
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def send_html(self, html):
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def see_other(self, url, cookie=None):
        self.send_response(303)
        self.send_header("Location", url)
        if cookie:
            name, value = cookie
            self.send_header("Set-Cookie",
                             "%s=%s; Path=/; HttpOnly; SameSite=Lax" % (name, value))
        self.end_headers()

    def read_form(self):
        from urllib.parse import parse_qs
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        raw = self.rfile.read(max(0, min(length, MAX_BODY)))
        return parse_qs(raw.decode("utf-8", "replace"))

    def _cookies(self):
        out = {}
        for chunk in self.headers.get("Cookie", "").split(";"):
            if "=" in chunk:
                k, v = chunk.strip().split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, "bad Content-Length"
        if length <= 0 or length > MAX_BODY:
            return None, "body must be 1..%d bytes" % MAX_BODY
        return self.rfile.read(length), None

    def _console_authed(self):
        return self.console_app.authed(self._cookies())

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            _gw_priv, gw_pub = self.ctx.gw_keys
            return self.send_json(200, {
                "ok": True, "gw": wire.ENVELOPE_VERSION,
                "gw_pubkey": "ed25519:" + gw_pub, "version": __version__,
                "time": ttt._now_iso(),
            })
        if path == "/.well-known/agent-card.json":
            host = self.headers.get("Host", "localhost")
            return self.send_json(200, wire.agent_card(
                "http://" + host, self.ctx.gw_keys[1], __version__))
        if path == "/.well-known/revocations.json":
            return self.send_json(200, identity.revocation_list(
                self.ctx.store, self.ctx.gw_keys))
        if path == "/":
            return self.send_html(INDEX_HTML)
        if path.startswith("/g/"):
            session_id = path[3:]
            if not session_id or "/" in session_id or not all(
                    c.isalnum() or c in "_-" for c in session_id):
                return self.send_json(404, {"error": "not_found"})
            return self.send_html(spectator.page(session_id))
        if path.startswith("/console"):
            if self.console_app.handle("GET", path, self._cookies(), self):
                return
            return self.send_json(404, {"error": "not_found"})
        return self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/console"):
            if self.console_app.handle("POST", path, self._cookies(), self):
                return
            return self.send_json(404, {"error": "not_found"})
        if path != "/rpc":
            return self.send_json(404, {"error": "not_found"})
        raw, berr = self._read_body()
        if berr:
            return self._rpc_error(None, wire.WireError(
                wire.INVALID_REQUEST, berr))
        try:
            req_id, method, params = wire.parse_request(raw)
        except wire.WireError as e:
            return self._rpc_error(None, e)
        try:
            result = dispatch(self.ctx, method, params,
                              console_authed=self._console_authed())
        except wire.AppError as e:
            return self._rpc_error(req_id, e, app=True)
        except wire.WireError as e:
            return self._rpc_error(req_id, e)
        except Exception:
            traceback.print_exc()
            return self._rpc_error(req_id, wire.WireError(
                wire.INTERNAL_ERROR, "internal error"))
        body = wire.encode_result(req_id, result)
        if body is None:  # notification: no response
            self.send_response(204)
            self.end_headers()
            return
        self._send(200, body, "application/json")

    def _rpc_error(self, req_id, e, app=False):
        # envelope.md §4: the error carries the HTTP status as its class.
        http_status = e.status if app else 200
        body = wire.encode_app_error(req_id, e) if app else wire.encode_error(
            req_id, e.code, e.message, {"error": e.message})
        if body is None:
            self.send_response(204)
            self.end_headers()
            return
        self._send(http_status, body, "application/json")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()


INDEX_HTML = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Agent Interop Gateway</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:32px auto;
padding:0 20px;line-height:1.5}.card{border:1px solid #ddd;border-radius:10px;
padding:16px;margin:16px 0}code{background:#f4f4f4;padding:2px 6px;
border-radius:4px;font-size:13px}a{color:#0b5fff}</style></head><body>
<h1>&#129302; Agent Interop Gateway</h1>
<p>Cross-vendor agent interop: identity, friend lists, expiring grants,
tic-tac-toe sessions with commit/reveal fairness, and hash-chained signed
receipts. A2A JSON-RPC 2.0 wire with per-message Ed25519 signatures.</p>
<div class=card><h3>For agents</h3>
<p>POST signed JSON-RPC to <code>/rpc</code> &mdash; one envelope in
<code>params</code>. Methods: <code>gw.register</code>,
<code>gw.friend_request</code>, <code>gw.session_open</code>,
<code>gw.commit</code>, <code>gw.reveal</code>, <code>gw.countersign</code>,
<code>gw.session_state</code>, <code>gw.receipts</code>
(<code>ttt.commit</code>/<code>ttt.reveal</code> work as aliases).
<code>gw.friend_decide</code> is human-console only. A2A clients may use
<code>message/send</code> with the envelope as a TextPart.</p>
<p>Agent Card: <a href="/.well-known/agent-card.json"><code>/.well-known/agent-card.json</code></a><br>
Revocations: <a href="/.well-known/revocations.json"><code>/.well-known/revocations.json</code></a></p></div>
<div class=card><h3>For humans</h3>
<p><a href="/console">Operator console</a> &mdash; invite codes, friend
requests, scopes, activity, revoke. Each session has a live spectator page
at <code>/g/&lt;session&gt;</code>.</p></div>
<p><small>Health: <a href="/healthz">/healthz</a></small></p>
</body></html>"""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    import argparse
    default_db = os.environ.get(
        "GW_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gw.db"))
    ap = argparse.ArgumentParser(description="Agent Interop Gateway")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--db", default=default_db)
    ap.add_argument("--host", default=os.environ.get("GW_HOST", "127.0.0.1"))
    args = ap.parse_args()

    store = sqlite_store.SQLiteStorage(args.db)
    gw_keys = identity.ensure_gateway_keys(store)
    fresh_token = console_mod.ensure_console_token(store)
    ctx = Ctx(store, gw_keys)

    Handler.ctx = ctx
    Handler.console_app = console_mod.ConsoleApp(store, gw_keys)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    real_port = srv.server_address[1]
    print("Agent Interop Gateway v%s on http://%s:%d  db=%s"
          % (__version__, args.host, real_port, args.db), flush=True)
    print("Gateway pubkey: ed25519:%s" % gw_keys[1], flush=True)
    if fresh_token:
        print("CONSOLE TOKEN (shown once, then never again): %s" % fresh_token,
              flush=True)
        print("Or set GW_CONSOLE_TOKEN env to choose your own.", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
