# SciCode A/B Stage 共性与机制审阅：固定流程

## 对象、分工和禁止改动

本轮只分析 SciCode100_STAGE_DELETION_N4_20261103 最新官方测试筛出的 A/B，当前 A133、B116，共249组。不是旧BrowseComp904组，不重新切分或生成。原对话01a1554f负责A，协作对话01a197fc负责B；全部逐组记录封存后共同比较功能相近的A/B。A定义为原C、四次已评分且0或1次C/W/N状态变化；B定义为四次已评分且3或4次状态变化。N→W属于状态变化但不是答对或质量改善。正式测试状态与语义解释分列。

输出根：`/file_storage01/home/weiyu/lanyi/projects/新实验/reports/SciCode100_STAGE_DELETION_N4_20261103/AB_FUNCTION_MECHANISM_ANALYSIS_20261104`。

## 每组必须由Codex阅读并保存

1. 原题、完整P、完整U（字段区间和工具）、原后续。
2. 四次完整新后续及真实工具调用/返回、提交代码与真实终态。
3. 完整P与G对照；P以封存INPUT_AUDIT.original_request/state和实际首请求为准。trajectory.prefix中可变列表的运行后快照不可据此当作初始输入。
4. 先写逐组实际工作和差异，再跨组归纳；不能套旧M1/M2/M3或按关键词生成机制。
5. 证据状态区分：材料可见、已提取、已采用、已改变行动。编程中还须区分推理草稿、write_code保存、run_python实际执行和submit_code正式提交；自然语言“代码已写好”不等于工具状态中已存在代码。
6. 每条续跑均写完整作用链：前置信息状态→U具体工作→判断变化→后续真实行动→正确性与成本。工作重建后仍要追问重建出了什么判断、如何采用。
7. 关键结论给源路径、source_side、JSON Pointer、字符[start,end)、exact_quote、Call ID（如有）和source SHA；不以整份证据卡代替具体原文。
8. 不能解释时明确写未知，不为每组强制归类。G补偿/方向提示/未来事实、采样、工具差异和预算均作为替代解释审核。终端无引导单列；单Stage重启不当作已经证明跳过功能。

## 每组JSON最小字段（语义字段手写，不由程序填默认结论）

- `case_id`, `category`, `trajectory_id`, `stage_id`, `main_problem_id`（官方主问题前缀），`official_subproblem_id`, `intervention`。
- `review_status`: IN_PROGRESS / COMPLETE。只有读完原始相关完整上下文与四条续跑、并完成下述字段，才能COMPLETE。
- `sources`: 文件路径、SHA和阅读范围；漏读片段须记录，不能COMPLETE。
- `original`: `pre_state`、`U_goal`、`U_operations`、`U_product`、`judgment_before_after`、`original_suffix_use`、`evidence`。
- `guide_audit`: G全文、P中对应信息、是否新增事实/行动方向/确定性、原文依据及不确定性。
- `rollouts`: 四个独立对象，各有 `branch_id`、`official_state`、`first_material_divergence`、`work_reconstruction`（目标/操作/产物逐项对照）、`judgment_change`、`action_chain`、`result_explanation`、`cost_localization`、`evidence`、`counterevidence`、`unknowns`。
- `cross_rollout_comparison`: 相同链出现在哪几次、路径相同但结果不同/结果相同但路径不同、是否真解释状态变化及反例。
- `stage_function`: 中性实际工作；`candidate_mechanism_chain`: 有证据的候选链或暂不能归纳；`limits`。

`evidence`每条包括source_side(ORIGINAL/NEW/P/G)、path、json_pointer、start、end、exact_quote、source_sha256、call_id（如适用）。工具对象整体可用pointer与其对应完整参数/返回，不从代码或Return中切断伪造新事件。

## 成本口径

原U切点之后的后缀与新后续比较；旧整条成本不能充当原后缀。生成、Prompt、工具(write/run/submit分别)、Actor分列。G与重放P单列并核对是否已计入；所有本批切点为RECONSTRUCTED_CHAR_EXACT，不能宣称原生token精确节省。现有成本没有可信切点对齐时报告未取得，不把全部差值归因于U。原与新可能跨后续子问题，要声明目标子问题窗口和整个分支窗口，不混算。

## 归纳与统计

A/B分别统计每个共性支持的Stage、不同主问题、不同子问题/原轨迹和续跑数；同主问题多个子问题不能当独立主问题。一个Stage可支持多条候选链，不强制互斥，标明重复。支持/反例/无法归类均完整保留。机制须解释相似功能为何因前态不同产生不同作用；不得用终态多数票取代中间链。所有汇总数字由已封存的模型审阅记录确定性复算。

每完成一组就实际保存到MODEL_REVIEWS/A或B。只有全部249组审完才给全量机制结论；机械验证和Codex语义自审不能冒充研究者验收。
