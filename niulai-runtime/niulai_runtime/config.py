"""Strict, non-secret-in-source policy for the Niulai runtime.

The private configuration declares intent. It never proves account access or a
successful cutover: those observations must be supplied by the operator/adapter.
"""
from dataclasses import dataclass
import json
import re
import stat
from pathlib import Path


class ConfigError(ValueError):
    """Safe diagnostic: messages contain codes, never configuration values."""


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    recipient: str
    automation_id: str
    scheduler_owner: str
    production_enabled: bool
    state_root: Path
    workspace_root: Path
    timezone: str = "America/New_York"
    slots: tuple[str, ...] = ("13:00", "19:00")
    grace_minutes: int = 60
    calendar: str = "XNYS"
    schema_version: int = 1


def require(condition, code):
    if not condition:
        raise ConfigError(code)


def _keys(value, expected, code):
    require(type(value) is dict and set(value) == set(expected), code)


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)


def validate_config(value, workspace_root):
    """Validate an in-memory policy. This performs no network or writes."""
    _keys(value, ("schema_version", "mode", "recipient", "automation_id",
                  "scheduler_owner", "production_enabled", "state_directory", "schedule"),
          "CONFIG_KEYS_INVALID")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1,
            "CONFIG_VERSION_UNSUPPORTED")
    require(value["mode"] in ("dry_run", "manual_test", "production"), "CONFIG_MODE_INVALID")
    require(type(value["production_enabled"]) is bool, "PRODUCTION_FLAG_INVALID")
    require(not value["production_enabled"] or value["mode"] == "production",
            "PRODUCTION_FLAG_MODE_MISMATCH")
    recipient = value["recipient"]
    require(type(recipient) is str and len(recipient) <= 254 and
            re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", recipient)
            and not recipient.lower().endswith((".invalid", ".example")), "RECIPIENT_INVALID")
    require(_identifier(value["automation_id"]), "AUTOMATION_ID_INVALID")
    require(_identifier(value["scheduler_owner"]), "SCHEDULER_OWNER_INVALID")
    schedule = value["schedule"]
    _keys(schedule, ("timezone", "slots", "grace_minutes", "calendar"), "SCHEDULE_KEYS_INVALID")
    require(schedule["timezone"] == "America/New_York", "TIMEZONE_POLICY_MISMATCH")
    require(schedule["slots"] == ["13:00", "19:00"], "SLOT_POLICY_MISMATCH")
    require(type(schedule["grace_minutes"]) is int and schedule["grace_minutes"] == 60,
            "GRACE_POLICY_MISMATCH")
    require(schedule["calendar"] == "XNYS", "CALENDAR_POLICY_MISMATCH")
    workspace = Path(workspace_root).resolve(strict=True)
    require(workspace.is_dir(), "WORKSPACE_INVALID")
    require(value["state_directory"] == ".niulai-state", "STATE_DIRECTORY_POLICY_MISMATCH")
    state = workspace / ".niulai-state"
    require(not state.is_symlink() and state.resolve().parent == workspace,
            "STATE_DIRECTORY_ESCAPE")
    if state.exists():
        require(state.is_dir(), "STATE_DIRECTORY_INVALID")
        require(stat.S_IMODE(state.stat().st_mode) & 0o077 == 0, "STATE_PERMISSIONS_UNSAFE")
    return RuntimeConfig(value["mode"], recipient, value["automation_id"],
                         value["scheduler_owner"], value["production_enabled"], state, workspace)


def load_config(path, workspace_root):
    """Only owner-private regular JSON files below .niulai-state are accepted."""
    workspace = Path(workspace_root).resolve(strict=True)
    state = workspace / ".niulai-state"
    path = Path(path).absolute()
    require(not state.is_symlink() and state.resolve().parent == workspace, "STATE_DIRECTORY_ESCAPE")
    require(not path.is_symlink() and path.is_file(), "CONFIG_FILE_INVALID")
    require(path.resolve().is_relative_to(state.resolve()), "CONFIG_OUTSIDE_PRIVATE_STATE")
    for ancestor in [path, *path.parents]:
        if ancestor == workspace:
            break
        require(not ancestor.is_symlink(), "CONFIG_SYMLINK_REJECTED")
        require(stat.S_IMODE(ancestor.stat().st_mode) & 0o077 == 0, "CONFIG_PERMISSIONS_UNSAFE")
    require(path.stat().st_size <= 65536, "CONFIG_TOO_LARGE")
    def unique_pairs(pairs):
        result = {}
        for key, val in pairs:
            require(key not in result, "CONFIG_DUPLICATE_KEY")
            result[key] = val
        return result
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError):
        raise ConfigError("CONFIG_JSON_INVALID") from None
    return validate_config(value, workspace)


def assert_recipient(config, observed_gmail_email, payload_recipient):
    """Call immediately before send with the live Gmail get_profile result.

    Deliberately exact, without Gmail dot/plus alias canonicalization. The send
    adapter must also reject Cc/Bcc and extra recipients.
    """
    require(observed_gmail_email == config.recipient, "GMAIL_IDENTITY_MISMATCH")
    require(payload_recipient == config.recipient, "EMAIL_RECIPIENT_MISMATCH")
