# 交付阅读说明

先读 `SAGE100_V1.3.2_Stage删除四次续跑与AB机制分析.md`。逐组完整分析见 `04_全部340组_逐组与四路分析.md`；精确证据在 `ANALYSIS/STAGE_REVIEWS/`，成本在 `ANALYSIS/COST_FACTS/`，统计与反向索引在 `ANALYSIS/MODEL_AUTHORED_SYNTHESIS/FINAL_STATISTICS/`。

包内实际复制100份原始轨迹、100份冻结映射、100份完整切分报告、340份原新四路语义记录、340份成本事实、全部归属及精确引文，不使用服务器符号链接。

2524条巨大完整新轨迹及请求响应/工具Return继续原样保存在本机：
`C:\Users\24413\Desktop\后训练\sage100_v132_stage_20261102\POSTGEN_EVIDENCE_EXPORT`。
本包不重复压入该大体积目录。全2524条相对路径、SHA、终态和评价索引在 `ANALYSIS/PEER_GOAL_COMPLETION_EVIDENCE_AUDIT/ALL2524_SOURCE_RESULT_INDEX.json`；以该本机证据根目录拼接。分析用1360路径的成本表另提供SHA。不能只访问原JSON内部旧服务器路径；应使用该实际本机根目录。

只复算统计：在解压后的本目录运行 `python ANALYSIS/MODEL_AUTHORED_SYNTHESIS/recompute_ab_statistics.py`。它不生成语义标签，不需要GPU，不会读Gold送模型；会在FINAL_STATISTICS重算表。

MANIFEST.json列包内每文件原始路径/大小/SHA。SHA256SUMS.txt涵盖全部非自身文件。ZIP已实际解压并逐件核验；解压校验结果位于ZIP旁的本机交付核验JSON。

研究结论是Codex建议，不是研究者独立人工验收。只有A/B作深层分析，其余目标仅保留客观覆盖/状态。
