# 深层作用机制及证据边界

|具体候选链（定义保持原文）|A：Stage/题/run/已观察续跑|B：Stage/题/run/已观察续跑|
|---|---|---|
|条件被绑定到哪个事件或身份，决定正确材料会被排除还是用于定向查证 (P1_K1)|15/5/10/18|21/16/17/35|
|已有对象或高区分度线索让替代查询重新汇聚到同一事实，保持的是产物而非原执行顺序 (P1_K2)|89/29/65/339|5/5/5/17|
|对象已锁定后，特定关系未证仍持续派发查询；最终有时改变的是接受缺口，而不是补齐证据 (P1_K3)|55/20/30/111|103/32/55/307|
|把具体对象用作下一查询的连接键，才能从题面词拼接转为可检验的关系工作 (P2_R1)|99/30/61/322|111/36/59/236|
|已获并已采用的事实被重新派为确认任务，会增加执行实例而不必改变答案 (P2_R2)|137/24/49/271|8/7/7/11|
|核心候选采用以后，未证关系是否继续驱动工作，决定核验延长还是带缺口提交 (P2_R3)|302/36/80/963|82/27/45/222|
|相关名称被移作题目所问的另一种称谓关系 (N001)|0/0/0/0|4/2/4/5|
|引导中的来源叙述被当作已经发生的真实取证 (N002)|4/4/4/7|3/3/3/3|
|条件对象转移或范围窄化制造额外核验任务 (N003)|16/10/13/22|9/4/6/16|
|保留判断功能，将补证前后两次完整比较集中为补证后一次 (N004)|15/10/14/41|0/0/0/0|
|一次真实返回的联合证据被采用，替代独立补证操作 (N005)|27/14/22/48|6/5/5/11|
|身份已采用后，新增独立条件补强未再执行而沿既有判断提交 (N006)|10/7/10/26|0/0/0/0|
|反复检索命中被用作接受未证身份的依据 (N007)|0/0/0/0|11/7/8/12|
|部分匹配条件被升为足够识别身份的标准 (N008)|5/2/2/14|40/16/23/89|
|所求关系已获证且已采用，后续不重取相同关系也可延续原判断 (N009)|7/7/7/19|0/0/0/0|
|未闭缺口反复触发未执行查询计划，旧判断反复重述但没有真实反馈更新 (N010)|1/1/1/1|1/1/1/1|

**以下完整定义原文中的“当前支持数”等数字是候选建立时的历史记录，不是本轮数量；本轮以顶部表格和可复算CSV为准。保留旧反例与限制，不静默改写原定义。**

各行是具体窗口中观察的候选作用链，不是该原U已证明因果必要/冗余。原文归属见locus、stage_attribution，兼容性与行为四态分列。

## P1_K1：条件被绑定到哪个事件或身份，决定正确材料会被排除还是用于定向查证

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "K1",
  "name": "条件被绑定到哪个事件或身份，决定正确材料会被排除还是用于定向查证",
  "definition": "问题中的时间、身份或关系尚需解释时，把错误对应当成已成立的不符，会让已见正确对象退出下一行动；将其保留为待证关系或修正解释，则能回到具体对象。",
  "prestate": "已有材料/候选，但题目条件与事实的对应不稳；不是所有材料都尚未返回。",
  "function_link": "跨F1初始发现、F2定向填槽和F3替代范围实施。相同表面取证工作可消费不同的条件解释。",
  "chain": "前提对应未核清→U或后继将解释用于候选/范围判断→错误不符派发旧范围/广搜；解释修正或待查不被当排除→实际Query转具体对象或直接接受→终态和消耗分开变化。",
  "support": [
    {
      "case": "01",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "四条均重现2000年代被误判不在16世纪之后；1/2/4后来修正后C，3仍加Spanish限制到N。",
      "locus": "错误排除在P；U实施替代范围；新路径纠错。不能算删除了错误比较。",
      "refs": [
        "O1",
        "N13",
        "N23",
        "N31",
        "N32",
        "N43"
      ]
    },
    {
      "case": "02",
      "observed": [
        3
      ],
      "not_observed": [
        1,
        2,
        4
      ],
      "excluded": [],
      "why": "新3误把截至2023理解为必须活到2023，真实转广搜，最后改回历史口径；新2相同完整返回却不误排。",
      "locus": "错误在新路径，原U是取资料而非原本纠正此错误。",
      "refs": [
        "N2_FIRST_QUERY_IDENTICAL_TO_N3",
        "N2_HISTORICAL_MARRIAGE_INTERPRETATION",
        "N3_FALSE_ASOF_DEATH_CONFLICT",
        "N3_INTERPRETATION_DRIVES_NEW_TASK",
        "N3_CORRECTS_INTERPRETATION_AT_ACCEPTANCE"
      ]
    },
    {
      "case": "04",
      "observed": [
        2,
        3
      ],
      "not_observed": [
        4
      ],
      "excluded": [
        1
      ],
      "why": "2/3明确读到Redman故事却错绑报道/受伤年代并回老剧；4暂疑但真查本人早伤后纠正。1没取得材料，不检验相同材料解释链。",
      "locus": "U末取得材料；采用及年代解释在原Z/NEW。",
      "refs": [
        "N2_DATE_MISBINDING",
        "N2_ACTUAL_WRONG_RESTRICTION",
        "N3_EXPLICIT_RECOGNITION_AND_WRONG_DATE",
        "N3_NEXT_WRONG_QUERY",
        "N4_DOUBT_KEPT_OPEN",
        "N4_1958_ADOPTED"
      ]
    }
  ],
  "correctness": "错误解释不必最终失败：四条后来纠正的路径均C，三条持续维持本错误的路径N。这里只描述七条具体链，不能由此宣称普遍预测率或纯删除因果。",
  "cost": "错误对应制造新的城市/老剧/广演员任务，或延长同对象取证；1122新3虽仍C且Call较原少，生成反增。170新2另有末轮纯文本循环，不能全算Search。",
  "counterexamples": [
    {
      "case": "06",
      "repeats": [
        1,
        2,
        3,
        4
      ],
      "why": "1951是真实不符，但只否定合作者匹配，没有推出主体错误；正确处理真实冲突不是本机制中的错误排除。"
    },
    {
      "case": "09",
      "repeats": [
        4
      ],
      "why": "真实追加核查区分学院1441与大学1209，新增证据能澄清条件，不是所有重查都有害。"
    },
    {
      "case": "04",
      "repeats": [
        4
      ],
      "why": "暂时怀疑年代后仍查同一人并修正，反对一见疑问就推断候选已永久排除。"
    }
  ],
  "unknown": "为何各seed采用不同解释仍无唯一答案。G、初始重求解及材料时点是替代解释。三个核心支持题都在B组，A用于边界对照，不能将此数外推A/B频率。"
}
```

## P1_K2：已有对象或高区分度线索让替代查询重新汇聚到同一事实，保持的是产物而非原执行顺序

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "K2",
  "name": "已有对象或高区分度线索让替代查询重新汇聚到同一事实，保持的是产物而非原执行顺序",
  "definition": "身份/线索锚点足够具体且仍在P或题目时，删除某次取证并不删除找到同一资料的条件；别的Query或共享返回可重建同一事实和判断，答案因而保持，调用组织却可能更省或更贵。",
  "prestate": "已识别Tzeni/Fathy/Tunisia/Ewuare/Joey等对象，或原题自带devil's basket高区分度词；所需事实在实际返回中能被重新取得并采用。",
  "function_link": "主要F2定向填槽，及F1中1239的特异描述发现。",
  "chain": "P/题目保留检索锚点→不同Query/顺序重新得到关键文档→模型实际提取并采用U的核心产物→候选/后续主路线恢复→答案保持或改善；费用差落在覆盖多条件、串并行、额外补查或漏查。",
  "support": [
    {
      "case": "02",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "泛希腊取证改为姓名Query，传记40600两婚一子产物恢复，法律证明仍未取得。",
      "locus": "U取人物资料，替代产物在NEW。",
      "key_doc": "40600",
      "original_event": 10,
      "refs": [
        "U_RETURN_BIOGRAPHY_MORE_CONDITIONS",
        "N1_ALTERNATIVE_NAME_QUERY",
        "N2_FIRST_QUERY_IDENTICAL_TO_N3",
        "N3_FIRST_QUERY_IDENTICAL_TO_N2"
      ]
    },
    {
      "case": "06",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "G先查另一人，之后真实查Fathy并用56811恢复1951及不符判断；原生日工作没有省掉。",
      "locus": "U事实及局部否定，在NEW次序后移。",
      "key_doc": "56811",
      "original_event": 2,
      "refs": [
        "O1",
        "N12",
        "N21",
        "N41"
      ]
    },
    {
      "case": "07",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "独特篮子词使一条或两条新入口仍带回59886及名字关系；四次均采用植物。",
      "locus": "空P；锚点来自题目，不是前文已确认答案。",
      "key_doc": "59886",
      "original_event": 0,
      "refs": [
        "U_ENTITY_SOURCE",
        "ORIGINAL_ADOPTION",
        "N1_ADOPTION",
        "N2_LATER_MATCH",
        "N3_FINAL",
        "N4_FINAL"
      ]
    },
    {
      "case": "08",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "国家已采用，重新查选举得到96911日期，推窗口并进行节目匹配；全部恢复。",
      "locus": "日期是U产物，月窗和采用是原Z/NEW。",
      "key_doc": "96911",
      "original_event": 2,
      "refs": [
        "U_ELECTION_CALL",
        "U_ELECTION_ADOPTION",
        "N1_ELECTION_CALL",
        "N2_WINDOW_USED",
        "N3_DATE_TO_WINDOW",
        "N4_DISTINGUISHES_INTERVALS"
      ]
    },
    {
      "case": "09",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "家系Query共同带回31955名字材料，认知确认恢复；专门加冕Query不必每条同样执行。",
      "locus": "名字材料原在P可见；U强化确认，NEW共享返回。",
      "key_doc": "31955",
      "original_event": 2,
      "refs": [
        "O_NAME_ALREADY_VISIBLE",
        "O_U_CONFIRM_ADOPT",
        "N1_LINEAGE_FIRST_CALL",
        "N2_COMBINED_RECHECK",
        "N4_REAL_NAME_RECHECK"
      ]
    },
    {
      "case": "10",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "P已定Joey，多个关键词Query都重新得24061的Atari型号并采用，父亲关系仍不在片段。",
      "locus": "U首次得型号；NEW重建，长U后段核查次数不同。",
      "key_doc": "24061",
      "original_event": 1,
      "refs": [
        "O2",
        "N12",
        "N21",
        "N31",
        "N41"
      ]
    }
  ],
  "correctness": "六题24条都恢复核心产物并C；这是有条件的过程支持，不证明功能不需要，也不保证所有题目关系证据无损。",
  "cost": "528四条费用均增；1239少Search但部分多Actor；1135有同Call但更多文字；78主要压缩原后继家系；408三少一多；1122一条因误解释多文字。变化不能只用被删U长度说明。",
  "counterexamples": [
    {
      "case": "05",
      "repeats": [
        1,
        2,
        3,
        4
      ],
      "why": "四次重建错误Eightball核验却两W两N。检索锚点未充分成立时，汇聚可能只是困在错误对象；重建不保证正确。"
    },
    {
      "case": "04",
      "repeats": [
        2,
        3
      ],
      "why": "关键故事实际回来了，却被错误时间解释排离后续行动；文档重取不等于产物正确采用。"
    },
    {
      "case": "03",
      "repeats": [
        2
      ],
      "why": "个人首单材料虽出现，未转成Jun.K演出核查，未完成该产物到行动转换。"
    }
  ],
  "unknown": "24条不是独立24道题；对检索锚点的可恢复性只是这批事后证据，不是预先证明任意Query都能恢复。G对姓名/核查顺序有补偿，纯删除必要性未定。"
}
```

## P1_K3：对象已锁定后，特定关系未证仍持续派发查询；最终有时改变的是接受缺口，而不是补齐证据

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "K3",
  "name": "对象已锁定后，特定关系未证仍持续派发查询；最终有时改变的是接受缺口，而不是补齐证据",
  "definition": "模型已经说出所缺的具体关系，但连续返回主要支持相邻事实，后续仍向同一对象索要该关系。只要这一缺口继续被选作当前任务，计算就增加；转为依其他匹配接受后，原缺口可以不闭合而产生Final。",
  "prestate": "有固定对象和可回答的候选属性，但另有法律事件、合作者、父亲购买或别名/出版关系未证。对象可能正确也可能错误，必须另审。",
  "function_link": "F2已有对象补关系；F3未证身份上的属性核查。",
  "chain": "固定对象+明确缺口→返回未给所需关系而主体/缺口未更新→再次选择同对象或邻近入口查询→累积生成/Prompt/工具成本；后来若放宽接受则提交，若仍不停止可耗尽上下文或生成。",
  "support": [
    {
      "case": "02",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "法律事件一直未证，四次都真实补查后按其他传记提交；3/4同六Call但额外任务来源不同。",
      "locus": "原Z及NEW；U实际只补传记。",
      "refs": [
        "N1_POLITICAL_PLAUSIBILITY_REPLACES_PROOF",
        "N2_ACCEPTS_AFTER_THREE_CALLS",
        "N3_CORRECTS_INTERPRETATION_AT_ACCEPTANCE",
        "N4_REPEATED_RETURNS_KEEP_GAP_ACTIVE",
        "N4_NEAR_END_CHANGE_TO_SUBMISSION"
      ]
    },
    {
      "case": "05",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "错误作者上的别名/出版社关系缺口持续发任务；1/4最终带冲突猜答W，2/3保持补查或纯意向到N。不同查询有时取得新属性，但没证书目整体关系。",
      "locus": "NEW，受G未证关系预设强烈影响。",
      "refs": [
        "N1_FALSE_ORIGINAL_REQUIREMENT_RELAXED",
        "N2_PSEUDONYM_PRESUPPOSED",
        "N2_LAST_PURE_INTENTION",
        "N3_NO_SUPPORT_BUT_CONDITION_PRESUPPOSED",
        "N3_LATE_REAL_QUERY",
        "N4_EXPLICIT_FOUNDED_CONFLICT"
      ]
    },
    {
      "case": "06",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "排除Fathy满足生日后，另一合作人仍未知；多入口和部分重复确认继续，最后未找到该人也提交Dina。",
      "locus": "原Z及NEW，原U的生日否定全恢复。",
      "refs": [
        "N13",
        "N14",
        "N21",
        "N23",
        "N31",
        "N32",
        "N42",
        "N43"
      ]
    },
    {
      "case": "10",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "Atari型号已取回，父子共同购买仍未证，四条均继续核后提交；第4条更久且长清单扩写，不增加所需关系证据。",
      "locus": "U长段后部、原Z与NEW。",
      "refs": [
        "N12",
        "N13",
        "N21",
        "N22",
        "N32",
        "N41",
        "N42",
        "N43"
      ]
    }
  ],
  "correctness": "16条内既有12C，也有257的2W/2N。区别不只是查多久，还在主体依据是否正确、是否允许未闭合关系不再阻止提交。C不证明法律/父亲等关系已验证。",
  "cost": "真正增加的是具体补关系Query、相同材料的累计Prompt和反复清单。257新2末轮10000纯生成不是Search。A408同型号四C仍三少一多，A528全C费用全增；不能由终态频率代替这一过程。",
  "counterexamples": [
    {
      "case": "09",
      "repeats": [
        4
      ],
      "why": "追加学校查询真实带来1209/1441层级证据，反对将所有继续核验称低增量。"
    },
    {
      "case": "08",
      "repeats": [
        1
      ],
      "why": "说再查但没执行，不能把一句意向计为取证或机制实例。"
    },
    {
      "case": "08",
      "repeats": [
        3
      ],
      "why": "主持和2023年份是不同条件，两个Call数量相同不等于同一缺口循环；其价值仍需按具体返回判断。"
    }
  ],
  "unknown": "必要缺口是真的，首次针对性核验可能合理；本机制只定位多次尝试未带来所需状态更新，不证明搜索已经穷尽或客观上无用。为何某seed最终停止仍无唯一解释，也不能从G和预算中分离U独特因果作用。"
}
```

## P2_R1：把具体对象用作下一查询的连接键，才能从题面词拼接转为可检验的关系工作

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "R1",
  "name": "把具体对象用作下一查询的连接键，才能从题面词拼接转为可检验的关系工作",
  "definition": "缺的不是更多泛材料，而是能连接题目条件的对象时，候选必须被明确采用并实际进入下一Call。这个转换可由新检索发现，也可由P中未采用线索触发；仅返回名字或反复复述题目不足以完成。",
  "prestate": "候选/连接实体尚未落实，或只是部分匹配、替代线索未采用。",
  "function_link": "跨F1定位、F4属性核查先后顺序；也为F2候选比较提供应落到真实行动的检验。",
  "chain": "未连上的题面条件→U或替代工作选择入口→返回具体人/物种或采用P线索→真实下一Query变具名对象及其关系→缩小后继工作；若仍缺关系，正确候选也可能不提交。",
  "support": [
    {
      "case": "01",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "四条都从新51676采用Larson并真实具名查论文；三个C，一个即使完成连接仍N。",
      "locus": "原U失败；转换是新后续取得人物并用于Query，不把它提前算成U已有。",
      "refs": [
        "N12",
        "N13",
        "N21",
        "N22",
        "N31",
        "N32",
        "N41",
        "N42"
      ]
    },
    {
      "case": "02",
      "observed": [
        1,
        2,
        3
      ],
      "not_observed": [
        4
      ],
      "excluded": [],
      "why": "三条用54513物种立刻查56046博客，直接赠苗关系支撑C；新4加未证抗菌限定，没取得物种，也未完成下一具名检索。",
      "locus": "新真实取证替代或接在重做U之后；G不含物种。",
      "refs": [
        "N1_REAL_ACTIVITY_QUERY",
        "N1_PAPER_RETURN",
        "N1_SPECIES_USED",
        "N1_DONOR_RETURN",
        "N2_ACTIVITY_QUERY",
        "N2_SPECIES_QUERY",
        "N3_PAPER_USE",
        "N3_SPECIES_QUERY",
        "N4_ADDED_SPECIFICITY",
        "N4_REAL_QUERY"
      ]
    },
    {
      "case": "03",
      "observed": [
        1
      ],
      "not_observed": [
        2,
        3,
        4
      ],
      "excluded": [],
      "why": "新1得到直接原名的18594后真实查Benko；2/3没有目标资料，4只识别较弱Signa结构材料却笼统否决，未查该人。",
      "locus": "U韩国尝试重建也可成功，差别在后继对象转换，不是U功能是否出现。",
      "refs": [
        "N1_DIRECT_COMPANY_RETURN",
        "N1_ADOPT_AND_GAP",
        "N1_PERSON_CALL",
        "N4_RELEVANT_RETURN",
        "N4_INCOMPLETE_REJECTION",
        "N4_NO_PERSON_QUERY"
      ]
    },
    {
      "case": "10",
      "observed": [
        1,
        2,
        3
      ],
      "not_observed": [
        4
      ],
      "excluded": [],
      "why": "三条先用14岁/Young线索，取得生日和歌曲，实际改查Mozzy；4知道替代线索却恢复旧主体属性并走向错歌。",
      "locus": "前三条没有重做U的Lil Durk歌曲工作，核心需求由替代对象路线完成。",
      "refs": [
        "O_P_BETTER_AGE_LEAD",
        "N1_EARLY_CONSTRAINT_ACTION",
        "N1_YOUNG_ACTUAL_QUERY",
        "N1_MANDO_ADOPTED",
        "N2_YOUNG_ACTUAL_QUERY",
        "N3_CANDIDATE_UPDATED",
        "N3_NEW_FEATURE_QUERY",
        "N4_CONFLICT_AND_ALT_VISIBLE",
        "N4_BACK_TO_OLD_SUBJECT"
      ]
    }
  ],
  "correctness": "这里的链条解释对象何时真正进入行动，不是保证正确Final的充分条件。853新4已经完成连接但仍N；1032三条C还有论文参考文献未核全；231核心歌名C不证明父亲/专辑条件充分。",
  "cost": "1032成功路径Search和Actor比原后缀更多，却避免原末轮10000Token无Call空转；231三条先验证身份、绕开旧主体四查而省；1046新1多一Call仍少生成。可定位不同成本项，不能统称更快或更省。",
  "counterexamples": [
    {
      "case": "01",
      "repeats": [
        4
      ],
      "why": "具体候选采用和具名Call都恢复仍N，连接只是中间环节，不是提交充分条件。"
    },
    {
      "case": "05",
      "repeats": [
        1,
        2,
        4
      ],
      "why": "正确人物已恢复，后面疾病关系继续驱动查询，反对把所有N都归因于没有采用对象。"
    },
    {
      "case": "08",
      "repeats": [
        1,
        2,
        3,
        4
      ],
      "why": "G已给正确名字，不能计作自主产生连接实体的正例；它还能导向N或无证属性。"
    }
  ],
  "unknown": "不能唯一解释某个查询为何召回不同文档或某seed为何更早转换。1046新4与新1材料不等价，1032抗菌限定改变返回不证明任何额外限定必然有害。教师方向、采样和预算保留。"
}
```

## P2_R2：已获并已采用的事实被重新派为确认任务，会增加执行实例而不必改变答案

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "R2",
  "name": "已获并已采用的事实被重新派为确认任务，会增加执行实例而不必改变答案",
  "definition": "当一个具体条件已有直接材料并已用于判断，后继又把它列作需要确认、真实再查，却没有补到当前另一个未解关系时，增加的是已支持条件的确认实例。功能仍保留，结果可以相同；不是仅因Query相似就认定无用。",
  "prestate": "不是所有条件都已解决，而是某一个将要重查的具体事实已返回且已采用。需要把它与其他仍缺条件分开。",
  "function_link": "F3定向填事实或确认关系后的任务再选择。",
  "chain": "某事实已支持并被采用→仍决定再确认同一事实→真实重复取得并使用相同支持→没有更新其他关键缺口或候选→答案保持但增加交互/输入或文字；整体费用还受其他被缩掉步骤影响。",
  "support": [
    {
      "case": "06",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "excluded": [],
      "why": "新2学校完成后重查P已采用的Baha护士事件；2/3同首Query及完整Return，3不重开该任务而C，2多一次仍C。",
      "locus": "不是U生日首次核验重复；重新开启的是P事件条件。",
      "refs": [
        "O1",
        "N22",
        "N24",
        "N25",
        "N26",
        "N31",
        "N32",
        "N34"
      ]
    },
    {
      "case": "07",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "excluded": [],
      "why": "新2已引用驾驶原句并称证实，仍真实再查驾驶；其他三条查尚未直接证实的节庆关系，不能同等算已证事实重复。",
      "locus": "U核心事实恢复后的一次额外决策。",
      "refs": [
        "N2_RECOVERS_QUERY",
        "N2_ALREADY_HAS_DRIVING",
        "N2_SECOND_CALL",
        "N2_FINAL",
        "N1_ACCEPTS_THEN_CHECKS"
      ]
    },
    {
      "case": "09",
      "observed": [
        4
      ],
      "not_observed": [],
      "excluded": [
        1,
        2,
        3
      ],
      "why": "新4已知女校名和合并关系仍连续三查精确女校名，没有增加镇史支持；其余路径也有确认，但涉及候选重评或一次精确名称确认，是否属于同类重新派发保留合理解释，不计本机制确定正例。",
      "locus": "不是U两Call确认是否存在，而是新后继将已知名称再当任务。",
      "refs": [
        "N4_DIRECT_QUERY",
        "N4_NAME_KNOWN_STILL_CHECK",
        "N4_CITY_SITE_TRANSFER",
        "N4_FINAL"
      ]
    }
  ],
  "correctness": "三个确定执行实例都保持核心C；这不证明条件核验全部无价值，更不证明母亲管理、节目或镇史证据充分。",
  "cost": "291新2与新3同首返回但多一Call/Actor及输入；191新2比原同切点各多一次且生成区间上升；205新4虽有额外名字确认，总Call仍少于原，生成却更多。不能把局部重复的成本和全后缀净差混为一谈。",
  "counterexamples": [
    {
      "case": "06",
      "repeats": [
        1
      ],
      "why": "同一Query同时得到出生和学校，是共享证据覆盖而少交互，不是没有做身份工作。"
    },
    {
      "case": "07",
      "repeats": [
        1,
        3,
        4
      ],
      "why": "所查节目关系尚无直接证明，再尝试不能因最终无增量就倒推为已证事实重复。"
    },
    {
      "case": "08",
      "repeats": [
        4
      ],
      "why": "R10采用纪念赛、R11又说没找到的状态反复可见，但随后Call是俱乐部Query，无法把具体费用唯一对应到重开纪念赛，不计正例。"
    }
  ],
  "unknown": "重新确认可能有合理核验价值，日志只支持是否增加新关系/改变候选。本机制未证明这些Call可无引导删除且保持全部质量。205三条备选归属暂不强判。"
}
```

## P2_R3：核心候选采用以后，未证关系是否继续驱动工作，决定核验延长还是带缺口提交

定义源：REGISTRY_CURRENT\V001_PILOT_SEEDS_UNMODIFIED.json；SHA 7493dd1d4c47b545ee81af8275c769d209d5522a19b756f56b3e5118b28c17c8

```json
{
  "id": "R3",
  "name": "核心候选采用以后，未证关系是否继续驱动工作，决定核验延长还是带缺口提交",
  "definition": "已有足以选定核心候选的材料，并不等于题目每条关系都已证实。若模型反复将同一未闭关系选为下一任务且没有取得相应证据，交互持续增加；若后来不再让该缺口阻止主答案，可能提交正确主体而证据仍不完整。",
  "prestate": "核心人物/歌名已实际采用；另有论文学历、职业启发、电影导演、节目关系或父亲服刑等具体信息缺口。",
  "function_link": "F2/F3后继整体充分性判断与取证安排，也见F1/F4新对象建立后的后段工作。",
  "chain": "核心采用已恢复→明确剩余关系缺口→真实围绕它取证但返回不闭合→有些路径维持该任务至预算N，有些改用其他匹配接受并提交→正确性、证据充分性、消耗分别变化。",
  "support": [
    {
      "case": "01",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "四条都采用Larson并查2015/Tufts，均未证具体论文；前三条带保留C，第四反复同Query到N。",
      "locus": "新后继；原U并无姓名或论文关系产物。",
      "refs": [
        "N14",
        "N23",
        "N33",
        "N41",
        "N42",
        "N43",
        "N44"
      ]
    },
    {
      "case": "05",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "excluded": [],
      "why": "四条恢复正确人物，疾病启发关系均未补齐；一条六查后带保留C，三条持续真实核验到N。",
      "locus": "身份采用之后，不以清单有无代替实际关系与Call检查。",
      "refs": [
        "N1_PARTIAL_COMPARE",
        "N1_LATE_QUERY",
        "N2_RESTORED_FACTS",
        "N2_GAP_RETRIGGER",
        "N2_LAST_QUERY",
        "N3_MULTIPLE_HYPOTHESES",
        "N3_STOP_WITH_UNSOLVED",
        "N4_COMPARE_RESTORED",
        "N4_LATE_QUERY"
      ]
    },
    {
      "case": "04",
      "observed": [
        1,
        3
      ],
      "not_observed": [],
      "excluded": [
        2,
        4
      ],
      "why": "新1/3均采用Audret并核电影，前者持续查到N，后者未证导演关系却C；2/4没有恢复同一个正确核心对象，不混为相同阶段。",
      "locus": "首婚/姓名恢复后的电影缺口。",
      "refs": [
        "N11",
        "N12",
        "N14",
        "N15",
        "N31",
        "N32",
        "N33",
        "N34"
      ]
    },
    {
      "case": "07",
      "observed": [
        1,
        3,
        4
      ],
      "not_observed": [
        2
      ],
      "excluded": [],
      "why": "三条仍查未被直接证实的节目关系，未补齐却按获奖/其它匹配C；新2所查是已直接支持的驾驶，属于R2对照。",
      "locus": "核心驾驶/学历恢复后的另一个关系，不把两类缺口状态混淆。",
      "refs": [
        "N1_ACCEPTS_THEN_CHECKS",
        "N1_SECOND_CALL",
        "N1_STILL_INDIRECT",
        "N3_ALREADY_INFERS",
        "N3_SECOND_CALL",
        "N4_SECOND_CALL",
        "N4_LIMIT_RECOGNIZED"
      ]
    },
    {
      "case": "10",
      "observed": [
        1,
        2,
        3
      ],
      "not_observed": [],
      "excluded": [
        4
      ],
      "why": "三条采用Mando/Mozzy后多次查父亲15年，仍未证却提交C；新4主关系错误而W，不当作同一已获核心关系的路径。",
      "locus": "替代正确人物之后的父亲/专辑补查。",
      "refs": [
        "N1_MANDO_ADOPTED",
        "N1_FINAL_WITH_GAP",
        "N2_UNPROVEN_ALBUM_FINAL",
        "N3_NEW_FEATURE_QUERY",
        "N3_FATHER_STILL_GAP",
        "N3_FINAL"
      ]
    }
  ],
  "correctness": "候选恢复与Final是两个环节；同一缺口没闭合既可能C也可能N。主体C必须与条件证据验收分开；如231某Final把未证父亲关系写成肯定，还需记无依据断言。",
  "cost": "853新4少一个Search却累计Prompt高于原；68三N文字较短却更多Call和输入，成功路径少后继核验；191少量额外核验后仍停止；231正确路径省旧主体查证但父亲工作仍多。不能由持续核验次数直接决定必要性。",
  "counterexamples": [
    {
      "case": "02",
      "repeats": [
        1,
        2,
        3
      ],
      "why": "论文参考文献仍未核全，但直接赠苗原句已取到；未闭的辅助识别条件未持续派发参考文献查询，说明有缺口不必进入长期核验。"
    },
    {
      "case": "09",
      "repeats": [
        2
      ],
      "why": "正确女校与较少调用伴随无源1874断言；表面上缺口消失可能只是被写成已满足，非真实证据闭合。"
    },
    {
      "case": "08",
      "repeats": [
        2
      ],
      "why": "教师已给正确名字仍可在比赛关系上耗尽；可见相似后段，但身份来源不同，不能据此补充无补偿删除的因果证据。"
    }
  ],
  "unknown": "能定位继续查了哪项关系及何时转提交，不能唯一解释某seed为何停止或形成所谓信心阈值。首次合理核验与后段低增量尝试须分开；没有穷尽检索的证明，也没有无G纯删除因果识别。"
}
```

## N001_RELATED_NAME_PROMOTED_TO_ASKED_DESIGNATION：相关名称被移作题目所问的另一种称谓关系

定义源：REGISTRY_CURRENT\V002_NEW_DESIGNATION_AND_GUIDE_SOURCE_CANDIDATES.json；SHA 5b99a45aeb084b54c855bc71f6bd69193444ba919bf8a095f0204eaac5a2ca9a

```json
{
  "registry_id": "N001_RELATED_NAME_PROMOTED_TO_ASKED_DESIGNATION",
  "name": "相关名称被移作题目所问的另一种称谓关系",
  "prestate": "具体主体已选定，所问的序号或曾考虑名称尚无直接证据；已有材料包含一个与主体有关的名称写法或命名背景。",
  "definition": "模型先承认所问关系没有被材料证明，却将相关名称或另一实体的改名关系当成题目所问的属性，最终正式选择该名称/数字。需要实际前述缺证、具体关联材料与正式选择三个节点，不能仅因Final错误或出现同词标注。",
  "function_relation": "可发生在取证失败反馈之后的证据解释及答案构造中；目标Stage可能只是此前的对象发现或失败取证，必须单独记录作用位置，不能都归目标U。",
  "chain": "已定主体但目标属性未知→读取相关名称/命名故事→错误将名称关系跨属性或跨实体迁移→在未取得目标关系的新支持时正式选答案→搜索结束但核心答案W；成本减少可能来自早结束，生成也可能变长。",
  "inclusions": [
    "实际使用名称记号作铭牌编号",
    "实际使用人物改名作城市曾考虑的名称"
  ],
  "exclusions": [
    "没有实际Final",
    "只有未执行的备选计划",
    "只有正确关系被否定后持续搜索而未接受",
    "无具体命名材料、纯common knowledge猜数字",
    "协议停止前未取得材料"
  ],
  "explicit_memberships": [
    {
      "case_id": "282__rep1__S003__FIRST_SENTENCE",
      "local_id": "NAME_NOTATION_PROMOTED_TO_NAMEPLATE_ATTRIBUTE",
      "observed": [
        3
      ],
      "not_observed": [
        1,
        2,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N32",
        "N33",
        "N34"
      ],
      "locus": "NEW3 Final; U原本只是未成功编号取证",
      "subtype": "名称样式Pen²→铭牌serial2"
    },
    {
      "case_id": "392__rep4__S003__FIRST_SENTENCE",
      "local_id": "BIBLICAL_PERSON_RENAMING_PROMOTED_TO_CITY_ALTERNATIVE",
      "observed": [
        2,
        4
      ],
      "not_observed": [
        1
      ],
      "uncertain": [],
      "excluded": [
        3
      ],
      "evidence": [
        "N2_BIBLICAL_CHILD_NOT_CITY",
        "N22",
        "N23",
        "N24",
        "N42",
        "N43",
        "N44",
        "N4_FORMAL_RELATION_TRANSFER"
      ],
      "locus": "NEW2/4实际Query/Final; U原本电影身份发现",
      "subtype": "圣经儿童改名→城市几乎用名"
    }
  ],
  "counterexamples": [
    "282新2明确知道Pen²不是serial却另用通常实验体编号猜001，不属于本细链；说明识别一种错误关系不足以保证答案正确。",
    "392新1也W但用实际土地名，不归儿童改名子链；新3协议无Call无Final排除。",
    "原282/392都未取得所问事实，却没有正式选择这些名字，持续取证至N。"
  ],
  "limits": "现只有两个不同题的三支明确细链；均原N且教师引导存在，不能宣称导致C退化、纯删除因果或自然分布发生率。该候选解释实际语义迁移与选择，不解释唯一的内部接受原因。",
  "relation_to_pilot_seeds": "与P1_K1同属条件/关系解释层，但本候选是错误接受所求属性，不是错误排除已见候选；不得扩写旧定义或将旧全部成员自动并入。与P2_R3可上下游相接：缺口驱动核验后，本候选在提交时错误关闭缺口。"
}
```

## N002_GUIDE_SOURCE_NARRATIVE_REIFIED_AS_OBSERVATION：引导中的来源叙述被当作已经发生的真实取证

定义源：REGISTRY_CURRENT\V002_NEW_DESIGNATION_AND_GUIDE_SOURCE_CANDIDATES.json；SHA 5b99a45aeb084b54c855bc71f6bd69193444ba919bf8a095f0204eaac5a2ca9a

```json
{
  "registry_id": "N002_GUIDE_SOURCE_NARRATIVE_REIFIED_AS_OBSERVATION",
  "name": "引导中的来源叙述被当作已经发生的真实取证",
  "prestate": "P中没有所称文档或工具Return；G以已经看到某Doc的口吻提供未来实体及来源。",
  "definition": "新模型未执行真实工具，却把G来源叙述当已见材料，进一步扩成其它并未返回的证据，并据此选择正式答案。必须逐项核实P、G与本分支真实Call，不能只凭虚构DocID判定来源来自G。",
  "chain": "空证据P加含来源的G→将教师叙述作为已见Return→扩展虚假多源一致→正式提交→少工具但无可比支持，不能作为原工作严格可省证据。",
  "explicit_memberships": [
    {
      "case_id": "427__rep1__S001__FIRST_SENTENCE",
      "local_id": "TEACHER_SOURCE_NARRATIVE_TREATED_AS_REAL_MULTI_DOCUMENT_SUPPORT",
      "observed": [
        3
      ],
      "not_observed": [
        1,
        2,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N31",
        "N32"
      ],
      "locus": "NEW3唯一Reasoning/Final，0真实Search"
    }
  ],
  "counterexamples": [
    "427另外三支真实执行Search，不能算同一种零Call来源复用。",
    "319 G给错误候选但四支仍真实取得事故证据，不能一律认G实体出现即来源污染。"
  ],
  "limits": "仅一题一支，作为干预风险个案保留，不计跨题机制已支持。与无G条件的假访谈或自然幻觉起点不同，未核前不得合并。",
  "relation_to_pilot_seeds": "不属于目标Stage本身的自然认知机制；必须与FIRST_SENTENCE实验条件影响分开，禁止用该案例证明原Stage无用。"
}
```

## N003_WRONG_CONSTRAINT_TARGET_DISPATCHES_UNREQUIRED_CHECK：条件对象转移或范围窄化制造额外核验任务

定义源：REGISTRY_CURRENT\V003_NEW_CONSTRAINT_TASK_CANDIDATES.json；SHA 27ec323c2ad6231b63fbe5717a33ac5c69dec34bf3a6a9e9b34ba8ce0a1067e0

```json
{
  "registry_id": "N003_WRONG_CONSTRAINT_TARGET_DISPATCHES_UNREQUIRED_CHECK",
  "name": "条件对象转移或范围窄化制造额外核验任务",
  "prestate": "原问题对条件归属或允许范围已有明确描述；候选或关系材料已可供使用，但模型用改写后的更窄/错误条件重新定义缺口。",
  "definition": "模型实际将一个角色的条件附给另一个角色，或将允许范围窄化为题目未要求的子类，并因此真正执行原题不要求的具体核验。必须同时有完整题面、明确错误条件表述、实际Call及返回后处理。仅出现错误词或未执行计划，不能计为完整出现。",
  "chain": "原条件归属/范围清楚→新认知改写为更窄或另一个对象→已有证据不能满足该伪条件→真实查询被派发以补不存在的必需缺口→增加工作/占上下文；修复改写可取消该任务，但真实剩余条件和提交仍需另查。",
  "function_relation": "可出现在初始拆题、候选比较或重列剩余缺口。目标U可能原本正确表述条件，具体错误在后续新路径；必须保留U与NEW位置，不能将所有影响归于被删原文。",
  "inclusions": [
    "影响者的出生年转成当前作者必须满足，从而实际反复查当前作者生日",
    "任一外祖辈转成必需男性，祖母已符合仍实际查其丈夫/母亲父亲"
  ],
  "exclusions": [
    "只是错误词但实际操作仍合理核对真实矛盾",
    "没有实际Call的未来计划",
    "真实题目要求尚未证实的核验",
    "材料来源本身矛盾所需独立核验",
    "出现不合但没有证据证明条件被移错角色"
  ],
  "explicit_memberships": [
    {
      "case_id": "625__rep1__S001__FIRST_SENTENCE",
      "local_id": "INFLUENCER_BIRTH_CONSTRAINT_ASSIGNED_TO_CURRENT_AUTHOR",
      "observed": [
        3,
        4
      ],
      "not_observed": [
        2
      ],
      "uncertain": [],
      "excluded": [
        1
      ],
      "evidence": [
        "O1",
        "N21",
        "N31",
        "N32",
        "N34",
        "N41",
        "N42",
        "N43"
      ],
      "locus": "NEW3/4身份恢复后实际生日Query",
      "subtype": "条件由影响者移到当前作者"
    },
    {
      "case_id": "784__rep4__S001__FIRST_SENTENCE",
      "local_id": "MATERNAL_GRANDPARENT_NARROWED_TO_MALE_CREATES_HUSBAND_TASK",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        4
      ],
      "uncertain": [
        3
      ],
      "excluded": [],
      "evidence": [
        "O1",
        "N21",
        "N22",
        "N24",
        "N25",
        "N3_MALE_RULE_BEFORE_BERNON_CHECK",
        "N3_ACTUAL_BERNON_METADATA_QUERY",
        "N31"
      ],
      "locus": "NEW2祖母1937已知后继续丈夫/父亲Query",
      "subtype": "允许任一外祖辈窄成男性"
    }
  ],
  "counterexamples": [
    "625新2不犯生日角色错仍因台词和影响未证而N；错误子任务不是全部失败必要条件。",
    "784新1允许祖母仍在真实导演条件上N；新2晚修复仍C，修复时点影响工作量而非唯一决定结果。",
    "784新3的男性错误明确，但实际第四Call仍核Bernon元数据且修正1919/1937，未展开丈夫搜索，所以保留UNCERTAIN，不因错表述计完整作用链。",
    "1096新1误读理论修饰对象会转广搜，但全文对比段确缺，后续理论核验有合理目的，当前不将整段纳入伪任务。"
  ],
  "cost_relation": "只将具体错误条件实际派发的工作作为机制证据，不把整条净Token差归它。联合批次可Search增加而Actor减少；无Final/提前有限提交亦会改变成本，均分列。",
  "relation_to_existing": "与P1_K1可有上游共同点，但此处强调额外任务派发而非错误排除候选，原六定义不变；与P2_R3不同，因为本候选的缺口不是原题真实未满足条件，不能混成所有剩余缺口的持续核验。",
  "limits": "当前两题三支明确，另有一支不确定；G均提前给候选，不能分离纯删除效应，也不能由三N或三C证明工作必要/有害。观测的是实际条件改写及Query后果，不推隐藏内部动机。"
}
```

## N004_FULL_COMPARISON_INSTANCES_CONSOLIDATED_AFTER_EVIDENCE：保留判断功能，将补证前后两次完整比较集中为补证后一次

定义源：REGISTRY_CURRENT\V005_NEW_COMPARISON_INSTANCE_COMPRESSION_CANDIDATES.json；SHA 2c445a90f6ddbb25dea7e11caf32824c42e18e81353fcf09fce9238b644b3da6

```json
{
  "registry_id": "N004_FULL_COMPARISON_INSTANCES_CONSOLIDATED_AFTER_EVIDENCE",
  "name": "保留判断功能，将补证前后两次完整比较集中为补证后一次",
  "prestate": "原路径已有候选材料，但仍有具体条件待真实补证；原U确实展开完整条件比较，原Z补证后又确实展开完整比较。",
  "definition": "新路径保留候选材料和该次真实补证，没有重现独立完整的前置比较实例，在补证后完成完整比较并采用候选。必须核对两侧实际展开次数与先后，不以简单列表、关键词、G中判断或Final重复解释替代完整实例证据。",
  "chain": "补证前候选判断可再次从已有材料恢复→后继G先指定具体待查项→新路径先实际补证→完整比较集中于证据齐备后→功能恢复但展开实例减少；是否净节省还取决于新增查询和表达。",
  "function_relation": "原Stage本来可能首次完成候选采用，并非内容必然无用；新路径是执行重组和后续恢复，不等无须比较。",
  "explicit_memberships": [
    {
      "case_id": "1095__rep1__S002__FIRST_SENTENCE",
      "local_id": "ONE_POST_EVIDENCE_FULL_COMPARISON_REPLACES_PRE_AND_POST_REVIEWS",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "uncertain": [],
      "excluded": [],
      "locus": "原补证前后完整比较与四新补证后完整比较",
      "subtype": "纪录片候选十条件比较后移"
    },
    {
      "case_id": "1239__rep1__S002__FIRST_SENTENCE",
      "local_id": "ONE_POST_EVIDENCE_FULL_COMPARISON_REPLACES_PRE_AND_POST_REVIEWS",
      "observed": [
        1,
        2,
        4
      ],
      "not_observed": [
        3
      ],
      "uncertain": [],
      "excluded": [],
      "locus": "原五条件接受及人口证据后复核，三新先补密度再完整比较",
      "subtype": "物种候选五条件比较后移"
    }
  ],
  "counterexamples": [
    "1239新3完整前置判断重建且后续再次比较，生成比原更多。",
    "1239新4也集中比较却多一次物种Search，含G净生成+7，不以节省定义成员。",
    "353rep2S003有比较后移但全部完整实例未逐项核清，且实际书/作者查询更多，当前不加入。"
  ],
  "cost_relation": "观察的是比较实例压缩，不等功能删除。分别核对生成含G一次、Prompt、Search和Actor；不把原U长度算节省。部分支调用相同但生成减少，额外Call可抵消收益。",
  "relation_to_existing": "与P1_K2保留锚点后恢复有关，但要求明确原两次完整比较及新一次，不把所有后续恢复归此候选。不同于P2_R2已知条件再次真实取证，这里是认知实例重组。",
  "limits": "目前显式两题、两Stage七支，两题G均给具体补证方向。不能证明无引导同样组织，也不能将核心姓名/物种正确当完整题目证据质量无损。只是候选解释，待研究者审核，不改Stage规则或冻结Pattern。"
}
```

## N005_ONE_REAL_RETURN_SUPPLIES_MULTIPLE_UNRESOLVED_RELATIONS：一次真实返回的联合证据被采用，替代独立补证操作

定义源：REGISTRY_CURRENT\V006_NEW_JOINT_RETURN_WORK_COMPRESSION_CANDIDATES.json；SHA 2d2f053eb89ad33d09ad20035609f042c005ecef03d9ff0b58d2dfab723ede10

```json
{
  "registry_id": "N005_ONE_REAL_RETURN_SUPPLIES_MULTIPLE_UNRESOLVED_RELATIONS",
  "name": "一次真实返回的联合证据被采用，替代独立补证操作",
  "prestate": "存在至少两项可区分的真实信息需求；原路径分开执行过相关取证，或计划另补其中一项，不能只因单Call回多个DocID就算功能合并。",
  "definition": "一项真实查询的完整模型可见Return同时给两个需求的直接证据，后续推理实际采用各关系，因而无需再单发其中一项独立Call。须分别核对目标、实际Query、各关系Return、采用位置和剩余真实Call。只提计划、DocID重合、同主题摘要或模型无源补事实不纳入。",
  "chain": "两真实缺口待解→一次Query同时返回各直接关系→后续真正采用两产物→保留证据功能但合并一次取证/交互→局部工作减少；其它新增核查可能抵消净收益。",
  "function_relation": "原工作功能仍在，执行方式及证据入口替代，不是无需证据或全功能跳过。",
  "explicit_memberships": [
    {
      "case_id": "291__rep1__S002__FIRST_SENTENCE",
      "local_id": "JOINT_RETURN_COVERS_IDENTITY_AND_SCHOOL_RELATIONS",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "locus": "NEW2单Call同时38712身份与第四文档93208学校关系并实际采用",
      "subtype": "一Call身份与学校"
    },
    {
      "case_id": "1023__rep3__S003__FIRST_SENTENCE",
      "local_id": "AD_QUERY_RETURN_ALSO_SUPPLIES_MACHINE_RELATION_WITHOUT_SEPARATE_CALL",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "locus": "NEW2第四广告Call带24356的1832机器关系，下一轮采用，无独立机器Call",
      "subtype": "广告查询附带机器条件"
    },
    {
      "case_id": "1138__rep1__S001__FIRST_SENTENCE",
      "local_id": "CONTRACT_QUERY_INCIDENTALLY_RESTORES_CERTIFICATE_SUPPORT",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "locus": "NEW2第二合同Call带19563证书全文，R3明确采用，实际未执行专门证书Query",
      "subtype": "合同查询附带证书条件"
    }
  ],
  "counterexamples": [
    "1138新2总Search比原多3、生成也多，局部替代不是总体节省的充分条件。",
    "另三支有独立Call可同样答对，联合取证不是保持结果必要条件。",
    "1023仍缺完整广告关系，291身份/学校其它叙述有不足，局部直接支持不能扩张为整题质量完美。",
    "同一Return只含题面条件或主题相关信息而未证明具体关系、或者未被采用，不能按多DocID归类。"
  ],
  "cost_relation": "单列被替代独立Call及其原位置，再复算全后续的生成/G一次/Prompt/Search/Actor。无源假设、提前错答与缺证不作为该机制正例。CHAR只保守生成区间，不给原生精确净省。",
  "relation_to_existing": "与P2_R1材料到行动可有先后联系，但本候选要求同时补多个需求并减少独立取证实例；与N004比较实例压缩不同，这是工具证据操作联合而非两次认知比较集中。不改六个既有试点定义。",
  "limits": "显式三题三Stage三支，各自其它三支作对照。均教师引导下且真实召回不可保证，不证明可稳定控制联合取证，不从这三支推广到全量比例。"
}
```

## N006_PREACCEPTED_IDENTITY_SUBMITTED_WITHOUT_NEW_CORROBORATION：身份已采用后，新增独立条件补强未再执行而沿既有判断提交

定义源：REGISTRY_CURRENT\V007_PREACCEPTED_IDENTITY_AND_DATE_SCOPE_CANDIDATES.json；SHA b7e7d0d98aac6e8eb1bbf0be0071fd8ca8f2cf58d3f61f3ad7059a47fb8b05f7

```json
{
  "registry_id": "N006_PREACCEPTED_IDENTITY_SUBMITTED_WITHOUT_NEW_CORROBORATION",
  "name": "身份已采用后，新增独立条件补强未再执行而沿既有判断提交",
  "prestate": "目标U之前，模型已从真实P材料明确采用具体身份/答案，并非只见到资料；仍有一项独立识别条件尚未得到直接支持。原U实际新增该条件直接证据，并在原后被使用，没有改变核心身份选择。",
  "definition": "删除后完整新路径依据P已采用身份直接组织提交，没有重查原局部条件，也没有等价新Return/关系推导替代该证据。必须同时核对先前采用、U真实新增、后续采用、新路径无该工作及正式答复，不能凭零Call或答对自动标记。",
  "chain": "核心身份已在P采用→U原本补另一个识别条件而不改身份→新路径把已有身份/所求名当足够答复依据→不再补独立条件直接提交→局部操作/往返减少，新增的直接支持也不再发生。",
  "function_relation": "这是独立证据补强与已有身份选择之间的关系，不是无新信息的重复确认；答案保持与证据完整性分开，不能直接称通用冗余。",
  "explicit_memberships": [
    {
      "case_id": "1095__rep1__S003__FIRST_SENTENCE",
      "local_id": "PREACCEPTED_IDENTITY_MAINTAINED_WITHOUT_DISTINCT_DOCUMENTARY_SUPPORT",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "uncertain": [],
      "excluded": [],
      "locus": "P已DuncanClarke接受，U真补纪录片，四新直接以采访/旧姓名提交无片名或新返回",
      "subtype": "特定纪录片关系不再补强"
    },
    {
      "case_id": "291__rep1__S003__FIRST_SENTENCE",
      "local_id": "PREACCEPTED_NAME_SUBMITTED_WITHOUT_INDEPENDENT_SCHOOL_CORROBORATION",
      "observed": [
        1,
        2
      ],
      "not_observed": [
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "locus": "P罕见护士事件及常用名已采用，U真补学校，新1/2直接Baha零Call，新3/4实际恢复学校",
      "subtype": "学校/哥哥身份条件不再补强"
    }
  ],
  "counterexamples": [
    "291新3/4同P/G仍真实补学校且同C，已有身份采用不决定必然省取证。",
    "1239S003已有物种身份，人口仍未证，四新全部真实恢复且费用不降，不纳此候选。",
    "原U两题确有P没有的新直接关系；不能以核心答项不变抹掉支持增加，也不能默认采访等于纪录片。",
    "1095新2还无据增学校年份，姓名C不能覆盖附述。"
  ],
  "cost_relation": "正支省掉原定向取证及其后Actor，Prompt/生成按真实切点记录，CHAR只区间。功能没有重建的观察和原题证据要求是否仍充分是两项判断，不从成本下降定义科学可省。",
  "relation_to_existing": "区别P2_R2已支持事实再查：本U真实取得新的独立关系；区别N004认知实例压缩：本新证据取证不恢复；区别N005联合返回：本无等价关系补偿，而非换入口同时得到。",
  "limits": "显式两题两Stage六支，已有身份接受的A子集观察，不宣称比例或预测因果。两G都引导盘点/所求名，不能分离教师对停止的补偿；既有其它独立支持能否足够识别与全条件证据覆盖由研究者分别审核。"
}
```

## N007_REPEATED_RETRIEVAL_USED_TO_ACCEPT_UNVERIFIED_IDENTITY：反复检索命中被用作接受未证身份的依据

定义源：REGISTRY_CURRENT\V009_NEW_RETRIEVAL_FREQUENCY_ACCEPTANCE_CANDIDATE.json；SHA c0a373429cb69f9154e29da33afa813733878e5193b04a71636ccdb26bfe5104

```json
{
  "registry_id": "N007_REPEATED_RETRIEVAL_USED_TO_ACCEPT_UNVERIFIED_IDENTITY",
  "name": "反复检索命中被用作接受未证身份的依据",
  "prestate": "已有具体弱候选；模型明确知道所需帖子关系、作品条件或其它身份桥梁仍缺/冲突，同一对象在真实查询中反复返回。",
  "definition": "原文明确用出现频繁/一致命中等作为候选最可能或可答的理由，并在缺少对应身份/关键条件直接支持时正式选择该候选；需要缺口认知、频率接受理由、实际Final三个节点。候选主体可碰巧正确，不能只因Final错误或检索重复标此链。",
  "chain": "具体关系尚未闭合→相近检索多次返回同对象→返回频率被明确转为接受理由→未完成关系验证而正式称匹配并回答→取证结束/生成组织变化，主体正确性与支持充分性分开。",
  "inclusions": [
    "明确说博客频繁出现所以好候选并正式宣称对应帖子",
    "明确说虽多条件缺口但作品持续命中故最可能并正式补肯定属性"
  ],
  "exclusions": [
    "只出现多次Query/DocID，没有模型采用频率的原文",
    "仅mostlikely但理由不是检索频率",
    "承认多次命中仍拒确认或继续Call而没有正式提交",
    "新独立文档真正补齐关键关系后基于该关系接受",
    "纯知识猜测、与检索频率没有可追踪联系"
  ],
  "explicit_memberships": [
    {
      "case_id": "266__rep3__S003__FIRST_SENTENCE",
      "local_id": "266R3S3_C",
      "observed": [
        1
      ],
      "not_observed": [
        2,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N1_FREQUENCY_ACCEPT",
        "N14",
        "N15"
      ],
      "locus": "NEW1 R16 /rounds/10/reasoning_content→/content",
      "subtype": "博客出现频率转接受，所问具体帖与错误剧名/职业关联未闭"
    },
    {
      "case_id": "1078__rep2__S007__FIRST_SENTENCE",
      "local_id": "1078R2S7_B",
      "observed": [
        3
      ],
      "not_observed": [
        1,
        2,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N3_LAST_MISSING_LIST",
        "N3_ACCEPTS_RETRIEVAL_FREQUENCY",
        "N3_UNSUPPORTED_FINAL_UPGRADE",
        "N3_UNSUPPORTED_DESTRUCTION_FINAL"
      ],
      "locus": "NEW3 R17 /rounds/9/reasoning_content→/content",
      "subtype": "已知家世/毁作/修复窗缺口后，以作品持续命中接受并Formal无证补属性"
    }
  ],
  "source_review": "ROOT实际读取两份PEER当前裁定及完整关键源字段，核对精确引用：266 case_266_r3_s3.json SHA0695232dbe9275e613e4fd0dc630231a499152c25de740c56c5b34ffb77e91e6；1078 case_1078_rep2_s007.json SHA3b78b13d18bb96e8ec170b38fc8d1d4bfc1f51580dced869eeebc60e56befb1f。根复核未改PEER文件/分区/旧数据，精确范围和字段SHA沿CURRENT_VALIDATION。",
  "direct_quotes": [
    {
      "case_id": "266__rep3__S003__FIRST_SENTENCE",
      "source": "new1",
      "pointer": "/rounds/10/reasoning_content",
      "quote": "I notice that \"In Asian Spaces\" appears frequently in the search results as a blog that reviews Korean dramas. This blog seems to be a good candidate"
    },
    {
      "case_id": "1078__rep2__S007__FIRST_SENTENCE",
      "source": "new3",
      "pointer": "/rounds/9/reasoning_content",
      "quote": "Despite these gaps, based on the pattern of information and the consistent appearance of this artwork in my searches, it seems like this is the most likely answer."
    }
  ],
  "counterexamples": [
    {
      "case_id": "266__rep3__S003__FIRST_SENTENCE",
      "repeats": [
        4
      ],
      "evidence": [
        "N44",
        "N45"
      ],
      "reason": "同样说多次返回InAsianSpaces，却明确不能确认所问帖子，Formal求更多资料；有频率认知不等确定接受。第三支C仅首选但未明确频率理由，不自动同链。"
    },
    {
      "case_id": "1078__rep2__S007__FIRST_SENTENCE",
      "repeats": [
        1
      ],
      "evidence": [
        "N1_MOST_LIKELY_BUT_CONTINUES",
        "N1_LAST_REAL_CALL"
      ],
      "reason": "说最可能但继续实际查至N；没有正式提交。不能把接受倾向作为行为终止。"
    },
    {
      "case_id": "1078__rep2__S008__FIRST_SENTENCE",
      "repeats": [
        1,
        2
      ],
      "evidence_source": "PEER017当前裁定/提案",
      "reason": "仍以最可能候选核查到N，是待对应核读反例索引，不在本版本新增正成员或自动统计相同频率理由。"
    }
  ],
  "correctness_and_cost": "两正例核心一C一W，故此链解释接受依据/支持差距而不预测必错。266new1真实切点含G生成净−1377、Search−3、Actor−2、Prompt−109245；1078new3生成净−492但Search/Actor同、Prompt+2644。不能把全部成本差归频率理由，尤其1078并无真实交互减少；数据见CURRENT_COSTS对应repeat。独立差值不可相加。",
  "relations": "可为P1_K3固定弱对象持续补证的后继关闭方式；区别N001名称属性迁移和N003制造额外核验任务，本候选改变的是接受/提交依据而非一定派更多Query。也区别单纯P2_R2重复已采用真事实；这里需要身份/关键关系尚未有证。",
  "limits": "只将当前两个明确链注册，四次续跑/同题邻Stage不冒充跨题数。不是每次多次命中都不合理，也不证明重复检索导致错误或原U因果必要；候选可能正确、G/采样/预算仍在。旧已完成开放链需在最终综合时按新定义实际回查，不关键词自动补标签；尚未核读的其它相关记录不计支持。"
}
```

## N008_PARTIAL_MATCH_PROMOTED_TO_SUFFICIENT_IDENTITY_CRITERIA：部分匹配条件被升为足够识别身份的标准

定义源：REGISTRY_CURRENT\V011_PARTIAL_IDENTITY_ACCEPTANCE_AND_EXPLICIT_ADDITIONS.json；SHA b78401b6498baf92e97cd601a201b7ca527579f0360528f3fc3b34a9200ff6e4

```json
{
  "registry_id": "N008_PARTIAL_MATCH_PROMOTED_TO_SUFFICIENT_IDENTITY_CRITERIA",
  "name": "部分匹配条件被升为足够识别身份的标准",
  "prestate": "只有局部主题/时期/家族产品等匹配支持一个待验证对象，具体用于区分身份的其它题面条件仍被明确承认为未证或冲突；尚无独立足够证据确认所问对象。",
  "definition": "模型明确把局部已匹配条件称为core、primary、most或closest等足够选择依据，未用新材料消解其它关键身份条件，仍正式选择同对象。必须同时核缺口认知、实际选择依据/条件优先改变、正式Final；不能只凭缺证+Final或错误结果标注。",
  "chain": "具体身份未充分确认→真实取证/比较没闭区别条件→已匹配的局部特征被升为足够作答条件→不再让剩余身份条件阻止正式选择→未完成核验较早结束/解释组织，正确性与成本各自记录。",
  "inclusions": [
    "作者三履历未证而以书主题/日期primary/core正式选书",
    "公司年龄/并购/面积未知或产品日期冲突仍以sons/Devil局部匹配closest/most正式公司名"
  ],
  "exclusions": [
    "已有独立直接证据确认所问答案，只对辅助关系保持不确定，不见部分身份条件升格的原文",
    "仅提出候选等待核验，没有Formal选择",
    "新Return实际补齐关键区别条件后接受",
    "只有错误答案没有可见判断过程",
    "仅多次命中却没明确部分条件优先理由，另按N007或保歧义审"
  ],
  "explicit_memberships": [
    {
      "case_id": "353__rep1__S003__FIRST_SENTENCE",
      "local_id": "THEME_DATE_MATCH_PROMOTED_TO_SUFFICIENT_ANSWER_DESPITE_BIO_GAPS",
      "observed": [
        1,
        2,
        4
      ],
      "not_observed": [
        3
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N1_UNVERIFIED_CRITERIA_REMAIN",
        "N13",
        "N14",
        "N23",
        "N2_CORE_INSTEAD_OF_FULL_IDENTITY",
        "N42",
        "N4_PRIMARY_INSTEAD_OF_FULL_IDENTITY",
        "N43"
      ],
      "locus": "NEW1/2/4 R10完整Reasoning→Formal W",
      "subtype": "书主题/日期替代未证作者身份"
    },
    {
      "case_id": "353__rep1__S006__FIRST_SENTENCE",
      "local_id": "PARTIAL_BOOK_THEME_DATE_ACCEPTED_WITH_AUTHOR_REQUIREMENTS_OPEN",
      "observed": [
        1,
        2,
        4
      ],
      "not_observed": [
        3
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N12",
        "N13",
        "N14",
        "N22",
        "N23",
        "N43",
        "N44"
      ],
      "locus": "NEW1R15、新2R11、新4R12完整末推理/Final",
      "subtype": "原具体履历核查四支全恢复，三支仍部分条件接受；新1实质多候选比较也在"
    },
    {
      "case_id": "427__rep1__S003__FIRST_SENTENCE",
      "local_id": "PARTIAL_COMPANY_MATCH_FORMALIZED_WHILE_REQUIRED_ATTRIBUTES_OPEN",
      "observed": [
        1,
        2,
        4
      ],
      "not_observed": [
        3
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N1_GAPS_BEFORE_FREQUENCY_ACCEPT",
        "N12",
        "N1_UNSUPPORTED_SITE_ASSERTION",
        "N23",
        "N2_FINAL_UNRESOLVED_DATE",
        "N2_FORMAL_SELECTION",
        "N42",
        "N4_LAST_MISSING_LIST",
        "N4_FINAL_ALL_CRITERIA"
      ],
      "locus": "NEW1R14、新2R17、新4R13末Reasoning→Formal W",
      "subtype": "公司后代/产品局部匹配代替缺并购/面积/年龄等身份要求"
    }
  ],
  "source_review": "ROOT实际读353两个不同切点的六类/真实Call/关键完整末字段，427三Formal及日期冲突字段，不根据旧摘要标签或W自动填；逐案精确证据与源SHA见CURRENT_VALIDATION对应文件。353两Stage同原轨迹不计为两题。",
  "counterexamples": [
    {
      "case_id": "353__rep1__S003__FIRST_SENTENCE",
      "repeats": [
        3
      ],
      "reason": "相同候选/缺口且广搜恢复，但不正式按部分条件接受，继续真查到N。"
    },
    {
      "case_id": "353__rep1__S006__FIRST_SENTENCE",
      "repeats": [
        3
      ],
      "reason": "同类缺证与真实补属性恢复，仍N，无Formal不能把中间mostlikely当正式选择。"
    },
    {
      "case_id": "427__rep1__S003__FIRST_SENTENCE",
      "repeats": [
        3
      ],
      "reason": "还真泛查后回Underwood但不Formal，故未完成接受链。"
    },
    {
      "case_id": "191__rep3__S003__TERMINAL_DROP_NO_ANCHOR",
      "reason": "已有较强独立主体证据，节目辅助关系仍弱；有缺口+Final不自动并入部分身份标准候选。"
    }
  ],
  "cost_and_quality": "本明确成员均W，原N→W不称改善。减少通常在未完成后继核验，但353S006new1真实多候选比较使生成反增而Search下降；427new2更少Search但生成增加，不能用机制名字预测所有成本维度。CHAR两个353Stage仅保守原生Token区间，不累加独立差值。",
  "relations": "与N007可在427new1重叠：N007是把反复命中当支持，N008是部分身份条件被当足以接受。两者不能互相自动推断。可接P1_K3固定对象补证之后形成一种退出，但不把所有有限接受都并此。与明确冲突后仍重新接受的开放链有交集，前者有未证也可成立，后者需要确切冲突原文。",
  "limits": "当前只有两不同题、三个Stage、两个原轨迹的明确成员，数值由索引集合复算。不是所有部分信息下作答都错，不声称唯一因果/冗余率；G/采样/语料返回/预算继续保留。较强主答案支持但辅助缺口未闭的案例须另审，不能通过放宽定义提高覆盖率。"
}
```

## N009_PREACCEPTED_TARGET_RELATION_REUSED_WITHOUT_EXTERNAL_RECONFIRMATION：所求关系已获证且已采用，后续不重取相同关系也可延续原判断

定义源：REGISTRY_CURRENT\V023_ROOT030_ADDITIONS_AND_PREACCEPTED_RECHECK_CANDIDATE.json；SHA 0599b11623e0e64c50f8dea961329f3170ade33699674829049ce861ac6be1f4

```json
{
  "registry_id": "N009_PREACCEPTED_TARGET_RELATION_REUSED_WITHOUT_EXTERNAL_RECONFIRMATION",
  "name": "所求关系已获证且已采用，后续不重取相同关系也可延续原判断",
  "prestate": "P同时保留目标关系的直接支持和模型实际提取/采用；目标Stage不是首次把材料用于该关系，也不是补另一个尚未直接支持的独立识别条件。需要证明已采用，不能只证明文档出现。",
  "definition": "原目标再次外部取得或佐证同一已被采用的题目所需关系，没有观察到该次结果改变识别条件、候选或回答决定。删除后某些续跑没有等价重新取证/新增替代证据，仍以P原支持和判断组织回答。实际过程是已完成的事实到判断转换在P中延续，使本次再次获取可以不发生；是否减少费用和是否完整质量保持分别从账本和产物核，不能由标签定义为成功。",
  "chain": "P目标事实直接获证并实际采用→原再确认同一关系且无新识别决定→删后不再取得等价或替代Return→旧证据/判断直接用于答复→可减少该次工具往返及后继组织。认知比较或Final解释仍可重现，不能把外部重取未发生说成全部功能消失。",
  "inclusions": [
    "原同书目完整片段再次返回且关系在P已采用",
    "当前年龄已有多源及完整接受，重查仍返回旧支持",
    "年窗在P已直接支持并接受，再添官方或日级佐证未改变题目所需身份/范围决定"
  ],
  "exclusions": [
    "只有返回可见，尚未被采用或产生行动/回答判断",
    "原U首次取得另一个尚未获证的独立识别条件",
    "新路径重新真查目标或花成本取得独立替代支持，不能作为本链不重取正例",
    "目标只有失败尝试，P尚无目标关系直接支持，不能同此链混并",
    "只因Final名称相同或Token下降推断P已支持",
    "G首次给出关键事实却当P早已知道"
  ],
  "function_relation": "区别P1_K2以保留身份重新获取缺失条件，N004保真实补证但合并认知比较，N005新返回联合补多个缺口，N006原首次补独立条件而新未重建。P2_R2描述实际再确认发生，此候选描述某些续跑该外部再确认没有再发生，是条件对照而非强行互斥类别。",
  "explicit_memberships": [
    {
      "case_id": "353__rep2__S004__FIRST_SENTENCE",
      "local_id": "ADOPTED_BOOK_RELATION_PRESERVED_WITHOUT_RETRIEVING_IDENTICAL_SUPPORT_AGAIN",
      "observed": [
        1,
        3,
        4
      ],
      "not_observed": [
        2
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "P_BOOK_ALREADY_ADOPTED",
        "P_BOOK_EXISTING_FULL_SNIPPET",
        "U_SAME_BOOK_FULL_SNIPPET",
        "N11",
        "N12",
        "N21",
        "N22",
        "N23",
        "N31",
        "N32",
        "N41",
        "N42"
      ],
      "locus": "P26789/94079已经采用，原E7重返与E5字节相同26789，新1/3/4零Call沿P直接Formal",
      "subtype": "相同书目支持再次获取被取消；G书名内部截句异常必须保留"
    },
    {
      "case_id": "270__rep3__S007__FIRST_SENTENCE",
      "local_id": "PREVIOUSLY_SUPPORTED_AGE_AND_ACCEPTANCE_PRESERVED_WITHOUT_REAL_RECHECK",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "O1",
        "O2",
        "U_TRUE_AGE_DOC",
        "N11",
        "N12",
        "O4",
        "N21",
        "N22",
        "N31",
        "N32",
        "N41",
        "N42"
      ],
      "locus": "P真实年龄47、多源采用和当前完整接受保留，U再查同年龄，新四无Call沿P答47",
      "subtype": "当前接受已完成，不再外部复查已知数值；GPerfect有收束补偿"
    },
    {
      "case_id": "299__rep1__S004__TERMINAL_DROP_NO_ANCHOR",
      "local_id": "PREACCEPTED_BUILDING_YEAR_RANGES_SUBMITTED_WITHOUT_NEW_OFFICIAL_CORROBORATION",
      "observed": [
        1,
        2,
        3,
        4
      ],
      "not_observed": [],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "P_READY_ACCEPTANCE",
        "P_DIRECT_YEAR_DOCUMENT",
        "U_OFFICIAL_CORROBORATION",
        "N1_SHORT_CONFIRMATION",
        "N1_DIRECT_FINAL",
        "N2_DIRECT_FINAL",
        "N3_DIRECT_FINAL",
        "N3_DETAIL_ERROR",
        "N4_COGNITIVE_RECHECK",
        "N4_DIRECT_FINAL"
      ],
      "locus": "P已全条件接受且95218直接2017/2020，U添官方/精确日，新四G0零Call沿P同建筑",
      "subtype": "同已闭条件增加来源独立性与日级精度未重建，不能写U没有任何新信息"
    }
  ],
  "counterexamples": [
    "353新2同P仍实际重查失败、追加作者查询才回用P，生成/工具/输入均增：条件存在不保证自然取消。",
    "本批291学校和299r3S3业主日期在P未证，四支均真查后采用，不能按已有名字都纳N009。",
    "261r4S9数值原新都未获直接支持，前两取消失败Query仍C不等本链目标关系已有证据。",
    "1023r3S5机器年新附带恢复而原Howe未重建，属于部分证据替代，不是P已闭该制造史条件。",
    "299r1新3尾句混开工/完工，核心C不代表所有说明质量保持。"
  ],
  "limits": "目前三不同题显式成员，都是所筛A案例，不能估计全量冗余率或必要性。353提取异常G、270肯定G、299G0分开；当前可支持有条件过程解释，不能证明纯删除因果。299官方来源/精确日真实新增且可能提升可靠性，本候选只判断题面名/年窗与接受状态无新增决定，不能把可靠性价值归零。共享未证辅助条件/新Final附述错误分别保留，机制出现不等严格质量无损可省。不能从成本/正确性选正例倒推定义成立，必须同时验P直接支持+实际采用、U目标同关系、新无真实重取三个节点。"
}
```

## N010_UNRESOLVED_GAP_REACTIVATES_UNEXECUTED_QUERY_PLANS_WITHOUT_STATE_UPDATE：未闭缺口反复触发未执行查询计划，旧判断反复重述但没有真实反馈更新

定义源：REGISTRY_CURRENT\V025_UNEXECUTED_QUERY_PLAN_CYCLE_CANDIDATE.json；SHA 6d533e1f47bef1313ae86c28bc676aaf5fc56b3679a085b1a56e97b52be2b527

```json
{
  "registry_id": "N010_UNRESOLVED_GAP_REACTIVATES_UNEXECUTED_QUERY_PLANS_WITHOUT_STATE_UPDATE",
  "name": "未闭缺口反复触发未执行查询计划，旧判断反复重述但没有真实反馈更新",
  "prestate": "模型明确指出某个身份/关系缺口，并在同一实际Assistant生成中多次重述已有候选或已知属性、提出要搜索；不能只依据终态N、长文本、相同词语或无工具自动判定。核心所问属性可已经知道，也可仍未形成可靠候选，须分别记录。",
  "definition": "真实原文反复出现未闭条件→下一查询意向/重新选择计划→没有实际Call及新Return→继续据原有信息描述不足或失败→再提出相同/近似工作计划的循环；没有可观察的新证据/行动状态推进，单次生成持续消耗预算且本轮没有提交Final。必须同时核对全部真实Call账本、完整消息和实际停止原因。没有执行的计划不算已执行取证，也不能把模型自述搜索失败当本分支已新得到返回。",
  "chain": "特定缺口保持未解→缺口持续触发新的查询意向而非可执行工具事件→没有真实反馈改变既有候选/方案→同一消息重述问题和候选后再次启动计划→消耗主要落在生成文本，未完成实际取证或提交。此链只描述已观察的维持过程，不能声称已确定为何没有发出工具调用。",
  "inclusions": [
    "明确多次计划/重估而真实工具表没有相应Call，旧候选/缺口反复回到原状态",
    "同一消息真实长度终止、没有Formal，不能将中间正确数字当提交",
    "有充分的完整原文或精确重复块核验，不能从少量关键词推断整个长消息"
  ],
  "exclusions": [
    "普通一次未执行计划后正常Formal",
    "真实多次Call及返回的固定缺口核验，属于其它行动实例分析",
    "长推理有实际新候选/推导推进且最后尚未完成，不能只看长度",
    "Call格式错误或服务错误导致工具未执行但原文没有相同计划循环",
    "模型已经真实提交Final，只是Final前有短重复陈述"
  ],
  "function_relation": "区别P1_K3真实返回后又重新实际查询，和P2_R3正确核心下真实继续核验；本候选是计划未成为行动、也未收束提交。区别N002无源来源叙述直接当事实Formal，本候选没有正式答复，且核心问题在没有新事件的反复重新计划。",
  "explicit_memberships": [
    {
      "case_id": "980__rep4__S001__FIRST_SENTENCE",
      "local_id": "REPEATED_REPLANNING_WITHOUT_TOOL_DISPATCH_OR_FINAL",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "N21",
        "N22",
        "N23",
        "N13",
        "N14",
        "N35",
        "N43",
        "N44"
      ],
      "locus": "新2R12真实10000Token/38884字符，前已有11Search但本轮0Call，无Final；两种完整块实读、中间重复精确核验",
      "subtype": "正确关系尚未获取，反复改变搜索解释与熟悉影片枚举，但新计划不发Call；原W→N不是正确性改善"
    },
    {
      "case_id": "319__rep1__S009__FIRST_SENTENCE",
      "local_id": "UNRESOLVED_IDENTITY_GAP_REPEATEDLY_REACTIVATES_UNEXECUTED_PLANS",
      "observed": [
        2
      ],
      "not_observed": [
        1,
        3,
        4
      ],
      "uncertain": [],
      "excluded": [],
      "evidence": [
        "O_P_TWO_BEFORE_CUT",
        "N2_PLANS_NOT_CALLS",
        "N2_FAILURE_STORY_WITHOUT_NEW_RETURN",
        "N2_NUMBER_AND_GAP_REPEAT",
        "N1_TRUE_FINAL",
        "N3_PLANNING_THEN_ACCEPTANCE",
        "N3_TRUE_FINAL",
        "N4_TRUE_FINAL_WITH_LIMIT"
      ],
      "locus": "新2R10单轮10000Token，全支0Call，无Formal；已知人数2与餐馆背景未配反复交替",
      "subtype": "核心所问数字已P接受且G重复确认，仍被背景缺口带回计划；不能用不知道数字解释无Final"
    }
  ],
  "counterexamples": [
    "319同Stage新3也提出未执行核验却能收束Formal，单次搜索意向或未解背景不是本循环充分条件。",
    "319新1/4同P/G与背景缺口，直接有限数值提交；980另三实际继续工具并有Formal，结果C或W均可能。",
    "353MSc精确年、1046特定bribery反复核验有真实Call/Return；即便无新事实也不是本无执行计划链。",
    "根部980与晚段319前态/原Stage功能不同，不能把共同失败过程反推两种U具同一因果功能。"
  ],
  "cost_relation": "980该支新生成13664+G18相对原后缀4468增加9214，末轮10000生成没有新Call；319该支10000+G18相对原1258增加8760且工具反少一次。分别记录，不累加独立反事实节省，也不从低工具/Prompt成本称有效省。",
  "full_read_audits": [
    "CURRENT_READ_AUDITS/980__rep4__S001__FIRST_SENTENCE__new2_exact_paragraph_coverage.json",
    "CURRENT_READ_AUDITS/319__rep1__S009__FIRST_SENTENCE__new2_exact_paragraph_coverage.json"
  ],
  "read_audit_detail": "两消息全部去重段落由模型实际逐段阅读：980共212段/11种、38884字符；319共217段/15种、39758字符。程序保存精确段落、原顺序、字符范围及SHA并逐字还原，不生成语义结论。不是只抽头尾外推整个长轮。",
  "limits": "目前显式两Stage/两不同题/两原轨迹各一续跑，均真实长度终止。候选解释未闭状态怎样在无反馈时反复维持计划及消耗位置，不解释工具协议为什么未产生/隐藏决策原因，不宣称足以预测失败或已完成因果证明。G/采样/历史差异保留，等待研究者裁定与后续其它案例反证。"
}
```

以上为本次统计的候选定义版本快照，非研究者正式冻结机制。候选ID保持独立，开放链完整保存。
