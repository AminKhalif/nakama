# ADR: signed envelopes over JSON-RPC

## Decision

Sign each Nakama envelope with Ed25519. The signature covers canonical JSON bytes
for all envelope fields except `sig`. The gateway verifies possession, key status,
and replay protection before state-changing operations.

The `message/send` compatibility endpoint carries an envelope in a text part.
It is a Nakama transport wrapper, not full A2A conformance. Ordinary A2A clients
still need Nakama signing and schema support to perform authorized operations.

The signature format and canonicalization contract are documented in
[the envelope specification](../../spec/envelope.md).
