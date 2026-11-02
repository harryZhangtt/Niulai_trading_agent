"""Private bounded HTTP worker. Credential bytes never enter argv or receipts."""
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import stat
import sys
from urllib import request, error

from shared.research_sources.artifacts import ROOT, encoded
from .contracts import CREDENTIAL_REF, ENDPOINT, MAX_ATTEMPT_TIMEOUT_SECONDS, number


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _retry_after(value, now=None):
    """Accept delta seconds or an HTTP date, never propagate nonfinite headers."""
    if not isinstance(value, str):
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            delay = max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def _credential(reference):
    if reference != CREDENTIAL_REF:
        raise ValueError('JUDGE_CREDENTIAL_UNSAFE')
    path = ROOT / CREDENTIAL_REF
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        if parent.is_symlink():
            raise ValueError('JUDGE_CREDENTIAL_UNSAFE')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or not 1 <= info.st_size <= 4096:
            raise ValueError('JUDGE_CREDENTIAL_UNSAFE')
        value = os.read(descriptor, 4097).decode().strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError('JUDGE_CREDENTIAL_UNSAFE')
        return value
    finally:
        os.close(descriptor)


def main():
    try:
        raw = sys.stdin.buffer.read(512*1024 + 4097)
        if len(raw) > 512*1024 + 4096:
            raise ValueError('JUDGE_TRANSPORT_FAILED')
        message = json.loads(raw)
        if set(message) != {'body', 'credential_ref', 'timeout_seconds', 'max_response_bytes'}:
            raise ValueError('JUDGE_TRANSPORT_FAILED')
        timeout, maximum = message['timeout_seconds'], message['max_response_bytes']
        if not number(timeout) or not 0 < timeout <= MAX_ATTEMPT_TIMEOUT_SECONDS or type(maximum) is not int or not 1 <= maximum <= 256*1024:
            raise ValueError('JUDGE_TRANSPORT_FAILED')
        key = _credential(message['credential_ref'])
        req = request.Request(ENDPOINT, data=message['body'].encode(), method='POST',
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                'Accept': 'application/json', 'User-Agent': 'WorkspaceTypedJudge/1.0'})
        try:
            with request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
                body = response.read(maximum + 1)
                if len(body) > maximum:
                    raise ValueError('JUDGE_RESPONSE_TOO_LARGE')
                result = {'status': response.status, 'body_base64': base64.b64encode(body).decode(), 'retry_after_seconds': None}
        except error.HTTPError as exc:
            # Never send a provider's error text back to the parent.
            retry_after = _retry_after(exc.headers.get('Retry-After') if exc.headers else None)
            result = {'status': exc.code, 'body_base64': '', 'retry_after_seconds': retry_after}
    except TimeoutError:
        result = {'code': 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME'}
    except error.URLError as exc:
        # A socket timeout may arrive inside URLError before the parent's hard
        # deadline. It is still an unknown provider/billing outcome, not proof
        # that the server did no work. Never expose exception text.
        result = {'code': 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME' if isinstance(exc.reason, TimeoutError)
                  else 'JUDGE_TRANSPORT_FAILED'}
    except FileNotFoundError:
        result = {'code': 'JUDGE_CREDENTIAL_UNAVAILABLE'}
    except ValueError as exc:
        code = str(exc)
        result = {'code': code if code in {'JUDGE_CREDENTIAL_UNSAFE', 'JUDGE_RESPONSE_TOO_LARGE'} else 'JUDGE_TRANSPORT_FAILED'}
    except Exception:
        result = {'code': 'JUDGE_TRANSPORT_FAILED'}
    sys.stdout.buffer.write(encoded(result))


if __name__ == '__main__':
    main()
