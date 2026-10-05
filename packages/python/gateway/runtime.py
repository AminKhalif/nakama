"""Embeddable gateway lifecycle independent of the command-line entry point."""
from http.server import ThreadingHTTPServer
from typing import Callable, Optional, Union

from .apps import AppRegistry
from .console import ConsoleApp, ensure_console_token
from .identity import ensure_gateway_keys
from .server import Ctx, Handler
from .sqlite_store import SQLiteStorage
from .store import Storage


class Gateway:
    """Reference HTTP runtime. Application factories receive the gateway store.

    The built-in operator console is instance-wide. Hosts must supply their own
    owner authentication and account linking before accepting calendar approvals.
    """
    def __init__(self, *, database: str, host: str = '127.0.0.1', port: int = 8080,
                 applications: Optional[Union[AppRegistry, Callable[[Storage], AppRegistry]]] = None):
        self.store = SQLiteStorage(database)
        try:
            self.keys = ensure_gateway_keys(self.store)
            self.console_token = ensure_console_token(self.store)
            registry = applications(self.store) if callable(applications) else applications
            self.context = Ctx(self.store, self.keys, registry)
            self.console = ConsoleApp(self.store, self.keys, scopes=self.context.applications.scopes())
            handler = type('GatewayHandler', (Handler,), {
                'ctx': self.context, 'console_app': self.console})
            self.http_server = ThreadingHTTPServer((host, port), handler)
        except BaseException:
            self.store.close()
            raise

    def serve_forever(self):
        self.http_server.serve_forever()

    def shutdown(self):
        """Call from another thread when serve_forever() is running."""
        self.http_server.shutdown()

    def close(self):
        """Call after the serving thread stops."""
        self.http_server.server_close()
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
