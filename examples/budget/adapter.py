"""Read-only budgeting example. Account ownership is bound to peer agent IDs."""
from copy import deepcopy
from nakama.apps import AppContext, Operation
from gateway.wire import AppError


class BudgetAdapter:
    app_id = 'budget'

    def __init__(self, accounts):
        # Operator-supplied mapping: agent_id -> summary. Never accept owner IDs
        # or external account tokens from a calling agent's input.
        self._accounts = deepcopy(accounts)

    def operations(self):
        return (Operation(
            name='summary', scope='app.budget:read',
            description='Read the approved peer\'s budget summary.',
            input_schema={'type': 'object', 'properties': {}, 'additionalProperties': False},
            handler=self.summary),)

    def summary(self, context: AppContext, data):
        if context.peer_id not in self._accounts:
            raise AppError('not_found', 'no budget linked to this peer', 404)
        return deepcopy(self._accounts[context.peer_id])
