# 搜索词账本判定 v4.6
- 状态 · 待人工验收。
- 轨迹 40｜Stage 430｜Judge 调用 0｜恢复资格复核前归属 29 条
- F_new 8｜F_corrected 1｜idle_type strict 89｜semantic 14｜none 327
| 结果 | 轨迹 | 平均 strict | 平均 semantic | 平均 F_new | 平均未纠正 F_new |
|---|---:|---:|---:|---:|---:|
| 答对 | 20 | 0.000 | 0.100 | 0.200 | 0.150 |
| 答错 | 6 | 1.833 | 0.167 | 0.500 | 0.500 |
| 未交卷 | 14 | 5.571 | 0.786 | 0.071 | 0.071 |

与 v4.4 比较
- 保留 8｜1233__rep8/4 (S)｜1238__rep4/4 (M)｜1238__rep4/3 (M)｜1238__rep6/3 (M)｜1238__rep7/11 (M)｜254__rep8/5 (M)｜391__rep2/5 (P)｜515__rep4/7 (P)
- 取消 6｜1238__rep7/2 (D)｜254__rep4/6 (A)｜254__rep5/1 (A)｜254__rep7/1 (A)｜790__rep6/1 (P)｜790__rep6/3 (P)
- 新增 0
- 8 个已人工确认事件（候选归属 / Stage 标签）
  - 515__rep4/7 (P) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 1233__rep8/4 (S) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 1238__rep7/11 (M) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 1238__rep4/3 (M) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 1238__rep4/4 (M) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 1238__rep6/3 (M) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
  - 254__rep8/5 (M) wrong_candidate / strict_repeat+wrong_candidate+F_new
  - 391__rep2/5 (P) wrong_candidate / wrong_candidate+F_new+protected_new_hypothesis
- 6 个已人工确认误判（候选归属 / Stage 标签）
  - 790__rep6/1 (P) aux / protected_new_hypothesis
  - 790__rep6/3 (P) none / 无标签
  - 254__rep5/1 (A) aux / protected_new_hypothesis
  - 254__rep7/1 (A) aux / protected_new_hypothesis
  - 254__rep4/6 (A) aux / protected_new_hypothesis
  - 1238__rep7/2 (D) aux / protected_new_hypothesis
