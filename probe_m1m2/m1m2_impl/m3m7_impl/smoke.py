"""One native group through the actual HF PPO forward/backward, without Adam or persistence."""

from argparse import ArgumentParser
from datetime import timedelta
import importlib
import json
import math
import os
from pathlib import Path
import time

import torch

from hf_pilot_train import TorchCollective, load_backend, load_step_inputs, rank_records, record_loss, write_once


def main():
    parser = ArgumentParser(description=__doc__)
    for key in ("input", "actor", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    a = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("WORLD_SIZE", 0)) != 4:
        raise ValueError("smoke requires one authorized four-rank Slurm job")
    rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(rank)
    device = torch.device("cuda", rank)
    torch.distributed.init_process_group("nccl", device_id=device, timeout=timedelta(minutes=30))
    collective = TorchCollective(rank, 4, device)
    try:
        prepared, manifest = load_step_inputs(a.input / "native-batch.json", a.input / "scores.pt")
        native = json.loads((a.input / "native-batch.json").read_bytes())
        if len(native["trajectories"]) != 8 or len({r["query_id"] for r in native["trajectories"]}) != 1:
            raise ValueError("smoke requires one complete source group")
        if not any(bool(record["action_advantages"].ne(0).any()) for record in prepared["records"]):
            raise ValueError("smoke would exercise only zero gradients")
        torch.manual_seed(20261109)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        backend = load_backend()
        # The production backend is read-only. This process binds its existing
        # scorer to the original round4 actor checkpoint for the smoke only.
        train = importlib.import_module("src.train_smoke")
        train.MODEL = str(a.actor.resolve(strict=True))
        model, _, kernels, _ = backend.make_model(rank)
        probes = [p.detach().flatten()[:16].cpu().clone() for p in model.parameters()
                  if p.requires_grad and p.numel()]
        torch.cuda.synchronize()
        if rank == 0:
            print(json.dumps({"phase": "model_ready", "group_size": 8, "records": len(prepared["records"]),
                              "action_tokens": prepared["global_token_count"]}), flush=True)

        state = {}
        def observe_hidden(_module, _inputs, output):
            allowed = state["allowed"]
            hidden = output[0]

            def check(grad):
                # These are direct objective gradients at causal prediction
                # positions. Context still conditions the policy.
                per_position = torch.count_nonzero(grad[0], dim=-1)
                state["off_mask"] += int(per_position[~allowed].sum())
                state["on_mask"] += int(per_position[allowed].ne(0).sum())
            hidden.register_hook(check)

        handle = model.module.model.model.register_forward_hook(observe_hidden)
        elapsed = time.monotonic()
        counts = torch.zeros(4, dtype=torch.float64, device=device)
        try:
            for step, record in enumerate(rank_records(prepared, rank=rank, world=4), 1):
                prompt = len(record["prompt_ids"])
                offsets = torch.tensor(record["action_offsets"], dtype=torch.long, device=device)
                mask = record["action_mask"].to(device=device, dtype=torch.bool)
                allowed = torch.zeros(prompt + len(record["completion_ids"]), dtype=torch.bool, device=device)
                allowed[prompt + offsets[mask] - 1] = True
                state.update(allowed=allowed, off_mask=0, on_mask=0)
                result, _, _, _ = record_loss(record, prepared, model, collective)
                result["loss"].backward()
                counts[0] += result["loss_numerator"].detach().double()
                counts[1] += int(mask.sum())
                counts[2] += state["off_mask"]
                counts[3] += state["on_mask"]
                del result
                print(json.dumps({"phase": "backward", "rank": rank, "record": step, "action_tokens": int(mask.sum())}),
                      flush=True)
        finally:
            handle.remove()
        norm = float(model.clip_grad_norm_(math.inf))
        param_fixed = all(torch.equal(p.detach().flatten()[:16].cpu(), before) for p, before in
                          zip((p for p in model.parameters() if p.requires_grad and p.numel()), probes, strict=True))
        totals = collective.sum(counts).tolist()
        changed = int(collective.maximum(int(not param_fixed)))
        loss = totals[0] / prepared["global_token_count"]
        if (not math.isfinite(loss) or not math.isfinite(norm) or norm <= 0 or changed
                or int(totals[1]) != prepared["global_token_count"] or totals[2] != 0 or totals[3] <= 0):
            raise ValueError("smoke loss, gradients, token count, or parameter probes failed")
        if rank == 0:
            write_once(a.out / "SMOKE.json", {
                "group_size": 8, "records": len(prepared["records"]), "loss": loss, "grad_norm": norm,
                "action_tokens": int(totals[1]), "off_mask_grad_elements": int(totals[2]),
                "nonzero_action_grad_positions": int(totals[3]), "optimizer_steps": 0, "saved_model_parameters": 0,
                "changed_parameter_probes": changed, "kl_coefficient": 0., "time": time.monotonic() - elapsed,
                "kernels": kernels, "score_config": manifest["score_config"],
            })
        collective.barrier()
    finally:
        torch.distributed.destroy_process_group()


if __name__ == "__main__":
    main()
