# ROOT_040 批次归纳

2 Stage / 1题 / 2原轨迹 / 8续跑；组别{'A': 2}。

以下机制是本人逐案裁定后的过程解释；统计由显式成员复算，非研究者独立人工金标准。


## functions

```json
{
  "description": "最新独立证据后整体接受及正式答案组织。",
  "members": [
    "1239__rep3__S004__TERMINAL_DROP_NO_ANCHOR"
  ],
  "distinction": "人口返回已有尚待采用，四完整恢复且文字全更长；不是外部再确认。"
}
```

```json
{
  "description": "无候选P的开放取证入口获取具体物种。",
  "members": [
    "1239__rep4__S001__FIRST_SENTENCE"
  ],
  "distinction": "原首次获取后才有物种；新教师直接给实体取代发现，部分真佐证与零Call区别。"
}
```


## comparisons

```json
{
  "id": "ROOT040_C1",
  "cases": [
    "1239__rep3__S004__TERMINAL_DROP_NO_ANCHOR",
    "1239__rep4__S001__FIRST_SENTENCE"
  ],
  "finding": "两A四C，前者G0纯认知全恢复、工具本就0且生成全增；后者G直接答案、大减工具但支持/独立性下降。",
  "counter": "答案保持既不等省功能，也不等更省/完整质量保持；两个机制不能按A合成冗余。"
}
```


## mechanism_tests

```json
{
  "id": "ROOT040_T1",
  "description": "G假来源叙述带答案后无真Return扩成条件说明。",
  "links": [
    {
      "case_id": "1239__rep4__S001__FIRST_SENTENCE",
      "local_id": "GUIDE_GIVEN_IDENTITY_AND_ALLEGED_RETURN_EXPANDED_WITHOUT_TRUE_TOOL_EVIDENCE"
    }
  ],
  "relation": "N002两支，P0/G19/零Call/附事实自补/Formal链齐；1/3真验证不归此零工具。",
  "counterexamples": [
    "同题无实体G有四真入口，G0最后判断四真重建而费增。"
  ],
  "unresolved": "不能从有答案预填的节省判自然Stage无用。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 2,
    "not_observed_rollouts": 2,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 2,
    "not_observed_local_chain_occurrences": 2,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "1239__rep4__S001__FIRST_SENTENCE"
    ],
    "question_ids": [
      "1239"
    ]
  }
}
```

```json
{
  "id": "ROOT040_T2",
  "description": "同认知恢复表达费用方向反例。",
  "links": [
    {
      "case_id": "1239__rep3__S004__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "POST_EVIDENCE_ACCEPTANCE_REBUILT_WITH_LONGER_EXPRESSION_NO_NEW_ACTION"
    }
  ],
  "relation": "开放功能/费用对照四更长，不强套已有机制正例。",
  "counterexamples": [
    "rep2同末段四短，不能按功能名预测费用。"
  ],
  "unresolved": "不造隐状态解释纯篇幅波动。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 4,
    "not_observed_rollouts": 0,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 4,
    "not_observed_local_chain_occurrences": 0,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "1239__rep3__S004__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "1239"
    ]
  }
}
```


## unresolved

```json
{
  "case_id": "1239__rep4__S001__FIRST_SENTENCE",
  "issue": "根P0近重启且G直接正确实体，Oracle严重补偿单列。"
}
```


## 限制
最终两Stage一题两run八分支，不能当两独立题；完成覆盖不等完成全部机制兼容/图谱/终包验收。