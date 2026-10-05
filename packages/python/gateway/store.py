"""Abstract storage interface for the gateway.

All persistence goes through this interface; every SQL statement lives in
sqlite_store.py. The game logic (sessions.py etc.) only ever calls these
methods, so the backend is swappable without touching the game.

Records are plain dicts with JSON-friendly values. Deadlines and expiries
are unix floats; created stamps are ISO-8601 UTC strings.
"""


class Storage:
    """Persistence contract. Implementations must be thread-safe."""

    def close(self): raise NotImplementedError

    # -- config ---------------------------------------------------------
    def get_config(self, key, default=None): raise NotImplementedError
    def set_config(self, key, value): raise NotImplementedError

    # -- agents ----------------------------------------------------------
    def create_agent(self, agent): raise NotImplementedError
    def get_agent(self, agent_id): raise NotImplementedError
    def get_agent_by_name(self, name_lower): raise NotImplementedError
    def get_agent_by_pubkey(self, pubkey_hex): raise NotImplementedError
    def update_agent(self, agent_id, fields): raise NotImplementedError
    def list_agents(self): raise NotImplementedError

    # -- invite codes (console-minted, single-use, 24h) -------------------
    def create_invite_code(self, code, agent_id, expires_at): raise NotImplementedError
    def get_invite_code(self, code): raise NotImplementedError
    def consume_invite_code(self, code): raise NotImplementedError
    def active_invite_code(self, agent_id): raise NotImplementedError

    # -- key revocation ---------------------------------------------------
    def revoke_key(self, pubkey_hex, reason): raise NotImplementedError
    def revoked_keys(self): raise NotImplementedError
    def is_revoked(self, pubkey_hex): raise NotImplementedError

    # -- friendships & grants ---------------------------------------------
    def create_friendship(self, fr): raise NotImplementedError
    def get_friendship(self, fr_id): raise NotImplementedError
    def get_friendship_between(self, a_id, b_id): raise NotImplementedError
    def pending_requests_for(self, agent_id): raise NotImplementedError
    def update_friendship(self, fr_id, fields): raise NotImplementedError
    def list_friendships(self): raise NotImplementedError
    def create_grant(self, grant): raise NotImplementedError
    def get_grant(self, grant_id): raise NotImplementedError
    def grants_for(self, agent_id): raise NotImplementedError
    def grants_for_friendship(self, friendship_id): raise NotImplementedError
    def set_grant_revoked(self, grant_id, revoked): raise NotImplementedError
    def set_grant_expiry(self, grant_id, expires_at): raise NotImplementedError

    # -- sessions & rounds (simultaneous-move rounds) ----------------------
    def create_session(self, s): raise NotImplementedError
    def get_session(self, session_id): raise NotImplementedError
    def update_session(self, session_id, fields): raise NotImplementedError
    def active_session_between(self, a_id, b_id, app): raise NotImplementedError
    def live_sessions_for(self, agent_id): raise NotImplementedError
    def all_sessions(self): raise NotImplementedError
    def create_round(self, r): raise NotImplementedError
    def get_round(self, session_id, n): raise NotImplementedError
    def update_round(self, session_id, n, fields): raise NotImplementedError

    # -- receipts -----------------------------------------------------------
    def save_receipt(self, session_id, kind, round_n, body, published): raise NotImplementedError
    def get_receipt(self, session_id, kind, round_n): raise NotImplementedError
    def published_receipts(self, session_id): raise NotImplementedError
    def mark_receipt_published(self, session_id, kind, round_n, body): raise NotImplementedError

    # -- outbox (gateway-originated push envelopes) --------------------------
    def push_envelope(self, recipient_id, session_id, msg_type, envelope): raise NotImplementedError
    def recent_for_recipient(self, recipient_id, session_id, limit): raise NotImplementedError

    def inbox_after(self, recipient_id, after, limit): raise NotImplementedError

    # -- replay protection -----------------------------------------------------
    def note_message(self, msg_id, from_id): raise NotImplementedError
    """Returns True on first sighting, False for a duplicate."""

    # -- activity feed --------------------------------------------------------------
    def log_event(self, kind, summary, agent_id=None, session_id=None): raise NotImplementedError
    def recent_events(self, limit=50): raise NotImplementedError
