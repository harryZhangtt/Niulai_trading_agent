"""Read the pilot's OpenAI credential locally, without copying native login tokens."""
from __future__ import annotations

import io
import os
import stat
from pathlib import Path

from dotenv import dotenv_values

PRIVATE_ENV = Path(__file__).resolve().parents[2] / ".langchain-pilot/.env"


class CredentialError(ValueError):
    """Pilot-generated, credential-free diagnostic."""


def openai_api_key() -> str:
    """Resolve on dispatch so graph/schema inspection needs no credential."""
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value and PRIVATE_ENV.exists():
        descriptor = os.open(PRIVATE_ENV, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16384):
                raise CredentialError("OPENAI_ENV_MUST_BE_OWNER_PRIVATE_FILE")
            # No interpolation from unrelated process variables and no shell execution.
            value = str(dotenv_values(stream=io.StringIO(stream.read()),
                                      interpolate=False).get("OPENAI_API_KEY") or "").strip()
    if not value or value.lower() in {"ferry", "your_openai_api_key", "replace_me"}:
        raise CredentialError("OPENAI_API_KEY_REQUIRED: set it locally in .langchain-pilot/.env")
    return value
