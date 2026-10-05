# Agent Interop — Public-Web Research Report

Research worker deliverable. All research from public web sources; no code, sign-ins, or external messages.
Date: 2026-10-04.

Source-confidence legend used throughout: **[P]** = verified from a primary source (official site, official repo/paper), **[S]** = from secondary reporting, **[U]** = could not verify / single uncorroborated source.

---

## Executive summary

- MIT's Project NANDA is real and verified: "Networked AI Agents in Decentralized Architecture," led by Prof. Ramesh Raskar (Camera Culture, MIT Media Lab), with arXiv papers on an agent index + cryptographically verifiable "AgentFacts." It is the closest existing work to our gateway concept.
- Google's A2A (v1.0, now under the Agentic AI Foundation) is the production agent-to-agent messaging standard (150+ orgs); MCP is the agent-to-tool standard (donated to the same foundation Dec 2025). Borrow both; neither defines the "friends list" discovery/identity layer — that's NANDA's niche.
- AGNTCY (Cisco → Linux Foundation) is a sprawling, still-shifting stack whose own "Agent Connect Protocol" spec repo was archived Apr 2026 — avoid as a foundation.
- Correction: "Transport Pi" doesn't exist as a product. Pi is Mario Zechner's open-source *coding-agent harness* (pi-mono); "pi transport" is an internal config label. Not Inflection AI's Pi.
- "Dots" is almost certainly New Computer's Dot companion app — which shut down Oct 2025. Family members can't have Dots anymore.
- "Instinct" is the hottest personal-agent product in the world right now (Spear Street Technology, $1B raised at $10B valuation on 2026-09-28) and just launched a **Trusted Person Network**: an Instinct-to-Instinct agent protocol for exactly our family-coordination use case. It is proprietary and single-vendor — the market opening for our cross-vendor gateway.
- Trust primitives exist piecemeal: commit-reveal (textbook crypto), ERC-8004 (on-chain identity/reputation/validation registries — Draft EIP), AP2 (signed consent mandates for payments), x402 (pay-per-use over HTTP 402). No standard agent escrow found; ERC-8004 deliberately excludes staking/slashing.
- NANDA's own architecture is *federated, not fully decentralized* (a "Registry Quilt" of federated registries with CRDT sync). That is itself evidence that full decentralization is a v-later concern.

---

## A. MIT Project NANDA — deep dive

**What it is.** NANDA = **"Networked AI Agents in Decentralized Architecture"** [P] — an open infrastructure initiative for an "Internet of AI Agents" / "Open Agentic Web." It is run by **Project NANDA at the MIT Media Lab**, founded and led by **Prof. Ramesh Raskar** (Associate Professor, MIT Media Lab; director of the Camera Culture research group) [P]. Research portal at nanda.mit.edu, open-source site at projectnanda.org, developer sandbox "NandaTown" [S].

**Position in the stack.** NANDA explicitly does *not* define agent-to-agent messaging. It is the discovery + federation layer that sits above messaging protocols: it builds on MCP and A2A (Google's A2A described by Raskar as the "roads," the NANDA Index as "the directory of houses and businesses") and also supports NLWeb [S]. The three-phase roadmap: (1) Index (discovery/registry), (2) Protocol (communication/teaming), (3) Economy (markets, pricing, co-learning) [S].

**Core artifacts.**

- **NANDA Index** — a federated name-resolution system where agents register and are discovered; described as "DNS for agents." Hosted at ~15 universities and partner institutions [S].
- **AgentFacts** — JSON-LD documents signed as **W3C Verifiable Credentials** describing an agent's capabilities, endpoints, reputation, and identity. Formal, versioned schema (fields: ID, AgentName, Endpoints, UsageFormat, Certification, Capabilities, Discovery, Security) [P]. A2A Agent Card is treated as an embeddable subset ("AgentFacts is a superset of the Agent Card") [P]. Two hosting schemes: PrimaryFactsURL (on the agent's domain) and PrivateFactsURL (third-party hosted, privacy-preserving) [P].
- **Registry Quilt** — federation of multiple registries using CRDT gossip (sub-60s convergence); each org can host its own registry, stitched into one discoverable fabric [S].
- **KYA (Know Your Agent)** — protocol for third-party attestation and reputation [S].
- **ZTAA (Zero Trust Agentic Access)** — introduced in the enterprise paper: never-trust-always-verify for agent sessions, plus AVC (Agent Visibility & Control) for enterprise governance [S].

**Trust/security design.** AgentFacts bind cryptographic signatures to capability assertions; revocation/key rotation via VC-Status lists targeted at sub-second latency; privacy-preserving discovery via verifiable, least-disclosure queries [P]. Identity is W3C VC/DID-flavored, not a blockchain-first design [P/S].

**Papers (all arXiv preprints unless noted).**

1. Raskar, R., Chari, P., Zinky, J., Wang, S., Singhal, R., Lincourt, R., Lambe, M., Grogan, J.J., Ranjan, R., Gupta, S., Bala, R., Joshi, A., Singh, A., Chopra, A., Stripelis, D., Bhuwan, B., Kumar, S., Gorskikh, M. — "Beyond DNS: Unlocking the Internet of AI Agents via the NANDA Index and Verified AgentFacts." arXiv:2507.14263 (Jul 2025). MIT Media Lab publication page also hosts it [P].
2. "Collaborative Agentic AI Needs Interoperability Across Ecosystems." arXiv:2505.21550 (May 2025) [P].
3. "Using the NANDA Index Architecture in Practice: An Enterprise Perspective." arXiv:2508.03101 (Aug 2025) — introduces ZTAA and AVC [S; from the projnanda GitHub README, which links the arXiv ID].
4. "A Survey of AI Agent Registry Solutions." arXiv:2508.03095 (Aug 2025) — compares MCP registry, A2A Agent Cards, Microsoft Entra Agent ID, and NANDA [S; same source].
5. "NANDA + ANS Security Blueprint: A Federated Registry Architecture for Secure, Capability-Aware Agent Discovery" (v0.2, repo-hosted PDF) — dual-trust anchoring with the Agent Name Service (ANS), zero-knowledge proofs, modular governance [P: listed in the aidecentralized/projnanda repo].

**Repos/code.** GitHub org `aidecentralized`: `projnanda` (docs/demos), `nandapapers` (papers), `nanda-quilt-of-registries-and-verified-agentfacts` (paper + README formalizing the AgentFacts schema and CRDT update protocol) [P]. Community SDKs exist (e.g., Nexartis' TypeScript "Homeport" implementation of the NANDA protocol, Apache-2.0) [S]. Live demos: join39 (personal agent directory, 1,000+ agents listed) and List39 (Agent Facts Registry) [S].

**Relevance to our gateway.** NANDA is the single best reference for the discovery/identity half of our gateway: versioned signed capability documents (AgentFacts), a friends-like registry concept (Join39 is literally "register your agent, get discovered"), and federated rather than monolithic infrastructure. The NANDA Index + AgentFacts pattern maps directly onto our open question of "identity + discovery," while A2A covers the messaging half.

Sources:
- https://thenewstack.io/how-mits-project-nanda-aims-to-decentralize-ai-agents/ (The New Stack) [S]
- https://www.media.mit.edu/publications/beyond-dns-unlocking-the-internet-of-ai-agents-via-the-nanda-index-and-verified-agentfacts/ (MIT Media Lab) [P]
- https://arxiv.org/pdf/2507.14263.pdf (arXiv) [P]
- https://github.com/aidecentralized/projnanda (GitHub org) [P]
- https://github.com/aidecentralized/nanda-quilt-of-registries-and-verified-agentfacts/blob/HEAD/README.md (schema spec) [P]
- https://github.com/awebai/a2ac/blob/HEAD/projects/nanda.md (third-party summary of layers) [S]
- https://luma.com/umtvs1uk (Raskar bio / acronym expansion) [S]

---

## B. Adjacent standards

### 1. Google's A2A (Agent2Agent)
Covers **peer-to-peer agent messaging/collaboration** (the "transport + semantics" layer for agent↔agent work), not discovery or identity. Spec: v1.0.0 released 2026-03-12, v1.0.1 on 2026-05-28; canonical Protocol Buffers schema with three bindings (JSON-RPC 2.0, gRPC, HTTP+JSON REST); discovery via Agent Cards at `/.well-known/agent-card.json`; task lifecycle with 8 states, SSE streaming, push webhooks, multi-tenancy `tenant` field. Trust model: **JWS-signed Agent Cards only — messages, parts, and artifacts carry no signature**, so it proves "who published the card" but not "who sent this message." Governance: announced Apr 2025 by Google, donated to the Linux Foundation (Jun 2025); moved again to the **Agentic AI Foundation (Aug 2026)**. Adoption is real: 150+ organizations, production use at Microsoft, AWS, Google (as of Apr 2026), 5 production SDKs. **Verdict: BORROW** — it is the production wire protocol for our V1 tic-tac-toe agents (and the third-agent auditor) to actually talk. One line why: it's the only agent-to-agent messaging spec with real enterprise adoption and signed discovery cards, and its gaps (unsigned messages) are exactly what our broker/auditor layer should add.

Sources: https://github.com/pete-builds/writ-protocol/blob/HEAD/docs/research/02-prior-art.md · https://github.com/technicalpickles/a2a-experiments/blob/HEAD/docs/pass-1-a2a-protocol.md · https://github.com/byterefinery/skills/blob/HEAD/.agents/skills-byterefinery/a2a/SKILL.md — all [S].

### 2. Anthropic's MCP (Model Context Protocol)
Covers **agent↔tool/context** integration (client-server; the "USB-C for AI tools"): tools, resources, prompts over JSON-RPC 2.0 (stdio, Streamable HTTP). Not agent-to-agent. Spec is date-versioned; current stable is **2025-11-25** (adds OAuth authorization-server discovery, server identity via `.well-known`, experimental Tasks for durable requests, JSON Schema 2020-12 default). An official MCP Registry (federated metaregistry) launched Sep 2025. Governance: **donated by Anthropic to the Agentic AI Foundation (Linux Foundation) Dec 2025**, co-founded by Anthropic, Block, and OpenAI — vendor-neutral now. Adoption is the deepest of any protocol here (OpenAI, Google DeepMind, Microsoft all integrate). Trust model: minimal — it defines wire format; authZ policies are the application's job, and tool descriptions/returned content can be malicious. **Verdict: BORROW** — as our agents' tool-access layer (V1 agents will need tools through MCP servers), but **not** as the agent-to-agent protocol itself. One line why: wrong layer for peer messaging, but it's the de-facto standard for giving agents tools and its registry work is directly instructive for our friends list.

Sources: https://hidekazu-konishi.com/entry/mcp_specification_version_timeline.html · https://dev.to/mohamed_fysil_9ba38502093/history-of-the-model-context-protocol-mcp-3n1g — [S].

### 3. AGNTCY (Cisco / Linux Foundation "Internet of Agents")
Not a single protocol — a **full infrastructure stack**: OASF (Open Agent Schema Framework, agent descriptions as OCI artifacts — a superset of A2A cards covering MCP servers too), Agent Directory (discovery, Kademlia DHT), SLIM (gRPC messaging with MLS/post-quantum crypto), DID-based identity, observability. Launched by Cisco's Outshift Mar 2025, donated to the Linux Foundation Jul 2025 with 70–75+ companies. Warning sign: its own **"Agent Connect Protocol" spec repo (`agntcy/acp-spec`) was archived Apr 11, 2026** — the connect-protocol piece appears to be folding into A2A [S]. Trust model: aspirations across DIDs/VCs and MLS, but the identity layer is described as less mature than messaging/discovery, and pieces overlap confusingly (ACP vs A2A vs SLIM). **Verdict: AVOID** as a foundation for now. One line why: too broad, still in flux, and its messaging piece is being subsumed by A2A — borrow nothing except OASF's schema-as-artifact idea if our AgentFacts-equivalent needs versioning later.

Sources: https://github.com/awebai/a2ac/blob/HEAD/projects/agntcy.md · https://linux.slashdot.org/story/25/07/29/2053245/cisco-donates-the-agntcy-project-to-the-linux-foundation · https://github.com/coilysiren/otel-a2a-relay/blob/HEAD/docs/protocols-survey-agntcy.md — [S].

### 4. Agent Protocol (AI Engineer Foundation)
Covers the narrow **client→agent execution** layer: a REST/OpenAPI API for hosting one agent as a service, with primitives **Tasks, Steps, Artifacts** (plus Threads/Store in some variants) and SDKs (Python/TS). From `AI-Engineer-Foundation/agent-protocol` (schemas: `/ap/v1/agent/tasks`, step lifecycle) [P]. Note: don't confuse with IBM/BeeAI's **ACP (Agent Communication Protocol)** with TrajectoryMetadata — that one merged into A2A in Aug 2025 and is now historical [S]. Trust model: none specified — it's a server API shape, not a trust framework. Adoption: developer-niche; overshadowed by A2A for peer interop. **Verdict: AVOID.** One line why: it's a hosting API for one agent, not an interop protocol — it solves neither cross-vendor messaging nor discovery nor identity.

Sources: https://github.com/ai-engineer-foundation/agentprotocol.ai/blob/HEAD/src/app/endpoints/page.mdx [P] · https://jtanruan.medium.com/open-standards-for-ai-agents-a-technical-comparison-of-a2a-mcp-langchain-agent-protocol-and-482be1101ad9 [S].

---

## C. Named products

### "Pi" / "Transport Pi"
The earlier note was half-right. **Pi is Mario Zechner's (badlogic's) open-source "Pi Agent Harness"** — a minimal terminal coding-agent harness (repo `badlogic/pi-mono`, now moved to `earendil-works/pi`), MIT-licensed, with `pi-coding-agent` CLI, `pi-agent-core` runtime, `pi-ai` unified multi-provider LLM API, an extension system, and a documented `pi --mode rpc` (stdio JSONL) mode for driving it programmatically [P/S]. It is **not** Inflection AI's consumer chatbot Pi. **"Transport Pi" does not exist as a product or protocol.** The phrase appears only as an internal config label in the pi ecosystem: `providerType: pi` — "Pi's native transport" for how the harness reaches LLM providers (vs `pi_compat` for OpenAI/Anthropic-compatible HTTP endpoints) [S]. Correction: drop "Transport Pi" from the plan; interop-wise pi is relevant only as a self-hosted harness with an RPC seam and extension API, not as a protocol owner.

Sources: https://github.com/badlogic/pi-mono [P] · https://github.com/geiserx/unsent/blob/HEAD/docs/research/pi.md [S] · https://github.com/imrj05/orbit/blob/HEAD/INTENT.md (RPC mode) [S] · https://github.com/limboinf/bitlab-agent/blob/HEAD/docs/connections.md ("pi transport" config label) [S].

### OpenClaw
Verified real and large. Open-source (MIT) **self-hosted personal AI assistant** by Peter Steinberger (originally Warelay, then Clawdbot/Moltbot after an Anthropic trademark complaint, renamed OpenClaw Jan 2026); now stewarded by the nonprofit **OpenClaw Foundation** (Steinberger joined OpenAI Feb 2026); ~247k GitHub stars by Mar 2026 [S]. Architecture: one long-lived local **Gateway** process routing between chat channels (WhatsApp/Telegram/Discord/Slack/Signal/iMessage/Matrix…) and model providers [P/S]. Interop-relevant interfaces: **MCP integration surface**, **webhook receiver** (inbound trigger automation), a **Gateway WebSocket protocol** for custom clients, the AgentSkills platform + ClawHub community registry, and a "Lobster" workflow engine [S]. Model: user self-hosts; multi-channel by design but no cross-vendor *agent-to-agent* protocol claimed. Relevant as a gateway-architectural peer: it proves the "single gateway process bridging chat channels" pattern at scale.

Sources: https://github.com/steviebuchicago/getting-started-with-openclaw/blob/HEAD/docs/01-what-is-openclaw.md · https://gizmodo.com/best-web-hosting/openclaw-vs-hermes · https://github.com/crs48/xnet/blob/HEAD/docs/explorations/0098_%5B_%5D_OPENCLAW_INTEGRATION.md (interface list) — [S].

### "Dots"
**Most likely New Computer's "Dot" — and it no longer exists.** Dot was an iOS AI companion ("friend and confidante") by San Francisco startup New Computer (Sam Whitmore, Jason Yuan), launched 2024; the company **announced its shutdown on 2026-09-05 [U: year ambiguous in reporting — TechCrunch article dated 2025-09-05] with service ending Oct 5**. No public API or interop surface was ever offered. If the intent was family members having Dot agents, that product is dead. (No other plausible "Dots" agent product surfaced; marking alternative candidates as unidentified rather than guessing.)

Sources: https://techcrunch.com/2025/09/05/personalized-ai-companion-app-dot-is-shutting-down/ [S].

### "Instinct"
**Real, and the most strategically relevant product found.** Instinct is an invite-only personal AI agent from San Francisco's **Spear Street Technology**, founded by 23-year-old **Noah Shinn** (lead author of the 2023 NeurIPS "Reflexion" paper; ex-Sierra) [S]. Interface: you text/call it (iMessage/WhatsApp/phone); it runs its own cloud computer + phone, connects to email/calendar/messages, and acts (booking, groceries, bills, subscriptions) — free during beta, payments via Stripe Link one-time cards [S]. Funding: **$1B Series C at a $10B valuation on 2026-09-28** (Sequoia, Benchmark, Coatue) [S]. Interop-relevant: on **2026-09-09 it launched the "Trusted Person Network," described as an Instinct-to-Instinct communication protocol** — two users' agents coordinate directly (scheduling, shared to-dos, E2E-encrypted file swaps), gated to trusted contacts with configurable access levels (e.g., spouse sees everything, colleague sees only a work calendar) [S]. This is a live, consumer-deployed instance of exactly our family-use-case — but **proprietary, single-vendor, invite-only, with no public protocol spec found**. Our gateway's cross-vendor, open version of the Trusted Person Network is the market gap.

Sources: https://thetechportal.com/2026/09/28/instict-ai-agent-startup-1-billion-funding-valuation/ · https://thenyledger.com/markets/couples-are-using-a-viral-ai-agent-to-do-their-emotional-labor-its-been-helpful-and-chaotic/ · https://www.eesel.ai/blog/instinct-ai-review · https://pjfp.com/noah-shinn-instinct-personal-ai-assistant-10-percent-a-day/ · https://cellcog.ai/blog/what-is-instinct-ai/ — [S].

---

## D. Anti-scam / trust primitives in the wild

1. **Commit-reveal.** The textbook primitive for games/fair exchange: commit `hash(value, nonce)` first (hiding + binding), reveal later. Standard crypto (Blum 1982 coin-flipping lineage), used widely in smart contracts [P]. Directly applicable to our V1 tic-tac-toe if players submit moves through the broker — commit to move, reveal after both committed, so neither player's agent (nor the broker) can front-run. Caveat to brief the planner: commit-reveal guarantees fairness of *inputs*, not truthfulness of *claims*.

2. **Escrow.** No named *agent-to-agent* escrow standard found — honest gap. The building blocks that exist: **AP2 (Google's Agent Payments Protocol**, announced Sep 2025, donated to FIDO Alliance, 60+ orgs) expresses payments as signed **Mandates** (Intent/Cart/Payment — W3C Verifiable Credentials), creating a non-repudiable audit trail of "the human approved this" [S]; **x402 (Coinbase)** reuses HTTP 402 to let agents pay for APIs/resources in stablecoins with no accounts — 100M+ transactions by Q1 2026, AWS/CloudFront integration [S]; classic **smart-contract escrow** (funds locked, released on delivery-or-dispute) is the generic pattern but no agent-specific escrow product was verified [U]. Recommendation to the planner: AP2-style signed mandates are the closest borrow for V1 (proof of authorization), full escrow is a later phase.

3. **Signed transcripts / audit logs.** **IBM/BeeAI ACP's TrajectoryMetadata** (every response carries its reasoning/tool-call chain) was the standout audit-receipt mechanism — but ACP is now historical (merged into A2A Aug 2025) [S]. Closest live equivalents: A2A's **signed Agent Cards** (card-level, not message-level) [S], AP2's mandate chains (payment-scoped) [S], and Instinct's self-reported per-action isolation (sandbox + short-lived credentials + hallucination filter) [S]. Gap: no adopted standard for message-level signed transcripts between agents.

4. **Reputation.** Two live models: **ERC-8004 "Trustless Agents"** (Ethereum EIP, Draft status) defines three on-chain registries — Identity (ERC-721 agent NFT pointing at an A2A-compatible AgentCard), Reputation (client-authorized subjective feedback), Validation (objective validator-recorded proof of work); agent registration files carry a `supportedTrust` array (e.g., `["reputation", "crypto-economic", "tee-attestation"]`) [S]; and NANDA's **AgentFacts + KYA** (off-chain VCs, third-party attestation/certification of capabilities) [P/S]. Both confirm the planner's instinct: reputation only works when split into *who vouches* (subjective) vs *what was proven* (objective).

5. **Staking/slashing.** ERC-8004 **deliberately leaves staking and slashing out of scope** [S]; projects layer it on themselves (e.g., Sigvara's retained `SigvaraStaking` bonds + slashing [S]). No standard exists; treat as a future mechanism, not a borrowable spec.

6. **TEE attestation** (bonus). Remote attestation that an agent ran unmodified code in a Trusted Execution Environment appears as a trust type in ERC-8004's `supportedTrust` [S] and in NANDA's attestation workstream [S] — the strongest available answer to "is the other side really running the model it claims," but requires hardware roots of trust and is a v-later concern.

Sources: https://en.wikipedia.org/wiki/Commitment_scheme [P] · https://github.com/imajus/verdikt/blob/HEAD/docs/roadmap/erc-8004.md · https://github.com/runtimeadmin/sigvara/blob/HEAD/docs/adr/0001-erc8004-as-identity-layer.md · https://eco.com/support/en/articles/13221214-what-is-erc-8004-the-ethereum-standard-enabling-trustless-ai-agents · https://github.com/sperax/erc8004-agents — [S] · https://www.epixelsoft.com/blog/agentic-payments-explained-ai-agent-payment-protocols · https://fintechzoom.com/business/artificial-intelligence/agentic-payments-what-happens/ · https://github.com/Custena/agent-payment-protocols · https://nohacks.co/blog/agent-payments-protocol-60-organizations — [S] · https://cryptoadventure.com/coinbases-x402-crypto-payments-over-http-for-ai-and-apis/ · https://cryptocompass.com/articles/how-x402-turns-a-forgotten-web-status-code-into-payments-for-ai-agents · https://www.banklesstimes.com/articles/2026/06/16/coinbase-aws-integrate-x402-to-enable-ai-agent-payments-on-cloudfront-and-waf/ — [S].

---

## Surprises / corrections

1. **"Transport Pi" doesn't exist.** Pi is Mario Zechner's open-source coding-agent harness (pi-mono → earendil-works/pi), not Inflection's Pi; "transport pi" is an internal LLM-provider config label. Strike it from the plan.
2. **"Dots" are dead.** If that's New Computer's Dot, it shut down Oct 2025 (announced Sep 2025). Family members can't have Dots. Any agent-interop design should assume the companion-agent endpoint is whatever replaces it.
3. **Instinct launched a proprietary Trusted Person Network (Sep 9, 2026)** — a deployed, consumer instance of our exact family-coordination thesis, one month before this research. It's single-vendor and closed. This is both validation and the competitive frame: our cross-vendor, open version is the gap.
4. **NANDA is not decentralized in the crypto sense** — its own design is a *federated* registry quilt (each org hosts its own registry, CRDT gossip syncs them). Even the decentralization maximalists federate. Strong evidence that V1 should be a hosted gateway with federation hooks, not on-chain identity.
5. **A2A deliberately leaves trust out.** Only the Agent Card is signed; messages/artifacts aren't. A2A + NANDA-style identity + a signed-transcript auditor layer is the combination nobody has shipped — that composition is our design space.
6. **ERC-8004 explicitly excludes staking/slashing** from scope. If the planner wants economic security, it must be built as a separate layer.
7. **No standard agent escrow exists.** AP2 (authorization mandates) and x402 (pay-per-use) cover payment trust, not escrow. Flag as a genuine gap, not an oversight.
8. **Governance churn is fast:** in the last 16 months both A2A and MCP moved into the new Agentic AI Foundation (Aug 2026 / Dec 2025), and AGNTCY's own connect protocol was archived (Apr 2026). Pin spec versions in the design doc (A2A v1.0.1, MCP 2025-11-25) rather than "the latest."

---

## What I could not verify

- Instinct's Trusted Person Network internals: no public protocol spec, API docs, or technical paper found — everything above is from founder interviews and secondary reporting. Its trust model, crypto, and anti-abuse design are undisclosed [U].
- Whether NANDA's Index is currently live/production or research-stage: the Index is "hosted at ~15 universities" per one secondary source [U]; Join39/List39 demos exist but real-world transaction volume is unknown [U].
- AgentFacts schema version number: the schema is described as "versioned" but no version string (e.g., v1.0) was found in the sources read [U].
- A named agent-specific escrow product or standard: none found after two attempts [U].
- NANDA papers 2508.03101 / 2508.03095 / 2508.03113: confirmed via the projnanda README's arXiv links; abstracts not read directly [U-level detail on 03101/03095].
- Dot shutdown year: TechCrunch URL is dated 2025-09-05 but secondary scrapes render inconsistent "days ago" stamps; treat year as 2025 with the URL as the citation [U].
- Inflection AI's Pi product status: not investigated — irrelevant once Pi was identified as Zechner's harness, but noted in case Inflection's Pi was meant [U].
