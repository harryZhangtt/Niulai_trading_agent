"""Deterministic full-test email composition and immutable source enforcement.

No model-generated replacement body is accepted. The trusted host supplies the
verified recipient/request and native source adapters supply the private files.
The first composition pins those files; every later validation recomputes them.
"""
from __future__ import annotations
import base64
from datetime import datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import threading
import types

from .delivery import DeliveryError, assert_content_parity, validate_payload

_IMPORT_LOCK = threading.RLock()
FILES = ('holdings/daily.json', 'holdings/daily.pdf', 'holdings/tiger_status.json',
         'prices/preparation_receipt.json', 'prices/price_view/price_view.json',
         'prices/price_result.json', 'prices/price_message.txt', 'prices/price.pdf')


def require(condition, code):
    if not condition:
        raise DeliveryError(code)


def _path(root, path, *, existing=True):
    boundary = root / '.niulai-state' / 'e2e'
    path = Path(os.path.abspath(path))
    require('..' not in Path(path).parts and path.is_relative_to(boundary)
            and path.resolve().is_relative_to(boundary.resolve()), 'GUARD_PATH_OUTSIDE_E2E')
    for ancestor in [path, *path.parents]:
        if ancestor == root:
            break
        require(not ancestor.is_symlink(), 'GUARD_PATH_SYMLINK')
    if existing:
        require(path.is_file() and path.stat().st_uid == os.getuid(), 'GUARD_SOURCE_MISSING')
    return path


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'GUARD_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    require(path.stat().st_size <= 20 * 1024 * 1024, 'GUARD_SOURCE_TOO_LARGE')
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def _stamp(value):
    require(isinstance(value, str), 'GUARD_SOURCE_TIME_REQUIRED')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise DeliveryError('GUARD_SOURCE_TIME_INVALID') from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'GUARD_SOURCE_TIME_INVALID')
    return parsed


def _preserved(root, name):
    path = root / 'niulai' / 'holdings' / name
    require(path.is_file() and not any(p.is_symlink() for p in [path, *path.parents] if p != root.parent),
            'GUARD_PRESERVED_SOURCE_INVALID')
    module = types.ModuleType('_niulai_guard_' + name.replace('.', '_'))
    module.__file__ = str(path)
    # compile/exec avoids writing __pycache__ into the preserved source snapshot.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module, _sha(path.read_bytes())


def _canonical(root, out, recipient, request_id):
    paths = {name: _path(root, out / name) for name in FILES}
    portfolio = _read(paths['holdings/daily.json'])
    tiger = _read(paths['holdings/tiger_status.json'])
    prep = _read(paths['prices/preparation_receipt.json'])
    view = _read(paths['prices/price_view/price_view.json'])
    result = _read(paths['prices/price_result.json'])
    require(tiger.get('committed') is True and tiger.get('release_requested') is True
            and tiger.get('mode') == 'run' and tiger.get('status') in ('rendered', 'rendered_partial', 'completed', 'partial'),
            'GUARD_TIGER_COMMIT_REQUIRED')
    require(tiger.get('source') == 'existing_owner_private_store', 'GUARD_TIGER_SOURCE_REQUIRED')
    require(prep.get('inputs_unchanged') is True and prep.get('live_state_unchanged') is True
            and type(prep.get('new_live_events')) is int and prep['new_live_events'] == 0
            and prep.get('production_slot_completed') is False and prep.get('mode') == 'replay'
            and prep.get('status') in ('completed', 'partial'), 'GUARD_PRICE_REPLAY_REQUIRED')
    require(isinstance(portfolio.get('accounts'), list) and len(portfolio['accounts']) == 1,
            'GUARD_SINGLE_ACCOUNT_REQUIRED')
    account = portfolio['accounts'][0]
    daily = account['daily_performance'];totals = account['position_totals']
    session = daily['session']
    require(isinstance(session, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', session)
            and session == prep.get('session') == view.get('session') == result.get('session') == tiger.get('session'),
            'GUARD_SESSION_MISMATCH')
    require(view.get('historical_presentation') is True and view.get('new_signal_records') == []
            and result.get('mode') == 'replay' and result.get('retrospective') is True
            and result.get('new_signals') == [] and result.get('id') == view.get('run_id') == prep.get('run_id'),
            'GUARD_REPLAY_PROVENANCE_INVALID')
    require(view.get('source_payload_sha256') == _sha(json.dumps(result, sort_keys=True).encode()),
            'GUARD_PRICE_SOURCE_HASH_MISMATCH')
    coverage = result['coverage']
    require(coverage == prep.get('coverage') == view.get('coverage'), 'GUARD_COVERAGE_MISMATCH')
    count = coverage['enabled_rules']
    require(all(type(coverage.get(k)) is int and coverage[k] >= 0 for k in ('enabled_rules', 'valid_rules', 'failed_rules'))
            and coverage['valid_rules'] == len(result['results']) and coverage['failed_rules'] == len(result['errors']),
            'GUARD_COVERAGE_COUNTS_INVALID')
    require(type(count) is int and count > 0 and count == len(result['results']) + len(result['errors'])
            == len(view['rows']) == sum(view['groups'].values()), 'GUARD_FULL_PRICE_SCOPE_REQUIRED')
    expected_ids = {str(r.get('rule_id') or r.get('id')) for r in result['results'] + result['errors']}
    require(len(expected_ids) == count and {str(r.get('rule_id') or r.get('id')) for r in view['rows']} == expected_ids,
            'GUARD_PRICE_RULE_SCOPE_MISMATCH')
    known = sum(row.get('pnl') is not None for row in daily['positions'])
    positions = len(daily['positions'])
    require(positions > 0 and all(isinstance(row.get('symbol'), str) and row['symbol'] for row in daily['positions']),
            'GUARD_HOLDINGS_SCOPE_REQUIRED')
    _stamp(totals.get('snapshot_query_at'));_stamp(totals.get('assets_query_at'))
    _stamp(view.get('as_of'))
    retrieved = [r['retrieved_at'] for r in result['results'] if r.get('retrieved_at')]
    retrieved += [r['retrieved_at'] for r in result.get('quote_only', []) if r.get('retrieved_at')]
    require(bool(retrieved), 'GUARD_PRICE_RETRIEVAL_TIME_REQUIRED')
    retrieved = sorted(set(retrieved), key=_stamp)
    price_text = paths['prices/price_message.txt'].read_text()
    require(bool(price_text.strip()), 'GUARD_COMPLETE_PRICE_TEXT_REQUIRED')
    price_pdf = paths['prices/price.pdf'].read_bytes()
    holdings_pdf = paths['holdings/daily.pdf'].read_bytes()
    for raw in (price_pdf, holdings_pdf):
        require(raw.startswith(b'%PDF-') and b'%%EOF' in raw[-2048:], 'GUARD_ACTUAL_PDFS_REQUIRED')
    partial = tiger['status'] in ('rendered_partial', 'partial') or prep['status'] == 'partial' or known < positions
    files = {name: _sha(path.read_bytes()) for name, path in paths.items()}
    source_digest = _sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
    with _IMPORT_LOCK:
        price_module, price_code_hash = _preserved(root, 'price_summary_view.py')
        composer, compose_code_hash = _preserved(root, 'compose_digest.py')
        old = sys.modules.get('price_summary_view')
        sys.modules['price_summary_view'] = price_module
        try:
            payload = composer.compose(portfolio, price_text, paths['holdings/daily.pdf'],
                'Niulai triggered | FULL scheduled E2E test | ' + request_id,
                recipient, historical=True, price_view=view)
        finally:
            if old is None:
                sys.modules.pop('price_summary_view', None)
            else:
                sys.modules['price_summary_view'] = old
    banner = ('<section style="border:2px solid #a16b00;padding:12px;margin:12px 0">'
        '<h2>Niulai triggered | FULL scheduled E2E test</h2><p><b>'
        + ('PARTIAL · 部分数据缺口' if partial else '已完成本次测试范围')
        + '</b> · Request ' + html.escape(request_id) + '</p><p>'
        + '本封用于完整调度 E2E 测试，不是生产槽位补发。价格来源为本次获取的历史重评，纽约交易日 '
        + html.escape(session) + '；不是当前实时行情，新增实时事件为 0。'
        + '</p><p>价格有效规则 ' + str(coverage['valid_rules']) + '/' + str(count)
        + '；逐股盈亏可计算 ' + str(known) + '/' + str(positions)
        + '。完整规则分组和全部逐股行保留于下文，两份 PDF 均为实际附件。</p><p>'
        + '持仓读取 ' + html.escape(totals['snapshot_query_at']) + '；资产读取 '
        + html.escape(totals['assets_query_at']) + '；价格来源获取 '
        + html.escape(retrieved[0]) + ' — ' + html.escape(retrieved[-1])
        + '。读取时间与历史报价时点分别保留。</p><p>冻结来源清单 SHA-256：'
        + source_digest + '</p></section>')
    body = payload['payload']['parts'][0]['body']['content']
    require(body.count('<body ') == 1 and '</body>' in body, 'GUARD_CANONICAL_HTML_INVALID')
    start = body.index('>', body.index('<body ')) + 1
    payload['payload']['parts'][0]['body']['content'] = body[:start] + banner + body[start:]
    payload['payload']['parts'].append({'mime_type': 'application/pdf', 'filename': 'Niulai_Price_Alert_Details.pdf',
        'content_disposition': 'attachment', 'body': {'base64_url_content': base64.urlsafe_b64encode(price_pdf).decode()}})
    fingerprint = validate_payload(payload, recipient, recipient)
    integrity = {'schema_version': 1, 'request_id': request_id, 'recipient': recipient,
        'source_files_sha256': files, 'source_digest': source_digest,
        'composer_sha256': compose_code_hash, 'price_renderer_sha256': price_code_hash,
        'canonical_payload_digest': fingerprint['digest']}
    return payload, integrity


def compose(root, out, recipient, request_id):
    root = Path(root).resolve(strict=True)
    out = _path(root, out, existing=False)
    require(out.is_dir(), 'GUARD_OUTPUT_DIRECTORY_REQUIRED')
    require(isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', request_id),
            'GUARD_REQUEST_ID_INVALID')
    payload, integrity = _canonical(root, out, recipient, request_id)
    path = _path(root, out / 'source_integrity.json', existing=False)
    raw = json.dumps(integrity, sort_keys=True, indent=2).encode()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        require(_read(path) == integrity, 'GUARD_IMMUTABLE_SOURCE_CHANGED')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return payload


def validate(root, out, candidate, recipient, request_id):
    canonical = compose(root, out, recipient, request_id)
    return assert_content_parity(canonical, candidate, recipient, recipient)
