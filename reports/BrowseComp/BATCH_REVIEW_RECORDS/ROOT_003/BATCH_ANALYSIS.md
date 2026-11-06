# ROOT_003 批次归纳

10 Stage / 10题 / 10原轨迹 / 40续跑；组别{'A': 5, 'B': 5}。

以下机制是本人逐案裁定后的过程解释；统计由显式成员复算，非研究者独立人工金标准。


## functions

```json
{
  "description": "主体已采用后补具体未知约束，或给已定主体增加独立支持。",
  "members": [
    "55__rep2__S005__FIRST_SENTENCE",
    "69__rep1__S004__FIRST_SENTENCE",
    "78__rep1__S003__FIRST_SENTENCE",
    "87__rep1__S003__FIRST_SENTENCE"
  ],
  "distinction": "69两事实全缺且四支真实恢复；87主体已由独特故事采用，两支可不做分类补证而核心C但支持少；55期刊关系未找到；78现任资料本身仍缺且U补到。相似核查操作的信息增量不同。"
}
```

```json
{
  "description": "多项材料已见后形成完整充分性判断、来源姓名选择与提交。",
  "members": [
    "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
    "261__rep2__S004__FIRST_SENTENCE"
  ],
  "distinction": "83已有最强主体/精确姓名但两关系缺；261长期没有论文候选，U判断全题无匹配。前者最终核心C、后者原正式拒答W，不混停止质量。"
}
```

```json
{
  "description": "无对象时选择线索入口并提供新候选材料，等待后继采用。",
  "members": [
    "226__rep3__S001__FIRST_SENTENCE",
    "257__rep1__S004__FIRST_SENTENCE",
    "270__rep4__S001__FIRST_SENTENCE"
  ],
  "distinction": "226初探只得局部地址未用；257旧书失败后实际改情节得新书；270原初两查已得正确菜/47，错误在后续排除。结果N不证明U没贡献。"
}
```

```json
{
  "description": "两已有候选中先核一个候选的具体条件，使后继能继续比较/排除。",
  "members": [
    "228__rep1__S003__FIRST_SENTENCE"
  ],
  "distinction": "U确取得Kwon学校1960，原后来才婚育排除；不是正确Ding首次采用。删除后四N不能把该校史产品改写成Stanford直接事实。"
}
```


## comparisons

```json
{
  "id": "ROOT003_C1",
  "cases": [
    "69__rep1__S004__FIRST_SENTENCE",
    "87__rep1__S003__FIRST_SENTENCE",
    "55__rep2__S005__FIRST_SENTENCE"
  ],
  "finding": "同为A核验，69P姓名已采用但两事实未知，四支全部真实恢复；87P独特故事已确定主体，两支直接答但分类/河名支持下降；55P核心已定，期刊关系仍缺，四支全部继续核查却只有一支全成本下降。",
  "counter": "不能将A自动分成无价值，也不能将重建视为结束解释；需要具体说维持哪个判断、哪项支持没恢复。"
}
```

```json
{
  "id": "ROOT003_C2",
  "cases": [
    "78__rep1__S003__FIRST_SENTENCE",
    "55__rep2__S005__FIRST_SENTENCE",
    "228__rep1__S003__FIRST_SENTENCE"
  ],
  "finding": "错误关系可产生新工作：78把现任学历归父亲后查现任大学，55把author作刊物后查创刊，228把部分建筑赠款对象作为游戏身份任务。下游目标与费用可追踪，但缺口真不存在和缺口只未证必须分开。",
  "counter": "78新4额外查Cambridge成立确有新证据，不能因多两Call统一说低效；新1错教育角色也能修复后C。"
}
```

```json
{
  "id": "ROOT003_C3",
  "cases": [
    "257__rep1__S004__FIRST_SENTENCE",
    "226__rep3__S001__FIRST_SENTENCE",
    "270__rep4__S001__FIRST_SENTENCE"
  ],
  "finding": "有正确材料不等有效行动：257三支取得新书但只有一支用1999原版关系转Sasquatch；226局部地址多次出现，唯一C晚才把地名写入Query；270原U本已拿到正确菜，后续却错排，四新因G先给正确菜/词义后定向查真实年龄。",
  "counter": "270的发现产物来自G，不能把它和226自主新采用当同样的可省证据；257新2根本没取得新书，不属于同材料出版关系对照。"
}
```

```json
{
  "id": "ROOT003_C4",
  "cases": [
    "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
    "261__rep2__S004__FIRST_SENTENCE"
  ],
  "finding": "全局判断既可重建又不决定是否再查：83四支都恢复姓名/充分性判断，仅一支执行两新Call；261三支恢复不足判断后再查两次到N、一支直接正式拒答W。",
  "counter": "83核心有据而两识别条件缺，261根本无论文对象；不能合并成同一种缺口或停止阈值，后者W/N变化没有答对率变化。"
}
```

```json
{
  "id": "ROOT003_C5",
  "cases": [
    "69__rep1__S004__FIRST_SENTENCE",
    "78__rep1__S003__FIRST_SENTENCE",
    "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
    "87__rep1__S003__FIRST_SENTENCE"
  ],
  "finding": "多核查和多文字分别计：69四支工具同数生成可短可长且Prompt全升；78额外工具既有真实新年证据也有错对象；83只有新3真再查，其它多拟Query但0Call；87两支0Call确少工作却少支持。",
  "counter": "不能从同核心C/少生成推全部计算下降，也不能以工具数多判新增工作无价值。"
}
```


## mechanism_tests

```json
{
  "id": "ROOT003_T1",
  "description": "局部线索或书目关系进入真实Query后才产生新的可核关系；有材料、说出关系与更新行动三个节点必须分开。",
  "links": [
    {
      "case_id": "226__rep3__S001__FIRST_SENTENCE",
      "local_id": "LOCAL_ADDRESS_VISIBILITY_TO_REAL_CITY_QUERY"
    },
    {
      "case_id": "257__rep1__S004__FIRST_SENTENCE",
      "local_id": "BIBLIOGRAPHIC_ROLE_ADOPTION_TO_CORRECT_PUBLISHER_QUERY"
    }
  ],
  "relation": "继续P2_R1。只把226新4/257新4实际转换计OBSERVED，未转换支保留NOT_OBSERVED或前态不符排除；不把反例也算正支持。",
  "counterexamples": [
    "226新3眼镜店地址有返却仍查Rotterdam；257新1/3书目有返仍查D&Q，均非没资料。",
    "转换仍不保证全题支持，226鱼公司/距离/时点没有全证。"
  ],
  "unresolved": "未转换的内部原因不能由日志唯一解释，G/采样和召回时点保留。",
  "deterministic_counts": {
    "observed_stage_count": 2,
    "different_questions": 2,
    "original_runs": 2,
    "observed_rollouts": 2,
    "not_observed_rollouts": 5,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 1,
    "observed_local_chain_occurrences": 2,
    "not_observed_local_chain_occurrences": 5,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 1,
    "total_distinct_rollouts_in_test": 8,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "226__rep3__S001__FIRST_SENTENCE",
      "257__rep1__S004__FIRST_SENTENCE"
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
  "id": "ROOT003_T2",
  "description": "部分或错误关系提升为工作前提，会实际派发另一对象的属性核验；错误过程可只增加费用/削弱解释，也可改变答案。",
  "links": [
    {
      "case_id": "55__rep2__S005__FIRST_SENTENCE",
      "local_id": "METADATA_IDENTITY_CREATES_FOUNDING_SUBTASK"
    },
    {
      "case_id": "78__rep1__S003__FIRST_SENTENCE",
      "local_id": "EDUCATION_ROLE_ERROR_DISPATCHES_WRONG_PERSON_WORK"
    },
    {
      "case_id": "228__rep1__S003__FIRST_SENTENCE",
      "local_id": "PARTIAL_BUILDING_MATCH_CREATES_GAME_IDENTITY_TASK"
    },
    {
      "case_id": "257__rep1__S004__FIRST_SENTENCE",
      "local_id": "WRONG_PUBLICATION_ROLE_PRODUCES_FOUNDING_YEAR_WORK"
    }
  ],
  "relation": "支持ROOT001_T2上位比较，但保留元数据身份、父子教育、建筑赠款、出版角色各子链，不能仅同名错误绑定就统一。",
  "counterexamples": [
    "55和78可核心C但费用增加；257同错角色新1长查N、新3短接受W，成本方向不统一。",
    "228初次尝试部分候选可合理，只有持续任务前提/反馈不更新链有证据，不能提前称全部无用。"
  ],
  "unresolved": "一些新名字/错误角色源头未证，不脑补从哪个Doc误读来。",
  "deterministic_counts": {
    "observed_stage_count": 4,
    "different_questions": 4,
    "original_runs": 4,
    "observed_rollouts": 8,
    "not_observed_rollouts": 6,
    "uncertain_rollouts": 1,
    "excluded_rollouts": 1,
    "observed_local_chain_occurrences": 8,
    "not_observed_local_chain_occurrences": 6,
    "uncertain_local_chain_occurrences": 1,
    "excluded_local_chain_occurrences": 1,
    "total_distinct_rollouts_in_test": 16,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "228__rep1__S003__FIRST_SENTENCE",
      "257__rep1__S004__FIRST_SENTENCE",
      "55__rep2__S005__FIRST_SENTENCE",
      "78__rep1__S003__FIRST_SENTENCE"
    ],
    "question_ids": [
      "55",
      "78",
      "228",
      "257"
    ]
  }
}
```

```json
{
  "id": "ROOT003_T3",
  "description": "已采用核心主体的证据和待核事实状态不同，稳定答案可来自真实补证恢复，也可来自省掉辅助支持。",
  "links": [
    {
      "case_id": "69__rep1__S004__FIRST_SENTENCE",
      "local_id": "ADOPTED_PERSON_AND_OPEN_FACTS_RESTORE_SAME_QUERY_PRODUCT"
    },
    {
      "case_id": "87__rep1__S003__FIRST_SENTENCE",
      "local_id": "ALREADY_ADOPTED_SUBJECT_PRESERVED_WITHOUT_AUXILIARY_SUPPORT"
    }
  ],
  "relation": "是A内前态对照，不把两不同子机制合成统一成功标签。69对P1_K2恢复有支持；87为主体已采用后少支持的候选，不计严格全质量省。",
  "counterexamples": [
    "87另两支仍真实重建核验；69全部Prompt更多，没有全资源省。"
  ],
  "unresolved": "辅助条件的证据标准研究者需裁定，核心名称正确不能代替所有约束。",
  "deterministic_counts": {
    "observed_stage_count": 2,
    "different_questions": 2,
    "original_runs": 2,
    "observed_rollouts": 6,
    "not_observed_rollouts": 2,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 6,
    "not_observed_local_chain_occurrences": 2,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 8,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "69__rep1__S004__FIRST_SENTENCE",
      "87__rep1__S003__FIRST_SENTENCE"
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
  "id": "ROOT003_T4",
  "description": "全局不足或接受判断实际发生后，是否把缺口再次转成真实工具行动仍需单独观察；该判断存在不等停止开关。",
  "links": [
    {
      "case_id": "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "GAP_INTENTION_BECOMES_REAL_TOOL_ACTION_ONLY_IN_ONE"
    },
    {
      "case_id": "261__rep2__S004__FIRST_SENTENCE",
      "local_id": "NO_MATCH_JUDGMENT_DOES_NOT_IMPLY_SEARCH_STOP"
    }
  ],
  "relation": "83属于已有主体剩余关系P2_R3边界，261无论文对象不得硬套R3；上位共性仅判断到执行的分离。",
  "counterexamples": [
    "83另三支缺口同样写出但0Call；261新2输入one more G却0Call正式拒答。",
    "原261本身全局盘点后也再查一次，不能把U定义为立即停止。"
  ],
  "unresolved": "同缺口下为何某seed执行/停止仍未知，不用隐藏信心阈值补。",
  "deterministic_counts": {
    "observed_stage_count": 2,
    "different_questions": 2,
    "original_runs": 2,
    "observed_rollouts": 4,
    "not_observed_rollouts": 4,
    "uncertain_rollouts": 0,
    "excluded_rollouts": 0,
    "observed_local_chain_occurrences": 4,
    "not_observed_local_chain_occurrences": 4,
    "uncertain_local_chain_occurrences": 0,
    "excluded_local_chain_occurrences": 0,
    "total_distinct_rollouts_in_test": 8,
    "status_overlap_across_component_links": false,
    "counting_note": "Rollout counts deduplicate case_id and repeat; local-chain occurrences count each explicit component. Statuses across different components need not be exclusive.",
    "observed_cases": [
      "261__rep2__S004__FIRST_SENTENCE",
      "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR"
    ],
    "question_ids": [
      "83",
      "261"
    ]
  }
}
```

```json
{
  "id": "ROOT003_T5",
  "description": "教师提供决定性定位键时，候选发现被补偿，随后一真实Call可取回年龄并避开原错误长路线；这解释低成本改善却不证明原发现可省。",
  "links": [
    {
      "case_id": "270__rep4__S001__FIRST_SENTENCE",
      "local_id": "ORACLE_LOCATOR_REPLACES_INITIAL_DISCOVERY"
    }
  ],
  "relation": "与试点551等G给人物的限制同方向，本批仍只一题，不冻结新可省机制。",
  "counterexamples": [
    "同题原U已经返回正确菜，错误是在后续时间条件；删U并不是直接删错误排除Stage。",
    "新3不含菜名的Query仍用教师barbershop关系，不视作无提示自主发现。"
  ],
  "unresolved": "没有同P无G对照，不能宣称原U纯删除因果或严格可省。",
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
      "270__rep4__S001__FIRST_SENTENCE"
    ],
    "question_ids": [
      "270"
    ]
  }
}
```


## unresolved

```json
{
  "case_id": "55__rep2__S005__FIRST_SENTENCE",
  "issue": "错刊名短暂更正又退回；新2放宽首卷题意伴随省，不算全质量无损。"
}
```

```json
{
  "case_id": "69__rep1__S004__FIRST_SENTENCE",
  "issue": "四支全部恢复补证，无法由稳定C识别功能纯省；Prompt均升。"
}
```

```json
{
  "case_id": "78__rep1__S003__FIRST_SENTENCE",
  "issue": "新3正式Final前后自矛盾保留UNCERTAIN；新4多查确得1209不能算重复。"
}
```

```json
{
  "case_id": "83__rep1__S005__TERMINAL_DROP_NO_ANCHOR",
  "issue": "无G更短判断表达可能，但全恢复且共缺两条件；不能证明整个认知功能跳过。"
}
```

```json
{
  "case_id": "87__rep1__S003__FIRST_SENTENCE",
  "issue": "两支不核辅助条件仍C，原P只有断言不是独立分类/河名直接证据。"
}
```

```json
{
  "case_id": "226__rep3__S001__FIRST_SENTENCE",
  "issue": "根重启，旧U地址没有留P；晚多店采用不推多源必要规则。"
}
```

```json
{
  "case_id": "228__rep1__S003__FIRST_SENTENCE",
  "issue": "四N不同中介，原U只是Kwon学校条件；母校/受赠校及日期角色错配。"
}
```

```json
{
  "case_id": "257__rep1__S004__FIRST_SENTENCE",
  "issue": "三支恢复新书仍两失败，出版角色是后继环节；原U首Call仍旧对象。"
}
```

```json
{
  "case_id": "261__rep2__S004__FIRST_SENTENCE",
  "issue": "W/N全未成功，少生成一部分是没FormalFinal，不能全归U短盘点消失。"
}
```

```json
{
  "case_id": "270__rep4__S001__FIRST_SENTENCE",
  "issue": "强未来菜名/命名关系G，原始发现已经成功，四C不能算严格可省。"
}
```


## 限制
本批不同切点与前批有同题，不能把批内10题逐批相加为全局题数。每个候选显式列观察/未观察/不确定/排除四支，各统计解释必须保留机制出现方向、前态和条件，不能将对照计正支持。机械引用/成本PASS非研究级金标准。