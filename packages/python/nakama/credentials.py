"""Local agent credentials. Never pass private keys in connector configuration."""
import json
import os
import stat
from pathlib import Path

from gwclient import ClientError, GWClient, public_key_from_private


def register_agent(path, base_url, name, vendor='python', owner_display_name=None):
    """Reserve a private file, then register and persist one agent. No overwrite."""
    path = Path(path).expanduser()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as target:
            client = GWClient.new(base_url)
            client.register(name, owner_display_name=owner_display_name, vendor=vendor, schemas=['gw/1', 'friends/1', 'receipts/1'])
            json.dump({'version': 1, 'base_url': client.base_url,
                       'agent_id': client.agent_id, 'private_key_hex': client.private_key_hex,
                       'public_key_hex': client.public_key_hex}, target)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return client


def load_client(path):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(Path(path).expanduser(), flags)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ClientError('credentials must be a regular file')
        if os.name == 'posix' and info.st_mode & 0o077:
            raise ClientError('credentials must be private: chmod 600 the file')
        try:
            data = json.load(source)
            if data['version'] != 1 or not isinstance(data['agent_id'], str) or not data['agent_id']:
                raise ValueError('invalid identity')
            if public_key_from_private(data['private_key_hex']) != data['public_key_hex']:
                raise ValueError('keypair mismatch')
            return GWClient(data['base_url'], private_key_hex=data['private_key_hex'],
                            public_key_hex=data['public_key_hex'], agent_id=data['agent_id'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError('invalid credentials file') from exc
