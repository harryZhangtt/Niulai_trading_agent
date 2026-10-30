"""Maintained completion entry points, composing source checks with Niulai gates.

The preserved migration scripts are read as dependencies, never modified.
The coordinator supplies the frozen contract separately from author artifacts.
"""
import importlib
import json
from pathlib import Path
import sys
from shared.research_sources.artifacts import ROOT, private_path, read, require, save
from .coverage import validate

LEGACY = ROOT / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts'


def legacy(name):
    if str(LEGACY) not in sys.path:
        sys.path.insert(0, str(LEGACY))
    module = importlib.import_module(name)
    require(Path(module.__file__).resolve().is_relative_to(LEGACY), 'LEGACY_MODULE_ORIGIN_REJECTED')
    return module


def finalize(item, output_directory, *, contract, packet):
    record = json.loads(private_path(item['record']).read_text())
    # Before legacy finalization can produce a completed record.
    receipt = validate(contract, packet, record=record)
    private_path(output_directory, create=True)
    result = legacy('finalize_research').assemble(item, output_directory)
    final = json.loads(Path(result['record']['path']).read_text())
    final['source_coverage_evidence'] = {'contract': contract, 'packet': packet, 'receipt': receipt}
    result['record'] = save(output_directory, final)
    return result


def complete(item, run_id, *, contract):
    record = read(item['record'])
    coverage = record.get('source_coverage_evidence') or {}
    require(coverage.get('contract') == contract, 'COMPLETION_SOURCE_CONTRACT_REQUIRED')
    receipt = validate(contract, coverage['packet'], record=record)
    require(coverage.get('receipt') == receipt, 'COMPLETION_SOURCE_RECEIPT_STALE')
    old = legacy('research_completion').inspect_record(item, run_id)
    return {**old, 'source_coverage': receipt}
