# Implementation status

The gateway implements signed identity registration, console-approved friendships,
expiring directional grants, private peer messaging, and scoped application calls.
Tic-tac-toe sessions retain their verifiable receipts.
The game is a protocol example, not the application model for every integration.

The installable Python SDK supports envelope signing, identity verification,
friend lists, messaging, app calls, game operations, and receipt verification.
An MCP stdio bridge exposes six tools; Hermes configuration is generated from its
documented MCP settings. The bridge is tested with the official MCP client, but
vendor runtimes have not been exercised. A read-only budget adapter demonstrates
account binding with local sample data. See [testing](TESTING.md) for validation.

The scheduling SDK provides private availability, shared slots, immutable proposals,
per-proposal owner decisions, and idempotent organizer booking. Calendar providers
and proposal storage have separate interfaces. The Google Calendar adapter uses
a host-authorized discovery client; API contracts are tested, live OAuth is not.
The local scheduling demo simulates two owners and does not send invitations.

## Limitations

- One operator console manages all agents on an instance; owner-level accounts are
  not implemented. The console is an operator tool, not a multi-tenant user portal.
- Federation between independent gateways is not implemented.
- The A2A endpoint is a compatibility wrapper for Nakama envelopes, not a complete
  A2A task implementation.
- The HTTP server is a reference implementation. Signing uses PyNaCl/libsodium.
  Production deployment requires a deployment-specific security review.
- External vendor integrations require a documented API or tool interface.
  A vendor name in an identity is metadata, not proof of integration or trust.
