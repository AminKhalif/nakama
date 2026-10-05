"""Agent identity: registration, signed identity documents, key rotation,
revocation.

Registration is the one pre-identity call: the envelope's `from` is the
literal "agent_unregistered" and the envelope signature itself is the
proof-of-possession (made with the private key matching the payload's
pubkey). The private key is never sent. The gateway answers with a signed
identity document; anyone holding the gateway's public key can verify it
offline.

Public keys are "ed25519:<64 hex>" on the wire (identity.md) and raw hex
in storage.
"""

import time
import uuid
from datetime import datetime, timezone

from . import crypto, wire

IDENTITY_TTL = 365 * 86400  # 1 year


def ensure_gateway_keys(store):
    """Load or create the gateway's Ed25519 keypair (hex). Stored in config."""
    priv = store.get_config("gw_privkey")
    if priv:
        return priv, crypto.pubkey_from_priv(priv)
    priv, pub = crypto.generate_keypair()
    store.set_config("gw_privkey", priv)
    return priv, pub


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_prefix(pubkey):
    """'ed25519:<64hex>' -> raw hex, or None."""
    if isinstance(pubkey, str) and pubkey.startswith("ed25519:"):
        hexpart = pubkey[len("ed25519:"):]
        if len(hexpart) == 64:
            try:
                bytes.fromhex(hexpart)
                return hexpart.lower()
            except ValueError:
                return None
    return None


def _as_list(value):
    return [str(x)[:200] for x in value] if isinstance(value, list) else []


def _as_dict(value):
    return dict(value) if isinstance(value, dict) else {}


def _issue_doc(gw_priv, agent_id, name, owner_display_name, vendor, pubkey_hex,
               endpoints, capabilities, schemas):
    doc = {
        "id": agent_id,
        "agent_name": name,
        "owner_display_name": owner_display_name,
        "vendor": vendor,
        "pubkey": "ed25519:" + pubkey_hex,
        "endpoints": endpoints,
        "capabilities": capabilities,
        "schemas": schemas,
        "accepts": [wire.ENVELOPE_VERSION],
        "certification": {},
        "issued_at": _now_iso(),
        "expires_at": datetime.fromtimestamp(time.time() + IDENTITY_TTL,
                                             timezone.utc).isoformat(timespec="seconds"),
        "did": None,
        "deprecated_schemas": [],
    }
    doc["gw_sig"] = "ed25519:" + crypto.sign(
        gw_priv, wire.canonical_bytes({k: v for k, v in doc.items()}))
    return doc


def register(store, gw_keys, env):
    """gw.register. `env` is the full envelope (from == 'agent_unregistered').

    The envelope signature, verified against the payload's pubkey, is the
    proof of possession. Returns (result, None) or (None, AppError).
    result: {"agent_id", "identity_document"}.
    """
    gw_priv, _gw_pub = gw_keys
    payload = env.get("payload") or {}
    pubkey_hex = _strip_prefix(payload.get("pubkey"))
    if not pubkey_hex:
        return None, wire.AppError("bad_request",
                                   'pubkey must look like "ed25519:<64 hex>"')
    # Proof of possession FIRST (envelope.md §6): the envelope must be
    # signed with the claimed key before any other field is trusted.
    # A forged signature must yield bad_signature, never a field error.
    sig_hex = wire.split_sig(env.get("sig"))
    body = {k: v for k, v in env.items() if k != "sig"}
    if not sig_hex or not crypto.verify(pubkey_hex, wire.canonical_bytes(body),
                                        sig_hex):
        return None, wire.AppError("bad_signature",
                                   "envelope must be signed with the claimed "
                                   "key", 401)
    name = (payload.get("name") or "").strip()
    owner_display_name = (payload.get("owner_display_name") or "").strip()[:100]
    vendor = (payload.get("vendor") or "").strip()[:100]
    if not name or len(name) > 40:
        return None, wire.AppError("bad_request", "name must be 1..40 characters")
    if not owner_display_name:
        return None, wire.AppError("bad_request", "owner_display_name is required")
    if not vendor:
        return None, wire.AppError("bad_request", "vendor is required")
    if not crypto.is_prime_order_pubkey(pubkey_hex):
        return None, wire.AppError("bad_request",
                                   "pubkey must be a prime-order Ed25519 point")
    if store.get_agent_by_name(name.lower()):
        return None, wire.AppError("name_taken",
                                   "that display name is already registered", 409)
    if store.get_agent_by_pubkey(pubkey_hex):
        return None, wire.AppError("bad_request",
                                   "that public key is already registered", 409)

    agent_id = "agent_" + uuid.uuid4().hex[:12]
    endpoints = _as_dict(payload.get("endpoints"))
    capabilities = _as_list(payload.get("capabilities"))
    schemas = _as_list(payload.get("schemas")) or ["ttt/1", "gw/1"]
    doc = _issue_doc(gw_priv, agent_id, name, owner_display_name, vendor,
                     pubkey_hex, endpoints, capabilities, schemas)
    try:
        store.create_agent({
            "id": agent_id, "name": name, "name_lower": name.lower(),
            "owner_display_name": owner_display_name, "vendor": vendor,
            "pubkey": pubkey_hex, "endpoints": endpoints,
            "capabilities": capabilities, "schemas": schemas,
            "identity_doc": doc, "created_at": doc["issued_at"],
            "expires_at": doc["expires_at"],
        })
    except Exception:
        # Lost a race with a concurrent registration of the same name/key.
        return None, wire.AppError("name_taken",
                                   "that display name is already registered", 409)
    store.log_event("agent.registered", "Agent '%s' registered" % name,
                    agent_id=agent_id)
    return {"agent_id": agent_id, "identity_document": doc}, None


def rotate_key(store, gw_keys, agent_id, new_pubkey):
    """Console-initiated key rotation (identity.md §4): new pubkey with the
    human credential, new identity document, same id, old key revoked."""
    gw_priv, _gw_pub = gw_keys
    agent = store.get_agent(agent_id)
    if not agent:
        return None, wire.AppError("not_found", "unknown agent", 404)
    new_hex = _strip_prefix(new_pubkey)
    if not new_hex or not crypto.is_prime_order_pubkey(new_hex):
        return None, wire.AppError("bad_request",
                                   'new pubkey must look like "ed25519:<64 hex>"'
                                   " and be a prime-order point")
    if store.get_agent_by_pubkey(new_hex):
        return None, wire.AppError("bad_request",
                                   "that public key is already registered", 409)
    old_hex = agent["pubkey"]
    store.revoke_key(old_hex, "key rotation")
    doc = _issue_doc(gw_priv, agent_id, agent["name"],
                     agent["owner_display_name"], agent["vendor"], new_hex,
                     agent["endpoints"], agent["capabilities"], agent["schemas"])
    store.update_agent(agent_id, {"pubkey": new_hex, "identity_doc": doc,
                                  "expires_at": doc["expires_at"]})
    store.log_event("key.rotated", "Agent '%s' rotated its key" % agent["name"],
                    agent_id=agent_id)
    return {"agent_id": agent_id, "identity_document": doc}, None


def get_identity(store, agent_id):
    """Return the signed identity document, or None."""
    agent = store.get_agent(agent_id)
    return agent["identity_doc"] if agent else None


def verify_identity_doc(doc, gw_pubkey):
    """Offline check of a gateway-issued identity document."""
    if not isinstance(doc, dict) or not doc.get("gw_sig", "").startswith("ed25519:"):
        return False
    if _strip_prefix(doc.get("pubkey")) is None:
        return False
    sig_hex = wire.split_sig(doc["gw_sig"])
    if not sig_hex:
        return False
    body = {k: v for k, v in doc.items() if k != "gw_sig"}
    return crypto.verify(gw_pubkey, wire.canonical_bytes(body), sig_hex)


def doc_expired(doc):
    try:
        exp = datetime.fromisoformat(doc["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp <= datetime.now(timezone.utc)
    except Exception:
        return True


def revoke_key(store, pubkey, reason=""):
    """Add a key (wire or raw-hex form) to the revocation list and freeze
    that agent's live sessions immediately."""
    hexpart = _strip_prefix(pubkey) or (pubkey if isinstance(pubkey, str) else "")
    hexpart = hexpart.lower()
    if len(hexpart) != 64:
        return None, wire.AppError("bad_request", "pubkey must be 64 hex chars")
    store.revoke_key(hexpart, reason or "revoked by operator")
    agent = store.get_agent_by_pubkey(hexpart)
    if agent:
        from . import sessions as ttt
        for s in store.live_sessions_for(agent["id"]):
            if s["status"] == "active":
                ttt.freeze_session(store, s["id"],
                                   "key revoked by operator")
        store.log_event("key.revoked", "Key revoked for agent '%s'"
                        % agent["name"], agent_id=agent["id"])
    return {"revoked": True}, None


def revocation_list(store, gw_keys):
    """The signed revocation list served at /.well-known/revocations.json."""
    gw_priv, _gw_pub = gw_keys
    body = {"revoked": sorted("ed25519:" + r["pubkey"]
                              for r in store.revoked_keys())}
    body["gw_sig"] = "ed25519:" + crypto.sign(gw_priv, wire.canonical_bytes(body))
    return body
