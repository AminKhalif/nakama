# Read-only budget application

This example demonstrates application extensibility without placing financial
business logic in the gateway. It uses operator-provided summary data, not a bank
API, payment provider, or production financial record.

1. Install `python -m pip install '.[apps]'` from the repository root.
2. Register agents and note their IDs.
3. Prepare a private JSON file mapping the data owner's agent ID to a summary:

```json
{"agent_example": {"currency": "USD", "monthly_limit": 1200}}
```

4. Restart the same gateway database with the adapter:

```bash
NAKAMA_BUDGET_ACCOUNTS=/absolute/private/accounts.json \
  python examples/budget/server.py --db gateway.db --host 127.0.0.1 --port 8080
```

5. Request friendship. In the console accept with `app.budget:read` selected.
6. Call `client.invoke_app("budget", "summary", owner_agent_id, {})`.

The adapter uses `AppContext.peer_id` to select the approved peer's data. The
request cannot supply another owner's identifier; its JSON Schema rejects all
input properties. The gateway denies non-friends, expired/revoked grants, and
revoked peer identities before calling the adapter.

A production financial connector must additionally map verified owners to linked
accounts, hold provider tokens in a secret store, enforce provider permissions,
and declare separate read/write scopes. This example provides none of those
external account integrations and cannot execute a financial transaction.
