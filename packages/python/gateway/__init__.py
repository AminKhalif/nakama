"""Nakama reference gateway: signed operations, scoped grants, and SQLite storage.

Messaging and application adapters are independent of the example game protocol.
Signing uses the shared PyNaCl/libsodium backend.
"""

__version__ = "0.4.0"
__all__ = [
    "apps", "messaging", "crypto", "wire", "store", "sqlite_store", "identity",
    "friends", "sessions", "receipts", "spectator", "console", "server",
]
