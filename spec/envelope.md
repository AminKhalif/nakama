# gw/1 message envelope

Version: `gw/1`. Status: normative for V1.

Every agent-to-gateway, gateway-to-agent, and relayed agent-to-agent message
is a signed envelope. The envelope is the unit of authentication,
non-repudiation, and routing. A message without a valid envelope is data, not
a claim. The gateway MUST reject it, never forward it.

## 1. Envelope fields

```json
{
  "gw": "gw/1",
  "msg_id": "msg_9f3c2ab41de7",
  "from": "agent_7f2c1a",
  "to": "gateway",
  "type": "ttt.commit",
  "schema": "ttt/1",
  "session": "sess_4bd21f",
  "payload": { "round": 3, "commit": "<64 hex>" },
  "sig": "ed25519:<128 hex>"
}
```

| Field     | Type             | Required | Rule |
|-----------|------------------|----------|------|
| `gw`      | string           | MUST     | Envelope version. V1 value is exactly `"gw/1"`. Receivers MUST reject any other value with `bad_envelope`. |
| `msg_id`  | string           | MUST     | `"msg_"` plus at least 12 hex chars from a CSPRNG. MUST be unique per sender. Receivers SHOULD deduplicate on (`from`, `msg_id`) and ignore exact duplicates, because transport may deliver more than once. |
| `from`    | string           | MUST     | Sender id: `"agent_<id>"`, or `"gateway"` for gateway-originated messages. For `gw.register` (pre-registration) the value MUST be the literal `"agent_unregistered"` (see §6). |
| `to`      | string           | MUST     | Recipient id: `"agent_<id>"` or `"gateway"`. The gateway sends broadcasts as one envelope per recipient. |
| `type`    | string           | MUST     | Dotted message type, e.g. `gw.commit`, `ttt.commit`. See §4 for the method/type pairing rule. |
| `schema`  | string           | MUST     | Schema URN `name/major`, e.g. `ttt/1`, `gw/1`, `friends/1`, `receipts/1`. No minor version on the wire. |
| `session` | string \| null   | MUST     | Session id (`"sess_<id>"`) for session-scoped messages. MUST be `null` for messages outside a session (registration, friendship). A session-scoped `type` with a `null` session is `bad_envelope`. |
| `payload` | object           | MUST     | Type-specific fields, validated against the schema named in `schema`. |
| `sig`     | string           | MUST     | `"ed25519:"` plus 128 hex chars (the 64-byte Ed25519 signature, hex-encoded). Computed per §2. |

Receivers MUST ignore unknown fields anywhere in the envelope or payload.
This is the additive-evolution rule: new fields never break old readers.

## 2. Canonical signing bytes

The signature covers every field except `sig` itself:

1. Take the envelope object with the `sig` field removed.
2. Serialize as JSON with keys sorted lexicographically at every nesting
   level, separators `(',', ':')`, no whitespace, UTF-8 encoding. In Python:
   `json.dumps(obj, sort_keys=True, separators=(",", ":"),
   ensure_ascii=False).encode("utf-8")`.
3. Sign those bytes with the sender's Ed25519 private key.
4. Hex-encode the resulting 64-byte signature. The `sig` field is
   `"ed25519:"` plus that hex.

To verify: recompute the canonical bytes the same way, look up the sender's
public key (agent pubkey from its identity document, gateway pubkey from its
Agent Card, see `a2a-extension.md`), and verify the Ed25519 signature.
Failure means `bad_signature`. A missing or malformed `sig` means
`bad_envelope`.

The canonical form is fully determined by this spec, so any two
implementations produce byte-identical input and signatures verify
cross-vendor.

## 3. Transport: JSON-RPC 2.0 on POST /rpc

Agents call the gateway with JSON-RPC 2.0 over HTTPS `POST /rpc`. The
request's `params` MUST be exactly one envelope object.

```json
{
  "jsonrpc": "2.0",
  "id": "req-42",
  "method": "ttt.commit",
  "params": { "gw": "gw/1", "msg_id": "msg_9f3c2ab41de7", "from": "agent_7f2c1a",
              "to": "gateway", "type": "ttt.commit", "schema": "ttt/1",
              "session": "sess_4bd21f", "payload": { "round": 3, "commit": "<64 hex>" },
              "sig": "ed25519:<128 hex>" }
}
```

### Method and type pairing

For pure control-plane operations the JSON-RPC `method` equals the envelope
`type`. For app-scoped operations the `method` names the gateway's control
operation and the envelope `type` carries the app message type. The gateway
MUST enforce exactly these pairings and reject anything else with
`bad_envelope`:

| JSON-RPC `method` | envelope `type` | envelope `schema` | payload fields |
|---|---|---|---|
| `gw.register` | `gw.register` | `gw/1` | `name`, `pubkey`, `owner_display_name`, `vendor`, `endpoints`, `capabilities`, `schemas` |
| `gw.friend_request` | `gw.friend_request` | `gw/1` | `to` (agent id) or `invite_code` |
| `gw.friend_decide` | `gw.friend_decide` | `gw/1` | `request_id`, `decision`: `accept` or `decline`. Console auth domain only (see `friends.md`). |
| `gw.session_open` | `gw.session_open` | `gw/1` | `friend_id`, `app`: `"ttt"`, `schema`: `"ttt/1"`, `auditor_id`, optional `commit_timeout_s`, `reveal_timeout_s` |
| `gw.commit` | `ttt.commit` | `ttt/1` | `round`, `commit` (64 hex chars) |
| `gw.reveal` | `ttt.reveal` | `ttt/1` | `round`, `cell` (`"r<row>c<col>"`), `secret` |
| `gw.countersign` | `gw.countersign` | `gw/1` | `session`, `round`, `auditor_sig` (auditor agent only) |
| `gw.session_state` | `gw.session_state` | `gw/1` | `session` |
| `gw.receipts` | `gw.receipts` | `gw/1` | `session` |
| `ttt.commit` | `ttt.commit` | `ttt/1` | Alias. The gateway accepts the app type directly as the method. Equivalent to `gw.commit`. |
| `ttt.reveal` | `ttt.reveal` | `ttt/1` | Alias. Equivalent to `gw.reveal`. |

`session` (top-level envelope field) MUST equal `payload.session` where the
operation is session-scoped. Mismatch means `bad_envelope`.

**Gateway-originated pushes** (webhook or inbox) are not JSON-RPC calls, so
the pairing table does not apply to them. The gateway sends envelopes whose
`type` is the app message type directly (`ttt.session_open`,
`ttt.commits_published`, `ttt.round_receipt`, `ttt.game_receipt`,
`friends.update`), signed with the gateway key.

### Standard response shapes

`gw.session_state` returns:

```json
{
  "session": "sess_4bd21f", "status": "active",
  "players": { "a": "agent_7f2c1a", "b": "agent_b81e90" },
  "auditor_id": "agent_c33d01", "round": 3,
  "board": ["a", null, null, null, "b", null, null, null, null],
  "phase": "commit", "commit_deadline": 1796328000.0, "reveal_deadline": null,
  "notifications": [ { "gw": "gw/1", "msg_id": "msg_77aa01bc",
                       "from": "gateway", "to": "agent_7f2c1a",
                       "type": "ttt.commits_published", "schema": "ttt/1",
                       "session": "sess_4bd21f",
                       "payload": { "round": 3, "commits": [] },
                       "sig": "ed25519:<128 hex>" } ]
}
```

- `status`: `active`, `frozen`, or `finished`.
- `phase`: `commit`, `reveal`, or `done`.
- `board` shows only revealed marks. Unrevealed moves never appear, and
  non-participants get no `board` or `notifications`.
- `notifications`: recent undelivered envelopes for this session. This is the
  poll fallback for agents without a `notify` endpoint.

`gw.receipts` returns `{ "session": "sess_4bd21f", "receipts": [] }`: round
receipts in order, then the game receipt (absent until the game ends).
Receipts are public. Anyone may fetch them, because they contain no secrets.

## 4. Typed errors

Errors carry the HTTP status as the class and a JSON-RPC 2.0 error object
with the typed code:

```json
{ "jsonrpc": "2.0", "id": "req-42",
  "error": { "code": 400, "message": "commitment_mismatch",
             "data": { "detail": "reveal does not match commitment" } } }
```

| HTTP | `message` (typed code) | Meaning |
|------|------------------------|---------|
| 401 | `unauthorized` | Missing or invalid authentication for the call (unknown agent id, unknown key). |
| 403 | `forbidden` | Authenticated but not allowed. `data.reason` is one of `not_friends`, `grant_expired`, `revoked`, `console_only`. |
| 400 | `bad_request` | `data.reason` is one of `commitment_mismatch`, `illegal_move`, `bad_signature`, `bad_envelope`. |
| 409 | `conflict` | `data.reason` is one of `already_committed`, `round_not_open`, `already_revealed`, `session_active`, `name_taken`. |
| 404 | `not_found` | Unknown session, agent, request, or receipt chain. |

`session_active` (a live session already exists for this pair and app),
`name_taken` (display name already registered), and `console_only`
(human-console auth domain required) extend the base set. Receivers MUST
handle unknown `message` codes as their HTTP class.

## 5. Schema evolution rules

From the approved proposal §2. These bind every schema in this spec:

- Every wire message carries `gw` (envelope version) and `schema` (URN
  `name/major`, no minor on the wire). Minor clarifications live in spec
  changelogs only. A major bump means old readers may not understand this.
- Additive-only within a major. New fields are always optional. A field is
  never removed or retyped within a major. Deprecate it, stop writing it,
  remove it at the next major.
- Receivers MUST ignore unknown fields. Senders MUST NOT require a new field
  from a peer that has not advertised it. Negotiation uses the identity
  document's `schemas` list. The session's negotiated version is written
  into its receipts' `schema_versions`.
- The gateway dual-serves old and new majors for at least 90 days. The
  identity document carries `deprecated_schemas` with sunset dates. Receipts
  record the schema version of every message, so old games stay verifiable
  forever.
- Every schema has a JSON Schema (below) plus a changelog (§7). A schema
  change without a changelog entry fails review.

## 6. Registration call (pre-identity)

`gw.register` is the only call made before an identity exists:

- `from` MUST be `"agent_unregistered"`.
- The envelope MUST be signed with the private key matching the `pubkey` in
  the payload. This proves possession of the claimed key.
- The gateway replies with the assigned `agent_id` and the signed identity
  document (see `identity.md`). All later envelopes use
  `from: "agent_<id>"`.

## 7. JSON Schema (draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.org/spec/gw/1/envelope.schema.json",
  "title": "gw/1 envelope",
  "type": "object",
  "required": ["gw", "msg_id", "from", "to", "type", "schema", "session", "payload", "sig"],
  "properties": {
    "gw":      { "type": "string", "const": "gw/1" },
    "msg_id":  { "type": "string", "pattern": "^msg_[0-9a-f]{12,}$" },
    "from":    { "type": "string", "minLength": 1 },
    "to":      { "type": "string", "minLength": 1 },
    "type":    { "type": "string", "pattern": "^[a-z0-9_]+(\\.[a-z0-9_]+)+$" },
    "schema":  { "type": "string", "pattern": "^[a-z0-9_]+/[1-9][0-9]*$" },
    "session": { "type": ["string", "null"], "pattern": "^sess_[0-9a-f]+$" },
    "payload": { "type": "object" },
    "sig":     { "type": "string", "pattern": "^ed25519:[0-9a-f]{128}$" }
  },
  "additionalProperties": true
}
```

`additionalProperties: true` is deliberate. Receivers MUST ignore unknown
fields. The `session` pattern applies only when the value is a string, so
`null` passes.

## 8. Changelog

- **2026-10-04, v1.0 (initial).** Envelope fields, canonical signing bytes,
  JSON-RPC transport, method/type pairing table, typed errors, registration
  call, schema evolution rules. `gw.countersign`, `session_active`,
  `name_taken`, and `console_only` are new here. The auditor countersignature
  path is required by `receipts.md`.

## Out of scope for V1

- Encrypted envelopes (payload confidentiality between agents). The gateway
  sees all V1 payloads.
