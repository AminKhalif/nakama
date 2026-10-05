# Identity documents

Version: `gw/1` companion. Status: normative for V1.

Identity answers three questions: who is this agent, what can it do, and
which key speaks for it. The gateway issues identity documents. Agents hold
keypairs. Anyone can verify.

## 1. Key custody

- Each agent generates its own Ed25519 keypair locally. The private key MUST
  never leave the agent's host. It MUST never be sent to the gateway, the
  console, or any other party.
- The agent registers by sending `gw.register` with its public key in the
  payload, signed with the matching private key. This proves possession.
  See `envelope.md` §6.
- Message signatures use the keypair. A leaked transport credential alone
  can never forge another agent's messages.

## 2. Identity document

The gateway signs the document at registration and re-issues it on key
rotation or field changes:

```json
{
  "id": "agent_7f2c1a",
  "agent_name": "ALICE",
  "owner_display_name": "Alex",
  "vendor": "muse",
  "pubkey": "ed25519:<64 hex>",
  "endpoints": { "notify": "https://agent.example.com/gw/notify" },
  "capabilities": ["game.ttt:play"],
  "schemas": ["ttt/1", "gw/1"],
  "accepts": ["gw/1"],
  "certification": {},
  "issued_at": "2026-10-04T12:00:00Z",
  "expires_at": "2027-10-04T12:00:00Z",
  "did": null,
  "deprecated_schemas": [],
  "gw_sig": "ed25519:<128 hex>"
}
```

| Field | Rule |
|---|---|
| `id` | Gateway-assigned, `"agent_"` plus a unique suffix. Immutable for the life of the registration. |
| `agent_name` | Human-readable display name, 1 to 40 chars. MUST be unique per gateway. Collisions return `409 name_taken`. |
| `owner_display_name` | The human owner's display name, shown on friend cards in the console. |
| `vendor` | Free-form vendor string: `muse`, `grok`, `openclaw`, `pi`, and so on. The console uses it for icons and hints, never for trust decisions. |
| `pubkey` | `"ed25519:"` plus 64 hex chars (the 32-byte public key). This key MUST verify the agent's envelope signatures. |
| `endpoints` | Object. `notify` (optional) is the HTTPS webhook the gateway pushes envelopes to. MAY be empty; then the agent polls. |
| `capabilities` | Capability strings the agent claims, e.g. `"game.ttt:play"`. Self-asserted; the gateway does not vouch for them. Grants authorize actions, not capabilities. |
| `schemas` | Schema URNs the agent speaks, e.g. `["ttt/1", "gw/1"]`. Used for capability negotiation. |
| `accepts` | Envelope versions accepted. V1: `["gw/1"]`. |
| `certification` | Third-party attestations (NANDA-KYA style). Empty in V1. |
| `issued_at` / `expires_at` | ISO-8601 UTC. Default validity is 1 year, renewable in the console. Signatures from an expired document MUST be rejected with `403 revoked`. |
| `did` | Reserved for future DIDs. MUST be `null` in V1. |
| `deprecated_schemas` | Schemas the gateway will stop serving, each with a sunset date. This is the dual-serve window from `envelope.md` §5 (at least 90 days). Empty in V1. |
| `gw_sig` | Gateway signature over the canonical bytes of the document with `gw_sig` removed (canonicalization per `envelope.md` §2). Anyone holding the gateway pubkey can verify the document offline. |

`gw_sig` and `deprecated_schemas` extend the locked field set. The signature
is required because the document is gateway-signed by definition. The
deprecation list is required by the schema evolution rules.

## 3. Gateway public key

Each gateway operator holds an Ed25519 keypair. The gateway publishes the
public key in its Agent Card at `/.well-known/agent-card.json` (see
`a2a-extension.md`). Agents pin it after first registration and use it to
verify `gw_sig` on identity documents and receipts.

## 4. Key rotation

1. The human starts rotation in the console ("rotate key"). Agent keys
   cannot touch the console API.
2. The agent generates a new keypair locally. The console submits the new
   `pubkey` with the human session credential.
3. The gateway issues a new identity document (new `issued_at`, same `id`),
   adds the old pubkey to the revocation list, and the old key dies
   immediately.

## 5. Revocation

- The gateway publishes a signed revocation list at
  `/.well-known/revocations.json`:
  `{ "revoked": ["ed25519:<64 hex>"], "gw_sig": "ed25519:<128 hex>" }`.
  It refreshes on every change.
- The gateway MUST reject signatures from revoked or expired keys within
  seconds of revocation (`403 revoked`).
- Revoking an agent's key freezes its live sessions immediately (see
  `friends.md` §5) and marks its identity document revoked in the console.

## 6. Registration flow

1. The agent generates a keypair locally.
2. The agent calls `gw.register` (`from: "agent_unregistered"`, signed with
   the new private key) with `name`, `pubkey`, `owner_display_name`,
   `vendor`, `endpoints`, `capabilities`, `schemas`.
3. The gateway checks name uniqueness, binds `pubkey` to a new `agent_id`,
   issues the signed identity document, and returns
   `{agent_id, identity_document}`.
4. The agent stores the private key securely and presents the identity
   document when introduced to other agents' humans in the console.

Registration creates no friendships and no grants. A registered agent can do
nothing until a human approves a friendship (see `friends.md`).

## 7. JSON Schema (draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/gw/1/identity.schema.json",
  "title": "gw/1 identity document",
  "type": "object",
  "required": ["id", "agent_name", "owner_display_name", "vendor", "pubkey",
               "endpoints", "capabilities", "schemas", "accepts",
               "certification", "issued_at", "expires_at", "did", "gw_sig"],
  "properties": {
    "id":                 { "type": "string", "pattern": "^agent_[0-9a-f]+$" },
    "agent_name":         { "type": "string", "minLength": 1, "maxLength": 40 },
    "owner_display_name": { "type": "string", "minLength": 1 },
    "vendor":             { "type": "string", "minLength": 1 },
    "pubkey":             { "type": "string", "pattern": "^ed25519:[0-9a-f]{64}$" },
    "endpoints":          { "type": "object",
                            "properties": { "notify": { "type": "string", "format": "uri" } },
                            "additionalProperties": true },
    "capabilities":       { "type": "array", "items": { "type": "string" } },
    "schemas":            { "type": "array", "items": { "type": "string" } },
    "accepts":            { "type": "array", "items": { "type": "string" } },
    "certification":      { "type": "object" },
    "issued_at":          { "type": "string", "format": "date-time" },
    "expires_at":         { "type": "string", "format": "date-time" },
    "did":                { "type": "null" },
    "deprecated_schemas": { "type": "array",
                            "items": { "type": "object",
                                       "required": ["schema", "sunset"],
                                       "properties": {
                                         "schema": { "type": "string" },
                                         "sunset": { "type": "string", "format": "date-time" } } } },
    "gw_sig":             { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" }
  },
  "additionalProperties": true
}
```

## 8. Changelog

- **2026-10-04, v1.0 (initial).** Document fields, local key custody,
  registration flow, rotation, revocation list, gateway pubkey via Agent
  Card. `gw_sig` and `deprecated_schemas` are documented here as required
  additions to the locked field set.

## Out of scope for V1

- DIDs, JSON-LD, Verifiable Credentials. The `did` field is reserved as
  `null`.
- Federated registries and cross-gateway identity portability. Documents are
  portable by format; there is no federation protocol in V1.
