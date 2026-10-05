"""Agent Interop Gateway -- reference gateway (M2).

Stdlib-only Python 3.9+ package. Modular, decoupled:

  crypto       Ed25519 (vendored pure-Python, RFC 8032) behind sign/verify/keygen
  wire         A2A JSON-RPC 2.0 framing + signed-envelope handling (swappable)
  store        abstract Storage interface (agents, friends, grants, sessions, ...)
  sqlite_store SQLite implementation of Storage (all SQL lives here)
  identity     agent registration, signed identity documents, key revocation
  friends      invite-code friend requests, expiring grants, revoke/unfriend
  sessions     tic-tac-toe sessions: commit/reveal, deadlines, win/draw
  receipts     hash-chained, gateway-signed (+auditor-countersigned) receipts
  spectator    live spectator page (HTML)
  console      human operator console (HTML) -- separate auth domain
  server       HTTP entry point: python3 server.py --port 8080 --db gw.db

Version: 0.1.0 (gw/1 wire, ttt/1 game schema).
License: Apache-2.0.
"""

__version__ = "0.1.0"
__all__ = [
    "crypto", "wire", "store", "sqlite_store", "identity", "friends",
    "sessions", "receipts", "spectator", "console", "server",
]
