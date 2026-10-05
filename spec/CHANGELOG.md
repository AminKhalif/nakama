# Spec changelog

All notable changes to the `spec/` normative documents. Each schema file
carries its own per-file changelog; this file tracks cross-cutting changes.

The format is based on Keep a Changelog. Dates are UTC.

## [1.0.0] - 2026-10-04

Initial normative V1 spec set (M1):

### Added
- `envelope.md`: `gw/1` envelope, canonical signing bytes, JSON-RPC 2.0
  transport on `POST /rpc`, method/type pairing table, typed errors
  (401/403/400/409/404), schema evolution rules, registration call.
- `identity.md`: gateway-signed identity documents, local key custody,
  registration flow, key rotation, signed revocation list, gateway pubkey
  distribution.
- `friends.md`: friendship lifecycle, scopes (`game.ttt:play`,
  `game.ttt:spectate`), expiring grants, console requirements, immediate
  revocation with session freeze, invite codes.
- `receipts.md`: round receipt, game receipt, step-by-step chain
  verification algorithm, honest statement of what the chain proves.
- `ttt-v1.md`: `ttt/1` rules, message types, commitment formula, round
  flow, deadline/forfeit semantics, auditor duties, edge cases.
- `a2a-extension.md`: A2A v1.0.1 compatibility statement (pure vs
  extension, interop story, separability), gateway Agent Card.

### Decisions recorded
- Wire protocol is A2A v1.0.1 (JSON-RPC binding) plus per-message Ed25519
  signatures. A2A signs Agent Cards, not messages.
- Commitment: `sha256("gw/1|<session_id>|r<round>|<agent_id>|<cell>|<secret>")`.
- Receipts: per-round plus final game receipt, hash-chained, doubly signed
  (gateway plus auditor).
- The gateway referees during the game. The auditor verifies and
  countersigns. Anyone can audit afterward from receipts alone.
- Apache-2.0. Anyone-can-run operator model.

## 2026-10-05: messaging and application extensions

Added signed `gw.friends_list`, `gw.message_send`, `gw.inbox`, `gw.apps_list`, and
`gw.app_invoke` operations. See `applications.md`. Existing envelope, identity,
and game contracts remain compatible. Empty console scope selection now creates
no grants instead of silently granting default game access.

## 0.4.0 — Scheduling SDK

- Calendar availability, shared slots, meeting proposals, status, and guarded booking
  use the existing application operation envelope.
- Separate calendar provider and proposal-store interfaces; durable SQLite approvals
  and booking intent; host-controlled owner/account bindings.
- Typed scheduling client, Google Calendar discovery-client adapter, local meeting
  demo, and embeddable gateway lifecycle.
- Plain operator copy and accurate scheduling/approval boundaries.
