"""Local-only EIY v5 checker/reducer/publisher CLI; no provider or network path."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from investment.research.acquisition_eiy_checker_v5 import check_eiy_evaluation_v5
from shared.research_sources.artifacts import ROOT,read
from shared.research_sources.information_yield_v5_contracts import ArtifactRefV5
from tuning.evals.information_fetch.information_yield.evaluator_v5 import evaluate_fresh_eiy_evaluation_v5,evaluate_fresh_now_evaluation_v5
from tuning.evals.information_fetch.information_yield.publisher_v1 import CANONICAL_INFORMATION_YIELD_V5_ROOT,publish_eiy_result_v1,publish_now_diagnostic_v1

class InformationYieldV5CliError(ValueError):pass

def _load_ref(path:Path)->dict[str,str]:return ArtifactRefV5.from_mapping(json.loads(path.read_text())).to_mapping()
def _read_ref(value):
    ref=ArtifactRefV5.from_mapping(value);return read({"path":str(ref.resolve(ROOT)),"sha256":ref.sha256})
def _canonical_publication_root(raw:Optional[str])->Path:
    if raw is None or raw!=str(CANONICAL_INFORMATION_YIELD_V5_ROOT):raise InformationYieldV5CliError("EIY_PUBLICATION_ROOT_NOT_CANONICAL")
    return CANONICAL_INFORMATION_YIELD_V5_ROOT

def main(argv:Optional[Sequence[str]]=None)->int:
    parser=argparse.ArgumentParser(prog="information-yield-v5")
    parser.add_argument("--evaluation-ref",type=Path,required=True,help="JSON file containing an immutable manifest/custody ref")
    parser.add_argument("--publication-root",help="exact canonical EIY v5 operational publication root")
    parser.add_argument("--mode",choices=("evaluation","now_diagnostic"),required=True)
    args=parser.parse_args(argv)
    publication_root=_canonical_publication_root(args.publication_root)
    fresh=check_eiy_evaluation_v5(_load_ref(args.evaluation_ref),read_ref=_read_ref,workspace_root=ROOT)
    if args.mode=="evaluation":published=publish_eiy_result_v1(evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=fresh),publication_root=publication_root)
    else:published=publish_now_diagnostic_v1(evaluate_fresh_now_evaluation_v5(fresh_evaluation=fresh),publication_root=publication_root)
    print(json.dumps(published,sort_keys=True,separators=(",",":")))
    return 0

if __name__=="__main__":raise SystemExit(main())
