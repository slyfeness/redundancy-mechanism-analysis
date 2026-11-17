"""Instrument the unchanged FSDP pilot within a private coexistence update."""
import os
from pathlib import Path
import sys

import torch

from hf_pilot_train import main, run_update, write_once
import hf_pilot_train


def measured_update(*args, **kwargs):
    result = run_update(*args, **kwargs)
    rank = int(os.environ["LOCAL_RANK"])
    output = Path(sys.argv[sys.argv.index("--output-root") + 1])
    torch.cuda.synchronize()
    write_once(output / f"MEMORY-rank{rank}.json", {
        "rank": rank, "checkpoint_started": False,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(rank),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(rank),
    })
    return result


if __name__ == "__main__":
    hf_pilot_train.run_update = measured_update
    raise SystemExit(main())
