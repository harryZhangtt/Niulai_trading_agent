"""Bounded public acquisition. No investment coverage decisions or model updates."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from html.parser import HTMLParser
import json
import os
import re
import time
from urllib import request, parse, error
import xml.etree.ElementTree as ET
from .artifacts import ROOT, SOURCE_STATE, SourceError, private_path, read, require, save

HOSTS = {'arxiv.org', 'export.arxiv.org', 'api.openalex.org', 'docs.nvidia.com',
         'developer.nvidia.com', 'rocm.docs.amd.com', 'docs.cloud.google.com',
         'mlcommons.org', 'www.sec.gov', 'sec.gov', 'investor.nvidia.com', 'nvidianews.nvidia.com',
         'newsroom.servicenow.com', 'investor.servicenow.com'}
PAPER_ID = re.compile(r'^\d{4}\.\d{4,5}v[1-9]\d*$')


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@contextmanager
def arxiv_budget():
    state = private_path(SOURCE_STATE / 'runtime/rate', create=True)
    fd = os.open(state / 'arxiv.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        previous = stream.read()
        delay = 3.1 - (time.time() - float(previous or '0'))
        if delay > 0:
            time.sleep(min(delay, 3.1))
        stream.seek(0); stream.truncate(); stream.write(str(time.time())); stream.flush()
        yield


def get(url, *, opener=None):
    u = parse.urlsplit(url)
    require(u.scheme == 'https' and u.hostname in HOSTS and not u.username and not u.password
            and not u.port and not u.fragment and len(url) <= 4096, 'SOURCE_URL_REJECTED')
    req = request.Request(url, headers={'User-Agent': 'InvestmentEvidencePilot/0.1',
        'Accept': 'application/json,application/atom+xml,text/html'})
    try:
        with (opener or request.build_opener(NoRedirect())).open(req, timeout=18) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            require(len(raw) <= 4 * 1024 * 1024, 'SOURCE_RESPONSE_TOO_LARGE')
            return raw, response.headers.get('Content-Type', '')
    except error.HTTPError as exc:
        raise SourceError('SOURCE_HTTP_' + str(exc.code)) from None
    except (error.URLError, TimeoutError, OSError):
        raise SourceError('SOURCE_NETWORK_FAILED') from None


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []; self.headings = []; self.skip = 0; self.heading = None
        self.labels = []; self.label = None; self.password_field = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.heading = []
        if tag in ('title', 'h1'):
            self.label = []
        if tag == 'input' and str(dict(attrs).get('type') or '').lower() == 'password':
            self.password_field = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in ('h1', 'h2', 'h3', 'h4') and self.heading is not None:
            self.headings.append(' '.join(self.heading)); self.heading = None
        if tag in ('title', 'h1') and self.label is not None:
            self.labels.append(' '.join(self.label)); self.label = None

    def handle_data(self, data):
        value = ' '.join(data.split())
        if self.skip or not value:
            return
        self.chunks.append(value)
        if self.heading is not None:
            self.heading.append(value)
        if self.label is not None:
            self.label.append(value)


def _payload_error(parser):
    """Recognize page-level failure, not error vocabulary inside a document."""
    text = '\n'.join(parser.chunks)
    # Reference pages can legitimately be titled with an HTTP error. An
    # explanatory introduction distinguishes that case from an outage wrapper.
    reference = re.search(r'\bthis (?:guide|reference|document|tutorial) '
                          r'(?:explains|describes|documents|covers)\b', text[:1600], re.I)
    failure = (r'(?:(?:http\s+)?(?:error\s+)?(?:401|403|407|429|500|502|503|504)'
               r'(?:\s*[-:]?\s*(?:unauthorized|forbidden|proxy authentication required|'
               r'too many requests|internal server error|bad gateway|service unavailable|gateway timeout))?'
               r'|service (?:unavailable|temporarily unavailable)|bad gateway|gateway timeout|'
               r'internal server error|authentication (?:failed|required)|authorization required|'
               r'unauthorized|forbidden|access denied|too many requests|rate limit(?: exceeded)?|'
               r'just a moment(?:\.{3})?|(?:please )?verify (?:that )?you are (?:a )?human|'
               r'checking your browser|sorry,? you have been blocked|robot check|'
               r'captcha(?: verification)?|page not found|404(?:\s*[-:]?\s*not found)?)')
    if not reference and any(re.fullmatch(failure + r'[.!]?', label.strip(), re.I) for label in parser.labels[:4]):
        return True
    login = any(re.fullmatch(r'(?:log[ -]?in|sign[ -]?in)(?: required| to continue| to .{1,80})?[.!]?',
                             label.strip(), re.I) for label in parser.labels[:4])
    if login and not reference and (parser.password_field or re.search(
            r'password|sign in to continue|login required|log in to continue', text[:2000], re.I)):
        return True
    # Some services send a JSON error in a nominal HTML response. Only parse an
    # otherwise bare visible payload; code examples embedded in prose remain docs.
    visible = '\n'.join(chunk for chunk in parser.chunks if chunk not in parser.labels).strip()
    try:
        payload = json.loads(visible)
    except (ValueError, TypeError):
        payload = None
    return isinstance(payload, dict) and (bool(payload.get('error')) or payload.get('success') is False
        or str(payload.get('status', '')).lower() in {'error', 'failed', 'failure', 'unauthorized', 'forbidden'}
        or str(payload.get('status_code', payload.get('code', ''))) in {'401', '403', '407', '429', '500', '502', '503', '504'})


def document_receipt(directory, *, provider, url, raw, identifier, published_at=None, version=None, metadata=None):
    parser = Document(); parser.feed(raw.decode('utf-8'))
    text = '\n'.join(parser.chunks)
    require(not _payload_error(parser), 'SOURCE_PAYLOAD_ERROR')
    require(len(text) > 200 and parser.headings, 'SOURCE_DOCUMENT_INVALID')
    observed = datetime.now(timezone.utc).isoformat()
    receipt = {'schema_version': 1, 'provider': provider, 'source_url': url,
        'upstream_id': identifier, 'source_version': version, 'published_at': published_at,
        'retrieved_at': observed, 'available_at': published_at or observed,
        'availability_basis': 'provider_publication' if published_at else 'first_observed',
        'access_level': 'document', 'raw': save(directory, raw, suffix='html'),
        'text': save(directory, text.encode(), suffix='txt'), 'headings': parser.headings,
        'metadata': metadata or {}, 'truth_or_independence_certified': False}
    return save(directory, receipt)


def fetch_arxiv(paper_id, directory, *, getter=get, budget=arxiv_budget):
    require(isinstance(paper_id, str) and PAPER_ID.fullmatch(paper_id), 'VERSIONED_ARXIV_ID_REQUIRED')
    with budget():
        atom, _ = getter('https://export.arxiv.org/api/query?' + parse.urlencode({'id_list': paper_id}))
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entries = ET.fromstring(atom).findall('a:entry', ns)
    require(len(entries) == 1, 'ARXIV_IDENTITY_UNCONFIRMED')
    e = entries[0]
    actual = e.findtext('a:id', namespaces=ns).rsplit('/', 1)[-1]
    require(actual == paper_id, 'ARXIV_VERSION_MISMATCH')
    # The selected revision's availability is its update time, not v1's date.
    available = e.findtext('a:updated', namespaces=ns)
    url = 'https://arxiv.org/html/' + paper_id
    with budget():
        raw, ct = getter(url)
    require('html' in ct and paper_id.encode() in raw, 'ARXIV_DOCUMENT_IDENTITY_UNCONFIRMED')
    return document_receipt(directory, provider='arxiv', url=url, raw=raw, identifier=paper_id,
        version=paper_id.rsplit('v', 1)[1], published_at=available,
        metadata={'title': e.findtext('a:title', namespaces=ns),
                  'first_submitted_at': e.findtext('a:published', namespaces=ns),
                  'publication_status': 'manuscript; journal/peer-review status not verified',
                  'atom': save(directory, atom, suffix='xml')})


def discover_openalex(query, directory, *, getter=get):
    require(isinstance(query, str) and 1 <= len(query) <= 500, 'PUBLIC_QUERY_INVALID')
    url = 'https://api.openalex.org/works?' + parse.urlencode({'search': query, 'per-page': 3})
    raw, _ = getter(url); result = json.loads(raw)
    require(isinstance(result.get('results'), list), 'OPENALEX_RESPONSE_INVALID')
    candidates = [{k: row.get(k) for k in ('id', 'doi', 'title', 'publication_date',
        'referenced_works', 'primary_location', 'locations')} for row in result['results']]
    return save(directory, {'schema_version': 1, 'provider': 'openalex', 'source_url': url,
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'access_level': 'metadata',
        'raw': save(directory, raw), 'candidates': candidates,
        'identity_warning': 'Merged publication/DOI candidates require primary-source verification',
        'truth_or_independence_certified': False})


def discover_arxiv(query, directory, *, getter=get, budget=arxiv_budget):
    require(isinstance(query, str) and 1 <= len(query) <= 500, 'PUBLIC_QUERY_INVALID')
    url = 'https://export.arxiv.org/api/query?' + parse.urlencode({'search_query': query, 'max_results': 3})
    with budget():
        raw, _ = getter(url)
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entries = ET.fromstring(raw).findall('a:entry', ns)
    candidates = [{'id': e.findtext('a:id', namespaces=ns), 'title': e.findtext('a:title', namespaces=ns),
        'abstract': e.findtext('a:summary', namespaces=ns), 'updated': e.findtext('a:updated', namespaces=ns)} for e in entries]
    require(all(c['id'] and '/abs/' in c['id'] for c in candidates), 'ARXIV_DISCOVERY_INVALID')
    return save(directory, {'schema_version': 1, 'provider': 'arxiv', 'source_url': url,
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'access_level': 'metadata',
        'raw': save(directory, raw, suffix='xml'), 'candidates': candidates,
        'truth_or_independence_certified': False})


def ingest_mcp_section(report_ref, primary_ref, directory):
    """Normalize a tested candidate's section output; retain primary ID/date evidence."""
    report, primary = read(report_ref), read(primary_ref)
    section = report.get('section', {})
    require(report.get('queried') is True and section.get('status') == 'success'
            and report.get('process_cleanup_verified') is True, 'MCP_SECTION_UNCONFIRMED')
    require(section.get('versioned_id') == primary.get('upstream_id')
            and primary.get('provider') == 'arxiv', 'MCP_PRIMARY_IDENTITY_MISMATCH')
    content = section.get('content')
    require(isinstance(content, str) and 20 <= len(content) <= 12000
            and section.get('returned_chars') == len(content), 'MCP_SECTION_INVALID')
    return save(directory, {'schema_version': 1, 'provider': 'arxiv_mcp_candidate',
        'source_url': primary['source_url'], 'upstream_id': primary['upstream_id'],
        'source_version': primary['source_version'], 'available_at': primary['available_at'],
        'published_at': primary['published_at'], 'availability_basis': primary['availability_basis'],
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'access_level': 'document',
        'read_scope': 'bounded extracted section', 'raw': report_ref,
        'text': save(directory, content.encode(), suffix='txt'), 'headings': [section['section']['title']],
        'metadata': {'primary_identity_receipt': primary_ref, 'server_version': report['version'],
                     'section': section['section']}, 'truth_or_independence_certified': False})


def fetch_document(url, directory, *, getter=get):
    u = parse.urlsplit(url)
    require(u.hostname in HOSTS - {'arxiv.org', 'export.arxiv.org', 'api.openalex.org'}
            and not u.query, 'DOCUMENT_HOST_REJECTED')
    raw, ct = getter(url)
    require('html' in ct, 'HTML_DOCUMENT_REQUIRED')
    return document_receipt(directory, provider='official_document', url=url, raw=raw, identifier=url)


def passages(receipt_ref, start=0, max_chars=6000):
    require(type(start) is int and start >= 0 and type(max_chars) is int and 1 <= max_chars <= 12000,
            'PASSAGE_RANGE_INVALID')
    receipt = read(receipt_ref)
    require(receipt.get('access_level') == 'document', 'DOCUMENT_READ_REQUIRED')
    text = read(receipt['text'], json_value=False).decode()
    require(start < len(text), 'PASSAGE_RANGE_INVALID')
    end = min(len(text), start + max_chars)
    return {'start': start, 'end': end, 'text': text[start:end],
            'locator': 'normalized-text:' + str(start) + ':' + str(end),
            'next_start': end if end < len(text) else None, 'receipt_sha256': receipt_ref['sha256']}
