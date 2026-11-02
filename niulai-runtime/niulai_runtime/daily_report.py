"""Canonical combined digest from finalized branches; no acquisition or sending."""
import base64
import html
import json
from pathlib import Path
import shutil
import sys

from .daily_work import private, atomic, require, sha
from .delivery import validate_payload, assert_content_parity
from .e2e_guard import _preserved, _IMPORT_LOCK


def failure_holdings(root, out, session, code):
    out = private(root, out, True)
    require(code.isascii() and code.replace('_', '').isalnum() and len(code) < 100, 'DAILY_ERROR_CODE_INVALID')
    status_path = out / 'tiger_status.json'
    if status_path.exists():
        original = json.loads(status_path.read_text())
        require(original.get('committed') is not True, 'READY_HOLDINGS_MUST_BE_REUSED')
        preserved = out / 'tiger_original_status.json'
        if not preserved.exists():
            atomic(preserved, original)
    # Unknown is explicit. No stale holdings or invented P&L rows are substituted.
    portfolio = {'accounts': [{'daily_performance': {'session': session,
        'aggregate_pnl': None, 'capital_return_pct': None, 'positions': [],
        'note': 'Holdings branch unavailable: ' + code + '. All holdings/P&L coverage is unknown.'},
        'position_totals': {}}]}
    atomic(out / 'daily.json', portfolio)
    atomic(out / 'tiger_status.json', {'status': 'unavailable', 'error': code, 'committed': False})
    from reportlab.pdfgen.canvas import Canvas
    canvas = Canvas(str(out / 'daily.pdf'))
    canvas.setTitle('Holdings unavailable - explicit partial report')
    for y, text in ((790, '[CODEX] Holdings branch unavailable'), (760, code),
                    (730, 'Session: ' + session), (700, 'NAV, securities, cash and P&L: UNKNOWN'),
                    (670, 'No previous report has been substituted.')):
        canvas.drawString(45, y, text)
    canvas.save()


def branch_state(out):
    price = json.loads((out / 'prices/branch.json').read_text())
    tiger = json.loads((out / 'holdings/tiger_status.json').read_text())
    holdings_ok = tiger.get('committed') is True and tiger.get('release_requested') is True
    require(holdings_ok or tiger.get('status') == 'unavailable', 'DAILY_TIGER_UNCONFIRMED')
    portfolio = json.loads((out / 'holdings/daily.json').read_text())
    positions = portfolio['accounts'][0]['daily_performance']['positions']
    partial = (price['status'] != 'completed' or not holdings_ok or
               any(row.get('pnl') is None for row in positions) or
               tiger.get('status') in ('partial', 'rendered_partial'))
    return {'partial': partial, 'pending': price['pending'],
            'blocked': price['blocked'] or not holdings_ok,
            'holdings_ok': holdings_ok, 'positions': len(positions),
            'price_status': price['status'], 'holdings_status': tiger['status']}


FILES = ('prices/price_result.json', 'prices/price_view.json', 'prices/branch.json',
         'prices/price_message.txt', 'prices/prior.json', 'prices/price.pdf', 'holdings/daily.json',
         'holdings/daily.pdf', 'holdings/tiger_status.json')


def canonical(root, directory, meta, identity, correction=False, original_id=None):
    source = directory / 'sources'
    price = json.loads((source / 'prices/price_result.json').read_text())
    view = json.loads((source / 'prices/price_view.json').read_text())
    portfolio = json.loads((source / 'holdings/daily.json').read_text())
    state = branch_state(source)
    holdings_session = portfolio['accounts'][0]['daily_performance']['session']
    if holdings_session != meta.get('holdings_session', holdings_session):
        state['partial'] = True
    rules = json.loads((Path(meta['inputs']) / 'alerts.json').read_text())['alerts']
    with _IMPORT_LOCK:
        renderer, renderer_sha = _preserved(root, 'price_summary_view.py')
        prior = json.loads((source / 'prices/prior.json').read_text())
        expected_view = renderer.build(price, prior=prior, definitions=rules, historical=price['mode'] != 'live')
        require(expected_view == view, 'DAILY_RULE_VIEW_CHANGED')
        require(len(view['rows']) == sum(r.get('enabled') is True for r in rules), 'DAILY_FULL_RULE_SCOPE_REQUIRED')
        composer, composer_sha = _preserved(root, 'compose_digest.py')
        old = sys.modules.get('price_summary_view'); sys.modules['price_summary_view'] = renderer
        subject = ('[CODEX] DAILY HOLDING UPDATE | ' + meta['ny_date'] + ' ' + meta['slot']
                   + ' NY | ' + ('PARTIAL' if state['partial'] else 'COMPLETE')
                   + (' | ACCEPTANCE' if meta['purpose'] == 'test' else '')
                   + (' | 补发' if correction else ''))
        try:
            payload = composer.compose(portfolio, (source / 'prices/price_message.txt').read_text(),
                source / 'holdings/daily.pdf', subject, meta['recipient'],
                historical=meta['purpose'] == 'test', price_view=view)
        finally:
            if old is None:
                sys.modules.pop('price_summary_view', None)
            else:
                sys.modules['price_summary_view'] = old
    if correction:
        require(isinstance(original_id, str) and original_id, 'DAILY_ORIGINAL_MESSAGE_REQUIRED')
    e = html.escape
    banner = ('<section style="border:2px solid #a16b00;padding:12px"><h2>[CODEX] '
              + ('PARTIAL · 部分数据缺口' if state['partial'] else '完整业务范围已生成')
              + (' · 补发' if correction else '') + '</h2><p>执行：定时 '
              + ('验收测试，独立去重空间，非生产槽位完成记录' if meta['purpose'] == 'test' else '生产并行发送')
              + '；NY 槽位 ' + e(meta['ny_date'] + ' ' + meta['slot']) + '；Work ' + e(identity)
              + '</p><p>价格观察截止 ' + e(price['as_of']) + '；价格交易日 ' + e(price['session'])
              + '；持仓 P&amp;L 对应已完成交易日 ' + e(holdings_session)
              + '。持仓/资产读取时点在正文单独列出。13:00 的当前持仓不代表已验证当日实时盈亏。</p><p>'
              + ('本次为历史/恢复重评，不证明原槽位实时送达，不产生新穿越。' if price['retrospective'] else
                 '阈值达到不是买入建议；新增信号记录不自动代表新穿越。')
              + (' 原始邮件 ID：' + e(original_id) if correction else '') + '</p></section>')
    body = payload['payload']['parts'][0]['body']['content']
    at = body.index('>', body.index('<body')) + 1
    payload['payload']['parts'][0]['body']['content'] = body[:at] + banner + body[at:]
    raw = (source / 'prices/price.pdf').read_bytes()
    payload['payload']['parts'].append({'mime_type': 'application/pdf', 'filename': 'Niulai_Price_Alert_Details.pdf',
        'content_disposition': 'attachment', 'body': {'base64_url_content': base64.urlsafe_b64encode(raw).decode()}})
    fp = validate_payload(payload, meta['recipient'], meta['recipient'])
    return payload, {'digest': fp['digest'], 'composer_sha256': composer_sha, 'renderer_sha256': renderer_sha,
                     'files': {name: sha((source / name).read_bytes()) for name in FILES}, **state}


def compose(root, out, meta, identity, correction=False, original_id=None):
    root = Path(root).resolve(); out = private(root, out, True)
    directory = private(root, out / 'mail' / ('correction' if correction else 'initial'), True)
    payload_path = directory / 'payload.json'
    if payload_path.exists():
        return validate(root, directory, meta, identity)
    for name in FILES:
        src = private(root, out / name); dst = private(root, directory / 'sources' / name)
        require(src.is_file(), 'DAILY_SOURCE_SNAPSHOT_REQUIRED')
        private(root, dst.parent, True)
        if dst.exists():
            require(sha(dst.read_bytes()) == sha(src.read_bytes()), 'DAILY_SOURCE_SNAPSHOT_CHANGED')
        else:
            shutil.copyfile(src, dst); dst.chmod(0o600)
    payload, integrity = canonical(root, directory, meta, identity, correction, original_id)
    atomic(directory / 'integrity.json', {**integrity, 'correction': correction, 'original_id': original_id})
    atomic(payload_path, payload)
    return {'directory': str(directory), **integrity}


def validate(root, directory, meta, identity):
    root = Path(root).resolve(); directory = private(root, directory)
    integrity = json.loads((directory / 'integrity.json').read_text())
    payload, observed = canonical(root, directory, meta, identity, integrity['correction'], integrity['original_id'])
    require(observed == {k: v for k, v in integrity.items() if k not in ('correction', 'original_id')}, 'DAILY_IMMUTABLE_SOURCE_CHANGED')
    assert_content_parity(payload, json.loads((directory / 'payload.json').read_text()), meta['recipient'], meta['recipient'])
    return {'directory': str(directory), **observed}
