# 冗余机制分析

本仓库保存三套已完成的 Stage 共性与作用机制分析人工审核包。根目录 ZIP 是原始封存归档，`reports/` 提供可直接浏览的 Markdown、CSV、JSON 与 JSONL 资料。

| 数据集 | 原始归档 | 在线阅读入口 | ZIP SHA-256 |
| --- | --- | --- | --- |
| BrowseComp-Plus | [ZIP](BrowseCompPlus_904Stage_Final_Function_Mechanism_Atlas.zip) | [reports/BrowseComp](reports/BrowseComp/INDEX.md) | `febee974be03cdae836b47cd255131c59e02e83d069fae62da9474789e2ee16c` |
| SAGE | [ZIP](SAGE100_V1.3.2_Stage删除四次续跑与AB340机制分析.zip) | [reports/SAGE](reports/SAGE/INDEX.md) | `3e0dce66794793b6b8fdd3df46412fef9acf5bd8173654d4e3fc635cb7de1737` |
| SciCode | [ZIP](SciCode_AB249_Stage共性与作用机制_完整分析.zip) | [reports/SciCode](reports/SciCode/INDEX.md) | `b4ae8136817df8fc358b49bfc5825d89d9558b77430c224e4b045fdc552a5b61` |

各数据集 `INDEX.md` 标出功能统计、机制支持数、支持案例、反例、逐 Stage 审阅、成本统计及源文件索引。SAGE 的重复原始轨迹仅保留在 ZIP 中，详情见其 [未展开清单](reports/SAGE/SKIPPED_FROM_EXPANSION.md)。

## 冗余 Judge 第一期

对冻结自然作答离线切分并构建逐 Stage 证据账本，输出 R1／R2b 判别、R2a 诊断和 GRPO 数值预览。人工审计报告与标签批准单独保存。原始数据和逐条含原文结果按授权存放，公开包提供复现入口、可发布的统计和合成例。运行只使用本地模型，优化器步数为零。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps .
python -m pytest tests -q
mkdir -p .phase1-private
cp configs/phase1.yaml .phase1-private/phase1.yaml
python -m redundancy_judge.cli inspect --config .phase1-private/phase1.yaml
python -m redundancy_judge.cli annotate --config .phase1-private/phase1.yaml --split dev --limit-questions 5
python -m redundancy_judge.cli annotate --config .phase1-private/phase1.yaml --split all --resume
python -m redundancy_judge.cli export-review --config .phase1-private/phase1.yaml
python -m redundancy_judge.cli audit --config .phase1-private/phase1.yaml
python -m redundancy_judge.cli reward-preview --config configs/reward_preview.yaml
python scripts/package_artifacts.py --run-id <phase1_run_id> --code-commit <frozen_commit>
python scripts/verify_artifacts.py --package <zip>
```

在配置副本内填写索引、输出、精确分词器、模型身份与代码提交。运行前启动本机 loopback 模型服务。在祝融使用 `scripts/zhurong_phase1.sbatch` 通过 Slurm 执行。提供原始数据时可使用 `scripts/index_browsecomp.py` 生成私有索引。工作目录的默认路径直接在配置中给出。

参见[数据清点](docs/data_inventory.md)、[接口](docs/interfaces.md)、[标注规程](docs/labeling_guide.md)、[验收](docs/acceptance.md)、[限制](docs/limitations.md)和[复现](REPRODUCE.md)。
