"""Shared pre-reservation validation for native acquisition dispatches.

This module validates only structural host compatibility. It does not reserve a
budget, dispatch a provider, or establish semantic support.
"""
import ipaddress
import re
from urllib.parse import urlsplit

from .artifacts import require

OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
QUESTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")

_CAPABILITIES = {
    "search_query": {"web_search", "openalex", "arxiv"},
    "open": {"official_document", "arxiv", "arxiv_mcp_candidate"},
    "find": {"web_search", "official_document", "arxiv", "arxiv_mcp_candidate"},
}


def operation_identifier(value, code):
    require(isinstance(value, str) and OPERATION_ID.fullmatch(value), code)
    return value


def question_identifier(value, code):
    require(isinstance(value, str) and QUESTION_ID.fullmatch(value), code)
    return value


def public_https_url(value, code):
    require(isinstance(value, str) and len(value) <= 4096, code)
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    require(
        parsed.scheme == "https"
        and bool(host)
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and parsed.port in (None, 443)
        and host != "localhost"
        and not host.endswith((".local", ".internal")),
        code,
    )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        require(address.is_global, code)
    return value


def validate_dispatch(
    operation_id,
    arguments,
    *,
    questions=None,
    question_ids=(),
    source_role=None,
    one_item=False,
    id_code="ACQ_OPERATION_ID",
    arguments_code="ACQ_ARGUMENTS_INVALID",
    url_code="ACQ_URL_INVALID",
    binding_code="ACQ_QUESTION_BINDING",
    role_code="ACQ_SOURCE_ROLE",
    capability_code="ACQ_CAPABILITY_OPERATION",
):
    """Validate the contract shared by a controller and HostWeb before reservation."""
    operation_identifier(operation_id, id_code)
    require(isinstance(arguments, dict), arguments_code)
    keys = [key for key in ("search_query", "open", "find") if key in arguments]
    require(len(keys) == 1, arguments_code)
    key = keys[0]
    items = arguments[key]
    require(isinstance(items, list) and bool(items), arguments_code)
    if one_item:
        require(len(items) == 1, arguments_code)
    for item in items:
        require(isinstance(item, dict), arguments_code)
        if key in {"open", "find"}:
            require("ref_id" in item, arguments_code)
            public_https_url(item["ref_id"], url_code)

    if questions is not None:
        require(isinstance(question_ids, (list, tuple)) and 0 < len(question_ids) <= 8
                and len(set(question_ids)) == len(question_ids), binding_code)
        require(all(question_identifier(value, binding_code) for value in question_ids), binding_code)
        require(set(question_ids) <= set(questions), binding_code)
        for question_id in question_ids:
            row = questions[question_id]
            require(source_role in row["source_roles"], role_code)
            require(bool(set(row["capability_ids"]) & _CAPABILITIES[key]), capability_code)
    return ("search" if key == "search_query" else "open"), key, items
