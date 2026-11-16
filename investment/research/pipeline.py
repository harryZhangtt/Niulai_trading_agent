"""Maintained completion entry points, composing source checks with Niulai gates.

The preserved migration scripts are read as dependencies, never modified.
The coordinator supplies the frozen contract separately from author artifacts.
"""
import importlib
import json
from pathlib import Path
import sys
from shared.research_sources.artifacts import ROOT, private_path, publish_json_command, read, require, save
from .coverage import validate
from .requirements import load as load_contract

LEGACY = ROOT / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts'


def legacy(name):
    if str(LEGACY) not in sys.path:
        sys.path.insert(0, str(LEGACY))
    module = importlib.import_module(name)
    require(Path(module.__file__).resolve().is_relative_to(LEGACY), 'LEGACY_MODULE_ORIGIN_REJECTED')
    return module


def publish_contract_pointer(path, command):
    return publish_json_command(path, command, validator=load_contract)


def finalize(item, output_directory, *, contract, packet):
    record = json.loads(private_path(item['record']).read_text())
    # Reject missing coverage before legacy work, but publish no legacy pointer.
    validate(contract, packet, record=record)
    private_path(output_directory, create=True)
    module = legacy('finalize_research')
    result = module.assemble(item, output_directory, publish=False)
    final = read(result['record'])
    evidence = {'contract': contract, 'packet': packet}
    final['source_coverage_evidence'] = evidence
    # Recheck the fully transformed final record immediately before its save.
    evidence['receipt'] = validate(contract, packet, record=final)
    result['record'] = save(output_directory, final)
    module.publish_completion(output_directory, result)
    return result


def complete(item, run_id, *, contract):
    record = read(item['record'])
    coverage = record.get('source_coverage_evidence') or {}
    require(coverage.get('contract') == contract, 'COMPLETION_SOURCE_CONTRACT_REQUIRED')
    receipt = validate(contract, coverage['packet'], record=record)
    require(coverage.get('receipt') == receipt, 'COMPLETION_SOURCE_RECEIPT_STALE')
    old = legacy('research_completion').inspect_record(item, run_id)
    return {**old, 'source_coverage': receipt}
