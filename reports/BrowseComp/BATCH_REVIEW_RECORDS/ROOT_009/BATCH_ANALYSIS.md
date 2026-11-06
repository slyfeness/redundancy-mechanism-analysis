# ROOT_009 批次归纳

10 Stage / 10题 / 10原轨迹 / 40续跑；组别{'A': 5, 'B': 5}。

以下机制是本人逐案裁定后的过程解释；统计由显式成员复算，非研究者独立人工金标准。


## functions

```json
{
  "description": "把候选与题目各条件作完整接受比较或识别人物选择中的层级冲突。",
  "members": [
    "1239__rep1__S002__FIRST_SENTENCE",
    "92__rep1__S002__FIRST_SENTENCE",
    "191__rep1__S003__TERMINAL_DROP_NO_ANCHOR"
  ],
  "distinction": "1239首次整体采用但原补证后还有完整复核；92比较有团体成立/个人出道混淆，原后修复；191既采用新回教育/驾驶事实又整体接受，无G。不能把所有比较认作重复，也不能把原U错误排除当正确认知更新。"
}
```

```json
{
  "description": "通过宽搜或具体人物取证获取身份、书目式关系与实际所求数值；产物可能存在而未采用，也可能完全未取得。",
  "members": [
    "291__rep1__S002__FIRST_SENTENCE",
    "319__rep1__S002__FIRST_SENTENCE",
    "625__rep1__S004__FIRST_SENTENCE",
    "688__rep1__S001__FIRST_SENTENCE",
    "980__rep1__S003__FIRST_SENTENCE",
    "873__rep2__S003__FIRST_SENTENCE"
  ],
  "distinction": "291身份Query有Baha全名/出生资料；319长红知更鸟猜测加失败Query未给事故死亡数；625未找到对应对话集数；688六广搜没Ike；980有Bobby关系却不采用；873十一尝试未定位博客。均有取证不等U已解决目标。"
}
```

```json
{
  "description": "空P下长篇纯推理枚举诗人、重复候选和拟定未执行搜索，最后耗尽生成长度。",
  "members": [
    "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR"
  ],
  "distinction": "整轨单Stage无真实Call、无G，四新是自然重新起跑；后来终于真实查证可改C，但不得解释为成功跳过整段功能。"
}
```


## comparisons

```json
{
  "id": "ROOT009_C1",
  "cases": [
    "1239__rep1__S002__FIRST_SENTENCE",
    "191__rep1__S003__TERMINAL_DROP_NO_ANCHOR",
    "92__rep1__S002__FIRST_SENTENCE"
  ],
  "finding": "同样认知判断，少篇幅不一定少功能。1239三支删前盘点而补证后保留一次，与1095前批共同支持实例压缩；191四支都重建整体判断，其中新4因奖项不等节目数额外实际查；92有支绕开前置人物比较，直接具体演出材料也能得名。",
  "counter": "1239新3原样重建，成本更高；191新4追真缺口不宜称无价值重复；92正确名仍有歌曲原创关系错误。"
}
```

```json
{
  "id": "ROOT009_C2",
  "cases": [
    "291__rep1__S002__FIRST_SENTENCE",
    "319__rep1__S002__FIRST_SENTENCE",
    "980__rep1__S003__FIRST_SENTENCE"
  ],
  "finding": "不同证据入口可改变交互规模：291一份Return同时给身份和学校关系，合并两次工作；319直接事故入口可跳过失败宽搜，但链条识别未必获证；980错电影Query意外回正确电影也能更新，另两C先具名关系Query。",
  "counter": "不是关键词越具体必然越好；291来源第四文档和正文时间需如实，319三支仍有背景无据/一支另得真实Spur身份，新1错Query成功不能一般化。"
}
```

```json
{
  "id": "ROOT009_C3",
  "cases": [
    "625__rep1__S004__FIRST_SENTENCE",
    "873__rep2__S003__FIRST_SENTENCE",
    "980__rep1__S003__FIRST_SENTENCE"
  ],
  "finding": "无目标证据后的推断替代要看具体错用关系。625将OVA在10/11间的位置当所问场景位置，873把题目未说改变当次年BMI不变，980则把不合年龄放宽到60s—70s以保留旧片。共同点是待核假设被提高为答案依据，证据对象/关系各不相同。",
  "counter": "873新2正式拒答而非默认值；625原C本来没有对应对话直接证据，不能说删除丢失已证6；980三C获得新剧情，材料状态也变。"
}
```

```json
{
  "id": "ROOT009_C4",
  "cases": [
    "688__rep1__S001__FIRST_SENTENCE",
    "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
    "980__rep1__S003__FIRST_SENTENCE"
  ],
  "finding": "已识别冲突或候选不等后续选择被约束。688新2明确WNBA1996冲突仍查Gabby；673新3知道Arnimal时间却把题目先后关系读成命名关系，继续查非必要人物；980新3保留正确争端却仍旧片。",
  "counter": "673新1/2/4真查诗人而C，688新3持续换人N并非相同冲突循环；不能把所有N归同一机制。"
}
```

```json
{
  "id": "ROOT009_C5",
  "cases": [
    "319__rep1__S002__FIRST_SENTENCE",
    "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
    "873__rep2__S003__FIRST_SENTENCE"
  ],
  "finding": "减少生成不等减少全部资源或提高质量：319保留6618前缀重放且四支真实事故检索；673新四生成都更少但Search/Actor/Prompt均多；873四项都少却仍全不正确，其中一次正式拒答。",
  "counter": "N→W属C/W/N变化但无准确率改善；不同原始切点成本不可用整条原总量代替，CHAR只保守区间。"
}
```


## mechanism_tests

```json
{
  "id": "ROOT009_T1",
  "description": "返回实体或关系进入实际具名核查，使宽假设转为可验证对象；记录采用与真实行动的时间差。",
  "links": [
    {
      "case_id": "92__rep1__S002__FIRST_SENTENCE",
      "local_id": "RETURNED_PERSONAL_DEBUT_FACT_USED_TO_SELECT_REAL_GROUP_QUERY"
    },
    {
      "case_id": "319__rep1__S002__FIRST_SENTENCE",
      "local_id": "NEW_CHAIN_RELATION_EVIDENCE_UPDATES_BACKGROUND_VERIFICATION_OBJECT"
    },
    {
      "case_id": "688__rep1__S001__FIRST_SENTENCE",
      "local_id": "RETURNED_PLAYER_USED_AS_REAL_NAME_AND_TEAM_VERIFICATION_KEY"
    },
    {
      "case_id": "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "RETURNED_POET_NAME_USED_IN_REAL_VERIFICATION_BEFORE_LIMITED_SUBMISSION"
    },
    {
      "case_id": "980__rep1__S003__FIRST_SENTENCE",
      "local_id": "RELATION_ENTITY_USED_IN_QUERY_BEFORE_TARGET_MOVIE_RETURN"
    }
  ],
  "relation": "P2_R1显式成员续增，分A/B、首句/无G、同题既往不增题。",
  "counterexamples": [
    "980新1先错Query偶然回正确片而C，不支持必须先改正确Query。",
    "673新3已识别诗人但未实际具名查询不等完全未采用；后来新增命名要求仍阻碍。",
    "319新1/3同C却未纠正连锁身份，正确所问数字可在身份链不充分时得到。"
  ],
  "unresolved": "查询决策和返回不同共同变化，只能给可观察链，不独证删除因果。",
  "deterministic_counts": {
    "observed_stage_count": 5,
    "different_questions": 5,
    "original_runs": 5,
    "observed_rollouts": 9,
    "not_observed_rollouts": 10,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 1,
    "observed_local_chain_occurrences": 9,
    "not_observed_local_chain_occurrences": 10,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 1,
    "total_distinct_rollouts_in_test": 20,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "319__rep1__S002__FIRST_SENTENCE",
      "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
      "688__rep1__S001__FIRST_SENTENCE",
      "92__rep1__S002__FIRST_SENTENCE",
      "980__rep1__S003__FIRST_SENTENCE"
    ],
    "question_ids": [
      "92",
      "319",
      "673",
      "688",
      "980"
    ]
  }
}
```

```json
{
  "id": "ROOT009_T2",
  "description": "补证前后两次完整比较改为补证后一次，保留实际判断功能但减少展开实例。",
  "links": [
    {
      "case_id": "1239__rep1__S002__FIRST_SENTENCE",
      "local_id": "ONE_POST_EVIDENCE_FULL_COMPARISON_REPLACES_PRE_AND_POST_REVIEWS"
    }
  ],
  "relation": "与ROOT008的1095有相同明确前后实例证据，可提出跨两题候选，不把所有推迟总结合并进来。",
  "counterexamples": [
    "1239新3重新进行前比较，后也比较，成本增加；新4多一次真实Search，认知压缩不保证净生成下降。",
    "两题G都明确补哪条缺口，有方向补偿。"
  ],
  "unresolved": "是否无需教师也会如此组织，现有分支不能定；只记录执行重组。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 3,
    "not_observed_rollouts": 1,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 3,
    "not_observed_local_chain_occurrences": 1,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "1239__rep1__S002__FIRST_SENTENCE"
    ],
    "question_ids": [
      "1239"
    ]
  }
}
```

```json
{
  "id": "ROOT009_T3",
  "description": "正确主体与未解特定关系之间，缺口可以额外派发真实核查，也可以在未补齐时仍有限提交。",
  "links": [
    {
      "case_id": "191__rep1__S003__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "AWARD_VERSUS_PRESENTATION_GAP_DISPATCHES_NEW_CHECKS_WITHOUT_DIRECT_CLOSURE"
    }
  ],
  "relation": "P2_R3新增一题，具体为获奖次数不等节目呈现数；已知数值与缺口是不同角色。",
  "counterexamples": [
    "其余三支C不额外查，其中新3只说准备核验而没有实际Call，不能算功能执行。",
    "新4三次真查仍未得到直接节目证据，消耗多不证明核验必要或有效。"
  ],
  "unresolved": "题名/姓名正确不能认所有要求证据充分，也不能用实际查而未闭合证明该条件不重要。",
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
      "191__rep1__S003__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "191"
    ]
  }
}
```

```json
{
  "id": "ROOT009_T4",
  "description": "已有返回缺口被未经支持的关系/时间推断替代，使模型选择具体核验对象或提交错误值。",
  "links": [
    {
      "case_id": "625__rep1__S004__FIRST_SENTENCE",
      "local_id": "OVA_RELATIVE_POSITION_PROMOTED_TO_TARGET_SCENE_LOCATION"
    },
    {
      "case_id": "873__rep2__S003__FIRST_SENTENCE",
      "local_id": "FIRST_POST_VALUE_CARRIED_TO_SECOND_WITHOUT_CHANGE_EVIDENCE"
    },
    {
      "case_id": "980__rep1__S003__FIRST_SENTENCE",
      "local_id": "PARTIAL_FEUD_EVIDENCE_RETAINED_WITH_RELAXED_AGE_CONSTRAINT_AND_WRONG_MOVIE"
    }
  ],
  "relation": "上位比较有三题，但三个具体推断不同，不直接注册为统一细机制。记录错误依据如何真实转查询/答案，不以W本身作支持。",
  "counterexamples": [
    "873新2考虑推断但正式拒绝确认，不算沿用值接受。",
    "625另外两W依剧情先验择集，无OVA位置解释；同W不同链。",
    "980真取得Dosti三C，纠正含新材料因素。"
  ],
  "unresolved": "原625C无直接对话证据，873原N无文章，不能用原新状态变化证明正确判断被移除。",
  "deterministic_counts": {
    "observed_stage_count": 3,
    "different_questions": 3,
    "original_runs": 3,
    "observed_rollouts": 5,
    "not_observed_rollouts": 6,
    "uncertain_rollouts": 1,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 5,
    "not_observed_local_chain_occurrences": 6,
    "uncertain_local_chain_occurrences": 1,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 12,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "625__rep1__S004__FIRST_SENTENCE",
      "873__rep2__S003__FIRST_SENTENCE",
      "980__rep1__S003__FIRST_SENTENCE"
    ],
    "question_ids": [
      "625",
      "873",
      "980"
    ]
  }
}
```

```json
{
  "id": "ROOT009_T5",
  "description": "识别候选冲突后仍让同一候选进入真实搜索，冲突没有成为行动排除条件。",
  "links": [
    {
      "case_id": "688__rep1__S001__FIRST_SENTENCE",
      "local_id": "RECOGNIZED_TEAM_ERA_CONFLICT_FAILS_TO_REMOVE_GABBY_FROM_REAL_SEARCH"
    }
  ],
  "relation": "本批一题单支的明确冲突—继续链，与前批同类需按具体候选/同一条件比较，不因为都有conflict合并。",
  "counterexamples": [
    "688新3会排除多个具体候选并换对象仍N，说明正确排除不充分保证成功。",
    "新1协议停无真实Call，排除机制分析；不能统作漏纠错。"
  ],
  "unresolved": "为什么仍保留Gabby的内部权重无日志直证，只能依据明确冲突与实际Query共现。",
  "deterministic_counts": {
    "observed_stage_count": 1,
    "different_questions": 1,
    "original_runs": 1,
    "observed_rollouts": 1,
    "not_observed_rollouts": 2,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 1,
    "observed_local_chain_occurrences": 1,
    "not_observed_local_chain_occurrences": 2,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 1,
    "total_distinct_rollouts_in_test": 4,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "688__rep1__S001__FIRST_SENTENCE"
    ],
    "question_ids": [
      "688"
    ]
  }
}
```

```json
{
  "id": "ROOT009_T6",
  "description": "已有题目先后关系被改写为命名要求，新的非必要条件派发真实人物查询。",
  "links": [
    {
      "case_id": "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "CHRONOLOGICAL_PREDECESSOR_RELATION_REWRITTEN_AS_NAMING_REQUIREMENT"
    }
  ],
  "relation": "与N003条件目标改写相关，但chronology→naming不等已有目标/范围窄化定义，保持局部待审，不擅自扩大登记。",
  "counterexamples": [
    "另外三支未强制命名关系且真实采用诗人C，仍缺水井直接支持。",
    "新3并非从未看到正确候选，而是识别后额外关系仍驱动其它Query。"
  ],
  "unresolved": "空P单Stage自然重新采样，不能作为纯局部删除机制证据。",
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
      "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "673"
    ]
  }
}
```


## unresolved

```json
{
  "case_id": "1239__rep1__S002__FIRST_SENTENCE",
  "issue": "重复比较实例压缩有两题证据但G给特定缺口，新4额外搜索抵消部分成本。"
}
```

```json
{
  "case_id": "92__rep1__S002__FIRST_SENTENCE",
  "issue": "部分正确人名伴歌曲原唱/日文来源无据或错解，CHAR生成只保守区间。"
}
```

```json
{
  "case_id": "191__rep1__S003__TERMINAL_DROP_NO_ANCHOR",
  "issue": "节目数缺直接支持，三支不查仍C不表示证据充分，无G自然重建判断。"
}
```

```json
{
  "case_id": "291__rep1__S002__FIRST_SENTENCE",
  "issue": "同Return两关系可省交互但母亲身份/转学因果仍不能据模型断言，局部重编码单列。"
}
```

```json
{
  "case_id": "319__rep1__S002__FIRST_SENTENCE",
  "issue": "新4真实取得Spur创始人/菜单，前三支C有背景无据或限制回答，不把所有额外查询算重复。"
}
```

```json
{
  "case_id": "625__rep1__S004__FIRST_SENTENCE",
  "issue": "原正确集数缺直接场景支持；OVA片段第十/十一之间不是场景位置，具体证据关系已定位。"
}
```

```json
{
  "case_id": "688__rep1__S001__FIRST_SENTENCE",
  "issue": "U未发现Ike，新1协议停止，新2旧候选冲突继续，新3换对象无果，三N不能同因。"
}
```

```json
{
  "case_id": "673__rep3__S001__TERMINAL_DROP_NO_ANCHOR",
  "issue": "整轨Stage从空P无G重新起跑，生成减少而其余资源增加；C仍缺水井证据。"
}
```

```json
{
  "case_id": "980__rep1__S003__FIRST_SENTENCE",
  "issue": "错Query能意外取得正确片，三C不能都解释成先正确关系查询，生日/角色附述另审。"
}
```

```json
{
  "case_id": "873__rep2__S003__FIRST_SENTENCE",
  "issue": "四W三错值一拒答，原N没有正确数值，G方向补偿且CHAR；未定位博客原因不能唯一归因。"
}
```


## 限制
10Stage/10题/10原轨迹/40支；8FIRST_SENTENCE、2TERMINAL分列，6原生精确/4字符重编码。全批A5 B5，B包含N→W和W→C，不用CWN变化代准确率变化。各检验成员有交叠不相加，未分组案例不强分类。Codex语义自审不是独立研究者金标准。