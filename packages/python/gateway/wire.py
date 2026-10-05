"""A2A JSON-RPC 2.0 framing (swappable wire layer).

This module owns everything about bytes on the wire and nothing about
game rules:

  * JSON-RPC 2.0 request parsing / response encoding (A2A's JSON-RPC binding)
  * the signed envelope: canonical bytes, sign/verify
  * typed application errors mapped onto JSON-RPC error codes
  * a compatibility shim for A2A `message/send`: the signed envelope rides
    as a TextPart, so off-the-shelf A2A tooling can carry our messages
  * the A2A Agent Card served at /.well-known/agent-card.json

Game logic (sessions.py etc.) never touches HTTP or JSON-RPC; it receives
a verified envelope dict and returns a plain result dict. To swap the wire
(e.g. gRPC, WebSocket), replace this module's framing functions and keep
the envelope format.
"""

import json
import re
import uuid

from . import crypto

ENVELOPE_VERSION = "gw/1"
GATEWAY_ID = "gateway"
REGISTER_FROM = "agent_unregistered"

# Methods that accept an envelope without a verified signature (public
# reads). Everything else requires a signed envelope from a registered,
# non-revoked key with a live identity document.
PUBLIC_METHODS = frozenset({"gw.session_state", "gw.receipts"})

# Methods agents may never call with an agent key (console auth domain).
CONSOLE_ONLY_METHODS = frozenset({"gw.friend_decide"})

# JSON-RPC 2.0 reserved codes. Application errors use the HTTP status as
# the JSON-RPC code and the typed name as the message (envelope.md §4).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# method -> (envelope type, envelope schema) pairing, enforced per
# envelope.md §3. ttt.commit / ttt.reveal are accepted as alias methods.
METHOD_TYPE_PAIRS = {
    "gw.register": ("gw.register", "gw/1"),
    "gw.friend_request": ("gw.friend_request", "gw/1"),
    "gw.friend_decide": ("gw.friend_decide", "gw/1"),
    "gw.session_open": ("gw.session_open", "gw/1"),
    "gw.commit": ("ttt.commit", "ttt/1"),
    "ttt.commit": ("ttt.commit", "ttt/1"),
    "gw.reveal": ("ttt.reveal", "ttt/1"),
    "ttt.reveal": ("ttt.reveal", "ttt/1"),
    "gw.countersign": ("gw.countersign", "gw/1"),
    "gw.session_state": ("gw.session_state", "gw/1"),
    "gw.receipts": ("gw.receipts", "gw/1"),
}

MSG_ID_RE = re.compile(r"^msg_[0-9a-f]{12,}$")


def canonical_bytes(obj):
    """Canonical signing bytes: JSON, sorted keys, no whitespace, UTF-8.

    The signature covers every envelope field except "sig" itself.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def new_msg_id(prefix="msg"):
    return prefix + "_" + uuid.uuid4().hex[:16]


def make_envelope(priv_hex, from_id, msg_type, payload, schema="gw/1",
                  session=None, to=GATEWAY_ID, msg_id=None):
    """Build and sign an envelope. Returns the dict including "sig"."""
    env = {
        "gw": ENVELOPE_VERSION,
        "msg_id": msg_id or new_msg_id(),
        "from": from_id,
        "to": to,
        "type": msg_type,
        "schema": schema,
        "session": session,
        "payload": payload,
    }
    env["sig"] = "ed25519:" + crypto.sign(priv_hex, canonical_bytes(env))
    return env


def make_gateway_envelope(gw_priv_hex, to, msg_type, payload, schema="gw/1",
                            session=None):
    """A gateway-originated push envelope (from "gateway"), signed with the
    gateway key. Used for ttt.session_open, ttt.commits_published,
    ttt.round_receipt, ttt.game_receipt, friends.update."""
    env = {
        "gw": ENVELOPE_VERSION,
        "msg_id": new_msg_id(),
        "from": "gateway",
        "to": to,
        "type": msg_type,
        "schema": schema,
        "session": session,
        "payload": payload,
    }
    env["sig"] = "ed25519:" + crypto.sign(gw_priv_hex, canonical_bytes(env))
    return env


def split_sig(sig):
    """Return the hex part of an "ed25519:<128 hex>" signature, else None."""
    if not isinstance(sig, str) or not sig.startswith("ed25519:"):
        return None
    hexpart = sig[len("ed25519:"):]
    if len(hexpart) != 128:
        return None
    try:
        bytes.fromhex(hexpart)
    except ValueError:
        return None
    return hexpart.lower()


def verify_envelope(env, pub_hex):
    """Check a signed envelope. Returns (True, "") or (False, reason)."""
    if not isinstance(env, dict):
        return False, "envelope must be an object"
    if env.get("gw") != ENVELOPE_VERSION:
        return False, "unsupported envelope version"
    for field in ("msg_id", "from", "to", "type", "schema", "payload"):
        if field not in env:
            return False, "envelope missing field: " + field
    sig_hex = split_sig(env.get("sig"))
    if not sig_hex:
        return False, "missing or malformed sig (want ed25519:<128 hex>)"
    body = {k: v for k, v in env.items() if k != "sig"}
    if not crypto.verify(pub_hex, canonical_bytes(body), sig_hex):
        return False, "bad signature"
    return True, ""


class WireError(Exception):
    """A JSON-RPC-level failure. Carries code/message/data for the response."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class AppError(Exception):
    """A typed application failure (e.g. not_friends, commitment_mismatch).

    `status` mirrors HTTP semantics so the HTTP layer can set a status code;
    the JSON-RPC error code is derived from it. `name` is the stable
    snake_case identifier clients match on.
    """

    def __init__(self, name, detail="", status=400):
        super().__init__(detail or name)
        self.name = name
        self.detail = detail
        self.status = status

    def rpc_code(self):
        # Kept for compatibility; the wire encoding uses status directly.
        return self.status


def validate_envelope_shape(env):
    """Check envelope structure per envelope.md §1/§7. Returns None or the
    typed reason for a bad_envelope rejection."""
    if not isinstance(env, dict):
        return "envelope must be an object"
    if env.get("gw") != ENVELOPE_VERSION:
        return "unsupported envelope version (want gw/1)"
    for field in ("msg_id", "from", "to", "type", "schema", "session", "payload"):
        if field not in env:
            return "envelope missing field: " + field
    if not MSG_ID_RE.match(env.get("msg_id") or ""):
        return "msg_id must match ^msg_[0-9a-f]{12,}$"
    if not isinstance(env.get("from"), str) or not env["from"]:
        return "envelope 'from' must be a non-empty string"
    if not isinstance(env.get("to"), str) or not env["to"]:
        return "envelope 'to' must be a non-empty string"
    if not isinstance(env.get("type"), str) or not env["type"]:
        return "envelope 'type' must be a non-empty string"
    if not isinstance(env.get("schema"), str) or not env["schema"]:
        return "envelope 'schema' must be a non-empty string"
    if env.get("session") is not None and not isinstance(env["session"], str):
        return "envelope 'session' must be a string or null"
    if not isinstance(env.get("payload"), dict):
        return "envelope 'payload' must be an object"
    return None


def parse_request(raw):
    """Parse raw JSON-RPC 2.0 request bytes.

    Returns (req_id, method, params). Raises WireError.
    Batch requests are rejected: A2A does not use them.
    """
    try:
        text = raw.decode("utf-8")
    except Exception:
        raise WireError(PARSE_ERROR, "request is not valid UTF-8")
    try:
        obj = json.loads(text)
    except Exception:
        raise WireError(PARSE_ERROR, "invalid JSON")
    if isinstance(obj, list):
        raise WireError(INVALID_REQUEST, "batch requests are not supported")
    if not isinstance(obj, dict):
        raise WireError(INVALID_REQUEST, "request must be a JSON object")
    if obj.get("jsonrpc") != "2.0":
        raise WireError(INVALID_REQUEST, 'missing or wrong "jsonrpc": want "2.0"')
    method = obj.get("method")
    if not isinstance(method, str) or not method:
        raise WireError(INVALID_REQUEST, 'missing or invalid "method"')
    params = obj.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise WireError(INVALID_PARAMS, '"params" must be an object')
    req_id = obj.get("id", _NO_ID)
    if req_id is not _NO_ID and req_id is not None \
            and not isinstance(req_id, (str, int)):
        raise WireError(INVALID_REQUEST, '"id" must be a string, number, or null')
    return req_id, method, params


# Sentinel marking "request carried no id" (a notification: no response).
_NO_ID = object()


def encode_result(req_id, result):
    if req_id is _NO_ID:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": req_id,
                       "result": result}).encode("utf-8")


def encode_error(req_id, code, message, data=None):
    if req_id is _NO_ID:
        return None
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return json.dumps({"jsonrpc": "2.0", "id": req_id,
                       "error": err}).encode("utf-8")


def encode_app_error(req_id, app_error):
    # envelope.md §4: the JSON-RPC code is the HTTP status, the message is
    # the typed code, and data carries the reason (== message) and detail.
    data = {"reason": app_error.name}
    if app_error.detail:
        data["detail"] = app_error.detail
    return encode_error(req_id, app_error.status, app_error.name, data)


# ---------------------------------------------------------------------------
# A2A compatibility shim.
#
# A pure-A2A client speaks message/send with a Message object whose parts
# carry content. Our signed envelope travels as a single TextPart; the
# gateway unwraps it, verifies the inner signature (the A2A extension),
# and answers with an A2A-shaped result whose TextPart holds the result.
# A2A framing works with off-the-shelf tooling; message authenticity still
# comes from the Ed25519 signature inside, which unsigned A2A clients lack.
# ---------------------------------------------------------------------------

def unwrap_a2a_message(params):
    """Extract the inner dict from message/send params (the envelope, or for
    public methods a bare params object). Signature checks happen later."""
    try:
        msg = params["message"]
        parts = msg["parts"]
    except (KeyError, TypeError):
        raise WireError(INVALID_PARAMS,
                        'message/send needs params.message.parts')
    texts = [p.get("text") for p in parts
             if isinstance(p, dict) and p.get("kind") == "text" and p.get("text")]
    if not texts:
        raise WireError(INVALID_PARAMS,
                        "message/send needs a text part carrying the envelope")
    try:
        inner = json.loads(texts[0])
    except Exception:
        raise WireError(INVALID_PARAMS, "text part is not a JSON object")
    if not isinstance(inner, dict):
        raise WireError(INVALID_PARAMS, "text part is not a JSON object")
    return inner


def wrap_a2a_result(result):
    """Wrap a result dict as an A2A message/send result."""
    return {
        "message": {
            "role": "agent",
            "messageId": new_msg_id("a2a"),
            "parts": [{"kind": "text",
                        "text": json.dumps(result, sort_keys=True)}],
        }
    }


def agent_card(base_url, gw_pubkey, version):
    """A2A v1.0.1 Agent Card for this gateway.

    The gateway Ed25519 key rides in the top-level gwPubkey extension
    field (a2a-extension.md), so agents can verify gateway signatures
    from discovery alone.
    """
    return {
        "name": "Agent Interop Gateway",
        "description": ("Open cross-vendor gateway: agent identity, friend lists, "
                        "expiring grants, turn-based game sessions with commit/reveal "
                        "fairness, and hash-chained signed receipts. Messages are "
                        "A2A JSON-RPC 2.0 with a per-message Ed25519 signature "
                        "extension (envelope gw/1)."),
        "version": version,
        "url": base_url,
        "protocolVersion": "1.0.1",
        "provider": {"organization": "agent-interop contributors"},
        "gwPubkey": "ed25519:" + gw_pubkey,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "securitySchemes": {
            "ed25519-envelope": {
                "type": "http",
                "scheme": "gw-envelope",
                "publicKey": gw_pubkey,
                "description": ("Every state-changing call carries a signed envelope "
                                '{"gw":"gw/1","msg_id","from","to":"gateway","type",'
                                '"schema","session","payload","sig":"ed25519:<128 hex>"}. '
                                "Canonical signing bytes: JSON sorted keys, "
                                "separators (',',':'), UTF-8. Gateway key: see gwPubkey."),
            }
        },
        "skills": [
            {"id": "game.ttt", "name": "Tic-tac-toe referee",
             "description": "Referees schema ttt/1 games: commit/reveal fairness, "
                            "move legality, win/draw detection, hash-chained signed "
                            "receipts. Play via the gw.* methods."},
            {"id": "gw.register", "name": "Register agent",
             "description": "Register {name, pubkey} with proof-of-possession; "
                            "get a gateway-signed identity document."},
            {"id": "gw.friend_request", "name": "Request friendship",
             "description": "Send a friend request using the other agent's "
                            "invite code (human shares it out-of-band)."},
            {"id": "gw.session_open", "name": "Open game session",
             "description": "Open a tic-tac-toe session (schema ttt/1) with a "
                            "friend and an auditor agent."},
            {"id": "ttt.commit", "name": "Commit move",
             "description": "Commit sha256(gw/1|<session>|r<round>|<agent>|"
                            "<cell>|<secret>)."},
            {"id": "ttt.reveal", "name": "Reveal move",
             "description": "Reveal {cell, secret}; the gateway verifies the "
                            "binding before applying the move."},
            {"id": "gw.receipts", "name": "Export receipts",
             "description": "Hash-chained, gateway-signed round and game "
                            "receipts for independent audit."},
        ],
    }
