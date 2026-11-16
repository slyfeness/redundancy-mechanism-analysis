"""Run the v3 M3 prompt-only re-exam and compare with frozen v2 IDs."""

import argparse
from pathlib import Path

from run_exam import digest, read
from run_exam_v2 import run_exam

PROMPTS = {"intent": "m3v3_intent.md", "verification": "m3v3_verification.md"}


def compare_v2(v3, v2):
    current, old = set(v3), set(v2)
    return {"both_r1": sorted(current & old), "v2_only": sorted(old - current), "v3_only": sorted(current - old)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("review", "manifest", "v1", "v2", "runtime", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    prior = read(args.v2)
    config = read(args.v2.parent / "config.json")
    if (prior["job_id"], prior["searches"], config["review_manifest_sha256"], config["v1_A_summary_sha256"]) != (
        187403, 532, digest(args.manifest), digest(args.v1 / "m3_exam_summary.json")
    ):
        raise ValueError("v2 summary is not bound to the same frozen exam inputs")
    run_exam(args, prefix="m3v3", prompts=PROMPTS,
             compare=lambda report: {"v2_comparison": compare_v2(report["new_r1_event_ids"],
                                                                 prior["new_r1_event_ids"])},
             extra_config={"v2_summary_sha256": digest(args.v2), "baseline_job": 187403})


if __name__ == "__main__":
    main()
