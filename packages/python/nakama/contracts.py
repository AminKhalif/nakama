"""Application declarations independent of gateway routing and persistence."""
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class AppContext:
    caller_id: str
    peer_id: str
    friendship_id: str


@dataclass(frozen=True)
class Operation:
    name: str
    scope: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[AppContext, Mapping[str, Any]], Any]


class AppAdapter(Protocol):
    app_id: str

    def operations(self) -> Sequence[Operation]: ...
