"""Friend graph: invite-code requests, expiring grants, revoke/unfriend.

Invite codes are minted in the console (single-use, 24h). A human shares
their agent's code out-of-band (chat, QR, voice); the other side's *agent*
sends gw.friend_request with that code. The recipient's human accepts or
declines in the console (gw.friend_decide is console-auth only: agent keys
get 403 console_only). Accepting mints directional, expiring grants and
pushes a friends.update envelope to both agents.

Revocation is immediate: unfriend, pause, or grant revoke takes effect on
the next gateway operation and freezes live sessions. Frozen sessions never
resume.
"""

import secrets
import time
import uuid
from datetime import datetime, timezone

from . import wire

DEFAULT_SCOPES = ("game.ttt:play", "game.ttt:spectate")
DEFAULT_GRANT_TTL = 365 * 86400  # 1 year
INVITE_TTL = 86400  # 24 hours

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _aname(store, agent_id):
    a = store.get_agent(agent_id)
    return a["name"] if a else agent_id


# ---------------------------------------------------------------------------
# invite codes
# ---------------------------------------------------------------------------

def mint_invite_code(store, agent_id):
    """Console action: mint a fresh single-use invite code for an agent."""
    if not store.get_agent(agent_id):
        return None, wire.AppError("not_found", "unknown agent", 404)
    for _ in range(20):
        code = ("".join(secrets.choice(_CODE_ALPHABET) for _ in range(4)) + "-"
                + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4)))
        if not store.get_invite_code(code):
            break
    else:
        return None, wire.AppError("bad_request", "could not mint a code", 500)
    store.create_invite_code(code, agent_id, time.time() + INVITE_TTL)
    store.log_event("invite.minted", "Invite code minted", agent_id=agent_id)
    return {"code": code, "expires_at": time.time() + INVITE_TTL}, None


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------

def friend_request(store, caller_id, payload):
    """gw.friend_request {to} or {invite_code}."""
    target_id = payload.get("to")
    if payload.get("invite_code"):
        code = (payload["invite_code"] or "").strip().upper()
        row = store.get_invite_code(code)
        if not row or row["used"] or row["expires_at"] <= time.time():
            return None, wire.AppError("bad_request",
                                       "unknown, used, or expired invite code")
        target_id = row["agent_id"]
        store.consume_invite_code(code)
    target = store.get_agent(target_id)
    if not target:
        return None, wire.AppError("not_found", "unknown agent", 404)
    if target_id == caller_id:
        return None, wire.AppError("bad_request", "you cannot friend yourself")
    fr = store.get_friendship_between(caller_id, target_id)
    if fr and fr["status"] == "pending":
        return None, wire.AppError("duplicate_request",
                                   "a friend request is already pending", 409)
    if fr and fr["status"] == "accepted":
        return None, wire.AppError("duplicate_request",
                                   "you are already friends", 409)
    fr_id = "fr_" + uuid.uuid4().hex[:12]
    store.create_friendship({
        "id": fr_id, "a_id": caller_id, "b_id": target_id, "status": "pending",
        "requested_by": caller_id, "created_at": _now_iso(), "decided_at": None,
    })
    store.log_event("friend.requested",
                    "%s requested friendship with %s"
                    % (_aname(store, caller_id), target["name"]),
                    agent_id=caller_id)
    return {"request_id": fr_id, "status": "pending",
            "to": target_id}, None


def human_decide(store, gw_keys, request_id, accept, scopes=None,
                 expires_at=None):
    """Console accept/decline. Accepting mints directional grants and pushes
    friends.update to both agents."""
    fr = store.get_friendship(request_id)
    if not fr:
        return None, wire.AppError("not_found", "unknown request", 404)
    if fr["status"] != "pending":
        return None, wire.AppError("bad_request", "request already decided", 409)
    decided = _now_iso()
    if not accept:
        store.update_friendship(request_id, {"status": "declined",
                                             "decided_at": decided})
        _push_update(store, gw_keys, fr, "declined", [], None)
        store.log_event("friend.declined",
                        "Friend request declined (%s)" % request_id)
        return {"request_id": request_id, "status": "declined"}, None
    store.update_friendship(request_id, {"status": "accepted",
                                         "decided_at": decided})
    scopes = list(scopes) if scopes else list(DEFAULT_SCOPES)
    exp = expires_at or (time.time() + DEFAULT_GRANT_TTL)
    exp_iso = datetime.fromtimestamp(exp, timezone.utc).isoformat(timespec="seconds")
    for agent_id, peer_id in ((fr["a_id"], fr["b_id"]), (fr["b_id"], fr["a_id"])):
        for scope in scopes:
            store.create_grant({
                "id": "grant_" + uuid.uuid4().hex[:12], "friendship_id": fr["id"],
                "agent_id": agent_id, "peer_id": peer_id, "scope": scope,
                "expires_at": exp, "revoked": False,
            })
        _push_update(store, gw_keys, fr, "accepted", scopes, exp_iso,
                     recipient=agent_id)
    store.log_event("friend.accepted",
                    "%s and %s are now friends"
                    % (_aname(store, fr["a_id"]), _aname(store, fr["b_id"])))
    return {"request_id": request_id, "status": "accepted",
            "scopes": scopes, "expires_at": exp_iso}, None


def _push_update(store, gw_keys, fr, status, scopes, expires_at, recipient=None):
    """Push a gateway-signed friends.update envelope to one or both agents."""
    gw_priv, _gw_pub = gw_keys
    targets = [recipient] if recipient else [fr["a_id"], fr["b_id"]]
    for agent_id in targets:
        peer_id = fr["b_id"] if agent_id == fr["a_id"] else fr["a_id"]
        env = wire.make_gateway_envelope(
            gw_priv, agent_id, "friends.update",
            {"friendship_id": fr["id"], "peer_id": peer_id, "status": status,
             "scopes": scopes, "expires_at": expires_at},
            schema="friends/1")
        store.push_envelope(agent_id, None, "friends.update", env)


# ---------------------------------------------------------------------------
# grants
# ---------------------------------------------------------------------------

def grant_active(store, friendship_id, agent_id, scope):
    """A grant is live iff it exists for this agent, is unrevoked, and
    unexpired. Grants are directional: each side needs its own."""
    now = time.time()
    for g in store.grants_for_friendship(friendship_id):
        if g["agent_id"] == agent_id and g["scope"] == scope \
                and not g["revoked"] and g["expires_at"] > now:
            return True, g
    return False, "grant_expired"


def set_grant_revoked(store, gw_keys, grant_id, revoked):
    g = store.get_grant(grant_id)
    if not g:
        return None, wire.AppError("not_found", "unknown grant", 404)
    store.set_grant_revoked(grant_id, revoked)
    fr = store.get_friendship(g["friendship_id"])
    if fr:
        scopes = [x["scope"] for x in store.grants_for(g["agent_id"])
                  if x["friendship_id"] == g["friendship_id"]
                  and not x["revoked"] and x["expires_at"] > time.time()]
        exp_iso = datetime.fromtimestamp(g["expires_at"],
                                         timezone.utc).isoformat(timespec="seconds")
        _push_update(store, gw_keys, fr, "accepted", scopes, exp_iso,
                     recipient=g["agent_id"])
    if revoked:
        from . import sessions as ttt
        ttt.freeze_pair(store, g["agent_id"], g["peer_id"],
                        "grant revoked by human")
    store.log_event("grant.revoked" if revoked else "grant.restored",
                    "Grant %s %s" % (grant_id, "revoked" if revoked else "restored"),
                    agent_id=g["agent_id"])
    return {"grant_id": grant_id, "revoked": revoked}, None


def set_grant_expiry(store, grant_id, expires_at):
    g = store.get_grant(grant_id)
    if not g:
        return None, wire.AppError("not_found", "unknown grant", 404)
    store.set_grant_expiry(grant_id, expires_at)
    return {"grant_id": grant_id, "expires_at": expires_at}, None


# ---------------------------------------------------------------------------
# revoke / unfriend
# ---------------------------------------------------------------------------

def revoke_friendship(store, gw_keys, friendship_id):
    """One-tap unfriend: friendship -> revoked, grants die, sessions freeze,
    both agents get friends.update."""
    fr = store.get_friendship(friendship_id)
    if not fr:
        return None, wire.AppError("not_found", "unknown friendship", 404)
    if fr["status"] == "revoked":
        return {"friendship_id": friendship_id, "status": "revoked"}, None
    store.update_friendship(friendship_id, {"status": "revoked",
                                            "decided_at": _now_iso()})
    for g in store.grants_for_friendship(friendship_id):
        store.set_grant_revoked(g["id"], True)
    _push_update(store, gw_keys, fr, "revoked", [], None)
    from . import sessions as ttt
    ttt.freeze_pair(store, fr["a_id"], fr["b_id"], "unfriended by human")
    store.log_event("friend.revoked",
                    "%s and %s are no longer friends"
                    % (_aname(store, fr["a_id"]), _aname(store, fr["b_id"])))
    return {"friendship_id": friendship_id, "status": "revoked"}, None
