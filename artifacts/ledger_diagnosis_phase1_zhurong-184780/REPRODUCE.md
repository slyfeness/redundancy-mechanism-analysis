# 复现冻结账本诊断

运行源码为 `4ab6908d68a6ab1a9ec33c9db2454669ca737721`。一期交付基准为
`3cc8a2f7549814421c5000abd0668b3d6d77715e`。在诊断分支运行下列步骤。
祝融的所有集群计算通过 CPU Slurm 作业提交，使用已安装的 Phase 05 Python 环境。
本地可用 Python 3.11 或 3.12。新增脚本仅使用标准库和一期项目依赖。

```bash
git diff --exit-code 4ab6908d68a6ab1a9ec33c9db2454669ca737721 -- src prompts configs
python -m pip install -r requirements.lock
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1
python -m pytest tests -q --junitxml=/path/to/new/test_results.xml
python scripts/reproduce_ledger_mechanisms.py --output /path/to/new/mechanism_reproduction.json
```

上面的九项机制复现只用合成夹具。测试与真实频率分别保存。

真实复现需要访问祝融受控目录。用一期 [run_manifest.json](../phase1_zhurong-184780/run_manifest.json)
和 [data_access.md](../phase1_zhurong-184780/data_access.md) 定位原始运行目录、缓存清单、原始轨迹
索引与校验值。冻结 `config.json` 在一期运行的父目录，内含权威索引、提示词、原生分词器和缓存版本。
直接传入原文件路径，代码不会将路径改指向新缓存。

在已有环境下通过 Slurm 执行下列实际入口，参数为经授权的实际路径。

```bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$FROZEN_SOURCE/src"
python -u scripts/diagnose_phase1_ledger.py --replay-only \
  --config "$FROZEN_CONFIG" \
  --manifest artifacts/phase1_zhurong-184780/run_manifest.json \
  --cache-manifest "$FROZEN_CACHE_SHA256SUMS" \
  --output "$NEW_PRIVATE_DIRECTORY"

python -u scripts/export_ledger_diagnosis.py \
  --private "$NEW_PRIVATE_DIRECTORY" --public "$NEW_SANITIZED_DIRECTORY"
```

模型适配器首先从冻结请求和配置重新计算缓存键。运行中禁用 Python HTTP opener，
找不到缓存会显式终止。脚本在独立目录使用原流水线写出比对产物。
不能仅从 GitHub 脱敏数据完整重放；公开逐行索引用 1 起始行号指向受控文件，
完整路径、范围与 SHA-256 在 `input_manifest.json`。运行日志仅提供无原文的汇总与作业执账记录。
