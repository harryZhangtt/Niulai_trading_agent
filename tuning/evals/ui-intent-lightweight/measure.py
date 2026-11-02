"""Optional existing-tokenizer measurement; never install dependencies."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'tuning/runtime/ui-intent-lightweight-20261102'
os.environ['TIKTOKEN_CACHE_DIR'] = str(ROOT / 'tuning/runtime/tokenizer-cache')
try:
    import tiktoken
except ImportError:
    raise SystemExit('TIKTOKEN_UNAVAILABLE_NO_INSTALL')

encoding = tiktoken.get_encoding('o200k_base')
result = {'kind': 'nonbilled_serialized_text_proxy',
          'tokenizer': 'tiktoken/' + importlib.metadata.version('tiktoken') + '/o200k_base',
          'scope': 'Serialized text only; excludes host framing, tools, output, reasoning and caching. Actual reported model usage is separate.',
          'texts': {}}
for label, path in [('baseline_policy', ROOT / 'ui/ROUTING.md'),
                    ('candidate_policy', ROOT / 'ui/portable/INTENT-CARD.md')]:
    raw = path.read_bytes()
    result['texts'][label] = {'bytes': len(raw), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                            'tokens_proxy': len(encoding.encode(raw.decode()))}
for claim in RUNTIME.glob('*-v*/*-claim.json'):
    value = json.loads(claim.read_text())
    raw = Path(value['prompt_ref']['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == value['prompt_raw_sha256']
    result['texts'][value['attempt_id']] = {'bytes': len(raw), 'raw_sha256': value['prompt_raw_sha256'],
                                           'tokens_proxy': len(encoding.encode(raw.decode()))}
path = RUNTIME / ('proxies-' + str(len(result['texts'])) + '-texts.json')
with path.open('x') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
print(json.dumps(result, indent=2))
