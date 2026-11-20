# M2 v6.1 主语清理修正

- 训练题 664｜留出题正文读取 0｜断言生成调用 0｜账本轨迹 399
- 可用题 449/664 → 610/664（91.87%）｜门槛 80%｜不足 2 条 54
- 撤销主语删除 1105｜恢复后入账 1072
- 其余规则仍删除 33｜answer_in_claim 25｜duplicate_claim 8
- Gold 补判请求 341｜轨迹补判 168｜沿用原判轨迹 231

| 不足 2 条的原因（按题计，可重叠） | 题数 |
|---|---:|
| answer_in_claim | 8 |
| answer_relation_missing | 1 |
| capitalized_word_not_in_question_or_names | 37 |
| condition_count_outside_2_to_10 | 45 |
| invalid_entity_table | 1 |
| invalid_json_or_record_fields | 2 |
| number_not_in_question_or_names | 35 |
| repair_response_unusable | 1 |
| span_not_verbatim | 12 |
| unknown_subject | 4 |
| unresolved_entity | 9 |
| unresolved_entity_table | 16 |

| 轨迹范围 | 结果 | N | 平均 C_new | 平均 v3 | 平均 DocID |
|---|---|---:|---:|---:|---:|
| 全量 | 答对 | 109 | 3.3303 | 3.5596 | 4.3486 |
| 全量 | 答错 | 56 | 1.8036 | 1.1786 | 2.4464 |
| 全量 | 未交卷 | 234 | 0.9957 | 1.0171 | 1.7137 |
| 可用题 | 答对 | 93 | 3.9032 | 3.2581 | 4.3548 |
| 可用题 | 答错 | 49 | 2.0612 | 1.3469 | 2.7143 |
| 可用题 | 未交卷 | 209 | 1.1148 | 1.1100 | 1.7560 |

- 空跑 Stage 4363｜缺失 0｜私有抽查 15
