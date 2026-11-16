"""Exact immutable bindings for the disabled metadata-only Claude preflight."""
from pathlib import Path

STATUS = "DISABLED_PROVIDER_FREE_PENDING_CLAUDE_V8_P0_V10_GRANTS_AND_FRESH_REVIEW"
MODEL = "claude-opus-5-5"
DISPLAY_MODEL = "Opus 5.5"
OWNER_UID = 501
WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")

DECISION_REF = (
    "tuning/architecture/r6_claude_current_readiness_audit_v1/readiness-decision-v1.json",
    14863,
    "301ad6789c4e3c979afcb0a61fa6b23c7ccc6f2a49d9a89f33ea3f5717d7fd24",
)
PROTOCOL_REF = (
    "tuning/architecture/r6_claude_current_readiness_audit_v1/protocol-v1.json",
    6073,
    "3f121d4e334c79081856aa448f32c3269b810fa94e937e18003992aac7fc06fc",
)
HISTORICAL_MEMBERSHIP_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-catalog-membership-interpretation-receipt.json",
    1659,
    "9f492a296ab261e7b7c7a2373a287f6a473577318300e35bba220e7bd3e3688c",
)
HISTORICAL_MEMBERSHIP_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-catalog-membership-interpretation-independent-review.json",
    4216,
    "f1b42f2cb81b3fd09ca5749813c7404e1057bb07055109e87239ebdb15432d27",
)
BINARY_IDENTITY_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-provider-binary-identity-current-20261111.json",
    1788,
    "d1307d8dc05cfb543ac2abc3e044f6de390d1bd7bd017538cbfa2a527a43d848",
)
BINARY_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-provider-binary-identity-current-20261111-independent-review-fable-20261111T085348Z.json",
    5166,
    "3af2710961a409f3c50077bf919b2c851422b185955572355254141d8cd5b40b",
)
DRIVER_DESIGN_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-live-driver-design.json",
    23525,
    "443b3b865b171a7202e5cb7dd23ab1fc3c2b47d178e6f35e7ab077ee0b128f10",
)
DRIVER_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-live-driver-provider-free-successor-v2-independent-review.json",
    11601,
    "d3bf74efbf46806bee88b7b4e08ffd2164039ba8a996e1688fb47f11d636a7fd",
)
ADAPTER_CONTRACT_REF = (
    "shared/job_runtime/providers/claude_host.py",
    28572,
    "4c8b3975d06fd6d543885b1a2bbff7dee6adf3b17b0aa9ca4f61f7ab19da56c1",
)
PROVIDER_CONTRACT_REF = (
    "shared/job_runtime/provider_contract.py",
    19663,
    "9de31552df5b1474bf3b29e36ce07278264e71a19f05b45cc1c09213d6873333",
)
CATALOG_PARSER_REF = (
    "shared/job_runtime/candidates/r6_one_off_claude_catalog_parser_v1/parser.py",
    16030,
    "c20e58cad66f866a5ce1865d8937ee0ff4a87aa4cc62bbf5a3a0c5a1bc01a502",
)
CATALOG_PARSER_REVIEW_REF = (
    "tuning/architecture/r6_one_off_claude_catalog_parser_v1/producer-verification-v2-final.json",
    7002,
    "bcbcdbfd37546e5b9ae9db591362c2f5810a8d622e43e9c872ad31056c55a35a",
)
CURRENT_V8_OPEN_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v8-independent-review-open-fable-20261113-8e9a8076.json",
    10896,
    "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d",
)

BINARY_PATH = Path("/Users/bytedance/.local/share/claude/versions/2.1.321")
BINARY_BYTES = 323686048
BINARY_SHA256 = "abc9feeeca8091d51b623291e044cf0528c2f6b74e0c1d6ef671d52c73f7cd3c"
BINARY_MODE = 0o755

AUTH_ARGV = (str(BINARY_PATH), "auth", "status", "--json")
CATALOG_ARGV = (
    str(BINARY_PATH), "-p", "--output-format", "stream-json", "--verbose",
    "--include-partial-messages", "--model", MODEL, "--effort", "low",
    "--permission-mode", "dontAsk", "--permission-prompts", "none",
    "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
    "--mcp-config", '{"mcpServers":{}}', "--tools", "",
    "--setting-sources", "", "--no-chrome", "--max-budget-usd", "0.01",
    "/model",
)
OUTPUT_ROOT = WORKSPACE / ".job-runtime" / "r6-claude-metadata-preflight-v1"
AUTH_OUTPUT_ROOT = OUTPUT_ROOT / "auth-status"
AUTH_REVIEW_OUTPUT_ROOT = OUTPUT_ROOT / "auth-status-review"
CATALOG_OUTPUT_ROOT = OUTPUT_ROOT / "model-catalog"
AUTH_TIMEOUT_SECONDS = 10
CATALOG_TIMEOUT_SECONDS = 30
FRESHNESS_SECONDS = 1800
MAX_OUTPUT_BYTES = 1024 * 1024

# Future authority is deliberately absent. A successor must replace every None
# with an exact byte count/hash and obtain independent review before activation.
FUTURE_AUTHORITY = {
    "auth_grant": {"path": "PENDING_EXACT_AUTH_GRANT", "bytes": None, "sha256": None},
    "auth_grant_review": {"path": "PENDING_EXACT_AUTH_GRANT_REVIEW", "bytes": None, "sha256": None},
    "catalog_grant": {"path": "PENDING_EXACT_CATALOG_GRANT", "bytes": None, "sha256": None},
    "catalog_grant_review": {"path": "PENDING_EXACT_CATALOG_GRANT_REVIEW", "bytes": None, "sha256": None},
    "claude_v8_clean_review": {"path": "PENDING_FRESH_CLEAN_CLAUDE_V8_REVIEW", "bytes": None, "sha256": None},
    "p0_v10_clean": {"path": "PENDING_CLEAN_P0_V10", "bytes": None, "sha256": None},
}
