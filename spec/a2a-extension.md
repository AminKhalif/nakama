# A2A compatibility

Status: normative for V1. Reference: Google A2A v1.0.1, pinned. (Governance
churn is fast; see `docs/research.md`.)

The gateway's wire protocol is Google's Agent2Agent (A2A) v1.0.1 with one
documented extension: per-message Ed25519 signatures. Everything else is
pure A2A.

## A2A compatibility statement

### (a) What is pure A2A v1.0.1

- **Transport framing: JSON-RPC 2.0.** Our `POST /rpc` endpoint, request,
  response, and error objects, and method routing are exactly A2A's
  JSON-RPC binding. A client that speaks A2A's JSON-RPC binding can frame
  requests to the gateway with no changes.
- **Discovery: Agent Card at `/.well-known/agent-card.json`.** The gateway
  publishes an A2A Agent Card describing itself: name, description, URL,
  provider, version, and its skills, including the tic-tac-toe referee skill
  (`game.ttt:play`, schema `ttt/1`). Any A2A client can discover the gateway
  the standard way.
- **Extensibility posture.** A2A permits additional fields on its objects,
  and receivers ignore what they do not understand. We rely on this and
  nothing else.

### (b) What is our extension, and why

Four additions, all specified in this tree:

1. **Per-message Ed25519 `sig` field** (`envelope.md` §2). Every envelope
   carries `"sig": "ed25519:<128 hex>"` over canonical signing bytes.
2. **`gw` envelope fields.** `gw`, `msg_id`, `from`, `to`, `type`,
   `schema`, `session`, `payload`: the envelope structure itself.
3. **`gw.*` method namespace.** `gw.register`, `gw.friend_request`,
   `gw.friend_decide`, `gw.session_open`, `gw.commit`, `gw.reveal`,
   `gw.countersign`, `gw.session_state`, `gw.receipts`.
4. **Receipt chain** (`receipts.md`). Hash-chained, doubly signed round and
   game receipts.

Why: A2A v1.0.1 signs Agent Cards but not messages. It proves who published
a card, not who sent a message. The gateway's whole value is proving what
crossed it (commitments, reveals, outcomes) so disputes are decidable after
the fact. Message-level signatures give non-repudiation: a player cannot
deny its commit, the gateway cannot deny what it published, and the auditor
cannot deny its countersignature. Without the extension there are no
trustworthy receipts, and without receipts the broker and auditor role is
unverifiable.

### (c) Interop story: pure-A2A clients still work

- A pure-A2A client can exchange messages with the gateway. Our envelopes
  are ordinary JSON objects, and the gateway accepts A2A-framed JSON-RPC
  calls. Unknown fields (`sig`, `gw`, `session`, and so on) are ignored by
  pure-A2A receivers per A2A's extensibility rules. The message still parses.
- Signature verification is additive, never required to parse. A client that
  does not verify signatures gets a working but unattested message stream.
  A client that does gets non-repudiation. Nothing about the base parse path
  depends on the extension.
- One hard boundary: operations that require attestation (submitting a
  commit, countersigning a receipt) require a valid `sig`. The gateway
  rejects unsigned claims with `bad_signature`. Reading state, discovery,
  and spectator views need no signatures.

### (d) The extension is cleanly separable

Remove the `sig` field, the `gw.*` methods, and the receipt chain, and what
remains is plain A2A messaging: JSON-RPC 2.0 transport, Agent Card
discovery, typed methods, extensible JSON payloads. The extension adds
fields and methods. It changes no A2A semantic. A future A2A version that
signs messages natively could replace our `sig` field one-for-one with no
other spec changes.

## Gateway Agent Card (V1)

The gateway MUST serve a valid A2A v1.0.1 Agent Card at
`/.well-known/agent-card.json` with at minimum: `name`, `description`,
`url`, `provider`, `version`, and a `skills` entry for the tic-tac-toe
referee (`id: "game.ttt"`, description, tags). The gateway's Ed25519 public
key is published in the card under the extension field
`"gwPubkey": "ed25519:<64 hex>"`, so agents can verify gateway signatures
(`identity.md` §3, `receipts.md` §3) from discovery alone.

## Changelog

- **2026-10-04, v1.0 (initial).** Compatibility statement (a) to (d),
  gateway Agent Card requirement, `gwPubkey` extension field.

## Out of scope for V1

- A2A gRPC and HTTP+JSON REST bindings. V1 is JSON-RPC 2.0 only.
- A2A task lifecycle and SSE streaming. Sessions are our task abstraction
  in V1.
