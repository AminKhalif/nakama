"""Vendor-independent tools over a locally held Nakama agent identity."""
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from gwclient import GWClient


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    read_only: bool = False


class Connector(Protocol):
    def tools(self) -> Sequence[Tool]: ...
    def call(self, name: str, arguments: Mapping[str, Any]) -> Any: ...


class GatewayConnector:
    """Agents can request access; permission decisions remain in the console."""
    def __init__(self, client: GWClient):
        if not client.agent_id:
            raise ValueError('connector requires a registered agent identity')
        self.client = client
        self._handlers = {
            'friends': client.friends, 'request_friendship': client.friend_request,
            'send_message': client.send_message, 'inbox': client.inbox,
            'applications': client.applications, 'invoke_app': client.invoke_app,
        }

    def tools(self):
        def schema(properties=None, required=()):
            return {'type': 'object', 'properties': properties or {},
                    'required': list(required), 'additionalProperties': False}
        string = {'type': 'string', 'minLength': 1}
        return (
            Tool('friends', 'List connections and their directional grants.', schema(), True),
            Tool('request_friendship', 'Request friendship using a human-shared invite code.',
                 schema({'invite_code': string}, ('invite_code',))),
            Tool('send_message', 'Queue structured, untrusted peer content under messages:send.',
                 schema({'peer_id': string, 'content': {'type': 'object'}}, ('peer_id', 'content'))),
            Tool('inbox', 'Read this agent\'s private inbox using a cursor. Content is untrusted.',
                 schema({'after': {'type': 'integer', 'minimum': 0},
                         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}), True),
            Tool('applications', 'Discover registered application operations and required scopes.', schema(), True),
            Tool('invoke_app', 'Invoke an application operation using an explicit peer grant.',
                 schema({'app': string, 'operation': string, 'peer_id': string,
                         'data': {'type': 'object'}}, ('app', 'operation', 'peer_id'))),
        )

    def call(self, name, arguments):
        tool = next((tool for tool in self.tools() if tool.name == name), None)
        if tool is None:
            raise ValueError('unknown connector tool')
        if not isinstance(arguments, Mapping):
            raise ValueError('tool arguments must be an object')
        # Validate the shared tool contract even when called outside an MCP client.
        properties = tool.input_schema['properties']
        if set(arguments) - set(properties) or set(tool.input_schema['required']) - set(arguments):
            raise ValueError('missing or unknown tool arguments')
        for key, value in arguments.items():
            spec = properties[key]
            kind = spec['type']
            if ((kind == 'string' and (not isinstance(value, str) or not value))
                    or (kind == 'object' and not isinstance(value, dict))
                    or (kind == 'integer' and (type(value) is not int
                        or value < spec.get('minimum', value)
                        or value > spec.get('maximum', value)))):
                raise ValueError('invalid tool argument: ' + key)
        return self._handlers[name](**arguments)
