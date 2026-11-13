The cluster files listed in run_manifest.json live in its restricted Phase 1
run directory under the Zhurong bulk storage project. Access requires separate
permission for the shared project storage. The inventory describes the immutable
historical BrowseComp-Plus source and its independent outcome ledger.
Verify SHA-256 before using the input index, private JSONL or replay cache.
The review CSV in this release is a field template. The restricted run holds
the event-coordinate CSV and blind prefix packets without automatic decisions,
reference answers or future responses.

For a full offline replay, verify the cache manifest identified in run_manifest.json,
make a new output directory, and link its real/model_cache to the frozen model_cache.
Use the same index, tokenizer, prompts, code, and configuration parameters, with
output_dir and run_dir set to the new paths. Use --resume --replay-only. A separate
pass can compare its report hashes with the listed frozen outputs. The deployment
and replay did not need network access to a Judge provider.
