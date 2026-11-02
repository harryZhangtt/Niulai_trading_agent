"""Bounded offline OOXML screening; never Excel evaluation or DCF approval."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALLOWED_ROOT = ROOT / '.job-runtime/calculation'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MAX_INPUT = 2 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_MEMBERS = 128
MAX_RATIO = 100


class ScreeningError(ValueError):
    """Fixed diagnostic codes only; no workbook content in errors."""


def _need(condition, code):
    if not condition:
        raise ScreeningError(code)


def _input_bytes(path, allowed_root):
    boundary = Path(allowed_root).resolve(strict=True)
    fixed_boundary = DEFAULT_ALLOWED_ROOT.resolve(strict=True)
    _need(fixed_boundary.is_relative_to(ROOT.resolve()) and boundary.is_relative_to(fixed_boundary),
          'ALLOWED_ROOT_OUTSIDE_CALCULATION_STATE')
    candidate = Path(os.path.abspath(path))
    _need(candidate.is_relative_to(boundary) and candidate.resolve().is_relative_to(boundary),
          'INPUT_OUTSIDE_ALLOWED_ROOT')
    node = candidate
    while node != boundary:
        _need(not node.is_symlink(), 'INPUT_SYMLINK_REJECTED')
        node = node.parent
    fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_INPUT, 'INPUT_SIZE_OR_TYPE_INVALID')
        value = handle.read(MAX_INPUT + 1)
    _need(len(value) <= MAX_INPUT, 'INPUT_TOO_LARGE')
    return value


def _xml(raw):
    upper = raw.upper()
    _need(b'\x00' not in raw, 'XML_ENCODING_UNSUPPORTED')
    _need(b'<!DOCTYPE' not in upper and b'<!ENTITY' not in upper, 'XML_DTD_OR_ENTITY_REJECTED')
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise ScreeningError('XML_INVALID') from None


def _numeric(raw):
    _need(isinstance(raw, str) and 0 < len(raw) <= 128, 'NUMERIC_VALUE_INVALID')
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ScreeningError('NUMERIC_VALUE_INVALID') from None
    _need(value.is_finite() and abs(value.as_tuple().exponent) <= 1000,
          'NONFINITE_OR_UNBOUNDED_NUMERIC_VALUE')
    return value


def _binding(value):
    _need(isinstance(value, str), 'BINDING_INVALID')
    match = re.fullmatch(r"(?:'([^']+)'|([^'!]+))!([A-Z]{1,3}[1-9][0-9]{0,6})", value)
    _need(match is not None, 'BINDING_INVALID')
    return match[1] or match[2], match[3]


def screen_xlsx(path, *, wacc_cell, growth_cell, allowed_root=DEFAULT_ALLOWED_ROOT):
    """Return screened/unverified/rejected, with numeric_validated always False.

    Explicit bindings must refer to literal annual-decimal rate cells. ``screened``
    means only the declared structural/domain checks completed. Cached formula
    values are never independently recalculated or numerically approved.
    """
    base = {'status': 'rejected', 'screening_only': True, 'numeric_validated': False,
            'errors': [], 'warnings': [], 'formula_cells': 0,
            'uncached_formula_cells': 0, 'external_execution_performed': False}
    try:
        bindings = {'wacc': _binding(wacc_cell), 'terminal_growth': _binding(growth_cell)}
        raw = _input_bytes(path, allowed_root)
        base['input_sha256'] = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            _need(0 < len(infos) <= MAX_MEMBERS, 'ZIP_MEMBER_COUNT_INVALID')
            _need(len({item.filename for item in infos}) == len(infos), 'ZIP_DUPLICATE_MEMBER')
            _need(sum(item.file_size for item in infos) <= MAX_TOTAL, 'ZIP_TOTAL_SIZE_EXCEEDED')
            documents = {}
            for item in infos:
                parts = PurePosixPath(item.filename).parts
                _need(not item.filename.startswith('/') and '\\' not in item.filename
                      and '..' not in parts, 'ZIP_PATH_INVALID')
                _need(not item.flag_bits & 1, 'ZIP_ENCRYPTION_UNSUPPORTED')
                _need(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                      'ZIP_COMPRESSION_UNSUPPORTED')
                _need(item.file_size <= MAX_MEMBER and
                      item.file_size <= MAX_RATIO * max(item.compress_size, 1), 'ZIP_EXPANSION_LIMIT')
                lower = item.filename.lower()
                _need(not any(token in lower for token in ('vbaproject', 'externallinks/', 'connections.xml')),
                      'EXTERNAL_OR_MACRO_PART_REJECTED')
                if item.is_dir():
                    continue
                with archive.open(item) as member:
                    payload = member.read(MAX_MEMBER + 1)
                _need(len(payload) <= MAX_MEMBER, 'ZIP_MEMBER_SIZE_EXCEEDED')
                if lower.endswith(('.xml', '.rels')):
                    node = _xml(payload)
                    for relation in node.iter():
                        _need(relation.get('TargetMode', '').lower() != 'external',
                              'EXTERNAL_RELATIONSHIP_REJECTED')
                        target = relation.get('Target', '').lower()
                        _need('://' not in target and not target.startswith(('file:', '\\\\')),
                              'EXTERNAL_RELATIONSHIP_REJECTED')
                    _need(b'macroenabled' not in payload.lower(), 'MACRO_CONTENT_TYPE_REJECTED')
                    documents[item.filename] = node
            _need('xl/workbook.xml' in documents and 'xl/_rels/workbook.xml.rels' in documents,
                  'WORKBOOK_PARTS_MISSING')
            relationships = {}
            for node in documents['xl/_rels/workbook.xml.rels']:
                key, target = node.get('Id'), node.get('Target', '')
                _need(key and key not in relationships and ':' not in target and '\\' not in target,
                      'WORKBOOK_RELATIONSHIP_INVALID')
                normalized = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                                               else posixpath.join('xl', target))
                _need(normalized.startswith('xl/') and '..' not in PurePosixPath(normalized).parts,
                      'WORKBOOK_RELATIONSHIP_OUTSIDE_ARCHIVE')
                relationships[key] = normalized
            sheets = {}
            for node in documents['xl/workbook.xml'].iter(NS+'sheet'):
                name, relation = node.get('name'), node.get(REL_NS+'id')
                _need(name and name not in sheets and relation in relationships,
                      'WORKBOOK_SHEET_IDENTITY_INVALID')
                part = relationships[relation]
                _need(part in documents, 'WORKSHEET_PART_MISSING')
                cells = {}
                for cell in documents[part].iter(NS+'c'):
                    coordinate = cell.get('r')
                    _need(coordinate and coordinate not in cells, 'WORKSHEET_CELL_IDENTITY_INVALID')
                    cells[coordinate] = cell
                    formula, cache = cell.find(NS+'f'), cell.find(NS+'v')
                    if cell.get('t') == 'e':
                        raise ScreeningError('EXCEL_ERROR_CELL')
                    if formula is not None:
                        base['formula_cells'] += 1
                        text = (formula.text or '').upper()
                        _need(not any(token in text for token in ('[', ']', '://', '|')) and
                              not re.search(r'(?:WEBSERVICE|HYPERLINK|RTD|CALL|REGISTER|EXEC|DDE|INDIRECT)\s*\(', text),
                              'UNSUPPORTED_EXTERNAL_OR_UNSAFE_FORMULA')
                        if cache is None or cache.text is None or cell.get('t') in ('str', 's', 'inlineStr', 'b'):
                            base['uncached_formula_cells'] += 1
                        else:
                            _numeric(cache.text)
                    elif cell.get('t') in (None, 'n') and cache is not None and cache.text is not None:
                        _numeric(cache.text)
                sheets[name] = cells
            values = {}
            for name, (sheet, coordinate) in bindings.items():
                cell = sheets.get(sheet, {}).get(coordinate)
                if cell is None or cell.find(NS+'f') is not None or cell.get('t') not in (None, 'n'):
                    base['warnings'].append('LITERAL_RATE_BINDING_UNAVAILABLE')
                    continue
                cache = cell.find(NS+'v')
                if cache is None or cache.text is None:
                    base['warnings'].append('LITERAL_RATE_BINDING_UNAVAILABLE')
                    continue
                values[name] = _numeric(cache.text)
            if len(values) == 2:
                _need(values['wacc'] > -1 and values['terminal_growth'] > -1 and
                      values['terminal_growth'] < values['wacc'], 'GORDON_RATE_DOMAIN_INVALID')
                base['literal_rates'] = {name: str(value) for name, value in values.items()}
            if base['uncached_formula_cells']:
                base['warnings'].append('FORMULA_RESULTS_UNVERIFIED')
            if base['formula_cells']:
                base['warnings'].append('FORMULAS_NOT_RECALCULATED')
            base['status'] = 'unverified' if base['uncached_formula_cells'] or len(values) != 2 else 'screened'
        return base
    except ScreeningError as exc:
        base['errors'].append(str(exc))
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, ValueError):
        base['errors'].append('WORKBOOK_UNREADABLE_OR_UNSUPPORTED')
    return base
