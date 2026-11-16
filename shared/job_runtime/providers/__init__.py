"""Source-only provider evidence adapters.

Provider modules are intentionally lazy: importing the Codex runner must not load
Claude-host custody dependencies, and neither module invokes a live provider.
"""

_CLAUDE_EXPORTS = {
    "CAPABILITIES", "CLAUDE_HOST_EVIDENCE_VERSION", "ClaudeHostAdapterError",
    "WorkspaceEvidenceResolver", "normalize_invocation",
}
_CODEX_EXPORTS = {
    "CodexCliAdapterError", "FinalOutputResolver",
    "NormalizedCodexRunnerEvidenceV1", "run_one_shot",
}

__all__ = sorted(_CLAUDE_EXPORTS | _CODEX_EXPORTS)


def __getattr__(name):
    if name in _CLAUDE_EXPORTS:
        from . import claude_host
        return getattr(claude_host, name)
    if name in _CODEX_EXPORTS:
        from . import codex_cli
        return getattr(codex_cli, name)
    raise AttributeError(name)
