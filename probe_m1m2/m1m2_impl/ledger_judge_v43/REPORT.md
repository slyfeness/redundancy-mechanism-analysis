# 搜索词账本判定 v4.3
- [已验证] 轨迹 40｜Stage 430｜新增 Judge 调用 0
- [已验证] semantic_repeat 13｜stale_return 10｜strict_repeat 89｜F_new 9｜F_corrected 1
- [已验证] v4.2 semantic_repeat 37｜保留 9｜新增 4｜取消 28
| 结果 | 轨迹 | 平均 semantic_repeat | 平均 stale_return | 平均 strict_repeat |
|---|---:|---:|---:|---:|
| 答对 | 20 | 0.200 | 0.100 | 0.000 |
| 答错 | 6 | 0.167 | 0.167 | 1.833 |
| 未交卷 | 14 | 0.571 | 0.500 | 5.571 |

各步格式为 步号 标签 / new_docids。
- [已验证] 408__rep2｜3 无标签/2｜4 无标签/3｜5 无标签/2｜6 semantic_repeat/0｜7 无标签/1｜8 无标签/2
- [已验证] 408__rep6｜4 无标签/1｜5 无标签/1｜6 无标签/1
- [已验证] 408__rep8｜3 无标签/3｜4 无标签/1｜5 无标签/2｜6 无标签/2
- [已验证] 790__rep1｜5 无标签/2｜6 无标签/2｜7 无标签/1｜8 semantic_repeat/0｜9 semantic_repeat/0
- [已验证] 515__rep4｜8 wrong_candidate/1｜9 semantic_repeat+wrong_candidate/0
- [已验证] 391__rep2｜11 无标签/1
