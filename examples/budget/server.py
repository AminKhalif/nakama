"""Embed the gateway with a read-only application. No external finance service."""
import json
import os

from nakama.apps import AppRegistry
from gateway.server import main
from adapter import BudgetAdapter

if __name__ == '__main__':
    with open(os.environ['NAKAMA_BUDGET_ACCOUNTS']) as source:
        accounts = json.load(source)
    main(applications=AppRegistry([BudgetAdapter(accounts)]))
