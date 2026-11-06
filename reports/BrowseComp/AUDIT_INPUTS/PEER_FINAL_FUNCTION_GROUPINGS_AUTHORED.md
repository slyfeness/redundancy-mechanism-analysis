# PEER已审504组的共性功能归纳建议

本文件以原U实际工作为依据，和新路径机制、功能是否重建、是否省耗分别记录。没有按机制ID倒推Function。Codex建议不等研究者金标准，也不与ROOT同名功能自动合并。

## 范围与计数

```json
{
  "scope": 504,
  "selected_stages": 502,
  "unselected_cases": [
    "319__rep3__S006__FIRST_SENTENCE",
    "377__rep4__S005__FIRST_SENTENCE"
  ],
  "source_function_units": 196,
  "unused_source_function_units": [],
  "duplicate_selectors": [],
  "groups": [
    {
      "family_id": "PF_ENTRY",
      "stage_cases": 127,
      "different_questions": 32,
      "original_runs": 75,
      "associated_rollouts": 508,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 54,
          "different_questions": 18,
          "original_runs": 40,
          "associated_rollouts": 216
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 71,
          "different_questions": 20,
          "original_runs": 35,
          "associated_rollouts": 284
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
      "stage_cases": 91,
      "different_questions": 29,
      "original_runs": 56,
      "associated_rollouts": 364,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 69,
          "different_questions": 19,
          "original_runs": 45,
          "associated_rollouts": 276
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
          "stage_cases": 20,
          "different_questions": 16,
          "original_runs": 16,
          "associated_rollouts": 80
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
      "family_id": "PF_OPEN_RELATION_CHECK",
      "stage_cases": 268,
      "different_questions": 36,
      "original_runs": 91,
      "associated_rollouts": 1072,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 171,
          "different_questions": 21,
          "original_runs": 57,
          "associated_rollouts": 684
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 2,
          "different_questions": 2,
          "original_runs": 2,
          "associated_rollouts": 8
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 86,
          "different_questions": 20,
          "original_runs": 35,
          "associated_rollouts": 344
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 8,
          "different_questions": 8,
          "original_runs": 8,
          "associated_rollouts": 32
        },
        {
          "group": "OUTSIDE_CURRENT_AB",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        }
      ]
    },
    {
      "family_id": "PF_RECONFIRM_ADOPTED",
      "stage_cases": 23,
      "different_questions": 11,
      "original_runs": 19,
      "associated_rollouts": 92,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 20,
          "different_questions": 8,
          "original_runs": 16,
          "associated_rollouts": 80
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 2,
          "different_questions": 2,
          "original_runs": 2,
          "associated_rollouts": 8
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        }
      ]
    },
    {
      "family_id": "PF_CANDIDATE_COMPARE",
      "stage_cases": 47,
      "different_questions": 24,
      "original_runs": 33,
      "associated_rollouts": 188,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 21,
          "different_questions": 9,
          "original_runs": 16,
          "associated_rollouts": 84
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
          "stage_cases": 24,
          "different_questions": 17,
          "original_runs": 18,
          "associated_rollouts": 96
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
      "stage_cases": 103,
      "different_questions": 28,
      "original_runs": 67,
      "associated_rollouts": 412,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 40,
          "different_questions": 16,
          "original_runs": 29,
          "associated_rollouts": 160
        },
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 57,
          "different_questions": 23,
          "original_runs": 57,
          "associated_rollouts": 228
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 3,
          "different_questions": 3,
          "original_runs": 3,
          "associated_rollouts": 12
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 3,
          "different_questions": 3,
          "original_runs": 3,
          "associated_rollouts": 12
        }
      ]
    },
    {
      "family_id": "PF_ANSWER_ORGANIZATION",
      "stage_cases": 62,
      "different_questions": 26,
      "original_runs": 62,
      "associated_rollouts": 248,
      "by_group_condition": [
        {
          "group": "A",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 58,
          "different_questions": 23,
          "original_runs": 58,
          "associated_rollouts": 232
        },
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 1,
          "different_questions": 1,
          "original_runs": 1,
          "associated_rollouts": 4
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 3,
          "different_questions": 3,
          "original_runs": 3,
          "associated_rollouts": 12
        }
      ]
    },
    {
      "family_id": "PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE",
      "stage_cases": 11,
      "different_questions": 5,
      "original_runs": 6,
      "associated_rollouts": 44,
      "by_group_condition": [
        {
          "group": "B",
          "condition": "FIRST_SENTENCE",
          "stage_cases": 6,
          "different_questions": 3,
          "original_runs": 3,
          "associated_rollouts": 24
        },
        {
          "group": "B",
          "condition": "TERMINAL_DROP_NO_ANCHOR",
          "stage_cases": 5,
          "different_questions": 4,
          "original_runs": 5,
          "associated_rollouts": 20
        }
      ]
    }
  ],
  "all_scope_cases_are_grouped_or_explicitly_unclassified": true,
  "original_new_function_separate": true,
  "classification_not_inferred_by_program": true,
  "counts_not_additive_across_families": true,
  "rollout_interpretation": "Four existing comparison trajectories are associated with each original Stage. These are NOT four confirmed restorations or four observed mechanism occurrences."
}
```

同一冻结Stage可以含多个实际功能，因此不同组的Stage、题目及续跑数不能相加。associated_rollouts是对应四条对照路径数量，不是四条均恢复功能。原四态和费用另见原case。

## 共性功能与边界

### PF_ENTRY：在目标身份尚未确立时选择证据入口并尝试取得可比较对象

没有已确定目标身份，或者当前只有局部匹配、未稳假设，需要寻找能连接题目条件的对象。允许已有多个名字或曾经失败，不等空白P。

从题目或失败反馈选择具体检索入口，真实尝试取得候选、关系线索或供下一步比较的材料。

可能首次返回目标人物，也可能只有弱对象、部分线索或未找到的反馈；必须保留原记录各自的实际结果。

不将返回姓名自动说成已采用；也不把原后继才采用/查询的人提前算给U。已有主体的纯属性补证不因仍在搜索而自动属于本组。

空P初始取证、已有失败后的替代入口、弱候选引导的身份探索分层保留；三者不是同一种信息状态。

既不等冗余，也不等首次取得正确答案；错误入口仍可能碰到真材料，G也可能提前提供原U身份。

显式成员来源：

- PEER_001 /functions/0：ALL
- PEER_002 /functions/0：18__rep1__S001,68__rep1__S001,202__rep1__S001,266__rep2__S001
- PEER_003 /functions/2：ALL
- PEER_004 /functions/3：ALL
- PEER_005 /functions/0：ALL
- PEER_005 /functions/2：724__rep2__S001
- PEER_006 /functions/1：ALL
- PEER_006 /functions/2：ALL
- PEER_006 /functions/3：ALL
- PEER_007 /functions/3：724__rep2__S002
- PEER_008 /functions/2：ALL
- PEER_009 /functions/2：ALL
- PEER_009 /functions/3：ALL
- PEER_010 /functions/2：724__rep2__S003
- PEER_011 /functions/1：ALL
- PEER_012 /functions/1：637__rep4__S001
- PEER_013 /functions/2：ALL
- PEER_013 /functions/3：ALL
- PEER_014 /functions/0：ALL
- PEER_014 /functions/2：ALL
- PEER_015 /functions/1：ALL
- PEER_016 /functions/2：ALL
- PEER_017 /functions/3：ALL
- PEER_018 /functions/2：ALL
- PEER_019 /functions/2：ALL
- PEER_020 /functions/1：ALL
- PEER_020 /functions/3：ALL
- PEER_021 /functions/1：853__rep2__S003,20__rep1__S004
- PEER_021 /functions/3：ALL
- PEER_022 /functions/2：ALL
- PEER_023 /functions/2：266__rep4__S002,724__rep2__S012
- PEER_023 /functions/3：20__rep3__S001
- PEER_024 /functions/0：ALL
- PEER_024 /functions/4：ALL
- PEER_025 /functions/3：ALL
- PEER_025 /functions/4：ALL
- PEER_026 /functions/4：ALL
- PEER_027 /functions/2：506__rep3__S001
- PEER_027 /functions/3：20__rep4__S003
- PEER_028 /functions/0：1135__rep4__S001,205__rep2__S001
- PEER_029 /functions/3：ALL
- PEER_030 /functions/0：ALL
- PEER_033 /functions/2：ALL
- PEER_034 /functions/1：ALL
- PEER_035 /functions/0：ALL
- PEER_036 /functions/2：ALL
- PEER_038 /functions/3：ALL
- PEER_040 /functions/0：ALL
- PEER_047 /functions/1：ALL
- PEER_048 /functions/1：ALL
- PEER_049 /functions/0：377__rep2__S006
- PEER_050 /functions/0：ALL
- PILOT /functions/0：1032__rep1__S011,170__rep1__S001,551__rep4__S001,853__rep1__S002

### PF_INTERPRET_ADOPT：将已有或新返材料对应到具体角色、关系或候选，并使判断可用于下一动作

材料或关系假说已经可见，但具体题目对应、采用或下一核验对象尚未完成；也可能需纠正早先对应。

解释谁与谁的关系、哪个年代属于哪个事件、材料支持哪个条件，明确采用、修正或建立具体行动对象。

形成可观察的条件判断或对象选择。是否真的进入下一Call从后继另验，不能由本组名预设成功。

简单返回事实、名字出现不自动纳入；解释可能正确、错误或有证据不足，功能存在不代表事实已经证实。纯推理也可实际完成这种更新。

首次采用已有可见材料、首次采用新返证据、重新解释或纠错分别留在源function/prestate；不把它们合成同样价值。

这是实际工作环节，不是R1、K1或M1的直接标签；可有正确关系转化，也可有无支持假说成为工作前提。

显式成员来源：

- PEER_001 /functions/1：ALL
- PEER_002 /functions/1：ALL
- PEER_003 /functions/0：ALL
- PEER_004 /functions/0：ALL
- PEER_004 /functions/3：ALL
- PEER_005 /functions/0：ALL
- PEER_006 /functions/1：1135__rep1__S001
- PEER_008 /functions/0：ALL
- PEER_008 /functions/1：970__rep1__S003
- PEER_008 /functions/3：ALL
- PEER_009 /functions/1：ALL
- PEER_010 /functions/1：618__rep1__S005
- PEER_011 /functions/1：ALL
- PEER_012 /functions/1：637__rep4__S001
- PEER_013 /functions/2：231__rep3__S001
- PEER_013 /functions/4：ALL
- PEER_014 /functions/1：289__rep2__S002
- PEER_015 /functions/1：1135__rep3__S002
- PEER_015 /functions/3：495__rep3__S007~T
- PEER_016 /functions/1：ALL
- PEER_016 /functions/3：ALL
- PEER_017 /functions/1：506__rep2__S002
- PEER_018 /functions/0：231__rep3__S005
- PEER_018 /functions/1：ALL
- PEER_020 /functions/0：1135__rep3__S005
- PEER_020 /functions/1：20__rep2__S002
- PEER_020 /functions/3：ALL
- PEER_021 /functions/1：ALL
- PEER_021 /functions/3：ALL
- PEER_023 /functions/0：ALL
- PEER_025 /functions/0：408__rep4__S002
- PEER_027 /functions/2：ALL
- PEER_028 /functions/0：170__rep4__S002
- PEER_029 /functions/0：1135__rep4__S002,170__rep4__S003
- PEER_029 /functions/2：ALL
- PEER_030 /functions/0：289__rep4__S001,528__rep2__S001
- PEER_030 /functions/1：ALL
- PEER_031 /functions/0：ALL
- PEER_031 /functions/2：202__rep3__S002
- PEER_032 /functions/0：ALL
- PEER_034 /functions/2：68__rep4__S003
- PEER_037 /functions/1：18__rep4__S004
- PEER_038 /functions/1：ALL
- PEER_038 /functions/3：528__rep3__S001
- PEER_039 /functions/2：ALL
- PEER_039 /functions/3：ALL
- PEER_040 /functions/1：ALL
- PEER_040 /functions/3：970__rep3__S010
- PEER_041 /functions/0：202__rep4__S004
- PEER_042 /functions/0：202__rep4__S006
- PEER_046 /functions/1：ALL
- PEER_047 /functions/1：319__rep3__S002
- PEER_047 /functions/2：ALL
- PEER_048 /functions/2：688__rep3__S004
- PEER_049 /functions/0：377__rep2__S006
- PEER_050 /functions/0：377__rep4__S002,980__rep3__S002
- PEER_050 /functions/2：ALL
- PEER_051 /functions/1：ALL
- PILOT /functions/0：551__rep4__S001,68__rep4__S002,408__rep1__S002

### PF_OPEN_RELATION_CHECK：针对一个具体尚未闭合的条件取得证据并处理本次结果

当前有可查询对象或关系端点，但这项具体条件尚无直接支持，或其对应仍未确定。主体可能稳定，也可能只是待核候选，必须保留该差别。

实际查询具体事实、条件或关系，读取完整返回，提取新增支持、局部不符、相关但不充分材料，或记录本次仍未得到。

可能首次新增事实、局部排除或仅有不足反馈；不是一个统一的成功产品。冻结长U可先补一个事实后继续核另一缺口，多功能保留。

与已直接支持且实际采用之后的外部再确认分开；不能把失败视作没有思考产物，也不能把未知年份和已知头衔当同一事实。

已采用主体下的真缺口、未稳候选的属性测试、首次成功局部补证、失败或部分支持后的下一尝试分别保留。各个实例仍按原Stage，不重新切分。

不把所有本组成员解释成R3、低增量搜索或循环；有真实新证据、有合理首次验证，也有持续未闭的后段。

显式成员来源：

- PEER_001 /functions/0：429__rep1__S004,18__rep1__S003
- PEER_002 /functions/2：ALL
- PEER_002 /functions/3：ALL
- PEER_003 /functions/1：ALL
- PEER_003 /functions/3：ALL
- PEER_004 /functions/0：ALL
- PEER_004 /functions/2：ALL
- PEER_005 /functions/1：637__rep1__S002
- PEER_005 /functions/2：599__rep3__S003~T,618__rep1__S003
- PEER_006 /functions/2：ALL
- PEER_006 /functions/3：ALL
- PEER_007 /functions/0：ALL
- PEER_007 /functions/1：ALL
- PEER_007 /functions/2：ALL
- PEER_007 /functions/3：724__rep2__S002
- PEER_008 /functions/1：ALL
- PEER_008 /functions/2：20__rep1__S003
- PEER_009 /functions/0：ALL
- PEER_009 /functions/1：528__rep1__S003,1218__rep2__S009
- PEER_009 /functions/2：1188__rep2__S003
- PEER_009 /functions/3：ALL
- PEER_010 /functions/1：301__rep4__S005,618__rep1__S005
- PEER_011 /functions/0：231__rep2__S005,408__rep2__S002
- PEER_011 /functions/2：ALL
- PEER_012 /functions/0：528__rep1__S004,853__rep2__S005,970__rep1__S006
- PEER_012 /functions/2：ALL
- PEER_013 /functions/1：ALL
- PEER_013 /functions/3：266__rep2__S007
- PEER_014 /functions/1：ALL
- PEER_014 /functions/2：1122__rep1__S003,724__rep2__S005
- PEER_015 /functions/0：637__rep4__S002,853__rep2__S006
- PEER_015 /functions/2：ALL
- PEER_015 /functions/3：1188__rep3__S002~T,266__rep2__S009~T
- PEER_016 /functions/0：20__rep1__S012,68__rep1__S006
- PEER_016 /functions/3：ALL
- PEER_017 /functions/1：ALL
- PEER_017 /functions/2：ALL
- PEER_018 /functions/0：970__rep1__S008,231__rep3__S005
- PEER_018 /functions/2：ALL
- PEER_019 /functions/0：205__rep1__S006,408__rep3__S004,506__rep2__S003,551__rep1__S016~T
- PEER_019 /functions/2：ALL
- PEER_020 /functions/0：ALL
- PEER_020 /functions/1：ALL
- PEER_020 /functions/2：ALL
- PEER_021 /functions/0：ALL
- PEER_021 /functions/1：ALL
- PEER_021 /functions/5：ALL
- PEER_022 /functions/0：ALL
- PEER_022 /functions/2：ALL
- PEER_023 /functions/0：ALL
- PEER_023 /functions/2：ALL
- PEER_024 /functions/1：506__rep2__S005
- PEER_024 /functions/3：ALL
- PEER_024 /functions/4：ALL
- PEER_025 /functions/0：ALL
- PEER_025 /functions/3：ALL
- PEER_025 /functions/4：ALL
- PEER_026 /functions/3：ALL
- PEER_026 /functions/4：ALL
- PEER_027 /functions/1：ALL
- PEER_027 /functions/2：724__rep4__S002
- PEER_027 /functions/3：20__rep4__S003
- PEER_028 /functions/0：170__rep4__S002
- PEER_028 /functions/1：ALL
- PEER_028 /functions/3：ALL
- PEER_029 /functions/0：ALL
- PEER_029 /functions/3：ALL
- PEER_030 /functions/1：ALL
- PEER_030 /functions/3：ALL
- PEER_030 /functions/4：ALL
- PEER_031 /functions/0：ALL
- PEER_031 /functions/1：ALL
- PEER_031 /functions/3：ALL
- PEER_032 /functions/0：18__rep3__S004
- PEER_032 /functions/1：853__rep4__S003,970__rep2__S008,202__rep3__S003
- PEER_033 /functions/0：ALL
- PEER_033 /functions/1：ALL
- PEER_033 /functions/2：853__rep4__S005,205__rep2__S004
- PEER_034 /functions/0：ALL
- PEER_034 /functions/1：ALL
- PEER_035 /functions/1：ALL
- PEER_036 /functions/0：ALL
- PEER_036 /functions/2：ALL
- PEER_037 /functions/0：ALL
- PEER_037 /functions/1：ALL
- PEER_038 /functions/2：ALL
- PEER_039 /functions/0：ALL
- PEER_039 /functions/3：ALL
- PEER_040 /functions/1：20__rep3__S004
- PEER_040 /functions/3：ALL
- PEER_040 /functions/4：ALL
- PEER_041 /functions/0：202__rep4__S003,205__rep4__S005,20__rep3__S005,970__rep4__S003
- PEER_041 /functions/1：ALL
- PEER_042 /functions/0：ALL
- PEER_042 /functions/2：205__rep4__S006
- PEER_043 /functions/1：ALL
- PEER_044 /functions/1：ALL
- PEER_046 /functions/2：ALL
- PEER_046 /functions/4：ALL
- PEER_047 /functions/0：ALL
- PEER_048 /functions/1：ALL
- PEER_048 /functions/2：980__rep2__S009
- PEER_049 /functions/0：688__rep3__S005,377__rep2__S008,377__rep3__S006
- PEER_050 /functions/1：ALL
- PEER_051 /functions/0：ALL
- PILOT /functions/0：1122__rep3__S006,1135__rep3__S003,205__rep4__S003,231__rep2__S002,408__rep1__S002,528__rep3__S003

### PF_RECONFIRM_ADOPTED：对已经获得且已用于判断的具体关系再次外部确认

相关具体事实在P或该复合U较早部分已有直接支持并实际采用。其他题目条件可以仍未闭，不能因此将已知事实也说成未知。

实际再次获取或佐证同一关系，可能换来源、补精度、提高可靠性，也可能只再次得到旧支持。

再次确认该事实，是否新增独立来源、精确日期、判断或身份改变必须另记。

不以同名字或同Query认定前态已完成；法律first/middle/登记形式仍未知的案例不可用普通姓名已知自动覆盖，另留混合或待定。

原P已采用、复合U先取得后又确认、同关系增加来源或精度分别标记；源中仅有可能的确认不自动扩大为已证精确关系。

并非全部没有价值。删除后可重做、可沿用P、可另取支持；成本与质量仍需四条真实续跑分别判断。

显式成员来源：

- PEER_004 /functions/1：ALL
- PEER_011 /functions/0：205__rep1__S003
- PEER_013 /functions/0：ALL
- PEER_016 /functions/0：205__rep1__S005
- PEER_017 /functions/0：289__rep2__S003
- PEER_018 /functions/0：20__rep1__S013
- PEER_021 /functions/2：ALL
- PEER_024 /functions/1：68__rep3__S002
- PEER_025 /functions/1：ALL
- PEER_026 /functions/1：ALL
- PEER_032 /functions/1：289__rep4__S003
- PEER_035 /functions/2：ALL
- PEER_038 /functions/0：ALL
- PEER_042 /functions/2：205__rep4__S007
- PEER_044 /functions/2：ALL
- PEER_046 /functions/3：ALL
- PEER_048 /functions/0：319__rep3__S007
- PEER_049 /functions/0：377__rep3__S006
- PEER_050 /functions/3：688__rep3__S006
- PILOT /functions/0：205__rep4__S003

### PF_CANDIDATE_COMPARE：对具体候选进行条件比较、排除、保留或核验优先级选择

有一个或多个实际待评候选，某些条件已返或被假设，但还需决定该对象符合什么、是否排除、接下来先查谁。

实质比较具体候选与条件，处理局部冲突或候选排序；可以纯推理，也可以与本次真实核验共同构成局部评价。

候选被排除、保留为可能、提升优先级或转向另一对象；证据充分与错误比较分别保留。

不因出现名字就纳入；仅仅列未来可能搜索不等已完成候选评估。对全题整体证据是否足够回答的判断另组，可在复合U中重叠。

局部事实否定单个条件与排除整个主体不是一回事；出生窗不符某合作者，不能写成否定歌手。

排除可正确或误判，候选恢复也不保证Final；不根据原C/W/N反推比较有无价值。

显式成员来源：

- PEER_001 /functions/1：ALL
- PEER_003 /functions/0：ALL
- PEER_003 /functions/3：ALL
- PEER_005 /functions/2：618__rep1__S003
- PEER_007 /functions/2：1218__rep2__S008
- PEER_007 /functions/3：495__rep3__S001
- PEER_008 /functions/0：ALL
- PEER_008 /functions/3：ALL
- PEER_009 /functions/1：ALL
- PEER_010 /functions/1：ALL
- PEER_011 /functions/1：1188__rep2__S004
- PEER_012 /functions/1：495__rep3__S005
- PEER_013 /functions/4：ALL
- PEER_014 /functions/2：1190__rep2__S002
- PEER_015 /functions/3：495__rep3__S007~T
- PEER_019 /functions/1：1078__rep2__S011,637__rep2__S001
- PEER_023 /functions/1：18__rep3__S002
- PEER_025 /functions/2：ALL
- PEER_026 /functions/2：ALL
- PEER_027 /functions/2：724__rep4__S002
- PEER_027 /functions/3：853__rep3__S006
- PEER_029 /functions/2：ALL
- PEER_031 /functions/0：205__rep2__S003,528__rep2__S002
- PEER_031 /functions/2：202__rep3__S002
- PEER_033 /functions/0：528__rep2__S003
- PEER_033 /functions/2：205__rep2__S004
- PEER_036 /functions/1：205__rep2__S007
- PEER_037 /functions/1：970__rep3__S005
- PEER_038 /functions/1：ALL
- PEER_039 /functions/2：ALL
- PEER_040 /functions/1：ALL
- PEER_045 /functions/0：ALL
- PILOT /functions/0：970__rep3__S002,68__rep4__S002,528__rep3__S003

### PF_SUFFICIENCY_AND_REMAINING_WORK：整合多项已知与缺口，判断是否接受答案及还需完成什么工作

有较集中候选或一组可比较材料，多条件支持程度不齐，需形成当前全题判断或剩余工作安排。

把已有证据、条件冲突与未证关系放在一起比较，决定接受、暂留、拒绝确认、继续哪项核验或准备作答。

形成完整或阶段性接受、明确的缺口安排或拒答决定。以后继续Search不取消这次已经发生的认知工作。

普通背景复述不自动算独立充分性判断；已有事实再次重申与完整比较需区分。也不能将后继才发生的接受提前算到U。

首次完整评估、已有接受后的再评估、带真缺口的有限接受、以无源断言填满条件、拒绝确认分别保留，不能都称证据充分。

本组不意味着所有题目条件已证，也不意味着已提交Formal或没有后续真实核验。

显式成员来源：

- PEER_001 /functions/2：ALL
- PEER_003 /functions/0：170__rep1__S003
- PEER_005 /functions/1：551__rep4__S005
- PEER_006 /functions/0：ALL
- PEER_007 /functions/4：ALL
- PEER_008 /functions/4：ALL
- PEER_009 /functions/4：ALL
- PEER_010 /functions/0：ALL
- PEER_011 /functions/3：ALL
- PEER_012 /functions/0：551__rep4__S007~T
- PEER_015 /functions/0：970__rep1__S007
- PEER_015 /functions/3：266__rep2__S009~T,495__rep3__S007~T
- PEER_017 /functions/0：408__rep2__S004~T,637__rep4__S003
- PEER_018 /functions/0：68__rep1__S007~T
- PEER_019 /functions/1：289__rep2__S004~T,528__rep1__S006,1078__rep2__S011
- PEER_020 /functions/0：970__rep1__S009
- PEER_021 /functions/4：ALL
- PEER_022 /functions/1：ALL
- PEER_023 /functions/1：202__rep2__S004,231__rep2__S006~T
- PEER_024 /functions/2：ALL
- PEER_025 /functions/2：ALL
- PEER_026 /functions/0：ALL
- PEER_027 /functions/0：ALL
- PEER_028 /functions/1：408__rep4__S005~T
- PEER_028 /functions/2：ALL
- PEER_029 /functions/1：ALL
- PEER_030 /functions/2：ALL
- PEER_031 /functions/2：170__rep4__S004~T
- PEER_032 /functions/2：ALL
- PEER_033 /functions/3：ALL
- PEER_034 /functions/2：205__rep2__S005
- PEER_034 /functions/3：ALL
- PEER_035 /functions/3：ALL
- PEER_036 /functions/1：ALL
- PEER_037 /functions/2：ALL
- PEER_038 /functions/4：ALL
- PEER_039 /functions/1：ALL
- PEER_040 /functions/2：ALL
- PEER_041 /functions/2：ALL
- PEER_042 /functions/1：ALL
- PEER_043 /functions/0：ALL
- PEER_044 /functions/0：ALL
- PEER_045 /functions/0：ALL
- PEER_046 /functions/0：ALL
- PEER_046 /functions/1：ALL
- PEER_047 /functions/2：319__rep3__S004
- PEER_047 /functions/3：ALL
- PEER_048 /functions/0：319__rep3__S008~T
- PEER_049 /functions/1：ALL
- PEER_049 /functions/2：ALL
- PEER_050 /functions/2：377__rep4__S004
- PEER_050 /functions/4：ALL
- PEER_051 /functions/1：ALL

### PF_ANSWER_ORGANIZATION：将已形成的候选或接受判断整理为可输出的具体答案

已有候选、答案字段或当前接受判断，下一工作是组织具体答复，而不只是寻找新证据。

实际组织姓名、字段、条件说明、草稿或最终答复表达；可与完整比较相邻或同在复合U。

形成具体待输出内容或答案组织。真实Formal是否存在、内容和终态依原轨迹单独记录，不由这个Function推定。

一句准备回答或未来拟答计划不自动算实际组织；也不把Final单独字段复制进U来凑功能。这里只纳批次原记录已明确实际组织的成员。

已接受后的表达、刚处理新返信息后才组织、带缺口或错误附述的组织分别保留；语言篇幅不是功能是否恢复的唯一依据。

组织再次发生可更短或更长；零Call不等认知工作省略，答案相同也不等证据质量完全保持。

显式成员来源：

- PEER_007 /functions/4：ALL
- PEER_008 /functions/4：ALL
- PEER_009 /functions/4：ALL
- PEER_010 /functions/0：1135__rep1__S003~T,170__rep1__S005~T,202__rep1__S006~T
- PEER_011 /functions/3：ALL
- PEER_012 /functions/0：551__rep4__S007~T
- PEER_013 /functions/0：ALL
- PEER_015 /functions/3：266__rep2__S009~T,495__rep3__S007~T
- PEER_017 /functions/0：408__rep2__S004~T
- PEER_018 /functions/0：68__rep1__S007~T
- PEER_019 /functions/1：289__rep2__S004~T
- PEER_021 /functions/4：ALL
- PEER_022 /functions/1：637__rep4__S005~T
- PEER_023 /functions/1：231__rep2__S006~T
- PEER_024 /functions/2：170__rep3__S005~T
- PEER_026 /functions/0：ALL
- PEER_027 /functions/0：205__rep1__S011~T,289__rep3__S004~T
- PEER_028 /functions/1：408__rep4__S005~T
- PEER_028 /functions/2：ALL
- PEER_029 /functions/1：18__rep2__S010~T
- PEER_030 /functions/2：202__rep2__S008~T
- PEER_031 /functions/2：170__rep4__S004~T
- PEER_032 /functions/2：506__rep3__S004~T,1135__rep4__S004~T,68__rep3__S007~T
- PEER_033 /functions/3：ALL
- PEER_034 /functions/3：ALL
- PEER_036 /functions/1：853__rep4__S010~T
- PEER_037 /functions/2：ALL
- PEER_038 /functions/4：ALL
- PEER_039 /functions/1：18__rep4__S007~T,202__rep3__S010~T,853__rep2__S010~T
- PEER_042 /functions/1：20__rep2__S013~T,528__rep3__S008~T
- PEER_043 /functions/0：202__rep4__S007~T,68__rep4__S012~T,205__rep4__S009~T
- PEER_044 /functions/0：970__rep4__S007~T,20__rep3__S013~T
- PEER_045 /functions/0：ALL
- PEER_046 /functions/0：ALL
- PEER_047 /functions/3：ALL
- PEER_048 /functions/0：319__rep3__S008~T
- PEER_049 /functions/2：ALL
- PEER_050 /functions/4：ALL
- PEER_051 /functions/1：ALL

### PF_INTERNAL_HYPOTHESIS_WITHOUT_TOOL_EVIDENCE：在没有新增真实工具证据时展开候选假设、关系推演或查询路线选择

本段没有实际Call/Return增加外部证据，可能是空P，也可能沿用既有猜测、模拟来源或未证关系。

实际比较备选、建立或修正假说、设计查询、反复选择路线；一些记录还将并未执行的查阅写成叙述，必须保留其真实性问题。

候选或计划、内部逻辑修正、未证断言或重复意向，不是新增外部证据。实际未执行的搜索仍不计Call。

不是所有纯推理都属于本组。已经有真实材料支撑的采用、完整判断和答案组织应按各自实际功能归组，不因无Call降成猜测。

有实质假说比较与无新增状态的长计划重复不同；组中保留源记录各自描述，不预设全部是循环或无用。

不自动套N010或认定任何能力上限；某些内部纠错有效，但仍不能用自述来源冒充真实工具返回。

显式成员来源：

- PEER_002 /functions/0：205__rep3__S001~T
- PEER_005 /functions/3：ALL
- PEER_007 /functions/3：495__rep3__S001
- PEER_010 /functions/1：495__rep3__S003
- PEER_010 /functions/2：694__rep1__S004~T
- PEER_012 /functions/1：495__rep3__S005
- PEER_013 /functions/4：ALL
- PEER_015 /functions/3：495__rep3__S007~T
- PEER_019 /functions/1：637__rep2__S001
- PEER_023 /functions/3：68__rep2__S001~T

## 未归或混合、需人工关注

- 319__rep3__S006__FIRST_SENTENCE：原U是在已采用事故数值及日期后再次局部肯定/承接，不含外部再确认，也没有足够依据按这一批记录称完整全题充分性评估。保留具体局部重申功能为单项，不为了覆盖把它塞入全局比较或外部确认。其后新支实际重查属于NEW行为，不能倒填成原U的Function。
- 377__rep4__S005__FIRST_SENTENCE：原普通姓名已采用，工具再次确认却可能要解决legal first/middle的精确形式。现有记录不能唯一确定是同一已证关系的再确认还是仍未知的法律形式核验，因此Function保留这两项备选，不纳确定的已采关系重复或确定的新条件补证。

其余混合源function的原描述、完整成员与distinction逐项保留在JSON entries中；选择例外按TSV明确列出，无关键词扩展。

## 对机制归纳的用途

相同功能还要按真实前态比较：资料是否只是可见、是否已采、是否已用于Call、候选是否稳定、是否首次补证、原产物是否在四支恢复。不能由本组计数推出可省率或必要性。

These families are explicit cross-batch comparison proposals. Their counts describe original U work, not the number of deletions that proved necessity or removability. Mechanism membership and NEW function reconstruction remain separate source fields. Researcher approval and ROOT alignment with its independent functions are still required.
