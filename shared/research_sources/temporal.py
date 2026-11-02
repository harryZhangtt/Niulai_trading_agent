"""Host-only point-in-time broker over an explicitly pinned local corpus.

No retrieval, provider, model, or clock calls occur here. Call this boundary before
constructing either comparison arm's prompt/tools. Only ``search``, ``open`` and
``worker_packet`` belong on the worker side; ``host_diagnostics`` contains future
identities/counts and must remain on the host. This is an application boundary,
not an OS sandbox or a cure for future knowledge in model weights.

Publication time is never proof that today's body existed then. Strict admission
uses the original acquisition observation time, plus all declared version/update
lower bounds. A later Store recording is an additional conservative lower bound.
An old issuer document captured today may be a useful reconstruction; declaring
that fact does not put it in a strict historical worker packet. Hashes establish
byte integrity and identity, not truthful timestamps or authenticated history.
"""
from copy import deepcopy
import re

from .artifacts import SourceError, digest, read, require
from .store import Store, instant


VERSION = 'pinned-temporal-v1'
_HASH = re.compile(r'[a-f0-9]{64}')
_CODE = re.compile(r'[A-Z][A-Z_0-9]{0,99}')
_BINDING = {'observation_id', 'revision', 'lifecycle_revision'}


def _time(value):
    try:
        return instant(value)
    except SourceError:
        raise SourceError('TEMPORAL_TIMESTAMP_INVALID') from None


def _ref(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'} and
            isinstance(value.get('sha256'), str) and _HASH.fullmatch(value['sha256']),
            'TEMPORAL_SOURCE_REF_INVALID')
    return deepcopy(value)


def _code(exc):
    return str(exc) if isinstance(exc, SourceError) and _CODE.fullmatch(str(exc)) else 'TEMPORAL_ARTIFACT_UNAVAILABLE'


def _pin(value):
    if isinstance(value, dict) and set(value) == {'path', 'sha256'}:
        return {'source_ref': _ref(value)}
    require(isinstance(value, dict) and {'source_ref'} <= set(value) <=
            {'source_ref', 'observation', 'qualified_reconstruction'}, 'TEMPORAL_PIN_INVALID')
    result = deepcopy(value)
    result['source_ref'] = _ref(result['source_ref'])
    if 'observation' in result:
        binding = result['observation']
        require(isinstance(binding, dict) and set(binding) == _BINDING and
                isinstance(binding['observation_id'], str) and bool(binding['observation_id']) and
                all(type(binding[k]) is int and binding[k] > 0 for k in ('revision', 'lifecycle_revision')),
                'TEMPORAL_LIFECYCLE_BINDING_INVALID')
    if 'qualified_reconstruction' in result:
        reconstruction = result['qualified_reconstruction']
        require(isinstance(reconstruction, dict) and set(reconstruction) == {'published_at', 'rationale'} and
                isinstance(reconstruction['rationale'], str) and 0 < len(reconstruction['rationale']) <= 2000,
                'TEMPORAL_RECONSTRUCTION_INVALID')
        _time(reconstruction['published_at'])
    return result


def _identity(source):
    provider, upstream = source.get('provider'), source.get('upstream_id')
    require(isinstance(provider, str) and provider and isinstance(upstream, str) and upstream,
            'TEMPORAL_SOURCE_IDENTITY_REQUIRED')
    # arXiv's upstream ID includes the revision; other adapters retain a stable
    # identity across source versions. Never group unrelated documents by title.
    if provider == 'arxiv':
        upstream = re.sub(r'v[1-9][0-9]*$', '', upstream)
    return provider, upstream


def _lifecycle(pin, store):
    binding = pin.get('observation')
    if binding is None:
        return None
    require(isinstance(store, Store), 'TEMPORAL_STORE_REQUIRED')
    row = store.read(binding['observation_id'], binding['revision'], include_withdrawn=True)
    require(row['state'] == 'active' and row['lifecycle_revision'] == binding['lifecycle_revision'],
            'TEMPORAL_LIFECYCLE_MISMATCH')
    require(row['payload'].get('source_ref') == pin['source_ref'], 'TEMPORAL_SOURCE_BINDING_MISMATCH')
    # An ordinary revision must not erase a usable historical version. A current
    # withdrawal does revoke new use of every revision. Historical lifecycle is
    # bound separately from the latest active version.
    head = store.read(binding['observation_id'], include_withdrawn=True)
    require(head['state'] == 'active', 'TEMPORAL_SOURCE_WITHDRAWN')
    return row


class TemporalBroker:
    """Prepare on the host, then hand workers only screened method results.

    Pins are source refs or ``{'source_ref': ref, 'observation': binding}``.
    ``qualified_reconstruction`` is optional reviewer context, never an override.
    For a later cutoff create another broker; a prior worker packet is not an
    accepted input. All candidate versions must be pinned, including eligible
    historical revisions; Store.find's latest-head view is intentionally unused.
    """

    def __init__(self, pins, *, cutoff, scope='public', store=None):
        require(isinstance(pins, (list, tuple)) and len(pins) <= 1000, 'TEMPORAL_PINS_INVALID')
        require(isinstance(scope, str) and 0 < len(scope) <= 192, 'TEMPORAL_SCOPE_INVALID')
        require(store is None or isinstance(store, Store), 'TEMPORAL_STORE_REQUIRED')
        self._cutoff = _time(cutoff).isoformat()
        self._scope = scope
        self._store = store
        self._pins = []
        self._invalid = []
        for value in pins:
            try:
                self._pins.append(_pin(value))
            except (SourceError, ValueError, TypeError) as exc:
                # Fail closed per item without reflecting malformed input in a
                # worker exception (or echoing arbitrary text in diagnostics).
                sha = value.get('source_ref', value).get('sha256') if isinstance(value, dict) and isinstance(value.get('source_ref', value), dict) else None
                self._invalid.append({'source_sha256': sha if isinstance(sha, str) and _HASH.fullmatch(sha) else None,
                    'status': 'blocked', 'reason_codes': [_code(exc)], 'worker_visible': False, 'basis': None})
        self._refresh()

    @property
    def cutoff(self):
        return self._cutoff

    @property
    def scope(self):
        return self._scope

    def _inspect(self, pin):
        ref = pin['source_ref']
        diagnostic = {'source_sha256': ref['sha256'], 'source_ref': deepcopy(ref), 'source_version': None,
            'raw_sha256': None, 'text_sha256': None, 'status': 'blocked', 'reason_codes': [],
            'worker_visible': False, 'basis': None, 'observation': deepcopy(pin.get('observation'))}
        try:
            source = read(ref)
            require(isinstance(source, dict), 'TEMPORAL_SOURCE_INVALID')
            identity = _identity(source)
            diagnostic['source_version'] = source.get('source_version')
            diagnostic['source_identity_sha256'] = digest(identity)
            source_scope = source.get('access_scope')
            require(source_scope is None or source_scope == self.scope, 'TEMPORAL_SCOPE_MISMATCH')
            diagnostic['scope_basis'] = 'source_receipt' if source_scope is not None else 'host_requested_scope'
            require(source.get('access_level') == 'document', 'TEMPORAL_DOCUMENT_REQUIRED')
            row = _lifecycle(pin, self._store)
            # Hash-check all bytes before any title, excerpt, or content reaches
            # the worker. Ref relabeling cannot reuse an earlier source binding.
            raw = read(_ref(source.get('raw')), json_value=False)
            text_bytes = read(_ref(source.get('text')), json_value=False)
            require(bool(raw) and bool(text_bytes), 'TEMPORAL_CONTENT_EMPTY')
            diagnostic.update(raw_sha256=source['raw']['sha256'], text_sha256=source['text']['sha256'])
            text = text_bytes.decode('utf-8')
            # ``available_at`` may mean v1 publication in legacy receipts. Never
            # let it move a freshly observed mutable body back in time.
            observed = source.get('retrieved_at')
            if observed is None:
                diagnostic.update(status='unknown', reason_codes=['TEMPORAL_OBSERVATION_TIME_UNKNOWN'])
                return diagnostic, None
            bounds = [('retrieved_at', _time(observed))]
            for key in ('available_at', 'modified_at', 'updated_at', 'version_available_at'):
                if source.get(key) is not None:
                    bounds.append((key, _time(source[key])))
            if row is not None:
                bounds.append(('store_recorded_at', _time(row['recorded_at'])))
            available = max(at for _, at in bounds)
            diagnostic.update(available_at=available.isoformat(), observed_at=_time(observed).isoformat(),
                version_available_at=source.get('version_available_at'),
                availability_provenance={'source_receipt_sha256': ref['sha256'],
                    'bounds': {key: at.isoformat() for key, at in bounds},
                    'claim': 'host_acquisition_receipt_not_authenticated_historical_attestation'},
                basis='first_observed_pinned_version')
            if available > _time(self.cutoff):
                reconstruction = pin.get('qualified_reconstruction')
                if reconstruction is not None and _time(reconstruction['published_at']) <= _time(self.cutoff):
                    diagnostic.update(status='qualified_reconstruction', basis='declared_reconstruction_only',
                        reason_codes=['TEMPORAL_CAPTURE_AFTER_CUTOFF', 'TEMPORAL_RECONSTRUCTION_NOT_STRICT'],
                        reconstruction=deepcopy(reconstruction))
                else:
                    diagnostic['reason_codes'] = ['TEMPORAL_VERSION_AFTER_CUTOFF']
                return diagnostic, None
            metadata = source.get('metadata') or {}
            require(isinstance(metadata, dict), 'TEMPORAL_METADATA_INVALID')
            title = metadata.get('title') or source.get('title') or next(iter(source.get('headings') or []), None) or identity[1]
            require(isinstance(title, str) and len(title) <= 4096, 'TEMPORAL_TITLE_INVALID')
            require(isinstance(source.get('source_url'), str), 'TEMPORAL_SOURCE_URL_INVALID')
            diagnostic.update(status='eligible', reason_codes=[], worker_visible=True)
            document = {'source_id': ref['sha256'], 'source_version': source.get('source_version'),
                'title': title, 'source_url': source['source_url'], 'text': text,
                'raw_sha256': source['raw']['sha256'], 'text_sha256': source['text']['sha256'],
                'available_at': available.isoformat(), 'availability_basis': 'first_observed_pinned_version',
                'read_scope': source.get('read_scope', 'pinned normalized document'), 'scope': self.scope}
            return diagnostic, (identity, available, document)
        except (SourceError, OSError, ValueError, TypeError, UnicodeError) as exc:
            diagnostic['reason_codes'] = [_code(exc)]
            return diagnostic, None

    def _refresh(self):
        # Recheck immutable byte hashes and mutable lifecycle at every exposure.
        # No worker packet/search/open can revive a prepared-then-withdrawn item.
        diagnostics, versions = deepcopy(self._invalid), {}
        for pin in self._pins:
            diagnostic, candidate = self._inspect(pin)
            diagnostics.append(diagnostic)
            if candidate is not None:
                identity, available, document = candidate
                versions.setdefault(identity, []).append((available, document, diagnostic))
        selected = {}
        for candidates in versions.values():
            # Deterministic tie-break over only eligible versions, never a future
            # head's revision, score, title, or count.
            candidates.sort(key=lambda item: (item[0], item[1]['source_id']))
            for _, _, diagnostic in candidates[:-1]:
                diagnostic.update(worker_visible=False, reason_codes=['TEMPORAL_ELIGIBLE_VERSION_SUPERSEDED'])
            document = candidates[-1][1]
            selected[document['source_id']] = document
        self._documents, self._diagnostics = selected, diagnostics

    def worker_packet(self):
        """Only worker-safe data; excluded identities, counts, refs stay host-side."""
        self._refresh()
        return {'schema_version': 1, 'guard_version': VERSION, 'cutoff': self.cutoff,
            'scope': self.scope, 'sources': [deepcopy(self._documents[key]) for key in sorted(self._documents)]}

    def search(self, query, *, limit=10):
        """Deterministic local retrieval, performed only after strict screening."""
        require(isinstance(query, str) and len(query) <= 2000 and type(limit) is int and 1 <= limit <= 100,
                'TEMPORAL_SEARCH_INVALID')
        self._refresh()
        terms = query.casefold().split()
        matches = []
        for source_id, document in sorted(self._documents.items()):
            haystack = (document['title'] + ' ' + document['text']).casefold()
            if all(term in haystack for term in terms):
                matches.append({'source_id': source_id, 'source_version': document['source_version'],
                    'title': document['title'], 'snippet': document['text'][:320],
                    'source_url': document['source_url']})
        return {'results': matches[:limit]}

    def open(self, source_id, *, start=0, max_chars=12000):
        require(isinstance(source_id, str) and type(start) is int and start >= 0 and
                type(max_chars) is int and 1 <= max_chars <= 12000, 'TEMPORAL_OPEN_INVALID')
        self._refresh()
        require(source_id in self._documents, 'TEMPORAL_SOURCE_UNAVAILABLE')
        document = self._documents[source_id]
        require(start < len(document['text']), 'TEMPORAL_OPEN_RANGE_INVALID')
        end = min(len(document['text']), start + max_chars)
        return {**{key: deepcopy(value) for key, value in document.items() if key != 'text'},
            'text': document['text'][start:end], 'start': start, 'end': end,
            'next_start': end if end < len(document['text']) else None}

    def host_diagnostics(self):
        """Reviewer-only receipt. Never append this to worker prompts or tools."""
        self._refresh()
        context = {'guard_version': VERSION, 'cutoff': self.cutoff, 'scope': self.scope, 'pins': self._pins}
        return {'schema_version': 1, 'guard_version': VERSION, 'cutoff': self.cutoff, 'scope': self.scope,
            'view': 'reviewer_diagnostic', 'corpus_binding_sha256': digest(context),
            'sources': [{**deepcopy(row), 'cutoff': self.cutoff, 'view': 'reviewer_diagnostic'} for row in self._diagnostics],
            'limits': ['timestamps_rely_on_host_acquisition_provenance', 'no_network_or_model_verification',
                'no_OS_sandbox', 'model_weight_contamination_not_removed', 'document_corpus_only',
                'qualified_reconstructions_never_worker_visible']}


def prepare_corpus(pins, *, cutoff, scope='public', store=None):
    """Construct one cutoff-bound broker shared by both comparison arms."""
    return TemporalBroker(pins, cutoff=cutoff, scope=scope, store=store)
