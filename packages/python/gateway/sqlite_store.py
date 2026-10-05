"""SQLite implementation of the Storage interface. All SQL lives here."""

import json
import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_lower TEXT NOT NULL UNIQUE,
    owner_display_name TEXT NOT NULL DEFAULT '',
    vendor TEXT NOT NULL DEFAULT '',
    pubkey TEXT NOT NULL UNIQUE,
    endpoints TEXT NOT NULL DEFAULT '{}',
    capabilities TEXT NOT NULL DEFAULT '[]',
    schemas TEXT NOT NULL DEFAULT '[]',
    identity_doc TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invite_agent ON invite_codes(agent_id);
CREATE TABLE IF NOT EXISTS revocations (
    pubkey TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    revoked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS friendships (
    id TEXT PRIMARY KEY,
    a_id TEXT NOT NULL,
    b_id TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fr_pair ON friendships(a_id, b_id);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    friendship_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_grant_agent ON grants(agent_id);
CREATE INDEX IF NOT EXISTS idx_grant_fr ON grants(friendship_id);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    a_id TEXT NOT NULL,
    b_id TEXT NOT NULL,
    auditor_id TEXT NOT NULL,
    app TEXT NOT NULL,
    schema TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    round INTEGER NOT NULL,
    board TEXT NOT NULL,
    commit_timeout_s REAL NOT NULL,
    reveal_timeout_s REAL NOT NULL,
    commit_deadline REAL,
    reveal_deadline REAL,
    countersign_deadline REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sess_pair ON sessions(a_id, b_id, app, status);
CREATE TABLE IF NOT EXISTS rounds (
    session_id TEXT NOT NULL,
    n INTEGER NOT NULL,
    commit_a TEXT,
    commit_b TEXT,
    cell_a TEXT,
    cell_b TEXT,
    PRIMARY KEY (session_id, n)
);
CREATE TABLE IF NOT EXISTS receipts (
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    round_n INTEGER NOT NULL,
    body TEXT NOT NULL,
    published INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY (session_id, kind, round_n)
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id TEXT NOT NULL,
    session_id TEXT,
    msg_type TEXT NOT NULL,
    envelope TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_recip ON outbox(recipient_id, session_id, id);
CREATE TABLE IF NOT EXISTS seen_messages (
    msg_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (msg_id, from_id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    agent_id TEXT,
    session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def _encode(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return value


def _decode(value):
    if value is None:
        return None
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class SQLiteStorage:
    """Thread-safe SQLite backend. One connection, one lock."""

    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    # -- small helpers -------------------------------------------------
    def _one(self, sql, args=()):
        row = self._db.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql, args=()):
        return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _write(self, sql, args=()):
        with self._lock, self._db:
            self._db.execute(sql, args)

    # -- config ---------------------------------------------------------
    def get_config(self, key, default=None):
        with self._lock:
            row = self._one("SELECT v FROM config WHERE k=?", (key,))
        return row["v"] if row else default

    def set_config(self, key, value):
        self._write("INSERT INTO config(k,v) VALUES(?,?) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                    (key, value))

    # -- agents ----------------------------------------------------------
    def create_agent(self, a):
        self._write(
            "INSERT INTO agents(id,name,name_lower,owner_display_name,vendor,"
            "pubkey,endpoints,capabilities,schemas,identity_doc,"
            "created_at,expires_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["id"], a["name"], a["name_lower"], a.get("owner_display_name", ""),
             a.get("vendor", ""), a["pubkey"], _encode(a.get("endpoints", {})),
             _encode(a.get("capabilities", [])), _encode(a.get("schemas", [])),
             _encode(a.get("identity_doc", {})), a["created_at"], a["expires_at"]))

    def _agent_row(self, row):
        row["endpoints"] = _decode(row["endpoints"]) or {}
        row["capabilities"] = _decode(row["capabilities"]) or []
        row["schemas"] = _decode(row["schemas"]) or []
        row["identity_doc"] = _decode(row["identity_doc"]) or {}
        return row

    def get_agent(self, agent_id):
        with self._lock:
            row = self._one("SELECT * FROM agents WHERE id=?", (agent_id,))
        return self._agent_row(row) if row else None

    def get_agent_by_name(self, name_lower):
        with self._lock:
            row = self._one("SELECT * FROM agents WHERE name_lower=?", (name_lower,))
        return self._agent_row(row) if row else None

    def get_agent_by_pubkey(self, pubkey_hex):
        with self._lock:
            row = self._one("SELECT * FROM agents WHERE pubkey=?", (pubkey_hex,))
        return self._agent_row(row) if row else None

    def list_agents(self):
        with self._lock:
            rows = self._all("SELECT * FROM agents ORDER BY created_at")
        return [self._agent_row(r) for r in rows]

    def update_agent(self, agent_id, fields):
        conv = {"endpoints": _encode, "capabilities": _encode,
                "schemas": _encode, "identity_doc": _encode}
        cols = ", ".join("%s=?" % k for k in fields)
        vals = [conv.get(k, lambda v: v)(v) for k, v in fields.items()]
        self._write("UPDATE agents SET %s WHERE id=?" % cols, vals + [agent_id])

    # -- invite codes ------------------------------------------------------
    def create_invite_code(self, code, agent_id, expires_at):
        self._write("INSERT INTO invite_codes(code,agent_id,created_at,expires_at,used)"
                    " VALUES(?,?,?,?,0)",
                    (code, agent_id, time.time(), expires_at))

    def get_invite_code(self, code):
        with self._lock:
            return self._one("SELECT * FROM invite_codes WHERE code=?", (code,))

    def consume_invite_code(self, code):
        self._write("UPDATE invite_codes SET used=1 WHERE code=?", (code,))

    def active_invite_code(self, agent_id):
        with self._lock:
            return self._one(
                "SELECT * FROM invite_codes WHERE agent_id=? AND used=0"
                " AND expires_at>? ORDER BY created_at DESC LIMIT 1",
                (agent_id, time.time()))

    # -- revocation ----------------------------------------------------------
    def revoke_key(self, pubkey_hex, reason):
        self._write("INSERT INTO revocations(pubkey,reason,revoked_at) VALUES(?,?,?)"
                    " ON CONFLICT(pubkey) DO UPDATE SET reason=excluded.reason,"
                    " revoked_at=excluded.revoked_at",
                    (pubkey_hex, reason or "", time.time()))

    def revoked_keys(self):
        with self._lock:
            return self._all("SELECT pubkey,reason,revoked_at FROM revocations")

    def is_revoked(self, pubkey_hex):
        with self._lock:
            return self._one("SELECT 1 FROM revocations WHERE pubkey=?",
                             (pubkey_hex,)) is not None

    # -- friendships & grants ---------------------------------------------------
    def create_friendship(self, fr):
        self._write("INSERT INTO friendships(id,a_id,b_id,status,requested_by,"
                    "created_at,decided_at) VALUES(?,?,?,?,?,?,?)",
                    (fr["id"], fr["a_id"], fr["b_id"], fr["status"],
                     fr["requested_by"], fr["created_at"], fr.get("decided_at")))

    def _fr_between_sql(self):
        return ("SELECT * FROM friendships WHERE "
                "((a_id=? AND b_id=?) OR (a_id=? AND b_id=?))")

    def get_friendship(self, fr_id):
        with self._lock:
            return self._one("SELECT * FROM friendships WHERE id=?", (fr_id,))

    def get_friendship_between(self, a_id, b_id):
        with self._lock:
            return self._one(self._fr_between_sql() + " ORDER BY created_at DESC LIMIT 1",
                             (a_id, b_id, b_id, a_id))

    def pending_requests_for(self, agent_id):
        with self._lock:
            return self._all(
                "SELECT * FROM friendships WHERE status='pending' AND"
                " (a_id=? OR b_id=?) ORDER BY created_at DESC", (agent_id, agent_id))

    def list_friendships(self):
        with self._lock:
            return self._all("SELECT * FROM friendships ORDER BY created_at DESC")

    def update_friendship(self, fr_id, fields):
        cols = ", ".join("%s=?" % k for k in fields)
        self._write("UPDATE friendships SET %s WHERE id=?" % cols,
                    list(fields.values()) + [fr_id])

    def create_grant(self, g):
        self._write("INSERT INTO grants(id,friendship_id,agent_id,peer_id,scope,"
                    "expires_at,revoked) VALUES(?,?,?,?,?,?,?)",
                    (g["id"], g["friendship_id"], g["agent_id"], g["peer_id"],
                     g["scope"], g["expires_at"], 1 if g.get("revoked") else 0))

    def get_grant(self, grant_id):
        with self._lock:
            row = self._one("SELECT * FROM grants WHERE id=?", (grant_id,))
        if row:
            row["revoked"] = bool(row["revoked"])
        return row

    def grants_for(self, agent_id):
        with self._lock:
            rows = self._all("SELECT * FROM grants WHERE agent_id=? ORDER BY scope",
                             (agent_id,))
        for r in rows:
            r["revoked"] = bool(r["revoked"])
        return rows

    def grants_for_friendship(self, friendship_id):
        with self._lock:
            rows = self._all("SELECT * FROM grants WHERE friendship_id=?",
                             (friendship_id,))
        for r in rows:
            r["revoked"] = bool(r["revoked"])
        return rows

    def set_grant_revoked(self, grant_id, revoked):
        self._write("UPDATE grants SET revoked=? WHERE id=?",
                    (1 if revoked else 0, grant_id))

    def set_grant_expiry(self, grant_id, expires_at):
        self._write("UPDATE grants SET expires_at=? WHERE id=?",
                    (expires_at, grant_id))

    # -- sessions & rounds ---------------------------------------------------------
    def create_session(self, s):
        self._write(
            "INSERT INTO sessions(id,a_id,b_id,auditor_id,app,schema,status,phase,"
            "round,board,commit_timeout_s,reveal_timeout_s,commit_deadline,"
            "reveal_deadline,countersign_deadline,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["a_id"], s["b_id"], s["auditor_id"], s["app"], s["schema"],
             s["status"], s["phase"], s["round"], _encode(s["board"]),
             s["commit_timeout_s"], s["reveal_timeout_s"], s.get("commit_deadline"),
             s.get("reveal_deadline"), s.get("countersign_deadline"),
             s["created_at"]))

    def get_session(self, session_id):
        with self._lock:
            row = self._one("SELECT * FROM sessions WHERE id=?", (session_id,))
        if row:
            row["board"] = _decode(row["board"]) or [None] * 9
        return row

    def update_session(self, session_id, fields):
        conv = {"board": _encode}
        cols = ", ".join("%s=?" % k for k in fields)
        vals = [conv.get(k, lambda v: v)(v) for k, v in fields.items()]
        self._write("UPDATE sessions SET %s WHERE id=?" % cols, vals + [session_id])

    def active_session_between(self, a_id, b_id, app):
        with self._lock:
            return self._one(
                "SELECT * FROM sessions WHERE app=? AND status='active' AND"
                " ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?))"
                " ORDER BY created_at DESC LIMIT 1",
                (app, a_id, b_id, b_id, a_id))

    def live_sessions_for(self, agent_id):
        with self._lock:
            rows = self._all(
                "SELECT * FROM sessions WHERE status='active' AND"
                " (a_id=? OR b_id=? OR auditor_id=?) ORDER BY created_at DESC",
                (agent_id, agent_id, agent_id))
        for r in rows:
            r["board"] = _decode(r["board"]) or [None] * 9
        return rows

    def all_sessions(self):
        with self._lock:
            rows = self._all("SELECT * FROM sessions ORDER BY created_at DESC")
        for r in rows:
            r["board"] = _decode(r["board"]) or [None] * 9
        return rows

    def create_round(self, r):
        self._write("INSERT INTO rounds(session_id,n,commit_a,commit_b,cell_a,cell_b)"
                    " VALUES(?,?,?,?,?,?)",
                    (r["session_id"], r["n"], r.get("commit_a"), r.get("commit_b"),
                     r.get("cell_a"), r.get("cell_b")))

    def get_round(self, session_id, n):
        with self._lock:
            return self._one("SELECT * FROM rounds WHERE session_id=? AND n=?",
                             (session_id, n))

    def update_round(self, session_id, n, fields):
        cols = ", ".join("%s=?" % k for k in fields)
        self._write("UPDATE rounds SET %s WHERE session_id=? AND n=?" % cols,
                    list(fields.values()) + [session_id, n])

    # -- receipts ---------------------------------------------------------------------
    def save_receipt(self, session_id, kind, round_n, body, published):
        self._write("INSERT INTO receipts(session_id,kind,round_n,body,published,"
                    "created_at) VALUES(?,?,?,?,?,?)"
                    " ON CONFLICT(session_id,kind,round_n) DO UPDATE SET"
                    " body=excluded.body, published=excluded.published",
                    (session_id, kind, round_n, _encode(body),
                     1 if published else 0, time.time()))

    def get_receipt(self, session_id, kind, round_n):
        with self._lock:
            row = self._one("SELECT * FROM receipts WHERE session_id=? AND kind=?"
                            " AND round_n=?", (session_id, kind, round_n))
        if row:
            row["body"] = _decode(row["body"]) or {}
            row["published"] = bool(row["published"])
        return row

    def published_receipts(self, session_id):
        with self._lock:
            rows = self._all("SELECT * FROM receipts WHERE session_id=? AND"
                             " published=1 ORDER BY round_n, kind DESC",
                             (session_id,))
        for r in rows:
            r["body"] = _decode(r["body"]) or {}
            r["published"] = True
        return [r["body"] for r in rows]

    def mark_receipt_published(self, session_id, kind, round_n, body):
        self._write("UPDATE receipts SET body=?, published=1 WHERE session_id=?"
                    " AND kind=? AND round_n=?",
                    (_encode(body), session_id, kind, round_n))

    # -- outbox ---------------------------------------------------------------------------
    def push_envelope(self, recipient_id, session_id, msg_type, envelope):
        self._write("INSERT INTO outbox(recipient_id,session_id,msg_type,envelope,"
                    "created_at) VALUES(?,?,?,?,?)",
                    (recipient_id, session_id, msg_type, _encode(envelope),
                     time.time()))

    def recent_for_recipient(self, recipient_id, session_id, limit):
        with self._lock:
            rows = self._all(
                "SELECT envelope FROM outbox WHERE recipient_id=? AND"
                " (session_id=? OR ? IS NULL) ORDER BY id DESC LIMIT ?",
                (recipient_id, session_id, session_id, limit))
        envs = [_decode(r["envelope"]) for r in rows]
        envs.reverse()
        return envs

    # -- replay protection ----------------------------------------------------------------------
    def note_message(self, msg_id, from_id):
        """True on first sighting; False for a duplicate. Prunes entries
        older than 7 days opportunistically."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT 1 FROM seen_messages WHERE msg_id=? AND from_id=?",
                (msg_id, from_id)).fetchone()
            if row:
                return False
            self._db.execute(
                "INSERT INTO seen_messages(msg_id,from_id,seen_at) VALUES(?,?,?)",
                (msg_id, from_id, time.time()))
            self._db.execute("DELETE FROM seen_messages WHERE seen_at<?",
                             (time.time() - 7 * 86400,))
            return True

    # -- activity feed -------------------------------------------------------------------------------
    def log_event(self, kind, summary, agent_id=None, session_id=None):
        self._write("INSERT INTO events(ts,kind,summary,agent_id,session_id)"
                    " VALUES(?,?,?,?,?)",
                    (time.time(), kind, summary, agent_id, session_id))

    def recent_events(self, limit=50):
        with self._lock:
            return self._all("SELECT * FROM events ORDER BY id DESC LIMIT ?",
                             (limit,))
