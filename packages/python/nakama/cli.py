import argparse
import json
import sys

from . import ClientError, GatewayError
from .connectors import GatewayConnector, get_profile
from .credentials import load_client, register_agent


def main():
    parser = argparse.ArgumentParser(description='Nakama agent SDK and connectors')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo', help='Run a disposable local messaging and permission demo')
    register = commands.add_parser('register', help='Register and save a local agent identity')
    register.add_argument('--gateway', required=True)
    register.add_argument('--name', required=True)
    register.add_argument('--vendor', default='python')
    register.add_argument('--owner', default=None)
    register.add_argument('--credentials', required=True)
    mcp = commands.add_parser('mcp', help='Serve agent tools over MCP stdio')
    mcp.add_argument('--credentials', required=True)
    config = commands.add_parser('connector-config', help='Print configuration without credentials')
    config.add_argument('--vendor', choices=['hermes', 'mcp', 'muse', 'instinct', 'dots', 'openclaw'], required=True)
    config.add_argument('--credentials', required=True)
    config.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    try:
        if args.command == 'demo':
            from .demo import run
            run()
        elif args.command == 'register':
            client = register_agent(args.credentials, args.gateway, args.name, args.vendor, args.owner)
            print(json.dumps({'agent_id': client.agent_id, 'gateway': client.base_url}))
        elif args.command == 'connector-config':
            from pathlib import Path
            print(json.dumps(get_profile(args.vendor).stdio_config(
                python=args.python, credentials=str(Path(args.credentials).expanduser().resolve())), indent=2))
        else:
            from .connectors.mcp import create_server
            create_server(GatewayConnector(load_client(args.credentials))).run(transport='stdio')
    except (ClientError, GatewayError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, 'nakama: %s\n' % exc)
