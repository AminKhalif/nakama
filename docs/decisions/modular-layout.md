# ADR: package boundaries

## Decision

Maintain the SDK, gateway, protocol specifications, and examples in one repository.
The SDK must be installable independently of running the gateway. Transport,
connector, application, and persistence interfaces belong in separate modules.

Game operations are retained for compatibility and as a conformance example.
New application operations use explicit scoped adapters rather than adding domain
rules to the HTTP handler or extending the tic-tac-toe state machine.

Protocol changes include documentation and tests covering authorization failures.
