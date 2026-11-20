# 生成前账本与搜索词判定

- 轨迹 40｜Stage 430｜Judge 调用 65/80｜ψ 0｜留出题正文读取 0
- 历史命中 2240｜显式标题 0｜带思考 Stage 429
- direction on_track 430/430（100.00%）｜wrong_candidate 0/430（0.00%）｜contradicts_ledger 0/430（0.00%）
- repeat new 383/430（89.07%）｜strict_repeat 46/430（10.70%）｜semantic_repeat 1/430（0.23%）｜justified_recheck 0/430（0.00%）
- 校验失败后保守默认 62
- strict_repeat 一致（有效搜索 Stage）321/348（92.24%）｜TP 40｜FP 6｜FN 21｜TN 281
- semantic_repeat 后出现 C_new 0/1（0.00%）

| 结果 | 轨迹数 | 平均 F_new | 平均未纠正 F_new | semantic_repeat 数 |
|---|---:|---:|---:|---:|
| 答对 | 20 | 0.000 | 0.000 | 0 |
| 答错 | 6 | 0.000 | 0.000 | 0 |
| 未交卷 | 14 | 0.000 | 0.000 | 1 |
