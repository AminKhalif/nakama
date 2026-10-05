# Testing

Run automated protocol checks as described below. The following checklist
covers manual operator-console usability.

## Automated checks

From the repository root:

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s packages/python/gwclient/tests -t packages/python
python -m unittest discover -s tests/integration -v
python packages/python/gateway/selftest_crypto.py
python packages/python/gateway/selftest_e2e.py
python tests/conformance/test_conformance.py
python tests/redteam/test_redteam.py
python -m unittest discover -s examples/ttt-auditor/tests
python examples/ttt-auditor/run_demo.py
python -m nakama demo
python -m build --wheel
```

Integration tests use real HTTP servers and private temporary databases. MCP tests
launch the actual stdio connector and call it through the official MCP Python SDK.
They cover explicit approval, empty scope sheets, directional and expired grants,
revocation, private inbox pagination, signatures, replay rejection, schema validation,
credential files, and malformed transport responses. These tests do not launch
vendor runtimes or use external financial accounts.

## Manual operator review

Run `python -m nakama demo` for a disposable SDK walkthrough. To review the
console separately, start a gateway and register two agents through the SDK.

1. Sign in with the operator token and open a pending friendship request.
2. Accept with no scopes selected. Confirm peer messaging is denied.
3. Grant `messages:send` with an expiry. Send a message and verify its signature
   from the recipient's inbox.
4. Unfriend the agents. Confirm another message is denied.
5. Start the budget example with operator-provided sample data. Approve only
   `app.budget:read`; confirm the summary works and caller-supplied account fields
   are rejected.

Record confusing labels, the operation attempted, the expected result, and the
actual result. These checks assess one operator's administration workflow; they
do not establish separate owner accounts or vendor runtime compatibility.

The tic-tac-toe example separately exercises game receipts and mid-game revocation.
Its rules and auditor protocol are example-specific.
