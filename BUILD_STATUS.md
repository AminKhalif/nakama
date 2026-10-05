# Implementation status

The gateway implements signed identity registration, console-approved friendships,
expiring directional grants, and tic-tac-toe sessions with verifiable receipts.
The game is a protocol example, not the application model for every integration.

The Python client supports envelope signing, identity verification, game operations,
and independent receipt verification. See [testing](TESTING.md) for validation.

## Limitations

- One operator console manages all agents on an instance; owner-level accounts are
  not implemented. The console is an operator tool, not a multi-tenant user portal.
- Federation between independent gateways is not implemented.
- The A2A endpoint is a compatibility wrapper for Nakama envelopes, not a complete
  A2A task implementation.
- The HTTP server and pure-Python cryptography are reference implementations.
  Production deployment requires a deployment-specific security review.
- External vendor integrations require a documented API or tool interface.
  A vendor name in an identity is metadata, not proof of integration or trust.
