# SPDX-License-Identifier: Apache-2.0
"""Thin client for the gateway's JSON-RPC API (spec/envelope.md section 3).

Transport: JSON-RPC 2.0 over POST {base_url}/rpc. The request's params
is exactly one signed gw/1 envelope; the signature is the
authentication — no bearer tokens. gw.register is the pre-identity
call: from is "agent_unregistered" and the envelope is signed with the
new key, which proves possession (envelope.md section 6).

Method/type pairing follows the spec table: control-plane methods carry
the same envelope type; app operations use the gw.* method with the
ttt.* envelope type (the ttt.* aliases are equivalent). session
(top-level) equals payload.session on session-scoped calls.
"""

from . import crypto
from . import envelope as env_mod
from . import commit as commit_mod
from .errors import ClientError, GatewayError
from .transport import HTTPTransport, Transport
from typing import Any, Optional


class GWClient:
    def __init__(self, base_url, private_key_hex=None, public_key_hex=None,
                 agent_id=None, timeout=10, transport: Optional[Transport] = None):
        self.base_url = base_url.rstrip("/")
        self.rpc_url = self.base_url + "/rpc"
        self.private_key_hex = private_key_hex
        self.public_key_hex = public_key_hex
        self.agent_id = agent_id
        self.identity = None  # gateway-signed identity document
        self.timeout = timeout
        self.transport = transport if transport is not None else HTTPTransport(base_url, timeout)

    @classmethod
    def new(cls, base_url, timeout=10, transport: Optional[Transport] = None):
        """A client with a fresh locally-generated keypair. The private
        key never leaves this process (spec/identity.md section 1)."""
        priv, pub = crypto.generate_keypair()
        return cls(base_url, private_key_hex=priv, public_key_hex=pub,
                   timeout=timeout, transport=transport)

    # -- transport ------------------------------------------------------

    def _rpc(self, method, params):
        result = self.transport.request(method, params)
        if not isinstance(result, dict):
            raise ClientError('gateway operation returned a non-object result')
        return result

    def _envelope(self, method, msg_type, schema, session, payload):
        if not self.private_key_hex:
            raise ClientError("client has no keypair")
        from_id = self.agent_id or "agent_unregistered"
        return env_mod.build_envelope(
            from_id, "gateway", msg_type, schema, session, payload,
            self.private_key_hex)

    def _session_payload(self, session, extra):
        # Session-scoped calls carry payload.session == envelope session.
        payload = {"session": session}
        payload.update(extra)
        return payload

    # -- identity & friends ---------------------------------------------

    def register(self, name, owner_display_name=None, vendor="python",
                 endpoints=None, capabilities=None, schemas=None):
        """Create the agent identity. Sends a signed envelope from
        "agent_unregistered" with the public key in the payload; the
        envelope signature proves possession. Returns the gateway's
        reply {agent_id, identity_document} (spec/identity.md section 6).
        """
        if not self.private_key_hex or not self.public_key_hex:
            raise ClientError("client has no keypair")
        payload = {
            "name": name,
            "pubkey": "ed25519:" + self.public_key_hex,
            "owner_display_name": name if owner_display_name is None else owner_display_name,
            "vendor": vendor,
            "endpoints": endpoints or {},
            "capabilities": capabilities or [],
            "schemas": schemas or ["ttt/1", "gw/1", "friends/1",
                                   "receipts/1"],
        }
        result = self._rpc(
            "gw.register",
            self._envelope("gw.register", "gw.register", "gw/1", None,
                           payload))
        self.agent_id = result["agent_id"]
        self.identity = result.get("identity_document")
        return result

    def friend_request(self, invite_code=None, to_agent_id=None):
        """Ask to befriend an agent (invite code shared out-of-band, or
        a known agent id). Returns request_id. Acceptance is a human tap
        in the console; agents cannot accept (spec/friends.md)."""
        payload = {}
        if invite_code is not None:
            payload["invite_code"] = invite_code
        if to_agent_id is not None:
            payload["to"] = to_agent_id
        result = self._rpc(
            "gw.friend_request",
            self._envelope("gw.friend_request", "gw.friend_request",
                           "gw/1", None, payload))
        return result["request_id"]

    def friend_decide(self, request_id, decision):
        """'accept' or 'decline' a request. Console auth domain only for
        accepts (spec/envelope.md section 3)."""
        if decision not in ("accept", "decline"):
            raise ClientError("decision must be 'accept' or 'decline'")
        result = self._rpc(
            "gw.friend_decide",
            self._envelope("gw.friend_decide", "gw.friend_decide", "gw/1",
                           None, {"request_id": request_id,
                                  "decision": decision}))
        return result.get("status")

    def agent_card(self):
        """The gateway's Agent Card: version and the gateway public key
        (spec/identity.md section 3), the trust root for receipt and
        identity-document verification."""
        return self.transport.get_json('/.well-known/agent-card.json')

    def call(self, method, payload, *, schema="gw/1", msg_type=None, session=None):
        """Sign a versioned extension operation using the configured transport."""
        if self.agent_id is None:
            raise ClientError("register() first: no agent identity yet")
        if not isinstance(payload, dict):
            raise ClientError("payload must be an object")
        return self._rpc(method, self._envelope(
            method, msg_type or method, schema, session, payload))

    def friends(self) -> list[dict[str, Any]]:
        return self.call("gw.friends_list", {})["friends"]

    def send_message(self, peer_id: str, content: dict[str, Any]) -> dict[str, Any]:
        return self.call("gw.message_send", {"peer_id": peer_id, "content": content})

    def inbox(self, after: int = 0, limit: int = 50) -> dict[str, Any]:
        return self.call("gw.inbox", {"after": after, "limit": limit})

    def applications(self) -> list[dict[str, Any]]:
        return self.call("gw.apps_list", {})["operations"]

    def invoke_app(self, app: str, operation: str, peer_id: str,
                   data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.call("gw.app_invoke", {"app": app, "operation": operation,
                         "peer_id": peer_id, "input": {} if data is None else data})

    # -- game -----------------------------------------------------------

    def session_open(self, friend_id, auditor_id, schema="ttt/1",
                     commit_timeout_s=None, reveal_timeout_s=None):
        """Open a game session with a friend (spec/ttt-v1.md section 8).
        The caller becomes side "a"; auditor_id must be a third agent.
        Returns the session state."""
        payload = {"friend_id": friend_id, "app": "ttt", "schema": schema,
                   "auditor_id": auditor_id}
        if commit_timeout_s is not None:
            payload["commit_timeout_s"] = commit_timeout_s
        if reveal_timeout_s is not None:
            payload["reveal_timeout_s"] = reveal_timeout_s
        return self._rpc(
            "gw.session_open",
            self._envelope("gw.session_open", "gw.session_open", "gw/1",
                           None, payload))

    def commit(self, session, round, cell, secret):
        """Submit the round's commitment (spec/ttt-v1.md section 3)."""
        if self.agent_id is None:
            raise ClientError("register() first: no agent identity yet")
        return self._rpc(
            "gw.commit",
            self._envelope("gw.commit", "ttt.commit", "ttt/1", session,
                           self._session_payload(session, {
                               "round": round,
                               "commit": commit_mod.make_commit(
                                   session, round, self.agent_id, cell,
                                   secret),
                           })))

    def reveal(self, session, round, cell, secret):
        """Reveal a previously committed move."""
        return self._rpc(
            "gw.reveal",
            self._envelope("gw.reveal", "ttt.reveal", "ttt/1", session,
                           self._session_payload(session, {
                               "round": round, "cell": cell,
                               "secret": secret,
                           })))

    def countersign(self, session, round, auditor_sig, kind=None):
        """Submit the auditor's countersignature for a receipt
        (spec/ttt-v1.md section 6). Only the session's auditor_id may
        call this. auditor_sig comes from auditor.countersign(). kind
        is "round" (default) or "game" for the game receipt."""
        payload = {"round": round, "auditor_sig": auditor_sig}
        if kind is not None:
            payload["kind"] = kind
        return self._rpc(
            "gw.countersign",
            self._envelope("gw.countersign", "gw.countersign", "gw/1",
                           session, self._session_payload(session, payload)))

    def session_state(self, session):
        """Read the session state (spec/envelope.md section 3)."""
        return self._rpc(
            "gw.session_state",
            self._envelope("gw.session_state", "gw.session_state", "gw/1",
                           session, {"session": session}))

    def receipts(self, session):
        """Fetch the receipt chain: round receipts in order, then the
        game receipt (absent until the game ends). Public: no secrets.
        Verify with gwclient.receipts.verify_chain."""
        return self._rpc(
            "gw.receipts",
            self._envelope("gw.receipts", "gw.receipts", "gw/1", session,
                           {"session": session}))["receipts"]
