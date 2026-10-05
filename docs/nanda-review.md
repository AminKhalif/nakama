# NANDA architecture review

Reviewed on 2026-10-05. This is an architectural comparison, not a claim of NANDA
compatibility. No external registry is contacted by Nakama at runtime.

## Sources examined

- [Beyond DNS paper](https://arxiv.org/abs/2507.14263) and the
  [authors' architecture text](https://github.com/aidecentralized/NANDA-Quilt-of-Registries-and-Verified-AgentFacts).
- [NANDA Index v2](https://github.com/projnanda/nanda-index-v2), commit
  `8ff5ddbca2d11f71298fa26b4de4275739a1be8f`: locator parsing, resolution,
  federation, signing, index record schemas, and account/domain verification.
- [AgentFacts schema](https://github.com/projnanda/agentfacts-format), commit
  `89e938c08a7166341201568055c0a3b6852d26e4`.
- [NANDA adapter](https://github.com/projnanda/adapter), commit
  `ad29a0423fcce9d4beb28b425bf61fa198679b42`: SDK packaging and registry/bridge code.

## Useful architectural separation

NANDA's index resolves identities to discovery records. Its current implementation
supports organization and personal entries, and directs callers toward catalogs,
cards, or DNS-based discovery. Execution lives downstream. The research additionally
proposes richer signed AgentFacts, adaptive resolution, and decentralized updates.
Research proposals and deployed code should be assessed separately.

For Nakama, discovery, authentication, permission, and execution should remain
separate concerns. Locating an endpoint or verifying its metadata does not establish
that a particular owner approved a particular operation. Nakama's private connection
graph and grants can complement an external discovery system.

## What to adopt

| Idea | Application to Nakama | MVP decision |
| --- | --- | --- |
| Stable identity independent of runtime address | An agent can change connectors without losing its connections | Keep opaque agent IDs; do not use vendor names as trust |
| Discovery separate from execution | A resolver can be added without moving authorization into it | Keep gateway URL configuration explicit today |
| Structured capabilities | Apps describe operations, input schemas, and permission scopes | Implement through the app and connector contracts |
| Expiry and revocation | Permission must be checked at execution, including after discovery | Check live keys and grants on each call |
| Owner verification | Display names do not establish ownership | Prioritize owner accounts and credential binding before consumer launch |
| Multiple registration/discovery paths | Vendors can expose different interfaces | Use adapters; do not force a vendor-specific runtime |

## What to defer

A global registry, CRDT replication, adaptive endpoint selection, JSON-LD credential
issuance, trust-zone federation, and third-party capability attestation each introduce
new operational and trust dependencies. None is needed to prove an approved connection
between two agents and a scoped app. Add them when a concrete integration needs them.

The current Index v2 is TypeScript; the older adapter is Python. Both are viable.
Language choice is independent of whether the architectural boundaries are sound.

## Where Nakama's inherited design needed correction

- Game commit/reveal and auditor receipts solve the example game's fairness
  requirements. They should not define every application operation.
- Signed identity documents prove a gateway assertion about a key. They do not
  verify the human named in a self-reported owner field.
- Ed25519 signatures do not prevent prompt injection, establish capability quality,
  encrypt content, or replace permission checks.
- The A2A text-part wrapper is a custom compatibility surface. It must not be
  described as complete A2A conformance.
- A central gateway is a practical MVP enforcement point, not a demonstrated
  requirement for every future topology.
- Duplicate handwritten signing implementations add avoidable maintenance and
  security risk. The shared native crypto backend replaces them.

## Recommended integration seam

If NANDA discovery is added, define a resolver that returns an endpoint, protocol,
expiry, and provenance. Keep it optional and separate from `Transport`. Resolving an
agent must never approve friendship or create an application grant. Any fetched URL
needs timeout, size, redirect, and SSRF controls before it is usable in the gateway.

Do not publish private friend graphs or financial metadata into a discovery index.
Public registration should be an explicit owner decision. Existing Nakama identity
documents have a different schema from AgentFacts; translating them needs a versioned
mapping and compatibility tests, rather than renaming the documents.

## Product implication

A narrow developer product can provide approved connections, private messages, and
scoped app operations. A short SDK quickstart and one useful cross-vendor workflow
can establish demand before adopting Internet-scale discovery architecture.
NANDA can become an optional discovery integration as that demand expands.
