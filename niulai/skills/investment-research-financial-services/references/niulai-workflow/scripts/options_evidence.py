#!/usr/bin/env python3
"""Opt-in equity-options completion gate; never certify source truth or a fill.

Historical records without the profile are exempt. Research-only partial records
remain non-actionable. Current supported topology is long call / call debit spread.
The ordinary underlying-research, review and persistence gates still apply.
"""
import argparse
import base64
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

import options_payoff_checks as payoff
import options_scenario_checks as scenario
import evidence_crosscheck as crosscheck
from rationale_guard import REPORT_CSS, publication_times

VERSION = '2026-10-24-options-evidence-1'
METHODS = {m.__name__ + '.py': m for m in (payoff, scenario, crosscheck)}
CHECKS = {'contract_terms', 'quote_independence', 'iv_assumptions', 'exercise_and_carry',
          'model_adequacy', 'horizon_thesis', 'catalyst_and_falsifier', 'decision_rationale', 'rendered_payoff'}


def fail(message):
    raise ValueError('Options evidence: ' + message)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError('timezone')
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        fail('timezone-aware timestamp required')


def text(value):
    if not isinstance(value, str) or not value.strip():
        fail('nonempty explanation required')
    return value


def method_hashes():
    return {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in METHODS.items()}


def payoff_svg(result):
    """Canonical same-budget expiry plot, derived from recomputed output only."""
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 570" role="img" aria-label="Options and shares expiry payoff comparison">',
             '<rect width="760" height="570" fill="white"/>',
             '<text x="35" y="24" font-family="sans-serif" font-size="16">Expiry P&amp;L, same budget; intrinsic cash-equivalent diagnostic</text>']
    for panel, name in enumerate(('requested', 'usd_1000')):
        case = result['budget_cases'][name]
        grids = [case['options']['grid'], case['shares']['grid']]
        xs = [float(r['expiry_stock_price']) for r in grids[0]]
        ys = [float(r['pnl']) for grid in grids for r in grid] + [0.0]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        dx, dy = max(xmax - xmin, 1), max(ymax - ymin, 1)
        top = 65 + panel * 250
        x = lambda value: 80 + (value - xmin) / dx * 620
        y = lambda value: top + 160 - (value - ymin) / dy * 160
        parts += [f'<text x="35" y="{top-15}" font-family="sans-serif" font-size="13">{escape(name)} budget USD {escape(case["budget"])}; blue=options, green=shares</text>',
                  f'<path d="M80,{top} V{top+160} H700" fill="none" stroke="#333"/>',
                  f'<line x1="80" x2="700" y1="{y(0):.3f}" y2="{y(0):.3f}" stroke="#888" stroke-dasharray="4 4"/>']
        for grid, color in zip(grids, ('#2563eb', '#15803d')):
            points = ' '.join(f'{x(float(r["expiry_stock_price"])):.3f},{y(float(r["pnl"])):.3f}' for r in grid)
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        parts += [f'<text x="80" y="{top+180}" font-size="11">Stock price {xmin:g} → {xmax:g}; P&amp;L USD {ymin:g} → {ymax:g}</text>',
                  f'<text x="80" y="{top+199}" font-size="11">Option maximum loss USD {escape(case["options"]["max_loss_amount"])}; opening cost USD {escape(case["options"]["opening_cash_required"])}</text>']
    parts += ['<text x="35" y="560" font-size="11">Not pre-expiry fair value. Physical exercise, assignment funding, closing fees and taxes require review.</text>', '</svg>']
    return '\n'.join(parts)


def visible_payoff(document, expected, labels, *, image_uri=None):
    """Conservative static presentation admission, not a browser visibility proof.

Only the maintained report stylesheet is admitted. Dynamic/external styling and
inline styles are rejected rather than partially interpreted. Actual rendering,
layout legibility and honest independent inspection still require human/agent
review; this parser does not certify every browser layout or accessibility rule.
"""
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []; self.figure_visible = False; self.invalid = False
            self.visible_text = []; self.style_text = []; self.in_style = False
            self.offsets = [0]
            for line in document.splitlines(keepends=True): self.offsets.append(self.offsets[-1] + len(line))
        def handle_starttag(self, tag, attrs):
            attr = dict(attrs)
            hidden = self.stack[-1][1] if self.stack else False
            hidden = (hidden or 'hidden' in attr or attr.get('aria-hidden', '').lower() == 'true'
                      or tag in {'head', 'title', 'style', 'template', 'script', 'noscript', 'iframe', 'object', 'textarea', 'xmp', 'plaintext'}
                      or (tag in {'details', 'dialog'} and 'open' not in attr))
            if (tag in {'script', 'iframe', 'object', 'embed', 'foreignobject'}
                    or (tag == 'link' and 'stylesheet' in attr.get('rel', '').lower())
                    or 'style' in attr or any(key.startswith('on') for key in attr)
                    or any(re.match(r'\s*javascript:', value or '', re.I) for value in attr.values())):
                self.invalid = True
            if tag == 'style': self.in_style = True; self.style_text = []
            line, col = self.getpos(); offset = self.offsets[line-1] + col
            if image_uri is None and expected and tag == 'svg' and not hidden and any(t == 'body' for t, _ in self.stack) and document.startswith(expected, offset):
                self.figure_visible = True
            if image_uri is not None and tag == 'img' and not hidden and any(t == 'body' for t, _ in self.stack) and attr.get('src') == image_uri:
                self.figure_visible = True
            if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
                self.stack.append((tag, hidden))
        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs); self.handle_endtag(tag)
        def handle_endtag(self, tag):
            if tag == 'style':
                if ''.join(self.style_text).strip() != REPORT_CSS: self.invalid = True
                self.in_style = False
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]; break
        def handle_data(self, data):
            if self.in_style: self.style_text.append(data)
            if self.stack and not self.stack[-1][1] and any(t == 'body' for t, _ in self.stack):
                self.visible_text.append(data)
    parser = Parser(); parser.feed(document); parser.close()
    visible = ' '.join(' '.join(parser.visible_text).split())
    if parser.invalid or not parser.figure_visible or any(' '.join(label.split()) not in visible for label in labels):
        fail('payoff/IV presentation is hidden, dynamic, externally styled or not visibly embedded in static body content')


MODEL_SELECTION_VERSION = '2026-10-24-options-model-selection-1'
MODEL_SELECTION_EFFECTIVE_AT = '2026-10-24T00:18:03Z'


def selection_required(record, block, observed_publication_times):
    dates = [record['subject']['cutoff']] + list(observed_publication_times) + publication_times(record.get('persistence', {}))
    return 'model_selection' in block or any(stamp(t) >= stamp(MODEL_SELECTION_EFFECTIVE_AT) for t in dates)


def selection_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_selection(selection, cutoff, subject, legs, scenarios, structured, pair, raw, payoff_packet):
    """Optional numerical adapters are invoked only for the selected method.

    Date-level FD is not an intraday American engine; surface remains diagnostic.
    Source truth and carry forecast adequacy still require the bound reviewer.
    """
    if not isinstance(selection,dict) or selection.get('version') != MODEL_SELECTION_VERSION:
        fail('versioned model_selection required for new actionable options')
    exercise = selection.get('exercise', {})
    if exercise.get('route') not in ('analytical_equivalence','american_fd'):
        fail('explicit analytical_equivalence or american_fd exercise route required')
    carry = structured(exercise.get('carry_artifact_id'))
    try:
        carry_end = date.fromisoformat(carry['valid_through'])
        if carry_end.isoformat() != carry['valid_through']: raise ValueError()
    except (ValueError,TypeError,KeyError): fail('valid carry horizon date required')
    if (carry.get('subject') != subject or carry.get('verification') != 'source_verified'
            or stamp(carry.get('available_at')) > cutoff
            or carry_end < max(date.fromisoformat(leg['expiry']) for leg in legs.values())):
        fail('dated source-verified dividend/carry assumptions required through expiry')
    text(carry.get('finding'))
    refs = carry.get('source_artifact_ids')
    if not isinstance(refs,list) or not refs: fail('dividend/carry source snapshots required')
    for aid in refs: raw(aid)
    if not isinstance(carry.get('dividends'),list): fail('explicit dividend schedule required')
    for field in ('rate','yield'):
        if type(carry.get(field)) not in (int,float) or not math.isfinite(carry[field]): fail('numeric carry required')
    for cid, inp in scenarios.items():
        if any(inp[field] != carry[field] for field in ('rate','yield')): fail('carry differs from exact scenario input')
    labels = []
    if exercise['route'] == 'analytical_equivalence':
        if carry['yield'] != 0 or carry['rate'] < 0 or carry['dividends'] or any(l['right'] != 'call' for l in legs.values()):
            fail('analytical equivalence requires calls, verified zero dividends/yield and nonnegative rates')
        text(exercise.get('equivalence_rationale'))
    else:
        # Import adapter lazily; its QuantLib dependency remains lazy too.
        import options_american_checks as american
        if exercise.get('method_sha256') != hashlib.sha256(Path(american.__file__).read_bytes()).hexdigest():
            fail('American method hash missing/stale')
        cases = exercise.get('cases')
        ids = {l['contract_id'] for l in legs.values()}
        if not isinstance(cases,list) or len(cases)!=len(ids) or {x.get('contract_id') for x in cases}!=ids:
            fail('American calculation required for every exact leg')
        for ref in cases:
            inp, out = pair(ref,american)
            cid = ref['contract_id']; leg = next(l for l in legs.values() if l['contract_id']==cid); base=scenarios[cid]
            if (inp.get('contract_id') != cid or inp.get('as_of') != cutoff.date().isoformat()
                    or inp.get('expiry') != leg['expiry'] or inp.get('exercise') != leg['exercise_style']
                    or inp.get('kind') != leg['right'] or inp.get('dividends',[]) != carry['dividends']):
                fail('American identity/date/style/dividends differ from exact leg')
            if any(Decimal(str(inp.get(k))) != Decimal(str(base[k])) for k in ('spot','strike','rate','yield','volatility')):
                fail('American inputs differ from exact scenario')
            expected=[]
            for row in base['scenarios']:
                if float(row['elapsed_days']) != int(row['elapsed_days']): fail('American adapter requires whole-date stress horizons')
                expected.append({'id':row['id'],'as_of':(cutoff+timedelta(days=row['elapsed_days'])).date().isoformat(),
                                 'spot':row['spot'],'volatility':row['volatility']})
            if inp.get('scenarios',[]) != expected: fail('American stress cases differ from linked scenario inputs')
        labels.append('American model: date-level FD diagnostic, not an executable quote')
        labels.append('American FD IV: European quote-implied proxy or stated assumption; not American-calibrated IV')
    surface = selection.get('surface', {})
    if surface.get('route') == 'not_used':
        text(surface.get('reason'))
    elif surface.get('route') == 'diagnostic':
        import options_surface_checks as surface_method
        if surface.get('method_sha256') != hashlib.sha256(Path(surface_method.__file__).read_bytes()).hexdigest():
            fail('surface method hash missing/stale')
        if surface.get('use') != 'diagnostic_only': fail('surface cannot be executable or a trade-pricing approval')
        inp,out = pair(surface,surface_method)
        if inp['symbol'] != subject or stamp(inp['valuation_at']) > cutoff or not out['nodes'] or out.get('executable') is not False:
            fail('surface subject/cutoff/nonempty diagnostic mismatch')
        text(surface.get('limitations'))
        labels.append('Surface use: '+('historical diagnostic' if inp['mode']=='historical_diagnostic' else 'eligible-quote European diagnostic')+' only; not executable')
    else:
        fail('surface route must be not_used with reason or linked diagnostic')
    path_refs = set()
    path = selection.get('path_review', {})
    if path.get('route') == 'conditional_scenarios':
        if path.get('probability_basis') != 'conditional_scenarios_not_calibrated' or path.get('quantitative_probabilities', 'missing') is not None:
            fail('conditional scenarios cannot claim calibrated/numerical outcome probabilities')
        text(path.get('reason'))
        labels.append('Probability basis: conditional_scenarios_not_calibrated')
    elif path.get('route') == 'simulated_paths':
        path_labels, path_refs = validate_paths(path, payoff_packet, structured, pair, raw)
        labels.extend(path_labels)
    else:
        fail('explicit conditional_scenarios or simulated_paths path_review required')
    return labels, path_refs


def replay_visual_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                if image.format!='PNG' or image.width*image.height>16_000_000: raise ValueError('image size/type')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:image.load()
        except (ImportError,ValueError,OSError,SyntaxError) as exc:fail('invalid or unavailable PNG replay decoder: '+str(exc))
        return 'png'
    try:
        root=ET.fromstring(data)
        if root.tag.split('}')[-1]!='svg' or not list(root): raise ValueError('empty SVG')
    except (ET.ParseError,ValueError):fail('replay visual must be a valid saved PNG or nonempty SVG')
    return 'svg'


def validate_paths(path, payoff_packet, structured, pair, raw):
    # Adapter and optional bootstrap dependencies are loaded only for this route.
    import options_path_checks as path_method
    if path.get('method_sha256') != hashlib.sha256(Path(path_method.__file__).read_bytes()).hexdigest():
        fail('path method hash missing/stale')
    try:
        inp, out = pair(path, path_method)
    except ImportError as exc:
        fail('optional path dependency unavailable: '+str(exc))
    if inp.get('payoff_packet') != payoff_packet:
        fail('path simulation must bind exact payoff contracts/quotes/fees/budget/cutoff')
    if Decimal(str(inp.get('spot'))) != Decimal(payoff_packet['underlying_quote']['quote']['ask']):
        fail('path initial spot differs from linked payoff quote')
    if path.get('probability_basis') != 'conditional_assumption_not_calibrated' or out.get('status') != path['probability_basis']:
        fail('simulated probabilities are conditional assumptions, not calibrated forecasts')
    cutoff = stamp(payoff_packet['as_of']); refs={path['input_artifact_id'],path['output_artifact_id']}
    origin_id=path.get('origin_artifact_id'); origin=structured(origin_id); refs.add(origin_id)
    import exchange_calendars as xc
    cal=xc.get_calendar('XNYS',start=inp['start_session'],end=out['expiry'])
    close=cal.session_close(inp['start_session']).to_pydatetime()
    if (origin.get('subject') != payoff_packet['subject'] or origin.get('session') != inp['start_session']
            or origin.get('price_basis') != 'regular_session_close' or stamp(origin.get('observed_at')) != close
            or stamp(origin.get('available_at')) > cutoff or stamp(origin['available_at']) < close
            or Decimal(str(origin.get('price'))) != Decimal(str(inp['spot']))):
        fail('path origin must be actual supported regular-session close, not a shifted current quote')
    text(origin.get('source_ref')); source=origin.get('source_artifact_id');raw(source);refs.add(source)
    assumption_id=path.get('assumptions_artifact_id'); assumptions=structured(assumption_id);refs.add(assumption_id)
    if (assumptions.get('simulation') != inp['simulation'] or assumptions.get('history','missing') != inp['history']
            or stamp(assumptions.get('available_at')) > cutoff
            or assumptions.get('probability_basis') != path['probability_basis']):
        fail('path assumptions/history/probability provenance differs from calculation')
    text(assumptions.get('finding'))
    sources=assumptions.get('source_artifact_ids')
    if not isinstance(sources,list) or not sources: fail('path assumption/history source artifacts required')
    for source in sources:raw(source);refs.add(source)
    replay_id=path.get('replay_manifest_artifact_id'); replay=structured(replay_id);refs.add(replay_id)
    expected={'start_session':out['start_session'],'future_sessions':out['calendar']['future_sessions'],
              'illustrative_paths':out['illustrative_paths'],'daily_stock_fan':out['daily_stock_fan']}
    if (replay.get('version') != 1 or type(replay['version']) is not int
            or replay.get('input_sha256') != out['input_sha256']
            or replay.get('output_sha256') != hashlib.sha256(raw(path['output_artifact_id'])).hexdigest()
            or replay.get('replay_data') != expected
            or replay.get('claim_scope') != 'sampled_stock_paths_not_interim_option_pnl'):
        fail('replay manifest must bind exact simulation output/sampled stock paths/time grid')
    visuals=replay.get('visual_artifact_ids')
    if not isinstance(visuals,list) or not visuals or len(set(visuals))!=len(visuals): fail('saved replay visualization artifacts required')
    for visual in visuals:
        data=raw(visual);refs.add(visual)
        replay_visual_type(data)
    return ['Probability basis: conditional_assumption_not_calibrated',
            'Replay: sampled stock paths, not interim option profits; sampling intervals exclude model uncertainty'], refs


def validate(record, *, observed_publication_times=()):
    opted = (record.get('instrument_profile') == 'equity_options'
             or record.get('subject', {}).get('security_type') == 'equity_options'
             or 'options_evidence' in record)
    if not opted:
        return {'status': 'exempt', 'actionable_certified': False}
    block = record.get('options_evidence')
    if not isinstance(block, dict) or block.get('version') != VERSION:
        fail('versioned options_evidence required for equity_options profile')
    if record.get('instrument_profile') != 'equity_options':
        fail('explicit equity_options instrument_profile required')
    if block.get('status') == 'research_only':
        if record.get('status') == 'complete' or record.get('result', {}).get('recommendation') != 'none':
            fail('research-only or blocked analysis cannot claim complete/actionable status')
        if not isinstance(block.get('blockers'), list) or not block['blockers']:
            fail('research-only analysis must state blockers')
        for blocker in block['blockers']: text(blocker)
        return {'status': 'research_only', 'actionable_certified': False, 'blockers': block['blockers']}
    if block.get('status') != 'actionable':
        fail('expected actionable or research_only status')
    if record.get('scope') != 'company_full':
        fail('actionable options require full underlying-company research')
    if block.get('method_sha256') != method_hashes():
        fail('calculator revision missing/stale; restore pinned methods for historical revalidation')
    arts = {a['id']: a for a in record.get('artifacts', [])}
    if len(arts) != len(record.get('artifacts', [])):
        fail('duplicate artifact IDs')
    needed = set()
    def raw(aid):
        if aid not in arts: fail('missing artifact ' + str(aid))
        a = arts[aid]; path = Path(a.get('path', ''))
        if not path.is_absolute() or not path.is_file(): fail('missing/relative artifact ' + str(aid))
        value = path.read_bytes()
        if not value or hashlib.sha256(value).hexdigest() != a.get('sha256'): fail('stale hash ' + str(aid))
        needed.add(aid)
        return value
    def structured(aid):
        return crosscheck.decode_packet(raw(aid))
    def pair(ref, module):
        if not isinstance(ref, dict) or not ref.get('input_artifact_id') or not ref.get('output_artifact_id'):
            fail('linked calculation input/output required')
        packet = getattr(module, 'decode_packet', crosscheck.decode_packet)(raw(ref['input_artifact_id']))
        computed = module.calculate(packet)
        if structured(ref['output_artifact_id']) != computed:
            fail('calculation output differs from recomputation')
        return packet, computed
    packet, calculated = pair(block.get('payoff'), payoff)
    cutoff = stamp(record['subject']['cutoff'])
    if packet['subject'] != record['subject']['ticker'] or stamp(packet['as_of']) != cutoff:
        fail('payoff subject/cutoff differs from research record')
    if not calculated['live_input_gate_passed'] or calculated['research_only'] or not calculated['contract_deliverable_verified']:
        fail('live quote/deliverable/depth gates not passed')
    if calculated['budget_cases']['requested']['options']['modeled_contracts'] < 1:
        fail('requested budget cannot establish an actionable option position')
    legs = {k: packet['strategy'][k] for k in ('long_leg', 'short_leg') if packet['strategy'][k] is not None}
    contract_fields = ('underlying', 'contract_id', 'right', 'strike', 'expiry', 'exercise_style', 'multiplier', 'standard_deliverable_confirmed')
    contracts = [{k: leg[k] for k in contract_fields + (('root_mapping',) if 'root_mapping' in leg else ())}
                 for leg in legs.values()]
    if block.get('contracts') != contracts: fail('exact contract terms missing or inconsistent')
    contract_terms_id = block.get('contract_terms_artifact_id')
    terms = structured(contract_terms_id)
    if terms.get('contracts') != contracts or stamp(terms.get('available_at')) > cutoff:
        fail('contract source snapshot does not bind exact terms/cutoff')
    text(terms.get('source_ref'))
    # Recompute each contract's diagnostic and prevent unrelated/assumed IV laundering.
    cases = block.get('scenario_cases')
    if not isinstance(cases, list) or len(cases) != len(legs): fail('one scenario packet per exact contract required')
    seen = set(); labels = []; scenario_inputs = {}
    for case in cases:
        cid = case.get('contract_id')
        if cid in seen or cid not in {leg['contract_id'] for leg in legs.values()}: fail('duplicate/unknown scenario contract')
        seen.add(cid); leg = next(l for l in legs.values() if l['contract_id'] == cid)
        inp, out = pair(case, scenario)
        scenario_inputs[cid] = inp
        expiry_at = stamp(case.get('expiry_at'))
        years = (expiry_at - cutoff).total_seconds() / (365 * 86400)
        if expiry_at.date().isoformat() != leg['expiry'] or years <= 0 or not math.isclose(inp['years'], years, rel_tol=0, abs_tol=1e-10):
            fail('scenario ACT/365 horizon differs from exact contract expiry')
        if inp['kind'] != 'call' or Decimal(str(inp['strike'])) != Decimal(leg['strike']) or Decimal(str(inp['spot'])) != Decimal(packet['underlying_quote']['quote']['ask']):
            fail('scenario identity/spot/strike differs from payoff inputs')
        if inp['quotes'] != {k: float(leg['quote'][k]) for k in ('bid', 'ask')}:
            fail('scenario IV inversion must use the exact linked bid/ask')
        iv = case.get('iv', {})
        if iv.get('basis') not in ('observed_model_implied', 'assumed') or iv.get('value') != inp['volatility']:
            fail('IV must be labeled observed_model_implied or assumed and match model input')
        iv_source = structured(iv.get('source_artifact_id')); text(iv.get('rationale'))
        if iv_source.get('contract_id') != cid or iv_source.get('basis') != iv['basis'] or iv_source.get('value') != iv['value'] or stamp(iv_source.get('available_at')) > cutoff:
            fail('IV provenance identity/basis/value/cutoff mismatch')
        text(iv_source.get('source_ref'))
        if iv['basis'] == 'observed_model_implied' and not out['quote_iv']['bid_iv'] <= inp['volatility'] <= out['quote_iv']['ask_iv']:
            fail('observed-model-implied IV lies outside linked quote inversion interval')
        stresses = case.get('stress_case_ids', {})
        if set(stresses) != {'price_down', 'delay', 'iv_crush', 'combined'} or len(set(stresses.values())) != 4:
            fail('four distinct price/delay/IV/combined stress cases required')
        by = {s['id']: s for s in inp['scenarios']}
        for kind, sid in stresses.items():
            s = by.get(sid)
            if s is None: fail('stress references absent scenario')
            if kind in ('price_down', 'combined') and s['spot'] >= inp['spot']: fail('price-down stress is not adverse')
            if kind in ('delay', 'combined') and s['elapsed_days'] <= 0: fail('delay stress has no elapsed time')
            if kind in ('iv_crush', 'combined') and s['volatility'] >= inp['volatility']: fail('IV-crush stress does not reduce IV')
        labels.append(f'IV basis: {cid}: {iv["basis"]}')
    model_selection = block.get('model_selection')
    if selection_required(record, block, observed_publication_times):
        selection_labels, path_review_refs = validate_selection(model_selection, cutoff, packet['subject'], legs, scenario_inputs, structured, pair, raw, packet)
        labels.extend(selection_labels)
    targets = {'underlying.ask': (packet['underlying_quote']['quote'], 'ask', None)}
    for name, leg in legs.items():
        for side in ('bid', 'ask'): targets[name + '.' + side] = (leg['quote'], side, leg['contract_id'])
    crossrefs = block.get('crosschecks', [])
    if not isinstance(crossrefs, list) or len(crossrefs) != len(targets) or {c.get('target') for c in crossrefs} != set(targets):
        fail('every used stock/option quote side requires a crosscheck')
    for ref in crossrefs:
        inp, out = pair(ref, crosscheck)
        if out['status'] != 'corroborated' or not inp['require_source_hashes'] or stamp(inp['as_of']) != cutoff:
            fail('quote crosscheck lacks independent current corroboration and source hashes')
        if (inp['max_age_seconds'] > packet['quote_policy']['max_age_seconds']
                or inp['max_time_skew_seconds'] > packet['quote_policy']['max_quote_skew_seconds']):
            fail('crosscheck cannot weaken payoff quote freshness/skew policy')
        quote, side, cid = targets[ref['target']]
        kind = 'option_quote' if cid else 'numeric'
        if inp['comparison_kind'] != kind: fail('wrong crosscheck instrument kind')
        snapshots = ref.get('source_artifact_ids')
        if not isinstance(snapshots, list) or len(snapshots) != 2:
            fail('both crosscheck source payload artifacts required')
        for observation, source_id in zip(inp['observations'], snapshots):
            raw(source_id)
            if arts[source_id]['sha256'] != observation['source']['sha256']:
                fail('crosscheck source payload hash does not match actual artifact')
            if observation.get('subject') != packet['subject'] or observation.get('unit') != 'USD/share' or observation.get('basis') != 'quote':
                fail('crosscheck quote subject/unit/basis mismatch')
            if cid and (observation.get('contract_key') != cid or observation.get('side') != side): fail('crosscheck contract/side mismatch')
            if not cid and observation.get('metric') != 'underlying_ask': fail('underlying crosscheck must explicitly be ask')
        if not any(Decimal(o['value']) == Decimal(quote[side]) and stamp(o['observed_at']) == stamp(quote['timestamp']) for o in inp['observations']):
            fail('crosscheck does not bind the actual payoff quote/value timestamp')
    figure_id = block.get('visualization_artifact_id')
    figure = raw(figure_id).decode()
    if figure != payoff_svg(calculated): fail('payoff visualization missing/stale/noncanonical')
    report_id = record['result']['report_artifact_id']; report = raw(report_id).decode()
    if figure not in report or any(label not in report for label in labels):
        fail('visible report lacks exact payoff visualization or explicit per-contract IV labels')
    visible_payoff(report, figure, labels)
    if selection_required(record, block, observed_publication_times) and model_selection['path_review']['route']=='simulated_paths':
        replay=structured(model_selection['path_review']['replay_manifest_artifact_id'])
        for aid in replay['visual_artifact_ids']:
            data=raw(aid)
            if replay_visual_type(data)=='svg':
                visible_payoff(report,data.decode(),[])
            else:
                uri='data:image/png;base64,'+base64.b64encode(data).decode()
                visible_payoff(report,'',[],image_uri=uri)
    review_id = block.get('review_artifact_id'); review = structured(review_id)
    author = record['audit']['author_id']; reviewer = record['audit']['independent_review']['reviewer_id']
    if review.get('reviewer_id') != reviewer or author.split('/')[-1] == reviewer.split('/')[-1] or review.get('status') != 'approved_options' or review.get('version') != VERSION:
        fail('independent options review missing/unapproved')
    if review.get('method_sha256') != block['method_sha256'] or review.get('contracts') != contracts:
        fail('review does not bind calculator versions and exact contracts')
    if selection_required(record, block, observed_publication_times) and review.get('model_selection_sha256') != selection_digest(model_selection):
        fail('independent review model_selection binding missing/stale')
    checks = review.get('checks', {})
    if set(checks) != CHECKS: fail('required options critic steps missing')
    for check in checks.values():
        if check.get('status') != 'reviewed': fail('options critic step not reviewed')
        text(check.get('finding'))
        refs = check.get('artifact_refs')
        if not isinstance(refs, list) or not refs: fail('critic finding lacks evidence artifacts')
        for aid in refs: raw(aid)
    if selection_required(record, block, observed_publication_times):
        text(review.get('path_probability_finding'))
        if not path_review_refs <= set(review.get('path_review_artifact_ids', [])):
            fail('independent path finding must review all path/source/replay artifacts')
        if model_selection['path_review']['route']=='simulated_paths':
            text(review.get('path_replay_visual_finding'))
            if review.get('path_replay_inspection_method') not in ('rendered_html','native_preview','image_inspection'):
                fail('actual rendered replay inspection required')
        exercise = model_selection['exercise']; carry_id = exercise['carry_artifact_id']
        carry_refs = {carry_id, *structured(carry_id)['source_artifact_ids']}
        if not carry_refs <= set(checks['exercise_and_carry']['artifact_refs']):
            fail('exercise/carry finding must explicitly review carry and source snapshots')
        calculation_refs = set()
        for ref in exercise.get('cases', []) if exercise['route']=='american_fd' else []:
            calculation_refs.update([ref['input_artifact_id'],ref['output_artifact_id']])
        if model_selection['surface']['route']=='diagnostic':
            calculation_refs.update([model_selection['surface']['input_artifact_id'],model_selection['surface']['output_artifact_id']])
        if not calculation_refs <= set(checks['model_adequacy']['artifact_refs']):
            fail('model adequacy finding must explicitly review advanced input/output artifacts')
    if review.get('visual_inspection_method') not in ('rendered_html', 'native_preview'):
        fail('rendered payoff inspection required')
    for aid in needed - {review_id}:
        if review.get('artifact_hashes', {}).get(aid) != arts[aid]['sha256']: fail('review hash missing/stale: ' + aid)
    if not needed <= set(record['audit']['independent_review'].get('reviewed_artifact_ids', [])):
        fail('main independent review did not cover all options artifacts')
    if record.get('status') == 'complete':
        receipts = {r['artifact_id']: r for r in record.get('persistence', {}).get('receipts', [])}
        if not needed <= set(receipts) or any(receipts[aid].get('sha256') != arts[aid]['sha256'] for aid in needed):
            fail('complete options package lacks matching save receipts')
    return {'status': 'validated', 'actionable_certified': False, 'actionable_evidence_validated': True,
            'version': VERSION, 'checked_artifacts': len(needed), 'semantic_truth_verified': False,
            'visual_layout_certified': False,
            'meaning': 'Structural/arithmetic evidence gate only; other research and actual persistence readback gates remain mandatory.'}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--record', required=True); a = p.parse_args()
    try: result, code = validate(json.loads(Path(a.record).read_text())), 0
    except (ValueError, KeyError, TypeError, OSError) as exc: result, code = {'status': 'rejected', 'error': str(exc)}, 2
    print(json.dumps(result, indent=2)); return code


if __name__ == '__main__': raise SystemExit(main())
