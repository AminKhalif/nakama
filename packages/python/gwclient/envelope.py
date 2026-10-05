# SPDX-License-Identifier: Apache-2.0
"""The gw/1 signed envelope: build, parse, and verify.

Envelope (locked format)::

    {"gw": "gw/1", "msg_id": "msg_…", "from": "agent_…", "to": "agent_…",
     "type": "ttt.commit", "schema": "ttt/1", "session": "sess_…",
     "payload": {...}, "sig": "ed25519:<128 hex chars>"}

Canonical signing bytes: JSON with sorted keys, separators (',', ':'),
UTF-8 encoded — computed over the envelope *without* the "sig" field.
Schema-evolution rule (carried from the proposal): receivers MUST ignore
unknown fields, so verify() never rejects an envelope for extra fields.
"""

import json
import re
import secrets

from . import crypto

REQUIRED_FIELDS = ("gw", "msg_id", "from", "to", "type", "schema",
                   "session", "payload")

_SIG_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")
_MSG_ID_RE = re.compile(r"^msg_[0-9a-f]{12,}$")

# Types that only make sense inside a session (envelope.md section 1:
# a session-scoped type with a null session is bad_envelope).
_SESSION_SCOPED_TYPES = frozenset([
    "ttt.commit", "ttt.reveal", "ttt.commits_published", "ttt.round_receipt",
    "ttt.game_receipt", "ttt.session_open",
    "gw.commit", "gw.reveal", "gw.countersign", "gw.session_state",
    "gw.receipts",
])
# Types that only make sense outside a session.
_SESSIONLESS_TYPES = frozenset([
    "gw.register", "gw.friend_request", "gw.friend_decide",
])


class EnvelopeError(ValueError):
    """Base class for envelope problems."""


class BadEnvelope(EnvelopeError):
    """The envelope is structurally invalid (not parseable JSON, wrong
    shape, missing/ill-typed required field, wrong envelope version)."""


class BadSignature(EnvelopeError):
    """The envelope is structurally fine but the signature is missing,
    malformed, or cryptographically invalid."""


def canonical(obj):
    """Canonical bytes of a JSON object: sorted keys, (',', ':')
    separators, UTF-8. Deterministic across languages for the same
    logical object."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def signing_bytes(envelope):
    """The exact bytes that are (or must be) signed: canonical JSON of
    the envelope with the 'sig' field removed."""
    unsigned = {k: v for k, v in envelope.items() if k != "sig"}
    return canonical(unsigned)


def build_envelope(from_id, to_id, msg_type, schema, session, payload,
                   private_key_hex, msg_id=None):
    """Build and sign an envelope. Returns the dict ready to JSON-encode
    and send. The private key never leaves the caller."""
    envelope = {
        "gw": "gw/1",
        "msg_id": msg_id or "msg_" + secrets.token_hex(8),
        "from": from_id,
        "to": to_id,
        "type": msg_type,
        "schema": schema,
        "session": session,
        "payload": payload,
    }
    sig = crypto.sign(private_key_hex, signing_bytes(envelope))
    envelope["sig"] = "ed25519:" + sig.hex()
    return envelope


def parse_envelope(raw):
    """Parse raw JSON (str/bytes) or an already-decoded dict into an
    envelope, checking structure. Raises BadEnvelope. Does NOT check the
    signature — use verify_envelope for that."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise BadEnvelope("envelope is not valid JSON: %s" % exc)
    elif isinstance(raw, dict):
        obj = raw
    else:
        raise BadEnvelope("envelope must be JSON text or a dict, got %s"
                          % type(raw).__name__)
    if not isinstance(obj, dict):
        raise BadEnvelope("envelope must be a JSON object")
    for field in REQUIRED_FIELDS:
        if field not in obj:
            raise BadEnvelope("envelope missing required field %r" % field)
    if obj["gw"] != "gw/1":
        raise BadEnvelope("unsupported envelope version %r" % (obj["gw"],))
    if not _MSG_ID_RE.match(obj["msg_id"]):
        raise BadEnvelope("msg_id %r must be 'msg_' plus at least 12 hex "
                          "chars" % (obj["msg_id"],))
    if not isinstance(obj["payload"], dict):
        raise BadEnvelope("envelope payload must be a JSON object")
    for field in ("from", "to", "type", "schema"):
        if not isinstance(obj[field], str):
            raise BadEnvelope("envelope field %r must be a string" % field)
    session = obj["session"]
    if session is not None and not isinstance(session, str):
        raise BadEnvelope("envelope field 'session' must be a string or "
                          "null")
    msg_type = obj["type"]
    if msg_type in _SESSION_SCOPED_TYPES and session is None:
        raise BadEnvelope("session-scoped type %r with null session"
                          % (msg_type,))
    if msg_type in _SESSIONLESS_TYPES and session is not None:
        raise BadEnvelope("sessionless type %r with non-null session"
                          % (msg_type,))
    return obj


def verify_envelope(envelope, public_key):
    """Fully verify an envelope: structure, signature format, and
    cryptographic validity.

    public_key is either the sender's public-key hex string or a
    callable mapping the envelope's "from" id to a public-key hex
    string (so one call can verify envelopes from many agents).

    Returns the envelope dict on success. Raises BadEnvelope for
    structural problems, BadSignature for signature problems.
    """
    env = parse_envelope(envelope)
    if callable(public_key):
        key_hex = public_key(env["from"])
    else:
        key_hex = public_key
    sig = env.get("sig")
    if not isinstance(sig, str) or not _SIG_RE.match(sig):
        raise BadSignature("envelope has missing or malformed 'sig' "
                           "(want 'ed25519:' + 128 hex chars)")
    if not crypto.verify(key_hex, signing_bytes(env),
                         bytes.fromhex(sig[len("ed25519:"):])):
        raise BadSignature("signature invalid for envelope %r from %r"
                           % (env["msg_id"], env["from"]))
    return env
