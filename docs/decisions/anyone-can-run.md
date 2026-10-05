# ADR: self-hosted gateway

## Decision

Any developer can run a gateway with SQLite and the provided HTTP server.
Clients explicitly select a gateway URL. There is no required hosted instance.

Each instance is a separate trust boundary. Signed identity documents and game
receipts can be verified offline with the issuing gateway's public key, but this
does not provide cross-instance friendship, routing, or federation.
