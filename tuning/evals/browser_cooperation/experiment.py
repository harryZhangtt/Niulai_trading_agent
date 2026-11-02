"""Seal before work; use the existing claim/finish gate, not an extra benchmark engine."""
import argparse
import json
from pathlib import Path

from shared.research_sources.artifacts import ROOT, digest, private_path, read, save
from shared.web_access.egolite import doctor
from shared.web_access.policy import DEFAULT_CONFIG, fingerprint, load_config
from tuning.evals.evidence_runtime import contracts

HERE = Path(__file__).parent


def prepare(directory, config_path=DEFAULT_CONFIG, spec_path=HERE/'cases.json'):
    directory = private_path(directory, create=True)
    config = load_config(config_path)
    closure = ['shared/web_access/' + name for name in
               ('__init__.py', 'policy.py', 'egolite.py', 'ego_read.js', '__main__.py')]
    pins = {'baseline': {'reader': 'host_native_open_and_pdf', 'native_backend_identity': 'not_exposed',
                         'search_manifest': 'same_frozen_candidates_both_arms'},
            'candidate': {'config_sha256': digest(config), 'source_sha256': {name:fingerprint(ROOT/name) for name in closure},
                          'egolite_cli_sha256': config['egolite']['sha256'], 'browser_version': 'unverified'}}
    graders = ['tuning/evals/browser_cooperation/grade.py', 'tuning/evals/browser_cooperation/experiment.py',
               'tuning/evals/evidence_runtime/contracts.py', 'shared/research_sources/artifacts.py', *closure]
    contract_ref = contracts.seal(spec_path, graders, pins, directory)
    worker_ref = save(directory/'inputs', contracts.worker_packet(contract_ref))
    preflight = doctor(config)
    result = {'schema_version':1, 'kind':'browser_comparison_preflight', 'contract_ref':contract_ref,
              'worker_ref':worker_ref, 'preflight':preflight,
              'comparison_status':'not_started' if preflight['status'] != 'blocked' else 'blocked',
              'quality_verdict':'inconclusive', 'live_paired_cases':0,
              'exposed_answers':'development_unblinded', 'scheduled_acceptance':'unverified',
              'native_baseline':'not_run_as_matched_trial', 'superiority_established':False}
    return {**result, 'preflight_ref':save(directory/'preflight',result)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args=parser.parse_args()
    print(json.dumps(prepare(args.out,args.config)))


if __name__=='__main__':main()
