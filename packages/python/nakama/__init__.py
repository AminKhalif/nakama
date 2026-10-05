"""Public Python SDK for Nakama. Existing gwclient imports remain supported."""
from typing import TYPE_CHECKING
from gwclient import GWClient, ClientError, GatewayError
from gwclient import verify_identity_document, verify_envelope, verify_chain
from gwclient.transport import A2ATransport, HTTPTransport, Transport

if TYPE_CHECKING:
    from .scheduling import SchedulingClient


class Client(GWClient):
    """Signed Nakama client with domain-specific SDK helpers."""
    @property
    def scheduling(self) -> 'SchedulingClient':
        from .scheduling import SchedulingClient
        return SchedulingClient(self)

__version__ = '0.4.0'
__all__ = ['Client', 'ClientError', 'GatewayError', 'A2ATransport', 'HTTPTransport', 'Transport',
           'verify_identity_document', 'verify_envelope', 'verify_chain']
