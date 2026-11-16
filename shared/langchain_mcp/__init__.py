"""Isolated MCP transport. Importing this package activates no host integration."""
from .client import MCPClient, MCPError, LOCAL, REMOTE, canonical, digest

__all__ = ['MCPClient', 'MCPError', 'LOCAL', 'REMOTE', 'canonical', 'digest']
