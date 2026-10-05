"""Stable SDK exceptions, independent of transport implementations."""


class GatewayError(Exception):
    """A JSON-RPC error returned by the gateway."""

    def __init__(self, code, message, data=None):
        self.code = code
        self.data = data
        super().__init__('gateway error %s: %s' % (code, message))


class ClientError(Exception):
    """Invalid client configuration, malformed response, or transport failure."""
