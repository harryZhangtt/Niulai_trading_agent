"""Caller-owned setup for an owner-private ledger directory.

The runtime adapter, not AnswerLedger, must call this before constructing a ledger.
"""
from __future__ import annotations
import os, stat
from pathlib import Path
from .contracts import ContractError, require

def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os,"O_DIRECTORY",0) | getattr(os,"O_NOFOLLOW",0) | getattr(os,"O_CLOEXEC",0)

def create_owner_private_directory(path: Path) -> None:
    """Create one final directory and fsync its already-existing containing directory."""
    require(isinstance(path,Path) and path.is_absolute() and path.name not in ("",".",".."),"LEDGER_PARENT_INVALID")
    parent_fd=os.open(str(path.parent),_directory_flags())
    try:
        os.mkdir(path.name,0o700,dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:os.close(parent_fd)
    info=os.stat(str(path),follow_symlinks=False)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o700 and info.st_nlink>=1,"LEDGER_PARENT_UNSAFE")
