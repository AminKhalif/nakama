"""Durable proposals and approvals; provider event IDs handle booking recovery."""
from contextlib import contextmanager
import json
import sqlite3
import threading
from typing import ContextManager, Protocol

from .models import SchedulingError


class ProposalStore(Protocol):
    def create(self, proposal: dict) -> None: ...
    def get(self, proposal_id: str) -> dict: ...
    def locked(self, proposal_id: str) -> ContextManager[dict]: ...
    def conflicts(self, proposal: dict) -> bool: ...
    def close(self) -> None: ...


class SQLiteProposalStore:
    """Use a separate database file. Each mutation holds a write transaction."""
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._db.execute('CREATE TABLE IF NOT EXISTS meeting_proposals (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self._db.commit()
        self._mutex = threading.RLock()

    def create(self, proposal):
        with self._mutex, self._db:
            self._db.execute('INSERT INTO meeting_proposals VALUES (?, ?)',
                             (proposal['id'], json.dumps(proposal, allow_nan=False)))

    def get(self, proposal_id):
        with self._mutex:
            row = self._db.execute('SELECT body FROM meeting_proposals WHERE id=?', (proposal_id,)).fetchone()
            if row is None:
                raise SchedulingError('meeting proposal not found')
            return json.loads(row[0])

    def conflicts(self, proposal):
        """Called inside locked(): block overlapping intents on either account."""
        from .models import TimeWindow
        participants = {proposal['caller_id'], proposal['peer_id']}
        window = TimeWindow.parse(proposal['start'], proposal['end'])
        with self._mutex:
            for row in self._db.execute('SELECT body FROM meeting_proposals WHERE id != ?', (proposal['id'],)):
                other = json.loads(row[0])
                if (other['state'] in ('booking', 'booked')
                        and participants.intersection((other['caller_id'], other['peer_id']))
                        and window.overlaps(TimeWindow.parse(other['start'], other['end']))):
                    return True
        return False

    @contextmanager
    def locked(self, proposal_id):
        with self._mutex:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                proposal = self.get(proposal_id)
                yield proposal
                self._db.execute('UPDATE meeting_proposals SET body=? WHERE id=?',
                                 (json.dumps(proposal, allow_nan=False), proposal_id))
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def close(self):
        with self._mutex:
            self._db.close()
