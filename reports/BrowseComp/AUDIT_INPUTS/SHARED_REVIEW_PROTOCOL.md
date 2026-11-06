# 904组深度验收共享执行口径

## 范围与写入责任

904组、3616条续跑均保留。SCOPE_904.csv为只读身份快照；ASSIGNMENTS.csv按整题唯一分配ROOT/PEER，禁止两边同时改同一案例。所有新裁定放ADJUDICATIONS/<case_id>.json，源数据、旧报告只读。

实验分组`ab_group`与深度等级`depth_grade`不同。原冻结分组保留，现条件按C/W/N变化数：原C且0/1变为A；3/4变为B。853__rep2/S008恰好2变，904覆盖中保留，AB统计中单列OUTSIDE_CURRENT_AB，不改旧分组。

## 审阅与分级

读取旧判定只是定位线索。亲自检查P/U/Z、G和四条新路径，引用实际Reasoning/Call/Return/Final。已充分阅读的材料可复用，仍须说明来源和证据是否足以支持本轮结论。不能用文件字段完整、引用机械PASS、预置标签或Python关键词替代深度判断。

- 深度A：具体说明U改变/维持什么判断，该判断怎样进入实际行动，四次结果与成本的差异有可核对的中间链。可以保留因果混杂，但不能用“不证明因果”掩盖缺失的行为解释。
- 深度B：实际行为差异可还原，但从U到关键决策/结果的作用链仍有缺口；明确缺在哪里。
- 深度C：仍主要是操作、重建、结果和费用描述，尚无具体判断—行动解释。
- 深度D：关键原始证据缺失、错关联或无法可靠还原。没有读过的记录是PENDING，不可批量填D。

## 统一记录（每例JSON）

必须包含：case_id、reviewer(ROOT/PEER)、review_status(REVIEWED)、ab_group、depth_grade、depth_grade_reason、source_bundle、source_bundle_sha256、historical_decision_path；pre_state、u_work、u_state_change、original_followthrough、guidance_audit；四条rollouts；mechanism_links；counterexamples_and_limits；unresolved；evidence。

另明确保存source_review_sufficiency（旧审阅哪些可复用、哪些不足）、depth_reason（可与depth_grade_reason相同但不能空）、locus（U/ORIGINAL_Z/NEW及具体Round，放每条mechanism_link中）、mechanism_occurrence_by_repeat（每条链的四态repeat分区及证据）。这些是作用位置/审阅充分性记录，不是自动语义分类器。

pre_state说明证据可见/提取/采用及真实缺口；文本可用中文字符串或具名对象，不用统一模板。rollouts每条：repeat、first_decision_divergence、first_actual_call_divergence、evidence_and_constraint_update、reconstruction、state(C/W/N)、cost_location、evidence_ids。成本具体数值由ROOT从真实账本和usage复算，不让两边手写汇总数字。

evidence每项：id、side(original/new1..new4)、pointer（指向完整包内对应原路径或branches/N下的字段，相对该路径根）、quote（精确子串）。可复用旧证据引用，但要实际检查其语义作用。不可用G本身作自主行为证据。引用ID需在本案唯一。

mechanism_links每项：local_chain_id、本例完整解释链（precondition→stage_work→judgment_change→action_change→outcome_and_cost）、observed_repeats、not_observed_repeats、uncertain_repeats、excluded_repeats及原因、evidence_by_repeat、candidate_registry_id（无合适者为空）、limits。四种repeat集合不重叠、合计1..4；无完整链可留空并说明，不强归类。

每条“支持”需区分：原U自身做了该动作；机制只在原Z/新路径出现；作用链是否能关联U；是否仅解释一部分路径。不能把新路径存在机制当成已证明被删U具有独特作用。

## 机制共享

先保留本例原始动作链，不强贴M1/M2/M3。提出跨题候选时放REGISTRY_PROPOSALS/<reviewer>_<id>.json，给定义、适用前提、区分性反例及支持ID。ROOT协调合并登记，PEER可直接反驳。最终统一图谱由审核后的记录生成，不能直接改旧L1—L4名称。支持/反例均单列Stage、原轨迹、题目、续跑数，跨题才算跨题支持，多个Stage/四次重复不冒充多个题目。

FIRST_SENTENCE与TERMINAL分别统计。单Stage无引导重启标RESTART_NOT_PROVEN_STAGE_SKIP，不能用它证明局部功能可删。

## 成本与证据

生成、G、Prompt、Search/Open、Actor分别记账。G对生成比较只加一次；Prompt实际usage已含G，不能再额外加。非NATIVE_TOKEN_EXACT不报伪精确原生生成差。无Final不从Reasoning补答，C/W/N不抹去条件证据不足。末次Return没有后继真实Actor请求时不能记成已采用。

ROOT执行唯一全量源SHA、引用、配对与账本核验，结果放MECHANICAL；该PASS不授予深度等级。每完成一批保存本案JSON，不等待几百例后统一生成语义标签。各自PROGRESS_ROOT/PEER.json只从已保存的正式裁定计数；工作读到一半可另存笔记，不算完成。

## 当前目标与停止

不运行GPU、Actor、Retriever、Judge；不更改旧数据/评价/Stage。最终以目标文件的全部9份报告及ZIP实际解压SHA验证为完成标准；中途不得把局部完成说成904完成，也不以目标文件已读作为整个研究工作完成。
