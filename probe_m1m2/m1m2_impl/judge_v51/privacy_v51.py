"""Apply the v5 privacy scan to the exact v5.1 commit and review files."""

import importlib.util
from pathlib import Path
import re
import sys

BASE = Path(__file__).resolve().parent.parent / "judge_v5_bounded"
sys.path.insert(0, str(BASE))
from rules import validate

spec = importlib.util.spec_from_file_location("bounded_privacy", BASE / "privacy.py")
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
original.guard.ALLOWED = re.compile(
    r"probe_m1m2/m1m2_impl/judge_v51/(?:run_v51\.py|rules\.py|privacy_v51\.py|test_v51\.py|COUNTS\.txt)|"
    r"probe_m1m2/m1m2_impl/judge_v5_bounded/(?:run\.py|run\.sbatch|privacy\.py)|"
    r"probe_m1m2/m1m2_impl/judge_v4/pilot\.py"
)


if __name__ == "__main__":
    if sys.argv[1] == "staged":
        original.guard.staged(Path(sys.argv[2]))
    else:
        sys.exit(original.check(*map(Path, sys.argv[2:]), version="v51", validate_claims=validate))
