"""CLI for a deterministic, read-only support run with rooted durable output."""
from __future__ import annotations

import argparse
from pathlib import Path

from .core import open_root_anchor, run_support, write_canonical_json


def main() -> int:
    here = Path(__file__).resolve().parent
    workspace = here.parents[1]
    parser = argparse.ArgumentParser(description="Build descriptive historical support geometry")
    parser.add_argument("--config", type=Path, default=here / "config.v1.json")
    parser.add_argument("--source-root", type=Path, default=workspace)
    parser.add_argument("--output-root", type=Path, default=here / "artifacts")
    parser.add_argument("--output-name", default="support-packet.json")
    parser.add_argument("--manifest-name", default="source-manifest.json")
    args = parser.parse_args()
    packet, manifest = run_support(args.config, args.source_root)
    # Publication order is payload manifest, then authority packet. Consumers accept
    # a pair only when packet.source_manifest_sha256 matches the manifest bytes.
    with open_root_anchor(args.output_root, "output root") as output_anchor:
        manifest_hash = write_canonical_json(args.output_root, args.manifest_name, manifest, root_anchor=output_anchor)
        packet["source_manifest_sha256"] = manifest_hash
        packet_hash = write_canonical_json(args.output_root, args.output_name, packet, root_anchor=output_anchor)
    geometry = packet["support_geometry"]
    print(f"status={packet['status']}")
    print(f"status_reasons={','.join(packet['status_reasons'])}")
    print(f"training_cloud_status={geometry['status']}")
    print(f"origin_id={packet['origin_id']}")
    print(f"policy_scope={packet['policy_scope']}")
    print(f"probability_feature_compatible={str(packet['probability_feature_compatible']).lower()}")
    print(f"expected_latest_completed_exchange_session={packet['expected_latest_completed_exchange_session']}")
    print(f"source_freshness_passed={str(packet['source_freshness']['passed']).lower()}")
    print(f"training_rows={geometry['training']['rows']}")
    print(f"manifest_sha256={manifest_hash}")
    print(f"packet_sha256={packet_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
