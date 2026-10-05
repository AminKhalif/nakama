# Architecture

Nakama provides a gateway and a client library for agents from different vendors.
The gateway enforces signed identity, friendships, and human-approved access.
Vendor connectors translate tool calls into client operations. Application adapters
implement domain operations behind explicit scopes.

## Boundaries

- `spec/`: versioned wire contracts and signature rules.
- `packages/python/gwclient/`: client operations and independent verification.
- `packages/python/gateway/`: authorization, persistence, routing, and console.
- `examples/`: runnable applications and protocol demonstrations.
- `tests/`: conformance and adversarial tests against a live gateway.

Domain code receives validated data. HTTP framing, vendor configuration, and SQL
belong in their own modules. A connector must not approve friendships, create
grants, or bypass gateway authorization.

## Current application

Tic-tac-toe exercises simultaneous commitments, reveals, deadlines, and signed
receipts. Those game rules remain separate from general messaging and application
operations. A financial-data integration should declare its own operations and
scopes; it should not reuse game sessions or game grants.

## Trust boundary

An agent signature proves possession of its key, not verified human ownership.
The operator console controls friendships and grants. The operator is trusted
with the gateway database and signing key. All agents on an instance share that
operator; separate owners and federated trust are future work.

The existing A2A `message/send` endpoint transports signed Nakama envelopes.
It does not implement the full A2A task lifecycle. MCP connectors expose the
client as tools while retaining the same signed gateway protocol.

## Necessary controls and optional protocol features

The MVP requires an agent record, authenticated operations, human-approved
connections, scoped grants, and revocation. It does not require global discovery,
federation, game auditors, or externally attested capability claims.

The current signed envelope and identity document formats are retained for existing
clients. They are implementation choices, not proof that every future integration
needs portable signed documents. Owner account verification is still missing and
must precede a multi-user consumer launch. See [the NANDA review](docs/nanda-review.md).
