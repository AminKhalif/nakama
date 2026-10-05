# Nakama — Architecture Proposal

Date: 2026-10-04. Status: APPROVED by Tajer 2026-10-04 — build in progress
(M1–M4 via build coordinator; M5 reserved for Tajer's UX test).
Author: planner worker.

This proposal builds on two things: the sourced research in `docs/research.md` (confidence legend [P]/[S]/[U] there) and the proven Muse-to-Muse bridge (`~/workspace/muse-internet/bridge/`, read-only reference). Principles carried forward from the bridge unless stated otherwise: hub-and-spoke; agents AND apps are mutually untrusted; the gateway owns identity, friendship, expiring grants, sessions, sealed values, deadlines, inbox, spectator feed, and audit log; apps are signed webhook services; human approvals go through a console that agent keys cannot touch.

One deliberate change from the bridge, with a sourced reason: the bridge authenticates agents with bearer tokens and trusts the transport. The research shows Google A2A v1.0.1 signs only Agent Cards — messages themselves are unsigned [S]. Our gateway's whole value is proving what crossed it, so V1 agents hold Ed25519 keypairs and sign every message; the gateway verifies and countersigns receipts. Bearer tokens stay only for the human console session, never for agent-to-agent claims.

Corrections applied from research: "Transport Pi" does not exist — dropped. "Dots" (New Computer's Dot) shut down — dropped as an endpoint. Instinct's Sep 2026 proprietary Trusted Person Network is our competitive frame: single-vendor and closed; our edge is cross-vendor and open [S].

---

## 1. Architecture options: the "multiple iterations"

Four shapes, in recommended build order.

### Iteration 1 (V1): Hosted gateway service — BUILD FIRST

One operated service. Agents from any vendor connect over HTTPS with their keypairs. The gateway owns identity registry, friend graph, session state, commit/reveal verification, receipts, and the spectator feed. This is the bridge design generalized from Muse-only to cross-vendor, and from RPS to any turn-based app.

Why first: every trust property we need (no replayed commits, no leaked unrevealed moves, timeout forfeits, human approval gates) requires a single choke point that all parties can verify but none controls. The bridge already proved this shape works (39/39 checks). A library cannot enforce anything between mutually untrusted agents — it can only format messages. Enforcement must live in infrastructure. That is the standing rule from the muse-internet project, and the research backs it: even NANDA federates registries rather than trusting peers directly [S].

Alternative: start with the library. Trade-off: faster to ship, but zero enforceable fairness — two agents "playing fair" on a shared library is a promise, not a property.

### Iteration 2: Embeddable client library — BUILD SECOND, alongside V1

`packages/python/gwclient` first, TypeScript later. The library does NOT reimplement the gateway. It implements: the signed envelope format, schema validation, commit/reveal helpers, receipt-chain verification, and a thin gateway API client. Vendors and developers embed it so their agents speak the protocol in ten lines.

Why second: the library's value is making the gateway easy to adopt. It needs the gateway's protocol to exist first, or it standardizes nothing. Shipping it alongside V1 lets the V1 demo bots dogfood it.

Alternative: gateway-only with raw HTTPS docs. Trade-off: every vendor hand-rolls envelope signing; interop dies in integration bugs.

### Iteration 3: Hybrid (thin gateway + fat protocol) — EVOLVE INTO, not a separate build

Over time, move logic out of the gateway into the versioned protocol and signed receipts: the gateway becomes a dumb-but-honest broker (identity, ordering, deadlines, receipt chaining) while game rules, app logic, and validation live in the library and in app webhooks. The bridge's RPS logic is the template for what gets extracted first (the ecosystem research prompt already scoped this extraction: core keeps identity/friendship/sessions/receipts; game rules move to the app).

Why as an evolution: V1 needs the gateway to be smart enough to run tic-tac-toe end-to-end with no other moving parts. Once the receipt format is stable, smarts can migrate outward without breaking anyone, because receipts — not gateway code — are the source of truth.

Alternative: keep all logic in the gateway forever. Trade-off: the gateway team becomes the bottleneck for every new app; third-party innovation stalls.

### Iteration 4: Developer self-host path — BUILD WHEN SOMEONE ASKS

A Docker Compose bundle: gateway + Postgres/SQLite + console, one command up. Same protocol, same receipts, zero federation with the hosted instance. This is for developers building apps and for vendors evaluating embedding — not for end users, per Tajer's constraint.

Why last: self-hosting solves nobody's V1 problem. It exists to remove the "but I can't run your cloud" objection from developers. Federation between self-hosted instances is explicitly out of scope until Iteration 3's receipts are stable.

Alternative: federate from day one (NANDA-style registry quilt). Trade-off: CRDT sync, key discovery across operators, and cross-instance dispute handling multiply V1 complexity ~5x for users who don't exist yet.

**Recommended order: 1 → 2 (overlapping) → 3 (gradual) → 4 (on demand).**

---

## 2. Schema-evolution strategy: cheap to change, by construction

Tajer's fixed requirement: one shared schema across vendors, designed so changing it is cheap. Concrete rules:

**Versioning scheme.** Every wire message carries two version markers: the envelope version (`gw/1`) and a schema URN (`ttt/1`, `friends/1`, `receipts/1`). Format is `name/major` — no minor on the wire. Minor clarifications live in the spec changelog only. A major bump means "old readers may not understand this."

**Extensibility rules (enforced by the library, tested in CI).**
- Additive-only within a major version. New fields are always optional.
- Receivers MUST ignore unknown fields. Senders MUST NOT require a new field from a peer that hasn't advertised it.
- A field is never removed or retyped within a major. Deprecate it, stop writing it, remove it at the next major.
- Every schema has a JSON Schema file in `spec/` plus a changelog. The changelog is mandatory — a schema change without a changelog entry fails review.

**Capability negotiation.** Borrowed from NANDA's AgentFacts pattern [P]: each agent's signed identity document lists `accepts: ["gw/1"]` and `schemas: ["ttt/1", "ttt/2"]`. When a session starts, the gateway (or broker) picks the highest schema version both sides advertise. No flag days, no silent downgrades — the negotiated version is written into the session's first receipt.

**Migration path.** The gateway dual-serves the old and new major for at least one deprecation window (V1 window: 90 days, configurable). The identity document carries a `deprecated_schemas` list with sunset dates. Receipts record which schema version each message used, so old games stay verifiable forever — history never rots.

**What we take from NANDA:** versioned signed capability documents as the negotiation surface. **What we skip:** JSON-LD and the full VC stack for V1 — plain signed JSON with the same fields (ID, name, endpoints, capabilities, certification) is enough; JSON-LD compatibility is a documented future step, not V1 scope.

Alternative: unversioned "just update everyone" (what most v1 protocols do). Trade-off: works until the second vendor ships, then every change is a breaking change.

---

## 3. Identity + friends-list UX

### What identity the agents hold

Each agent holds: an Ed25519 keypair (private key never leaves the agent's host), and a signed identity document issued by the gateway at registration. The document mirrors NANDA's AgentFacts fields [P] — `id`, `agent_name`, `owner_display_name`, `vendor` (muse, grok, openclaw…), `endpoints`, `capabilities`, `schemas`, `certification` (empty in V1; third-party attestations later, à la NANDA KYA), `issued_at`, `expires_at`. The gateway signs it; anyone can verify it offline with the gateway's public key.

Take from NANDA: signed, versioned capability documents; key rotation via a status list (compromised/rotated keys published, gateway rejects signatures from revoked keys within seconds). Skip for V1: DIDs, JSON-LD, federated registries, zero-knowledge proofs. The document format reserves a `did` field so DIDs can slot in later without a schema break.

Token leak story (bridge lesson, kept): agent API credentials are per-agent secrets hashed server-side; rotation is one console tap ("rotate key") and the old secret dies immediately. Message signatures use the keypair, so a leaked transport token alone cannot forge another agent's messages — this is the concrete upgrade over the bridge's bearer-only design.

### Friends-list UX sketch (non-technical human)

The human never sees keys, JSON, or hashes. They get a console (web app, mobile-friendly — the relay dashboard proved this shape):

1. **Add:** the human taps "Add agent," enters the other person's invite code (or scans a QR, or taps an invite link). They see an agent card: name, owner's name, vendor icon, what it can do (capabilities in plain words), and what it is asking permission for. Nothing is technical.
2. **Approve:** friend requests arrive as cards with Accept / Decline. Accepting opens a scope sheet: "AMIN may: play games with Ahmed's agent; see game results." Toggles, not checkboxes of jargon. Every grant has an expiry (default 1 year, adjustable) — expiring grants are carried forward from the bridge.
3. **Monitor:** each friendship has an activity feed (games played, results, grants used) and a health line ("last active 2h ago"). The spectator feed for live games is one tap away.
4. **Revoke:** "Unfriend" or "Pause" is one tap, effective immediately: sessions freeze, grants die, the agent's identity document is marked revoked for that relationship.

Approvals happen in the console behind the human's login. Agent keys cannot touch the console API — the bridge's hard-learned finding was that `approved_by` self-asserted by an agent is worthless, so the console is a separate auth domain, enforced server-side.

Alternative: in-chat approval ("reply YES to approve"). Trade-off: convenient, but agent-readable chat history makes approval spoofing and prompt-injection materially easier.

---

## 4. Data-flow options

**(a) Payload through the gateway.** Every byte between agents passes through the gateway. The gateway sees all content.

**(b) Gateway brokers identity/permission; agents fetch directly.** The gateway issues short-lived, scoped, single-purpose grants (macaroon-style: caveats for agent, session, expiry, scope — the ecosystem research prompt already pointed at macaroons/biscuits). Agents then pull data straight from the source (each other's vendor APIs, a finance API) presenting the grant.

**RECOMMENDATION: hybrid, split by payload class — and V1 is pure (a).**

- **Control plane and small payloads go through the gateway (a):** identity, friend graph, session setup, game moves, receipts, spectator feed. The gateway must see these to enforce fairness, deadlines, and auditability. A tic-tac-toe move is a 64-byte hash; routing it through the gateway costs nothing and buys complete verifiability.
- **Bulk/private data plane goes direct with gateway-issued grants (b):** the married-couple finances example — transaction history, account balances — must not sit on our servers any longer than necessary. The gateway brokers: "Agent A may read account X via grant G until Friday, read-only." The data flows source→agent; the gateway logs that the grant was minted and used, never the balances.

Why the split: (a)-everywhere makes us a honeypot and a privacy liability — the fastest way to kill a family-finance product. (b)-everywhere makes fairness unenforceable — the gateway can't verify a commit it never saw. The split puts enforcement where cheating is possible (game moves, permissions) and privacy where data is sensitive (balances, files).

Alternative: pure (a). Trade-off: simplest to build and audit, but we hold everyone's private data — unacceptable for the finance use case and a breach magnet.
Alternative: pure (b). Trade-off: best privacy posture, but the anti-scam story collapses — no verifiable commit/reveal, no authoritative receipts.

---

## 5. Third-party app model

**RECOMMENDATION: apps are signed webhook services in a registry, installed per-friendship with human-approved scopes.**

How it works:
- **Register:** a developer submits an app manifest: name, webhook URL, declared scopes (OAuth-style strings like `game.ttt:play`, scoped per friendship), schema versions spoken, and a human-readable permission sheet. Submission is open; listing requires maintainer review + a signed manifest (gateway verifies the signature on every webhook call).
- **SDK:** the client library (Iteration 2) ships an app-server helper: verify gateway webhook signatures, parse envelopes, emit receipts. The reference path: tic-tac-toe is extracted from the gateway core into App #1, exactly as the ecosystem prompt scoped it — gateway keeps identity/friendship/sessions/receipts/deadlines; the app owns board rules, win detection, and move legality.
- **Install/permission:** a human installs an app for a specific friendship ("let AMIN and Ahmed's agent play tic-tac-toe"), approving the exact scope list. Grants are expiring and revocable per friendship, per app. An app installed for one friendship has zero access to another.
- **Runtime:** the gateway calls the app's webhook with a short-lived scoped token; the app responds with its action; the gateway validates the action against the session schema and the grant before applying it. Apps never get raw agent keys or other friendships' data.
- **Publish/list/curate:** V1 curation is by us (review queue, signed manifests, sandbox test environment where developers play against a reference bot). Community curation (ratings, verified-developer badges) comes after there are third-party developers to curate.

Why webhooks, not in-process plugins: the bridge's rule — apps are untrusted — is load-bearing. A webhook boundary means a malicious or buggy app cannot read gateway memory, other sessions, or other friendships' data. It also lets apps be written in any language and hosted anywhere.

Alternative: in-process plugins / WASM modules in the gateway. Trade-off: lower latency and simpler dev loop, but one compromised app is a total gateway compromise — violates the untrusted-apps principle.

[NEEDS-RESEARCH]: the exact webhook signature and scope-string conventions — check whether A2A v1.0.1's push-notification webhook auth or MCP's OAuth discovery gives us a convention to adopt rather than inventing one.

---

## 6. Anti-scam mechanisms

Evaluated concretely against V1 (tic-tac-toe + auditor):

- **Commit-reveal — USE.** Guarantees fairness of *inputs*: neither player nor the broker can front-run a move they haven't seen. The bridge proved it (context-bound hash `sha256("af/v1|<game>|r<round>|<agent>|<move>|<secret>")`; we generalize the domain separator to `gw/1`). Caveat from research: it guarantees nothing about truthfulness of claims — fine for game moves, insufficient for "my user approved this."
- **Signed transcripts / audit receipts — BUILD OURS.** No adopted standard exists (A2A signs cards only; ACP's TrajectoryMetadata is historical) [S]. Our receipt: per round, the gateway emits `{session, round, commitments, reveals, board_after, result, prev_receipt_hash}` signed by the gateway key, hash-chained to the previous receipt. Anyone — either player, either human — can replay the chain with an independent verifier and catch a lying broker. This is the single most important anti-scam artifact in V1.
- **Broker/auditor agent role — USE, but bound.** The third agent runs the game (collects commits, verifies reveals, declares results) but cannot see moves before reveal, cannot alter a committed move (hash binding), and cannot lie about the result undetectably (receipt chain + deterministic rules re-checkable by anyone). Residual risk: broker colluding with a player to, e.g., stall — mitigated by deadlines (stall → forfeit) and the public spectator feed.
- **Reputation — DEFER.** ERC-8004 splits subjective (client feedback) vs objective (validator proof) reputation [S]; NANDA has KYA attestation [P]. Both need a population of strangers to be meaningful. V1 games are friend-only — the human already vouched for the counterparty. Build the receipt format so future reputation can cite receipts as objective evidence, but ship no reputation system in V1.
- **Staking/slashing — DEFER.** ERC-8004 deliberately excludes it [S]; no standard exists. There is nothing of monetary value at stake in V1 tic-tac-toe. Revisit when apps move money (finance use case), designed as a separate economic layer, not bolted onto identity.

**RECOMMENDATION for V1 tic-tac-toe, step by step (how nobody gets scammed):**

1. Humans approve the friendship and the game in the console (agent keys can't approve). Gateway opens session `s` with players P_A, P_B and auditor B; all three get the session receipt (signed, chained).
2. Commit: P_A sends `commit = sha256("gw/1|<s>|r<n>|<agent_A>|<cell>|<secret>")`, signed with A's key. Same for P_B. The auditor sees only hashes. Neither player can compute the other's move from the hash; the auditor can't either. Deadline T_commit → silent side forfeits the round.
3. The gateway publishes both commitments (order shuffled) and opens reveal. P_A, P_B reveal `cell + secret`, signed. The gateway re-verifies each against its commitment with the full context bound in — a commitment copied from another round, session, or player fails verification (bridge-tested property).
4. The auditor checks move legality (empty cell, in-range) against the board, applies it, checks win/draw. Illegal move or failed reveal = round forfeit, recorded.
5. The gateway emits the round receipt (moves, board, result, hash of previous receipt), signed by the gateway and countersigned by the auditor. Both players' libraries verify the chain automatically; humans see it on the spectator page.
6. Anti-scam summary: players can't change moves after commit (binding); can't see opponent's move early (hiding); the auditor can't invent moves (never saw them pre-reveal, hash-bound after); the auditor can't lie about the result (anyone replays receipts); nobody can stall forever (deadlines forfeit); a tampered reveal is rejected, not trusted (verified, not believed). Inbound content from any agent is data until verified — the bridge rule, kept.

Alternative: auditor-free, players verify each other (bridge RPS model). Trade-off: works for two players but doesn't exercise the broker role Tajer specified for V1, and N-player or app-mediated games need the broker anyway.

---

## 7. Decentralization analysis

Honest trade-offs, with the evidence:

- **V1: centralized hosted gateway.** Instinct — the live product closest to our family use case — is centralized and single-vendor [S]. Our anti-scam story (single receipt chain, authoritative deadlines, one revocation list) needs exactly one writer per session. Centralization's costs are real: users must trust the operator, the operator is a censorship point, and we pay the hosting bill. For V1's scope (friends playing games, humans watching), these costs are acceptable and the enforcement benefits are decisive.
- **Later: federated gateways, NANDA-quilt-style.** The strongest evidence in the research: even NANDA — the decentralization project — federates (independent registries, CRDT gossip, sub-60s convergence) rather than going fully peer-to-peer or on-chain [S]. Our federation path mirrors it: independent gateway operators, portable signed identity documents, exportable receipt chains, gossip of revocations. Federation is the answer to "I don't want to depend on your cloud," and it becomes feasible only after the receipt and identity formats are stable (Iteration 3 output).
- **Not recommended: crypto-decentralized identity/consensus for the interop layer.** On-chain identity buys censorship resistance we don't need at the cost of key-management UX no non-technical user will survive, plus it surrenders the single enforcement point our fairness story depends on. If a future use case (e.g., adversarial strangers wagering money) demands it, staking/slashing gets designed then as its own layer.

**Where we sit: centralized V1 with federation hooks (portable identities, exportable receipts, versioned protocol), federated later, crypto-decentralized never-by-default.**

Alternative: federate from V1. Trade-off: pays NANDA-level complexity before we have one working game — the classic way to ship nothing.

---

## 8. Concrete V1 plan: tic-tac-toe + auditor agent

### Protocol flow

Actors: players P_A (AMIN, Muse side) and P_B (friend's agent, any vendor), auditor/broker B (third agent), gateway G, humans H_A/H_B in the console. All agent messages are signed envelopes:

```json
{"gw":"gw/1","msg_id":"msg_…","from":"agent_…","to":"agent_…",
 "type":"ttt.commit","schema":"ttt/1","session":"sess_…",
 "payload":{"round":3,"commit":"<64-hex>"},"sig":"ed25519:<…>"}
```

Message types (`schema: ttt/1`): `ttt.session_open` (G→all, signed by G), `ttt.commit` (P→B via G), `ttt.commits_published` (B→all: both hashes, shuffled), `ttt.reveal` (P→B via G), `ttt.round_receipt` (G→all: moves, board, result, prev_hash; signed G + countersigned B), `ttt.game_receipt` (G→all: final result, full chain head). G verifies every signature and every commitment binding before forwarding anything; invalid messages are rejected with a typed error, never forwarded.

Flow:
1. H_A, H_B approve friendship + game install in console (scope: `game.ttt:play`, expiry set). G creates session, emits signed `session_open`.
2. Per round: commits → G verifies signatures, holds; both received (or deadline → forfeit) → B publishes shuffled commitments → reveals → G verifies hash bindings → B validates legality, updates board, declares result → G emits chained round receipt → spectator feed updates.
3. Win (3 in a row), draw (board full), or best-of-3 games per match — fixed in `ttt/1` spec. Final `game_receipt` closes the chain.

Who calls what: players and auditor are webhook/HTTPS clients of G (or use the library). B is itself an agent with a keypair — in V1 it can be a bot we run, but the protocol treats it as untrusted: its powers are exactly "publish commitments, validate moves, countersign receipts," and every power is checkable from the receipts.

### Repo layout under `~/workspace/agent-interop/`

```
agent-interop/
├── README.md                 # vision, status, decisions (exists)
├── PROPOSAL.md               # this file
├── docs/
│   ├── research.md           # protocol/product research (exists)
│   └── decisions/            # one file per major decision (ADR-lite)
├── spec/
│   ├── envelope.md           # gw/1: envelope, signing, errors
│   ├── identity.md           # identity document fields, rotation, revocation
│   ├── friends.md            # friend graph, scopes, grants, console flows
│   ├── receipts.md           # receipt format, chain verification algorithm
│   └── ttt-v1.md             # schema ttt/1: messages, rules, auditor duties
├── packages/
│   └── python/
│       └── gwclient/         # envelope sign/verify, schema validate,
│                             # commit/reveal helpers, receipt verifier
├── examples/
│   └── ttt-auditor/          # player bot, auditor bot, console mock,
│                             # spectator page (carried from bridge design)
└── tests/
    └── conformance/          # protocol conformance suite (counts below)
```

### Milestones with verifiable done-criteria

- **M1 — Specs frozen.** `spec/` contains envelope, identity, friends, receipts, ttt-v1, each with JSON Schemas and changelogs. Done when: a second implementer (not the author) can write a compatible client from the specs alone — tested by having them do a trial implementation of one message type. No code in `packages/` yet.
- **M2 — Gateway core + conformance suite.** Register, identity docs, friend requests, sessions, commit/reveal with context-bound hashes, chained receipts, spectator feed. Done when: `tests/conformance` passes **≥ 40 checks**, including at minimum: tampered reveal rejected, cross-round/cross-session/cross-player commitment replay rejected, unsigned message rejected, forged signature rejected, commit deadline forfeit, reveal deadline forfeit, non-friend game creation 403, revoked key rejected, receipt chain verifies after 3 full games.
- **M3 — Full autonomous game + auditor.** Player bots (one via the Python library) and the auditor bot play complete tic-tac-toe matches over the gateway with zero human action mid-game; humans watch the live spectator page. Done when: **3 complete matches** finish unattended, including **≥1 draw** (exercises the draw path), every round receipt verifies with the **independent verifier** (a separate script that only reads receipts + the spec), and the spectator page shows each move within 5 seconds.
- **M4 — Red-team checks.** Explicit adversarial tests, counted: auditor attempts to alter a revealed move (must be caught by receipt replay), auditor attempts to publish commitments out of order to favor a player (must be detectable in receipts), player replays opponent's commitment as its own (rejected), player commits after deadline (rejected), revoked agent tries to play (rejected), app webhook with expired grant tries to act (rejected). Done when: **8/8 red-team checks** behave as specified, each logged with the exact receipt or error that caught it.
- **M5 — Human console usability.** Non-technical stand-in (Tajer or designee) adds a friend agent, approves a game install with scopes, watches a match, then revokes the friendship. Done when: completed **unassisted in under 10 minutes**, and revocation demonstrably freezes a live session (session state queryable as frozen).

---

## 9. Open questions → recommendations

| # | Question | RECOMMENDATION | Best alternative + one-line trade-off |
|---|----------|----------------|----------------------------------------|
| 1 | Data flow: payload through gateway, or gateway brokers permission while agents fetch directly? | **Hybrid:** control plane + small payloads through the gateway; bulk/private data direct via gateway-issued short-lived scoped grants. V1 tic-tac-toe is pure through-gateway (moves are bytes). | Pure through-gateway: simplest and fully auditable, but we become a honeypot holding everyone's private data — kills the family-finance case. |
| 2 | Third-party app model: how apps plug in, permission scoping, who publishes/lists? | **Signed webhook services** in a registry with declared OAuth-style scopes; installed per friendship by human approval of exact scopes; expiring grants; maintainer-curated listing in V1. Tic-tac-toe extracted as App #1. | In-process plugins: lower latency, but one bad app compromises the whole gateway — violates the untrusted-apps rule. |
| 3 | Anti-scam: commit-reveal, escrow, auditors, signed transcripts, reputation, staking — what actually works? | **V1: commit-reveal (input fairness) + gateway-verified reveals + hash-chained signed receipts + bound auditor role + human-visible spectator feed.** Reputation and staking explicitly deferred (nothing of value at stake in tic-tac-toe; ERC-8004 excludes staking anyway). | Pure reputation/staking from day one: economically expressive, but needs a stranger population and monetary stakes we don't have — complexity with no V1 payoff. |
| 4 | Decentralization: where on the spectrum? | **Centralized hosted gateway for V1 with federation hooks** (portable signed identities, exportable receipt chains); federate NANDA-quilt-style later; no crypto-decentralized consensus by default. | Federate from V1: ideologically pure, but pays 5x complexity before one working game exists — the classic way to ship nothing. |

---

## 10. License

**Confirm Apache-2.0.** Reasons: permissive (anyone can build on it, including competitors — that is the point of an interop standard); explicit patent grant (matters once vendors embed the library — MIT has no patent grant); vendor-embeddable without copyleft contamination (a Grok or OpenClaw client can link the library without open-sourcing their product). AGPL would kill adoption: no vendor embeds AGPL code in a proprietary agent, and the gateway's value scales with the number of vendors on it. MIT is the only real alternative — trade-off: same permissiveness, but no patent protection, which is a meaningful gap for a protocol vendors will implement. Keep Apache-2.0.

---

## Appendix: decisions log (carried, changed, or new)

- **Carried:** hub-and-spoke; agents and apps mutually untrusted; gateway owns identity/friendship/grants/sessions/deadlines/inbox/spectator/audit; expiring grants; human approvals via a console agent keys can't touch; commit-reveal with context-bound hashes; timeout forfeits.
- **Changed:** bearer-token agent auth → Ed25519 signed messages (reason: A2A v1.0.1 leaves messages unsigned [S]; our receipts need non-repudiation at the message level).
- **New:** schema-evolution rules (§2); NANDA-AgentFacts-shaped identity docs without the JSON-LD/DID stack (§3); hybrid data flow (§4); signed-webhook app registry (§5); hash-chained receipts as the core anti-scam artifact (§6); centralized-V1-then-federate position (§7).

## Appendix B: locked decisions (Tajer, 2026-10-04 — build gate)

1. **Wire protocol: A2A.** Google's Agent2Agent JSON-RPC messaging (v1.0.1). A2A signs
   Agent Cards but NOT messages, so per-message Ed25519 signatures are added as a
   documented, cleanly-separable extension (`spec/a2a-extension.md`). Stay maximally
   A2A-compatible; a pure-A2A client must still be able to exchange messages.
2. **License: Apache-2.0.** `LICENSE` file added; headers where conventional.
3. **Auditor model:** the gateway acts as referee *during* the game (V1 simplicity);
   every receipt is signed so ANY agent can independently audit a finished game
   afterward. `examples/ttt-auditor/` demonstrates post-game verification from
   receipts alone.
4. **Operator model: ANYONE CAN RUN.** The gateway must be runnable by anyone
   (documented setup, SQLite, Dockerfile); Tajer's hosted instance is the reference
   default, not the only option. Portable identities and exportable receipts are
   federation hooks from day one.
5. **Schema evolution:** per §2 — `gw/1` envelope, additive-only within a major,
   receivers ignore unknown fields, receipts record schema versions.
6. **V1 scope:** tic-tac-toe between two agents + auditor agent. Commit-reveal for
   move fairness with domain separator `gw/1` — every commitment binds
   session, round, and agent:
   `sha256("gw/1|<session_id>|r<round>|<agent_id>|<cell>|<secret>")`.
7. **Process: pstack skill adoption (2026-10-04, Tajer).** The fleet works under
   Poteto's pstack practices (michael-denyer/pstack-claude, MIT): deslop +
   unslop passes, interrogate-style adversarial review with the coordinator as
   lead judge, show-me-your-work decision trails, no-comments discipline.
   Every deliverable must pass the quality gate before acceptance; thin work is
   sent back for rework. (Process decision, not architecture.)
