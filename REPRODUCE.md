# 复现第一阶段验收

1. 运行 `python scripts/verify_artifacts.py --package <zip>`，同时提供旁边的 `.zip.sha256`。
2. 在解包目录创建 Python 3.12 虚拟环境并安装 `requirements.lock`，运行 `python -m pytest tests -q --junitxml=test_results.xml`。
3. 使用验收目录的 `run_manifest.json` 对照代码、输入、提示词和模型指纹。用 `data_access.md` 找到获授权的原始记录与缓存。
4. 将运行配置中的路径指向受控文件，在同一冻结代码、模型和配置下执行 README 的命令。已有私有缓存可用时，`bash scripts/replay_acceptance.sh <config>` 只重放缓存。
5. 用逐轨迹摘要重算覆盖率、对照人工审查清单，并从奖励预览核对每个价位和策略掩码。合成测试可从 ZIP 单独复现，真实逐项标注需要私有数据和缓存或本地模型。
