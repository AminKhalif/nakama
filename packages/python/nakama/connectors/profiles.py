"""Configuration profiles describe verified surfaces, not vendor-owned agents."""
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass(frozen=True)
class ConnectorProfile:
    vendor: str
    config_root: Optional[str]
    status: str
    source: Optional[str] = None

    def stdio_config(self, *, python: str, credentials: str):
        if self.config_root is None:
            raise ValueError('no verified connector configuration for ' + self.vendor)
        if not python or not credentials:
            raise ValueError('python and credentials paths are required')
        entry = {'command': python, 'args': ['-m', 'nakama', 'mcp',
                                            '--credentials', str(Path(credentials).expanduser().resolve())]}
        return {self.config_root: {'nakama': entry}}


PROFILES = {
    'hermes': ConnectorProfile('hermes', 'mcp_servers', 'documented-mcp',
        'https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/mcp-config-reference.md'),
    'mcp': ConnectorProfile('mcp', 'mcpServers', 'generic-mcp',
        'https://modelcontextprotocol.io/docs/develop/build-server'),
    'muse': ConnectorProfile('muse', None, 'unverified-native'),
    'instinct': ConnectorProfile('instinct', None, 'unverified-native'),
    'dots': ConnectorProfile('dots', None, 'unverified-native'),
    'openclaw': ConnectorProfile('openclaw', None, 'unverified-native'),
}


def get_profile(vendor):
    try:
        return PROFILES[vendor]
    except KeyError as exc:
        raise ValueError('unknown connector profile: ' + vendor) from exc
