"""Provider-free CLI for the frozen one-origin SOXL descriptive snapshot."""
from __future__ import annotations
import argparse
from pathlib import Path
from .core import open_root_anchor, write_canonical_json
from .soxl_support import build_preregistration, load_soxl_config, run_soxl_support

def main() -> int:
    here=Path(__file__).resolve().parent; workspace=here.parents[1]
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,default=here/"soxl_config.v1.json")
    parser.add_argument("--source-root",type=Path,default=workspace)
    parser.add_argument("--output-root",type=Path,default=here/"artifacts"/"soxl")
    args=parser.parse_args()
    config=load_soxl_config(args.config)
    prereg=build_preregistration(config,args.config.read_bytes())
    # Preregistration is the first publication and precedes all bound-source reads.
    with open_root_anchor(args.output_root,"output root") as anchor:
        prereg_hash=write_canonical_json(args.output_root,"preregistration.v1.json",prereg,root_anchor=anchor)
    packet,manifest,observed_prereg=run_soxl_support(args.config,args.source_root)
    if observed_prereg != prereg:
        raise RuntimeError("preregistration changed during run")
    with open_root_anchor(args.output_root,"output root") as anchor:
        manifest["preregistration_sha256"]=prereg_hash
        manifest_hash=write_canonical_json(args.output_root,"source-manifest.v1.json",manifest,root_anchor=anchor)
        packet["preregistration_sha256"]=prereg_hash; packet["source_manifest_sha256"]=manifest_hash
        packet_hash=write_canonical_json(args.output_root,"support-packet.v1.json",packet,root_anchor=anchor)
    knn=packet["support_geometry"]["knn"]
    print(f"status={packet['status']}")
    print(f"geometry_status={packet['support_geometry']['status']}")
    print(f"origin_id={packet['origin_id']}")
    print(f"training_rows={packet['support_geometry']['training']['rows']}")
    print(f"neighbors={len(knn['neighbors'])}")
    print(f"packet_sha256={packet_hash}")
    return 0
if __name__=="__main__": raise SystemExit(main())
