# ROOT_004 批次归纳

10 Stage / 10题 / 10原轨迹 / 40续跑；组别{'A': 5, 'B': 5}。

以下机制是本人逐案裁定后的过程解释；统计由显式成员复算，非研究者独立人工金标准。


## functions

```json
{
  "description": "已有材料后进行完整候选比较、证据充分性判断和答案选择。",
  "members": [
    "69__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
    "78__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
    "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR",
    "87__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
    "270__rep4__S002__FIRST_SENTENCE"
  ],
  "distinction": "69证据已齐但接受工作仍恢复；87独立支持已在P且四支0Call接受；78大学日期缺，四支新真实查；83核心有据但石头缺口可导致重开实体；270比较真实产生错误时间排除，不能把同为条件盘点都当无新增作用。"
}
```

```json
{
  "description": "未定位对象时重选取证入口，并将新材料交给后续采用。",
  "members": [
    "55__rep2__S006__FIRST_SENTENCE",
    "226__rep3__S002__FIRST_SENTENCE",
    "257__rep4__S002__FIRST_SENTENCE"
  ],
  "distinction": "55由评论年份推期刊成立年不在题面区间；226泛工业查询没有对象；257短语Query真正找到正确作品。取证尝试相似但产品及错误位置不同。"
}
```

```json
{
  "description": "对已知候选核验排除条件，并推动转向另一候选。",
  "members": [
    "228__rep1__S004__FIRST_SENTENCE"
  ],
  "distinction": "U首度明确排除Kwon但所用婚育资料时点有局限，G直接给后续Ding方向；行为采用与事实证据充分性分开。"
}
```

```json
{
  "description": "全题已判断无匹配后重试，处理失败并正式报告未找到。",
  "members": [
    "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR"
  ],
  "distinction": "没有取得目标论文；四新重建失败判断后继续调用，原W新N并非正确性降低。"
}
```


## comparisons

```json
{
  "id": "ROOT004_C1",
  "cases": [
    "69__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
    "87__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
    "78__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
    "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR"
  ],
  "finding": "同为A末段判断，69全部0Call恢复且更短；87同样0Call恢复但篇幅可增可减；78全部增加两真实Call且有一支取得大学1209直接证据；83一支因石头条件重开植物候选到N。前态中已采用核心与未证条件不同，使相似盘点作用不同。",
  "counter": "不从A和答案保持推整个判断功能可省。69Prompt略升；78更多核查含真实增量；83失败不是丢了Hooker姓名。"
}
```

```json
{
  "id": "ROOT004_C2",
  "cases": [
    "257__rep4__S002__FIRST_SENTENCE",
    "270__rep4__S002__FIRST_SENTENCE",
    "228__rep1__S004__FIRST_SENTENCE"
  ],
  "finding": "功能重建必须追产物：257四支全恢复发现书，只有正确原版角色进入Query的两支C；270全恢复比较，但接受取代错误排除，部分先犯错再修复；228四支直接查Ding是G预给转换，不等于自主恢复原Kwon排除理由。",
  "counter": "真实Query、同一实体和标签FULL_REBUILT不能替代判断与使用；新2曾犯原时间错也能C，冲突一次出现不决定结局。"
}
```

```json
{
  "id": "ROOT004_C3",
  "cases": [
    "55__rep2__S006__FIRST_SENTENCE",
    "228__rep1__S004__FIRST_SENTENCE",
    "257__rep4__S002__FIRST_SENTENCE",
    "270__rep4__S002__FIRST_SENTENCE"
  ],
  "finding": "具体关系解释可生成后续工作：评论年份推创刊区间、大学合作作建筑归属、评论版次作原版、下界作时代排除。均可跟到真实下一Query，但每条关系及错误程度单独保留。",
  "counter": "55三支绕开原错年仍未证明期刊关系；228新1没走Webster同链；257新3错误但不具新4同样明确版次倒置；270新3城市疑虑与精确时间误读不混。"
}
```

```json
{
  "id": "ROOT004_C4",
  "cases": [
    "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR",
    "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR",
    "270__rep4__S002__FIRST_SENTENCE"
  ],
  "finding": "候选已采用与全题没候选两种缺口不同。83一个未证条件使姓名重新开放；270城市日期使已采用菜多查四次后仍以知识接受；261全题无对象，失败判断恢复后再查一次却无法进入下一Actor。",
  "counter": "不能把三者统称停止阈值或持续搜索冗余；城市/石头是实际题目条件，搜索本身可能合理，日志不能唯一解释停止。"
}
```

```json
{
  "id": "ROOT004_C5",
  "cases": [
    "226__rep3__S002__FIRST_SENTENCE",
    "257__rep4__S002__FIRST_SENTENCE",
    "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR"
  ],
  "finding": "B并不等退化：226原拒答W新三C一W，位置键实际采用可解释三成功；257原N新两C两W，找到作品不保证正确版次；261原W新四N，全都未答对，少生成与缺原FormalFinal相伴。",
  "counter": "必须先区分C/W/N转换与正确性变化，再解释中间过程，不把4/4状态不同等同4/4正确性改变。"
}
```


## mechanism_tests

```json
{
  "id": "ROOT004_T1",
  "description": "材料中的位置或出版角色变成真实查询对象时，原泛查改为具体对象核验；有材料但未采用保留负对照。",
  "links": [
    {
      "case_id": "226__rep3__S002__FIRST_SENTENCE",
      "local_id": "PLACE_KEY_MAKES_HISTORICAL_CONSTRAINTS_OBJECT_SPECIFIC"
    },
    {
      "case_id": "257__rep4__S002__FIRST_SENTENCE",
      "local_id": "FOUND_BOOK_ONLY_SUCCESS_WHEN_EDITION_ROLE_UPDATES_QUERY"
    }
  ],
  "relation": "延续P2_R1，但226的城市定位和257的原版角色两子链不等同，实际采用只按显式支计。",
  "counterexamples": [
    "226新3继续工业核验而W；257新3有书目仍D&Q，新4实际问原版且见Sasquatch仍解释反而W。",
    "采用新对象不自动证明全部条件，226距离/首层及年代事件仍有缺证。"
  ],
  "unresolved": "不能从只两题的正路径推出取证入口唯一必要，也不能用同DocID解释未采用的内部原因。",
  "deterministic_counts": {
    "observed_stage_count": 2,
    "different_questions": 2,
    "original_runs": 2,
    "observed_rollouts": 5,
    "not_observed_rollouts": 3,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 5,
    "not_observed_local_chain_occurrences": 3,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 8,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "226__rep3__S002__FIRST_SENTENCE",
      "257__rep4__S002__FIRST_SENTENCE"
    ],
    "question_ids": [
      "226",
      "257"
    ]
  }
}
```

```json
{
  "id": "ROOT004_T2",
  "description": "已采用且支持较充分的判断可在无G末段以更短认知过程重新完成；省一次展开/篇幅不等整个接受功能没做。",
  "links": [
    {
      "case_id": "69__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "SAME_SUFFICIENT_EVIDENCE_ACCEPTED_WITH_SHORTER_COGNITIVE_EXECUTION"
    },
    {
      "case_id": "87__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "SUPPORTED_CONCLUSION_REFORMULATED_WITHOUT_NEW_ACTION"
    }
  ],
  "relation": "不是P2_R2重复真实核验的同义词；此处零Call且独立接受判断仍重建，保留表达层和功能层分离。",
  "counterexamples": [
    "87新3/4生成更长，不是零Call就必然更省；69新1Finance假冲突也重现，仍比原短。",
    "69Prompt较原多12，生成降低不等所有资源下降。"
  ],
  "unresolved": "无无条件确定的整Stage可省证明，不能由稳定C直接判判断无作用。",
  "deterministic_counts": {
    "observed_stage_count": 2,
    "different_questions": 2,
    "original_runs": 2,
    "observed_rollouts": 8,
    "not_observed_rollouts": 0,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 8,
    "not_observed_local_chain_occurrences": 0,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 8,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "69__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
      "87__rep1__S004__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "69",
      "87"
    ]
  }
}
```

```json
{
  "id": "ROOT004_T3",
  "description": "关系或条件解释变成新任务前提：错创刊年引出年范围Query、大学合作变成建筑归属补证、版次/经济事件接成错误出版社成立年。",
  "links": [
    {
      "case_id": "55__rep2__S006__FIRST_SENTENCE",
      "local_id": "REVIEW_DATE_INFERENCE_CREATES_OUT_OF_RANGE_FOUNDING_QUERY"
    },
    {
      "case_id": "228__rep1__S004__FIRST_SENTENCE",
      "local_id": "EDUCATION_PARTNERSHIP_PROMOTED_TO_BUILDING_OWNERSHIP"
    },
    {
      "case_id": "257__rep4__S002__FIRST_SENTENCE",
      "local_id": "REVIEW_EDITION_AND_SPECULATOR_EVENT_MISBOUND"
    }
  ],
  "relation": "继续前批关系解释→具体核验任务提案，保留各子关系与正/不确定支，不扩写P1_K1定义来吞并。",
  "counterexamples": [
    "55错范围支仍核心C，其它支绕开错范围也没有查明期刊关系；257错误可使更短正式W或长N，不统一成本方向。",
    "228新2已知跨人婚育事实另一链，不能用建筑归属链覆盖全部失败。"
  ],
  "unresolved": "关系误解释的可见内容和下一Call可追，为什么模型选择该解释没有唯一内部证据。",
  "deterministic_counts": {
    "observed_stage_count": 3,
    "different_questions": 3,
    "original_runs": 3,
    "observed_rollouts": 4,
    "not_observed_rollouts": 6,
    "uncertain_rollouts": 2,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 4,
    "not_observed_local_chain_occurrences": 6,
    "uncertain_local_chain_occurrences": 2,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 12,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "228__rep1__S004__FIRST_SENTENCE",
      "257__rep4__S002__FIRST_SENTENCE",
      "55__rep2__S006__FIRST_SENTENCE"
    ],
    "question_ids": [
      "55",
      "228",
      "257"
    ]
  }
}
```

```json
{
  "id": "ROOT004_T4",
  "description": "错误排除不再持续约束具体候选，或被后续重解释修复后，实际行动从无对象探索返回正确对象。",
  "links": [
    {
      "case_id": "270__rep4__S002__FIRST_SENTENCE",
      "local_id": "WRONG_TIME_EXCLUSION_REMOVED_OR_REPAIRED_BEFORE_TARGET_QUERY"
    }
  ],
  "relation": "本批直接检验P1_K1；时间下界被误读是U真实工作，新1/2/4支持撤除/修复后的行动更新；新3保留不同初始疑虑的不确定分类。",
  "counterexamples": [
    "新2重建原错误并做三次替代取证仍能修复后C；不能宣称一次错误比较必然失败。",
    "新1虽然最终C仍四次未闭合城市查询，不把修正候选等同不再多算。"
  ],
  "unresolved": "本Stage没有删后失败内部反例；跨题匹配需保持精确的条件误读前提，不能按任何错误关系概括。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 3,
    "not_observed_rollouts": 0,
    "uncertain_rollouts": 1,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 3,
    "not_observed_local_chain_occurrences": 0,
    "uncertain_local_chain_occurrences": 1,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "270__rep4__S002__FIRST_SENTENCE"
    ],
    "question_ids": [
      "270"
    ]
  }
}
```

```json
{
  "id": "ROOT004_T5",
  "description": "缺口从判断进入真实行动后可改变成本与提交，但对象已定的辅助条件和全题未定位必须分开。",
  "links": [
    {
      "case_id": "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "UNVERIFIED_DISCRIMINATOR_REOPENS_ENTITY_DESPITE_NAME_RECOGNITION"
    },
    {
      "case_id": "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "FAILED_GLOBAL_JUDGMENT_REBUILT_BUT_ANOTHER_SEARCH_PRECEDES_FINAL"
    },
    {
      "case_id": "270__rep4__S002__FIRST_SENTENCE",
      "local_id": "ADOPTED_DISH_WITH_CITY_DATE_GAP_TRIGGERS_ADDITIONAL_CHECKS"
    }
  ],
  "relation": "83与270触及P2_R3既有候选/剩余条件边界，261无论文候选只作对照，不强制归入同机制。",
  "counterexamples": [
    "83其他三支提交，270其它三支不单查城市也C，261四支全N且原W同样没答案。",
    "必要题目条件不能凭末端未闭合或多查询就判冗余。"
  ],
  "unresolved": "目前能追实际缺口、行动和上下文终态，不能以隐藏信心阈值解释原Stage为何停止。",
  "deterministic_counts": {
    "observed_stage_count": 3,
    "different_questions": 3,
    "original_runs": 3,
    "observed_rollouts": 6,
    "not_observed_rollouts": 6,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 6,
    "not_observed_local_chain_occurrences": 6,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 12,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR",
      "270__rep4__S002__FIRST_SENTENCE",
      "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "83",
      "261",
      "270"
    ]
  }
}
```

```json
{
  "id": "ROOT004_T6",
  "description": "已显式接受原版和成立年后，再真实发起原书目确认；与尚未闭合条件的首次核查分开。",
  "links": [
    {
      "case_id": "257__rep4__S002__FIRST_SENTENCE",
      "local_id": "ACCEPTED_ORIGINAL_PUBLICATION_REOPENED_FOR_CONFIRMATION"
    }
  ],
  "relation": "P2_R2单题新支支持，不能把同支前一情节核查也统计为已证后重复。",
  "counterexamples": [
    "额外独立来源核验可以合理；只确定已采用后又查且答案没变，不证明这一次没有质量价值。"
  ],
  "unresolved": "新增独立核验提供多少置信支持没有唯一量化，不给固定冗余标签。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 1,
    "not_observed_rollouts": 3,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 1,
    "not_observed_local_chain_occurrences": 3,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "257__rep4__S002__FIRST_SENTENCE"
    ],
    "question_ids": [
      "257"
    ]
  }
}
```


## unresolved

```json
{
  "case_id": "55__rep2__S006__FIRST_SENTENCE",
  "issue": "更换年份框架可以恢复核心C但评论与刊物关系仍未证。"
}
```

```json
{
  "case_id": "69__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
  "issue": "四支更短完整重建，没有整功能省略；Prompt略升。"
}
```

```json
{
  "case_id": "78__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
  "issue": "新2实际1209来源已定向读验，新3只有college1441，不能复制证据。"
}
```

```json
{
  "case_id": "83__rep2__S010__TERMINAL_DROP_NO_ANCHOR",
  "issue": "石头条件共享缺证，一支因此重开实体N，不能称删除失去姓名。"
}
```

```json
{
  "case_id": "87__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
  "issue": "P支持较完整仍共享说话人数/性别叙述张力，完整接受重建不等纯重复无价值。"
}
```

```json
{
  "case_id": "226__rep3__S002__FIRST_SENTENCE",
  "issue": "三支城市采用后C但地理距离和事件时间支持不齐；G给商业方向。"
}
```

```json
{
  "case_id": "228__rep1__S004__FIRST_SENTENCE",
  "issue": "G给Ding转换，原婚育排除时点存在争议，四支不能算自主排除恢复。"
}
```

```json
{
  "case_id": "257__rep4__S002__FIRST_SENTENCE",
  "issue": "新3未采用和新4主动反解关系不同；核心发现均恢复。"
}
```

```json
{
  "case_id": "261__rep2__S005__TERMINAL_DROP_NO_ANCHOR",
  "issue": "四N主要无正式失败Final，既未丢正确论文也不能把所有少生成归U省。"
}
```

```json
{
  "case_id": "270__rep4__S002__FIRST_SENTENCE",
  "issue": "新3初始城市比较的隐藏关系原因不确定，城市成立日期仍未直接获证。"
}
```


## 限制
本批与前批有同题不同Stage，批内不同题目数不能跨批相加。四支机制出现与结果改善分列，反例和G提示保留。原生精确和CHAR边界各自成本口径保留，独立删除分支节省不得相加。以上为Codex语义审阅，不是独立人工金标准。