"""Typed convenience client; uses the same signed application protocol as MCP."""
from typing import Any
from gwclient import GWClient


class SchedulingClient:
    def __init__(self, client: GWClient):
        self._client = client

    def _call(self, peer_id: str, operation: str, data: dict) -> dict[str, Any]:
        return self._client.invoke_app('calendar', operation, peer_id, data)['result']

    def availability(self, peer_id: str, *, start: str, end: str) -> dict[str, Any]:
        return self._call(peer_id, 'availability', {'start': start, 'end': end})

    def find_slots(self, peer_id: str, *, start: str, end: str,
                   duration_minutes: int = 30, limit: int = 10) -> dict[str, Any]:
        return self._call(peer_id, 'find_slots', {'start': start, 'end': end,
            'duration_minutes': duration_minutes, 'limit': limit})

    def propose(self, peer_id: str, *, start: str, end: str, summary: str) -> dict[str, Any]:
        return self._call(peer_id, 'propose', {'start': start, 'end': end, 'summary': summary})

    def status(self, peer_id: str, proposal_id: str) -> dict[str, Any]:
        return self._call(peer_id, 'status', {'proposal_id': proposal_id})

    def book(self, peer_id: str, proposal_id: str) -> dict[str, Any]:
        return self._call(peer_id, 'book', {'proposal_id': proposal_id})
