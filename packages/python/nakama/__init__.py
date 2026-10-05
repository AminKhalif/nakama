"""Public Python SDK for Nakama. Existing gwclient imports remain supported."""
from gwclient import GWClient as Client, ClientError, GatewayError
from gwclient import verify_identity_document, verify_envelope, verify_chain
from gwclient.transport import A2ATransport, HTTPTransport, Transport

__version__ = '0.3.0'
__all__ = ['Client', 'ClientError', 'GatewayError', 'A2ATransport', 'HTTPTransport', 'Transport',
           'verify_identity_document', 'verify_envelope', 'verify_chain']
