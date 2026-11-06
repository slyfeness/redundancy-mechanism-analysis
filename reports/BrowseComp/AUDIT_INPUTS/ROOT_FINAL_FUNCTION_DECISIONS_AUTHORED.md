# ROOT400组与PEER功能定义的逐项对齐

仅复用已完成的原U语义材料，未按机制ID或关键词分组。8个中性功能定义直接引用PEER已写版本且原文件不改。每项判断的具体前态/工作/产物和边界见同名JSON的review_notes及entries。

## 覆盖与统计

```json
{
  "scope": 400,
  "selected_stage_cases": 400,
  "unselected_cases": [],
  "source_function_units": 163,
  "unused_source_function_units": [],
  "explicit_pilot_cases": [
    "1046__rep2__S003__FIRST_SENTENCE",
    "1239__rep1__S001__FIRST_SENTENCE",
    "191__rep1__S002__FIRST_SENTENCE",
    "257__rep1__S002__FIRST_SENTENCE",
    "270__rep4__S003__FIRST_SENTENCE",
    "291__rep3__S002__FIRST_SENTENCE",
    "78__rep2__S005__FIRST_SENTENCE",
    "92__rep1__S001__FIRST_SENTENCE"
  ],
  "explicit_pilot_count": 8,
  "groups": [
    {
      "family_id": "PF_ENTRY",
      "stage_cases": 131,
      "different_questions": 39,
      "original_runs": 90,
      "associated_rollouts": 524,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 54,
          "different_questions": 18,
          "original_runs": 44,
          "associated_rollouts": 216
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 75,
          "different_questions": 30,
          "original_runs": 48,
          "associated_rollouts": 300
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 2,
          "different_questions": 2,
          "original_runs": 2,
          "associated_rollouts": 8
        }
      ]
    },
    {
      "family_id": "PF_INTERPRET_ADOPT",
      "stage_cases": 78,
      "different_questions": 28,
      "original_runs": 55,
      "associated_rollouts": 312,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 49,
          "different_questions": 20,
          "original_runs": 37,
          "associated_rollouts": 196
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 7,
          "different_questions": 5,
          "original_runs": 7,
          "associated_rollouts": 28
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 22,
          "different_questions": 15,
          "original_runs": 17,
          "associated_rollouts": 88
        }
      ]
    },
    {
      "family_id": "PF_OPEN_RELATION_CHECK",
      "stage_cases": 174,
      "different_questions": 37,
      "original_runs": 82,
      "associated_rollouts": 696,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 95,
          "different_questions": 23,
          "original_runs": 50,
          "associated_rollouts": 380
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 67,
          "different_questions": 24,
          "original_runs": 35,
          "associated_rollouts": 268
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 11,
          "different_questions": 10,
          "original_runs": 11,
          "associated_rollouts": 44
        }
      ]
    },
    {
      "family_id": "PF_RECONFIRM_ADOPTED",
      "stage_cases": 13,
      "different_questions": 8,
      "original_runs": 12,
      "associated_rollouts": 52,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 10,
          "different_questions": 7,
          "original_runs": 9,
          "associated_rollouts": 40
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 3,
          "different_questions": 3,
          "original_runs": 3,
          "associated_rollouts": 12
        }
      ]
    },
    {
      "family_id": "PF_CANDIDATE_COMPARE",
      "stage_cases": 22,
      "different_questions": 17,
      "original_runs": 21,
      "associated_rollouts": 88,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 10,
          "different_questions": 7,
          "original_runs": 10,
          "associated_rollouts": 40
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 11,
          "different_questions": 10,
          "original_runs": 10,
          "associated_rollouts": 44
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        }
      ]
    },
    {
      "family_id": "PF_SUFFICIENCY_AND_REMAINING_WORK",
      "stage_cases": 101,
      "different_questions": 28,
      "original_runs": 61,
      "associated_rollouts": 404,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 40,
          "different_questions": 19,
          "original_runs": 30,
          "associated_rollouts": 160
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 50,
          "different_questions": 21,
          "original_runs": 50,
          "associated_rollouts": 200
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 7,
          "different_questions": 6,
          "original_runs": 7,
          "associated_rollouts": 28
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 4,
          "different_questions": 4,
          "original_runs": 4,
          "associated_rollouts": 16
        }
      ]
    },
    {
      "family_id": "PF_ANSWER_ORGANIZATION",
      "stage_cases": 54,
      "different_questions": 24,
      "original_runs": 54,
      "associated_rollouts": 216,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 50,
          "different_questions": 21,
          "original_runs": 50,
          "associated_rollouts": 200
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 4,
          "different_questions": 4,
          "original_runs": 4,
          "associated_rollouts": 16
        }
      ]
    },
    {
      "family_id": "PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE",
      "stage_cases": 6,
      "different_questions": 6,
      "original_runs": 6,
      "associated_rollouts": 24,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 5,
          "different_questions": 5,
          "original_runs": 5,
          "associated_rollouts": 20
        }
      ]
    }
  ],
  "all_scope_covered": true,
  "multi_memberships_are_not_independent_samples": true,
  "associated_rollouts_do_not_mean_function_restored": true
}
```

关联四条续跑不是四条功能重建。不同功能的成员可交叉，Stage、题目、原run、续跑均不得跨组相加。

## 关键混合边界

- ROOT_001/functions/0；92__rep3__S001__TERMINAL_DROP_NO_ANCHOR：ONLY_INTERNAL_HYPOTHESIS_WITHOUT_REAL_TOOL_EVIDENCE。同源其余初始Stage真取证，这例没有实际Call，不因工具样式文字或初始题型就归真实入口取证。
- ROOT_005/functions/0；673__rep1__S002__FIRST_SENTENCE：INTERPRET_AND_ADOPT_NOT_REAL_ENTRY_CALL。本U纯推理把P材料用于采用；其余同源包括真实取得材料的Stage，不把source function整组机械赋同一执行。
- ROOT_009/functions/1；980__rep1__S003__FIRST_SENTENCE：RETRIEVAL_NOT_COMPLETED_ADOPTION。Bobby关系虽然返回，原U未真正采用为下一对象；新路径的采用不能倒算原U功能。
- ROOT_017/functions/5；317__rep4__S001__TERMINAL_DROP_NO_ANCHOR：COMPOSITE_WHOLE_TRAJECTORY_FUNCTIONS。唯一U含13次真实取证、规则/候选比较及未识别赛事后猜20的接受组织。可多归原工作，但删除是根重启，不是成熟P下独立功能可省证明。
- ROOT_018/functions/2；191__rep3__S002__FIRST_SENTENCE, 228__rep1__S012__FIRST_SENTENCE：SPLIT_FIRST_SUPPORT_FROM_ALREADY_ADOPTED_RECONFIRMATION。前者首次取驾驶/训练直接支持；后者Stanford2019归属在P已接受，U两查仍同2019文且未补独立2023证据，同名确认不等相同前态。
- ROOT_024/functions/0；78__rep3__S004__FIRST_SENTENCE, 270__rep3__S003__FIRST_SENTENCE：FIRST_SCHOOL_DATE_VS_RECONFIRM_KNOWN_AGE。大学直接年表原P未有；菜肴人物47年龄关系已直接采用。G大部预填新学校支持另保风险，不能用结果四C把两次Call都称无增量。
- ROOT_027/functions/0；299__rep1__S004__TERMINAL_DROP_NO_ANCHOR：RECONFIRM_WITH_ADDITIONAL_RELIABILITY_AND_DAY_PRECISION。题面年窗和建筑身份已支持接受，U新添独立官方来源及精确29/30日；归再确认不等说没有新信息或可靠性价值，也不是首次补未知题面年窗。
- ROOT_028/functions/2；980__rep2__S002__FIRST_SENTENCE：UNRESOLVED_CANDIDATE_CHECK_AND_COMPARISON_NOT_ALREADY_DOCUMENTED_FACT_RECONFIRMATION。定向读prestate只见首轮演员兄弟杂文、R1熟悉候选年代警告，没有P直接生年证据和稳定合格主体。U真实查出生并作排除，不能仅因P警告相同而放入严格已获证且已采的外部再确认组。
- ROOT_033/functions/2；1046__rep2__S009__TERMINAL_DROP_NO_ANCHOR：ALLOW_NEW_STRUCTURE_SUPPORT_PLUS_OLD_COMPANY_CONFIRMATION。旧公司关系重取，同时U首次取上千公司/不透明相互结构直接文段并实际组织回答，三个工作分量保留，不全称重复。
- ROOT_034/functions/3；1046__rep3__S008__FIRST_SENTENCE：ALLOW_TWO_EVIDENCE_STATES_IN_ONE_JOINT_CHECK。P完整接受公司，但没有71883复杂持股网/53及数百关系直接说明。U旧公司再确认与第一次独立结构证明并存，旧卡把U细节放P已被当前记录纠正，不照搬旧卡。
- ROOT_036/functions/2；1096__rep2__S002__FIRST_SENTENCE：ACTUAL_ENTRY_CALL_RETURN_NOT_FUTURE_FRAMEWORK_EVALUATION。定向读真实function确认：换Aalborg入口、一次真实返回论文和会议，首次比较采用在下Stage。此U纳入口/具体关系取证，不把NEW的SFL门槛误归为原U已经实施。
- ROOT_037/functions/1；1096__rep2__S005__FIRST_SENTENCE：CLARIFY_INITIALLY_RECOGNIZED_RELATION_NOT_CERTAIN_MATURE_RECONFIRMATION。P已见节目单但初识别仍could，U真查同文引用开幕词后明确确认，归具体对应尚未确定的取证及采用，不归确定已证已采的再确认；机制N009是否成立仍按独立兼容复核，Function不替它裁定。
- ROOT_038/functions/0；1096__rep4__S003__FIRST_SENTENCE：MIXED_BATCH_NEW_RANK_FAILED_MEETING_OLD_KEYWORDS。一个真实联合批次同时核未知排名/会议和已见论文词序，新122在Z才采用；可多归未知关系核验与词序再确认，不把新采用回填到U，也不虚构批内逐次决策。
- ROOT_040/functions/0；1239__rep3__S004__TERMINAL_DROP_NO_ANCHOR：FIRST_USE_OF_VISIBLE_POPULATION_SUPPORT_AND_GLOBAL_ORGANIZATION。人口直接证据已刚返回但未被采用；U实际消费、对应全题并组织。不是材料可见等于早已完成认知。
- ROOT_PILOT/current_adjudication_function；78__rep2__S005__FIRST_SENTENCE：VERIFY_AND_ADOPT_CANDIDATE_NAME_NOT_FULL_PREADOPTION_ASSUMPTION。P有Ewuare资料和候选提取，但名字/家系仍待确认；U真核名并采用，按实际coronation Call而不是教育计划归具体核验+采用，不强按名字已见纳严格外部再确认。

## 显式成员选择

|功能族|批次|function序号（零基）|精确成员选择|
|---|---|---|---|
|PF_ENTRY|ROOT_001|0|78__rep1__S001,87__rep1__S001,226__rep1__S001,228__rep1__S001,257__rep1__S001,261__rep2__S001|
|PF_ENTRY|ROOT_001|1|69__rep1__S002|
|PF_ENTRY|ROOT_002|2|ALL|
|PF_ENTRY|ROOT_003|2|ALL|
|PF_ENTRY|ROOT_004|1|226__rep3__S002,257__rep4__S002|
|PF_ENTRY|ROOT_005|0|299__rep1__S001,377__rep1__S001,342__rep1__S001,392__rep4__S003|
|PF_ENTRY|ROOT_005|3|ALL|
|PF_ENTRY|ROOT_006|0|ALL|
|PF_ENTRY|ROOT_006|1|ALL|
|PF_ENTRY|ROOT_007|0|ALL|
|PF_ENTRY|ROOT_007|1|377__rep1__S002|
|PF_ENTRY|ROOT_007|3|689__rep3__S013|
|PF_ENTRY|ROOT_008|0|ALL|
|PF_ENTRY|ROOT_008|2|ALL|
|PF_ENTRY|ROOT_009|1|319__rep1__S002,688__rep1__S001,980__rep1__S003,873__rep2__S003|
|PF_ENTRY|ROOT_010|0|1023__rep3__S003,1138__rep1__S001|
|PF_ENTRY|ROOT_010|1|ALL|
|PF_ENTRY|ROOT_011|1|ALL|
|PF_ENTRY|ROOT_011|3|1023__rep2__S002|
|PF_ENTRY|ROOT_012|0|1023__rep2__S003|
|PF_ENTRY|ROOT_012|3|83__rep1__S001,1240__rep4__S001|
|PF_ENTRY|ROOT_013|1|ALL|
|PF_ENTRY|ROOT_014|0|83__rep2__S002,261__rep3__S002|
|PF_ENTRY|ROOT_014|1|ALL|
|PF_ENTRY|ROOT_015|3|ALL|
|PF_ENTRY|ROOT_016|3|ALL|
|PF_ENTRY|ROOT_017|2|ALL|
|PF_ENTRY|ROOT_017|4|ALL|
|PF_ENTRY|ROOT_017|5|ALL|
|PF_ENTRY|ROOT_018|0|ALL|
|PF_ENTRY|ROOT_019|5|ALL|
|PF_ENTRY|ROOT_020|2|191__rep4__S001|
|PF_ENTRY|ROOT_020|5|353__rep1__S007|
|PF_ENTRY|ROOT_020|6|ALL|
|PF_ENTRY|ROOT_021|1|ALL|
|PF_ENTRY|ROOT_021|4|ALL|
|PF_ENTRY|ROOT_023|1|ALL|
|PF_ENTRY|ROOT_024|3|ALL|
|PF_ENTRY|ROOT_025|2|291__rep2__S001,353__rep4__S002|
|PF_ENTRY|ROOT_026|2|ALL|
|PF_ENTRY|ROOT_027|2|ALL|
|PF_ENTRY|ROOT_027|3|980__rep1__S001|
|PF_ENTRY|ROOT_028|3|ALL|
|PF_ENTRY|ROOT_029|2|ALL|
|PF_ENTRY|ROOT_029|3|ALL|
|PF_ENTRY|ROOT_030|2|980__rep2__S007|
|PF_ENTRY|ROOT_031|2|ALL|
|PF_ENTRY|ROOT_032|0|ALL|
|PF_ENTRY|ROOT_033|3|ALL|
|PF_ENTRY|ROOT_034|1|ALL|
|PF_ENTRY|ROOT_035|0|ALL|
|PF_ENTRY|ROOT_036|2|ALL|
|PF_ENTRY|ROOT_037|3|ALL|
|PF_ENTRY|ROOT_038|2|1138__rep2__S001,1096__rep4__S001|
|PF_ENTRY|ROOT_039|2|1239__rep3__S001|
|PF_ENTRY|ROOT_040|1|ALL|
|PF_ENTRY|ROOT_PILOT|0|1046__rep2__S003,1239__rep1__S001,92__rep1__S001,270__rep4__S003|
|PF_INTERPRET_ADOPT|ROOT_002|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_004|0|270__rep4__S002|
|PF_INTERPRET_ADOPT|ROOT_004|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_005|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_007|1|688__rep2__S004|
|PF_INTERPRET_ADOPT|ROOT_007|2|784__rep4__S005|
|PF_INTERPRET_ADOPT|ROOT_008|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_008|2|377__rep3__S002,773__rep3__S001|
|PF_INTERPRET_ADOPT|ROOT_009|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_010|0|1138__rep1__S001|
|PF_INTERPRET_ADOPT|ROOT_011|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_012|0|319__rep1__S003|
|PF_INTERPRET_ADOPT|ROOT_012|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_012|4|ALL|
|PF_INTERPRET_ADOPT|ROOT_013|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_014|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_015|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_016|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_016|4|ALL|
|PF_INTERPRET_ADOPT|ROOT_017|3|ALL|
|PF_INTERPRET_ADOPT|ROOT_018|1|87__rep4__S002|
|PF_INTERPRET_ADOPT|ROOT_018|3|ALL|
|PF_INTERPRET_ADOPT|ROOT_019|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_020|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_020|3|ALL|
|PF_INTERPRET_ADOPT|ROOT_021|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_021|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_022|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_023|0|78__rep3__S003|
|PF_INTERPRET_ADOPT|ROOT_024|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_025|3|688__rep3__S002|
|PF_INTERPRET_ADOPT|ROOT_026|1|ALL|
|PF_INTERPRET_ADOPT|ROOT_027|1|78__rep4__S003|
|PF_INTERPRET_ADOPT|ROOT_029|0|261__rep4__S008,1023__rep3__S004|
|PF_INTERPRET_ADOPT|ROOT_029|1|1046__rep2__S002|
|PF_INTERPRET_ADOPT|ROOT_032|3|1046__rep1__S005,1046__rep2__S005|
|PF_INTERPRET_ADOPT|ROOT_033|1|299__rep4__S002|
|PF_INTERPRET_ADOPT|ROOT_034|2|ALL|
|PF_INTERPRET_ADOPT|ROOT_035|1|1095__rep2__S002~T,1095__rep3__S002~T,1095__rep4__S002,1239__rep1__S004~T|
|PF_INTERPRET_ADOPT|ROOT_037|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_037|1|1096__rep2__S005|
|PF_INTERPRET_ADOPT|ROOT_038|1|1096__rep4__S004|
|PF_INTERPRET_ADOPT|ROOT_038|2|1096__rep4__S002|
|PF_INTERPRET_ADOPT|ROOT_039|2|1239__rep3__S002|
|PF_INTERPRET_ADOPT|ROOT_040|0|ALL|
|PF_INTERPRET_ADOPT|ROOT_PILOT|0|257__rep1__S002,78__rep2__S005|
|PF_OPEN_RELATION_CHECK|ROOT_001|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_002|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_002|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_003|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_003|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_004|1|55__rep2__S006|
|PF_OPEN_RELATION_CHECK|ROOT_004|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_004|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_005|0|353__rep2__S002|
|PF_OPEN_RELATION_CHECK|ROOT_005|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_006|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_006|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_006|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_007|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_007|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_008|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_008|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_009|1|291__rep1__S002,319__rep1__S002,625__rep1__S004,980__rep1__S003,873__rep2__S003|
|PF_OPEN_RELATION_CHECK|ROOT_010|0|55__rep1__S002|
|PF_OPEN_RELATION_CHECK|ROOT_010|1|1046__rep1__S003,930__rep1__S005~T|
|PF_OPEN_RELATION_CHECK|ROOT_010|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_011|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_011|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_012|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_012|2|673__rep1__S006|
|PF_OPEN_RELATION_CHECK|ROOT_012|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_013|1|69__rep3__S002|
|PF_OPEN_RELATION_CHECK|ROOT_013|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_013|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_014|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_014|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_015|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_015|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_015|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_016|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_016|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_017|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_017|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_017|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_018|2|191__rep3__S002|
|PF_OPEN_RELATION_CHECK|ROOT_018|3|55__rep1__S004,282__rep4__S002|
|PF_OPEN_RELATION_CHECK|ROOT_019|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_019|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_019|5|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_020|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_020|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_020|5|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_021|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_021|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_021|5|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_021|6|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_022|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_022|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_022|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_023|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_024|0|78__rep3__S004|
|PF_OPEN_RELATION_CHECK|ROOT_024|1|261__rep4__S002,353__rep3__S004|
|PF_OPEN_RELATION_CHECK|ROOT_025|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_025|2|427__rep4__S004|
|PF_OPEN_RELATION_CHECK|ROOT_025|3|689__rep3__S014~T|
|PF_OPEN_RELATION_CHECK|ROOT_026|0|270__rep3__S005|
|PF_OPEN_RELATION_CHECK|ROOT_026|1|261__rep4__S005,291__rep2__S002|
|PF_OPEN_RELATION_CHECK|ROOT_027|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_028|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_028|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_029|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_030|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_030|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_030|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_030|4|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_031|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_032|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_032|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_033|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_033|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_034|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_034|3|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_035|2|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_036|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_036|1|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_036|2|1096__rep2__S002|
|PF_OPEN_RELATION_CHECK|ROOT_037|1|1096__rep2__S005,1096__rep2__S006,1096__rep3__S003|
|PF_OPEN_RELATION_CHECK|ROOT_038|0|1239__rep2__S003,1096__rep3__S006,1096__rep4__S003|
|PF_OPEN_RELATION_CHECK|ROOT_039|0|ALL|
|PF_OPEN_RELATION_CHECK|ROOT_PILOT|0|191__rep1__S002,257__rep1__S002,291__rep3__S002,78__rep2__S005|
|PF_RECONFIRM_ADOPTED|ROOT_002|1|83__rep1__S004|
|PF_RECONFIRM_ADOPTED|ROOT_018|2|228__rep1__S012|
|PF_RECONFIRM_ADOPTED|ROOT_019|1|ALL|
|PF_RECONFIRM_ADOPTED|ROOT_024|0|270__rep3__S003|
|PF_RECONFIRM_ADOPTED|ROOT_027|0|299__rep1__S004~T|
|PF_RECONFIRM_ADOPTED|ROOT_028|0|270__rep3__S007|
|PF_RECONFIRM_ADOPTED|ROOT_030|1|ALL|
|PF_RECONFIRM_ADOPTED|ROOT_033|2|1046__rep2__S009~T|
|PF_RECONFIRM_ADOPTED|ROOT_034|3|ALL|
|PF_RECONFIRM_ADOPTED|ROOT_036|3|1096__rep1__S009~T|
|PF_RECONFIRM_ADOPTED|ROOT_037|1|1096__rep2__S004|
|PF_RECONFIRM_ADOPTED|ROOT_038|0|1096__rep3__S004,1096__rep4__S003|
|PF_CANDIDATE_COMPARE|ROOT_002|0|ALL|
|PF_CANDIDATE_COMPARE|ROOT_004|0|270__rep4__S002|
|PF_CANDIDATE_COMPARE|ROOT_004|2|ALL|
|PF_CANDIDATE_COMPARE|ROOT_007|2|784__rep4__S005|
|PF_CANDIDATE_COMPARE|ROOT_008|2|773__rep3__S001|
|PF_CANDIDATE_COMPARE|ROOT_009|0|92__rep1__S002|
|PF_CANDIDATE_COMPARE|ROOT_012|1|ALL|
|PF_CANDIDATE_COMPARE|ROOT_012|4|ALL|
|PF_CANDIDATE_COMPARE|ROOT_014|2|ALL|
|PF_CANDIDATE_COMPARE|ROOT_015|1|ALL|
|PF_CANDIDATE_COMPARE|ROOT_016|4|ALL|
|PF_CANDIDATE_COMPARE|ROOT_017|5|ALL|
|PF_CANDIDATE_COMPARE|ROOT_018|3|342__rep1__S002|
|PF_CANDIDATE_COMPARE|ROOT_024|1|257__rep3__S003|
|PF_CANDIDATE_COMPARE|ROOT_025|3|688__rep3__S002|
|PF_CANDIDATE_COMPARE|ROOT_028|2|980__rep2__S002|
|PF_CANDIDATE_COMPARE|ROOT_029|1|1046__rep2__S002|
|PF_CANDIDATE_COMPARE|ROOT_038|2|1096__rep4__S002|
|PF_CANDIDATE_COMPARE|ROOT_PILOT|0|257__rep1__S002|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_001|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_003|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_004|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_004|3|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_007|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_008|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_009|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_011|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_012|2|1095__rep1__S004~T|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_013|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_015|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_016|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_016|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_017|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_017|5|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_018|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_019|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_019|3|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_020|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_021|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_022|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_022|3|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_023|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_024|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_025|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_026|0|257__rep3__S005~T|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_027|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_028|0|78__rep4__S004~T,291__rep2__S004~T|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_029|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_031|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_032|3|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_033|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_033|2|1046__rep2__S009~T|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_034|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_035|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_036|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_036|3|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_037|0|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_037|2|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_038|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_039|1|ALL|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_039|2|1239__rep3__S002|
|PF_SUFFICIENCY_AND_REMAINING_WORK|ROOT_040|0|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_003|1|83__rep1__S005~T|
|PF_ANSWER_ORGANIZATION|ROOT_004|0|69__rep1__S005~T,78__rep1__S004~T,83__rep2__S010~T,87__rep1__S004~T|
|PF_ANSWER_ORGANIZATION|ROOT_004|3|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_009|0|191__rep1__S003~T|
|PF_ANSWER_ORGANIZATION|ROOT_012|2|1095__rep1__S004~T|
|PF_ANSWER_ORGANIZATION|ROOT_013|0|92__rep1__S006~T|
|PF_ANSWER_ORGANIZATION|ROOT_016|0|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_017|0|69__rep3__S006~T|
|PF_ANSWER_ORGANIZATION|ROOT_017|5|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_019|3|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_020|1|78__rep2__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_021|0|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_022|1|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_023|0|191__rep4__S004~T,261__rep3__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_024|2|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_025|0|78__rep3__S005~T|
|PF_ANSWER_ORGANIZATION|ROOT_026|0|257__rep3__S005~T|
|PF_ANSWER_ORGANIZATION|ROOT_027|0|299__rep1__S004~T|
|PF_ANSWER_ORGANIZATION|ROOT_028|0|78__rep4__S004~T,291__rep2__S004~T|
|PF_ANSWER_ORGANIZATION|ROOT_029|0|270__rep3__S008~T|
|PF_ANSWER_ORGANIZATION|ROOT_031|0|261__rep4__S010~T,291__rep3__S004~T,299__rep3__S004~T,353__rep2__S005~T,1023__rep3__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_032|3|353__rep3__S005~T,1046__rep1__S007~T|
|PF_ANSWER_ORGANIZATION|ROOT_033|1|673__rep1__S007~T|
|PF_ANSWER_ORGANIZATION|ROOT_033|2|1046__rep2__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_035|1|1095__rep2__S002~T,1095__rep3__S002~T,1239__rep1__S004~T,1046__rep3__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_036|3|1095__rep4__S004~T,1096__rep1__S009~T|
|PF_ANSWER_ORGANIZATION|ROOT_037|2|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_038|1|1096__rep3__S007~T|
|PF_ANSWER_ORGANIZATION|ROOT_039|1|ALL|
|PF_ANSWER_ORGANIZATION|ROOT_040|0|ALL|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_001|0|92__rep3__S001~T|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_005|1|ALL|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_009|2|ALL|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_012|3|87__rep3__S001~T|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_020|4|ALL|
|PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE|ROOT_027|3|1023__rep1__S001~T|

## 综合成员表

FINAL_FUNCTION_EXPLICIT_COMBINED_MEMBERS.json为显式并集，包含不变PEER成员、这次ROOT成员和724r4S009一项明确次功能；两项PEER未归仍保留。旧PEER JSON/MD/CSV和原统计快照均不改。

## 限制

- These are original-U function families, not NEW mechanism findings or restoration labels.
- Within-family stage-specific P, operation, product and source distinction remain visible; no claim that all retrieval has equal information value.
- Multiple function memberships overlap; Stage, question, original run and four associated rollout counts are deduplicated separately and cannot be summed across families.
- Associated rollouts do not mean four functions were reconstructed, four mechanism occurrences, or four causal tests without G.
- ROOT can accept/refine these explicit groupings during final review; they are not researcher gold or an automatic merge by equal names.
