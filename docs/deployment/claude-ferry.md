# Optional user-scope Claude Code connection to Ferry

This is an explicitly user-requested personal client configuration, separate
from the repository's Codex scheduler and model profiles. It is not required to
run this workspace and is not installed automatically by project setup.

On2026-11-04 the existing Claude Code2.1.318 and Ferry0.1.98 were inspected.
`ferry config claude` prints configuration; it does not merge the settings itself.
The user requested this complete block in `~/.claude/settings.json`, preserving
all unrelated keys:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8790",
    "ANTHROPIC_AUTH_TOKEN": "ferry",
    "ANTHROPIC_API_KEY": "",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
    "CLAUDE_CODE_AUTO_MODE_SERVER": "0"
  },
  "model": "claude-gpt-5-6-sol-max[1m]",
  "enableArtifact": false
}
```

The literal `ferry` is the locally generated gateway placeholder, not an exported
upstream API key. Actual provider credentials remain owned by Ferry. Obtain the
current loopback URL and configuration from the installed Ferry CLI on another
device; the sample port is the observed local setting, not a discovery mechanism.

The original settings had no `env` block or gateway configuration. An atomic
merge of the requested fields was read back and JSON-validated; unrelated
preferences were compared and preserved. Original settings and mutation receipts
are private under `.job-runtime/claude-ferry-config-20261104/`, excluded from Git.
Rollback restores those original bytes only after reconciling later user edits.
No shell profile, managed policy, Codex settings or scheduler allocation was edited.

The local gateway returned HTTP200 from `/v1/models` with41 advertised models,
including `Ferry Opus 5.5`. The installed Claude binary contains support for the
discovery variable. This verifies configuration and catalog access, not model
inference, upstream identity or an already-running model menu. Restart Claude
Code and open `/model`; select the desired `Ferry …` entry. The requested default
is Ferry's `claude-gpt-5-6-sol-max[1m]`.

Claude's official [gateway connection documentation](https://code.claude.com/docs/en/llm-gateway-connect)
describes user settings, gateway credentials and model discovery. Preserve
existing user settings when merging. Never copy private Ferry authentication
stores, tokens or unrelated Claude state into project source or fixtures.
