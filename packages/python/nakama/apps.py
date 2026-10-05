"""Application interfaces for embedding a gateway; install the apps extra."""
from .contracts import AppAdapter, AppContext, Operation
from gateway.apps import AppRegistry

__all__ = ['AppAdapter', 'AppContext', 'AppRegistry', 'Operation']
