# 904全量任务：两轮试点后的统一执行协议

本文件只规范分析记录，不修改V1.3.2、原始轨迹、实验条件、答案评价或Pattern定义。

## 唯一覆盖与责任

- 根目录沿用 mechanism_atlas904_20261031。旧文件只读。
- CURRENT_SCOPE_904.csv 是本次唯一904身份、分组、原始来源、写入责任表。
- CURRENT_ADJUDICATIONS/<case_id>.json 保存本次正式逐案记录。每个case只有一个owner；原ASSIGNMENTS整题归属不变，扣除两轮已完成20例。不要排除这些题目的其它Stage。
- 两轮真源为 function_mechanism_new10_20261031 与 second10_deep_mechanism_20261031；不是更早的 mechanism_pilot10。
- 既有MECHANICAL的904 PASS只复用机械证据，不算深度分析904完成。
- 853__rep2/S008保留904覆盖，现四态2变为OUTSIDE_CURRENT_AB，当前AB统计单列，原冻结分组不改。
- ROOT协调全局台账、机制版本和最终交付；PEER只写自己的case和BATCH_REVIEW_RECORDS/PEER_NNN，不另建总体图谱。

## 每案最少记录

沿用通过试点的JSON字段：case_id、function、prestate(returned/extracted/adopted/action)、stage_effect、four(四次)、guidance_review、local_chain、attribution_limit、evidence_ids。允许一案多功能，不强制任何旧机制ID。

本次新增元信息：reviewer、review_status=REVIEWED、source_review_sufficiency、unresolved(具体问题和依据，允许空但不可模板)、mechanism_links。每条four还须清楚给出first_decision_divergence与first_actual_call_divergence，可用已有judgment/action配合明确位置，但不能只写多数结果。

每条four保留：repeat、state、judgment、action、restoration、cost_location、quality、evidence。具体数字引用已有真实账本并由统计程序复算，不手写总体计数。

evidence_ids可引用既有factual_record的证据ID；有新必要引文用extra_evidence[{id,source(original/new1..4),pointer,quote}]，按真实字段验证。

mechanism_links每项由Codex实际写：local_id、description、locus(U/ORIGINAL_Z/NEW及Round)、stage_attribution(可确定与不可确定)、observed_repeats、not_observed_repeats、uncertain_repeats、excluded_repeats、evidence_by_repeat、candidate_registry_id(可空)、counterevidence。四repeat分区不能重叠，合为1..4。没有可靠链可留空，但必须写具体缺口；不能用Python填机制标签。

20份已通过试点的记录原样复用，不为形式字段重审；用import_receipt关联其已封存报告、逐案记录和本次覆盖。之前更早十例的深度材料可复用作事实或审阅依据，但不自动计入本次已验收20例。

## 每批10例

1. 保存BATCH_REVIEW_RECORDS/<OWNER_NNN>/01_CASES.csv；尽量不同题和A/B覆盖，不强制凑比例。完成不足一批的最终尾数保留真实数量。
2. 复用已有六类材料，完整原工作与四条路径逐项检查。已有材料充分无需盲目重读巨量原始Token；关键冲突/缺证才定向查源。
3. 每完成一案立即保存新语义JSON，不最后通过程序批量构造标签。
4. 完成本批后由Codex写BATCH_ANALYSIS.json/md：共性功能、同功能不同前态对照、机制支持/反例/新链、与已有机制关系及未确定项。
5. 批内数量由程序按显式成员统计Stage、不同题、原轨迹、续跑；不得用同题重复当跨题支持。
6. ROOT核读批结论、维护版本化REGISTRY_CURRENT，处理合并/收窄时检查受影响旧映射。PEER的机制建议存REGISTRY_PROPOSALS_CURRENT，不直接改全局定义。

## 证据与解释

- P中出现、提取、采用、用于真实行动必须分开。
- 具体主体错误、关系错误、无新增Call、未提交Final、真假缺口分别记录，不强归同一机制。
- 无Final不能从推理补答案；C/W/N沿用现已封存语义评价，证据充分性另审。
- G是否在P中已有、是否预给答案实体分别判断，不能把G当自主行为。
- FIRST_SENTENCE与TERMINAL分别统计。单Stage重启标RESTART_NOT_PROVEN_STAGE_SKIP，不作为局部省略的因果证据。
- 原生精确与CHAR重编码分开，G计一次，Prompt/生成/Search/Open/Actor分项；独立分支净差不相加。
- 只解释可见的判断和行动，不猜隐藏信心或停止阈值。UNKNOWN要写缺什么依据，不能用通用免责声明替代分析。

## 断点与完成

当前状态只从实际已保存、机械引用通过并完成批内比较的记录计算。REVIEWED不等于研究者金标准。阶段成果保存后继续下一批，不因阶段结束提前宣称904完成。

最终必须具备用户要求的全部图谱、映射、正确性/成本对照、未解案例与总综合，以及完整ZIP实际解压SHA检查。只读研究数据，不启动GPU或新实验。

## 行政分工交接001（不改语义规则或研究数据）

PEER原分工452组完成、ROOT尚余104组时，为继续两人并行，将其中52个尚无当前裁定、尚未进入冻结批次的身份交给PEER，清单固定在CURRENT_OWNER_HANDOFF_001.json。CURRENT_SCOPE_904.csv及原ASSIGNMENTS.csv原样保留；只由current_ownership.py核对原scope SHA后应用明确from/to责任覆盖。原有已读、已写和全部20试点不交接。

此为此前不变owner约束的有记录行政例外，不改变case范围、A/B、事实卡、源SHA、Stage、定义、原新评价和成本，也不改变引用/语义检查标准。current_case_check和current_progress仅按交接后的实际责任识别新PEER记录；所有历史记录责任不变。实际模型审阅人仍必须填写真实ROOT/PEER，不冒名、不代填标签。
