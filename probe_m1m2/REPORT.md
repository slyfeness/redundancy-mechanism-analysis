# LedgerCredit M1/M2 小批量探查

**[已验证] 只读复用 190085 的 DeepSearch-World 4B 轨迹：冻结名单前 10 题，各 rep1/rep2，共 20 条；未采样、未调模型、未训练、未改训练代码。** 本文分三页组织；详细证据在链接文件。原数据位置见 [输入清单](input_integrity.json)，命令见 [commands.log](commands.log)。

## 1. 环境与配置

**[已验证] 用户已明确：LedgerCredit 以自有多轮生成器为主线，veRL 仅作备选，没有另一份 Agent Loop 仓库。** 190085 实际为 Qwen-Agent 原生记录器；当前训练链路为 `ledger-grpo/scripts/hf_pilot_train.py` → HF/FSDP 后端。本次按自有训练序列/掩码验收，不再以缺少 veRL 字段判失败。

[已验证] 策略为 `Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`，路径 `/file_storage01/home/weiyu/lanyi/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`，同目录 tokenizer；vLLM 0.19.1、torch 2.10.0、Transformers 5.5.1、tokenizers 0.22.2。四 TP1、T=1、top-p=1、top-k=0、上下文 65,536、每次生成上限 10,000、最多 20 次模型调用、guard 256。模型调用预算不等于工具调用数。[配置](run_config.json)；[源代码位置与哈希](source_audit.json)；[模板原文](chat_template.txt)。

## 2. 交互格式

**[已验证] 单轮为 reasoning + XML 工具调用，工具结果在下一轮 prompt 中；没有 summary 调度证据。** `search(query)` 返回最多 5 条 `{docid,caption,score}`；`open(docid,start=0)` 返回 `{docid,start,text,next_start}`，每段最多 8,000 字符。[定义](tool_schema.json)；[Search/Open 各两条原样返回](samples/tool_return_examples.json)。三组原样消息与原生 ID 导出见 [samples](samples/README.md)。

[已验证] `<think>/</think>` 为 **248068/248069**，`<tool_call>/</tool_call>` 为 **248058/248059**，返回标签为 **248066/248067**：均为独立 added token，但此 tokenizer 文件将它们标成 `special=false`。`<summary>` 为普通文本 **[27,1648,29]**，闭合为 **[510,1648,29]**。`im_start/im_end` 为 248045/248046；完整属性见 [token_protocol.json](token_protocol.json)。本批 summary、answer、plan 标签均为 0；出现的是 function/parameter 协议。`answer` 曾被当作不存在的工具调用，不是合法 Final 标签。

## 3. 模板、训练序列与 old logprob

**[已验证] 三轮合成工具对话保留全部历史 think/返回；追加真实 user 消息后，三个旧 think 全部不再渲染。** 依据模板 67–103 行和 [前后对照](samples/template_test.json)、[新 user 对照](samples/template_edge_tests.json)，不是模型推断。

[推断] **不是固定“整轨一条”，也不是固定“每轮一条”**：`hf_native.py:15–62` 按原生前缀完全一致合并成最大 span；前缀不一致另开 span，保留该轮完整 prompt。每个 span 是独立模型输入；横向拼接的 response_mask 只是信用分配坐标，不把不同 span 强拼成一条因果序列。

[推断] `hf_pilot_train.py:134–145` 在 `prompt_ids + completion_ids` 上调用后端，用 `len(prompt_ids)+action_offsets` 选择目标。`train_smoke.py:35–50` 用位置 p−1 的 hidden 预测原生 token p。采样 q 来自 vLLM 原始响应；本链路的 PPO old 是当前更新前 HF forward 的 **detach**（`hf_native.py:185–196`），不是重新分词后的概率，也不等同采样 q；q 用于 TIS。该实现依赖整批累计后只更新一次，不能外推到多 epoch。

[推断] veRL 备选桥要求外部已经给好 `[B,T] response_mask`，不负责采样或构造 native spans；需显式注册/加载插件。当前仓库训练入口检索只见 `hf_pilot_controller` 调 `hf_pilot_train`，没有启用该桥的调用；示例与 stub 测试不代表运行接入。旧参考源码记录保留，不再深入测试。

<div style="page-break-after: always;"></div>

## 4. Token 映射

**[已验证] 190085 保存了原生 token 和逐 token 采样 logprob，训练转换直接读取它们，不需要从文本重建动作。** `browsecomp_adapter.py:46–66` 与旧 `prepare_training.py:74–89` 均直接取原始 ID；记录器重套模板用于核验“下一轮输入”，不是替代此前生成 IDs。[历史独立核对](verification.json) 已核对 228 次请求、217 次工具关联。

| 190085 字段 | 保存情况 |
|---|---|
| messages、reasoning/content、工具参数/返回、raw_response | [已验证] 有 |
| `token_accounting.prompt_token_ids/completion_token_ids` | [已验证] 有，等于服务端原生 IDs |
| `raw_response.choices[0].logprobs.content` | [已验证] 有，逐生成 token 采样概率 |
| 整轨训练 mask、HF 更新前 old logprob | [已验证] 未持久化；190085 没有执行训练 |

[已验证] 自有链路 CPU 拼接/掩码复核结果见 [native_training](native_training/native_training_summary.json)；调用真实 `native_turn_layout` 和 `prepare_native_records`，并与冻结后端 `action_records(merge=True)` 逐 ID、位置、logprob 比对。**这是实际训练输入构造函数的离线验收，不是声称 190085 曾产生训练张量或完成参数更新。** 合成有效行掩码只测试接口，不充当奖励/训练资格。

[已验证] CPU 作业 190723：**20/20 原生输入与掩码核对通过，完整 Stage 唯一归属 17/20**；228 次调用合为 35 个最大 span，106,188 个 span 内观测/模板位置为 0。三个样本的原始 prompt IDs 与采样时模板核验 IDs 全部一致；生成文本 decode→encode 的独立诊断见 [roundtrip_diagnostic.json](native_training/roundtrip_diagnostic.json)，不用于构建训练输入。[逐轨迹检查](stage_mapping_check.csv) 将掩码正确性与 Stage 规则缺失分开。

[已验证] 3 条样本共 56 次生成，decode→encode 只有 **54/56** 逐 token 一致：rep1 第 14 轮 431→430 token；rep2 第 4 轮长度同为 154 但 ID 不同。均属于 `2062bbd3…` 题；完整 id/首个差异位置见上述 JSON。这证明“文本相同”不能替代原生动作身份；实际训练构造不采用重分词结果。

[已验证] 共 89,695 个生成 token，69,074 个可暂挂到单工具 Stage/Final；两条未完成生成占 20,000，另有并行共享部分 621 个，均未强行分配。新导出的 stage_ids 在实际 span 的零掩码位置标 -1；原样本中的下一轮 prompt 观测坐标另行保留。并行四个工具 Stage 的共享 think 数留空；完整轮级分类另存 [round_token_stats.csv](round_token_stats.csv)。

[已验证] 208 对相邻轮中 **15 对不是原生 token 严格追加**：8 对解码前缀仍一致，6 对发生空 think 的换行规范化，1 对非法工具正文在解析后丢失。不能把它们统称为遗忘。[逐处证据](samples/prefix_diagnostics.json)。

## 5. 结构统计

**[已验证] 217 个工具 Stage + 11 个 Final，平均 11.4 个/轨迹；另有 2 个未完成生成单元，不伪装成 Final。** 并行轮占 2/215=0.93%（4 个工具）；工具失败 1/217=0.46%；生成截断 2/20=10%；有 Final 11/20=55%；其余 7 条到 20 次调用上限。未见跨工具边界的未闭合 think；1 条生成的 think 未闭合，另 1 条存在额外 think 开头。无 summary。

[已验证] 下表为 [Stage CSV](stage_stats.csv) 的均值/中位数；空值不计入均值。context 计模型调用前原生 prompt；parallel 指同轮多调用，不证明执行时间重叠。完整数字及口径见 [汇总](structure_summary.json)。

| token 类别 | 均值 / 中位数 | 有效单元数 |
|---|---:|---:|
| think | 261.27 / 160.5 | 224（并行共享未分配） |
| summary | 0 / 0 | 224 |
| tool call | 33.56 / 33.5 | 228（含 Final 的零值） |
| observation（含返回标签） | 543.12 / 358 | 210 |
| Final 正文及结束协议 | 9.67 / 0 | 228（含非 Final 的零值） |

## 6. 数据集与原子条件

**[已验证] JSONL 原始规模：train 477,917、train_v1 235,478、test_v1 377；前两者不是互斥划分。** 存于 `/file_storage01/home/weiyu/lanyi/datasets/long-horizon-benchmarks-20261111/deepsearch-world`。三份均有 answers/entity_list/fuzzed_features，没有显式 constraints 或 gold evidence 字段。train/train_v1 分别有 11/7 条空题面或非法 features。[全文件字段统计](dataset_field_availability.json)；[SHA/规模](dataset_inventory.json)。

[已验证] `fuzzed_features` 是“原事实→改写描述”的 JSON 字符串，存在一条多个事实、关系和目标混合的情况；entity_list 是实体名单，不是已经验证的文档证据。各划分两条原样示例见 samples；已有 `deepsearch-world-pilot/score.py` 是本地 Judge 判分器，未找到随下载数据提供的官方评测脚本。[两条已有判分回执](samples/outcome_receipt_examples.json)。[推断] 三题拆解示范及歧义见 [atomic_condition_examples.json](samples/atomic_condition_examples.json)，不作为金标或固定 g 分母。

## 7. 可见层

**[已验证] 本批没有历史折叠/预算删历史，所有此前非空 reasoning 与工具返回均能在后续真实 prompt 中找到。** 本批最大上下文仅 18,576 token，不能外推到临近 65,536 的行为。仍附 [visibility.jsonl](visibility.jsonl) 逐 Stage 留证；并行调用共享同一前置状态。末轮 7 次返回没有下一轮 prompt 佐证，obs token 留空。非法工具正文变化见第 4 节，不等于删除正常工具返回。

[推断] `phase06_runtime.py:138–146` 先渲染并计数，若 prompt + 生成预算 + 256 超过窗口，停止而非删除历史；Search/Open 的返回长度限制属于工具接口，不能据此说模型一直看到文档全文。

<div style="page-break-after: always;"></div>

## 8. 可复用资产

**[推断] 原生 ID 捕获和工具绑定可以复用，旧生成轴不能直接当含观测间隙的训练 span 轴。** 下表为源码阅读结论，相关源哈希见 source_audit.json。

| 代码路径 | 可复用内容与边界 |
|---|---|
| `ledger-grpo/src/ledger_grpo/native_capture.py` | 捕获服务 ID/logprob；提供逐调用原生 IDs/logprob；mask 由训练 span 构造。 |
| `src/redundancy_judge/parse_stages.py` | 工具事件/原生生成轴；坐标是生成 token 串联，不含工具观测轴。 |
| `ledger-grpo/src/ledger_grpo/native_tool_coordinates.py` | 调用/返回绑定；其返回 offset 辅助函数会重新 tokenize，本次没有用于 T3。 |
| `ledger-grpo/src/ledger_grpo/event_deletion.py`、`event_continuation.py` | 删除/续跑事件绑定；并非新 Stage 的唯一归属策略。 |
| 旧 HF `src/native_spans.py` | 只有 exact native prefix 才合并，保留 action_offsets。 |
| `scripts/index_browsecomp.py:19–22` | TOKEN15 旧删除资产索引；边界口径不同，不能替代一工具一次 Stage。 |

[已验证] 当前模板及记录器没有独立 summary 折叠协议；未发现可直接复用的本任务 summary→可见性状态实现。

## 9. 待确认问题

**[已验证] 主线已确认，自有生成器，不再等待另一份 veRL 仓库。** 待确认：一轮多调用的共享思考归属；截断/无 Final 的生成 token 是否成为独立可训练 Stage；summary 是否为拟加入机制；原子条件的关系拆分、模糊限定词与金标证据审核口径。当前后端入口仍绑定历史基座路径，4B 正式训练部署及模型身份校验不在本次无模型探查中完成。

## 10. 对 M1/M2 设计的影响

**[推断] M1 应使用自有训练 span 坐标、原生 ID 与工具绑定，不重套模板回填优势。** think 开头通常在 prompt 中，正文/结束协议也要有归属；保留 span 边界并解决并行共享与未完成单元后，才能做到全部生成 token 唯一归属。15 处非严格追加由实际合并器另起 span，不应强拼成一条训练序列。

**[推断] M2 应分开“历史见过”和“本次实际可见”，并以文档+片段位置/内容哈希记账。** Search/Open 的同 docid 可返回不同页面片段；不可套用旧搜索摘要永远不变的假设。features 可辅助离线拆解，不能当作 agent 已取得的证据。summary 在本批没有观测支撑，设计须另验证。

[已验证] CPU 作业：190301 成功 4s；190302 合成夹具类型错误退出 161s；修正后 190303 成功 64s；独立检查 190306 成功 3s；补充审计 190308 成功 14s；最终原文/哈希复核 190311 成功 9s。全部 0 GPU、0 新模型请求、0 更新；20 份原轨迹前后 SHA 一致。GitHub 交付只新增 `probe_m1m2/`；私有性核验记录见 `github_visibility.json`。超过 5 MB 的原始大文件只列服务器路径，不上传。

[已验证] 本次修订新增 CPU 作业 190723；真实训练输入函数离线通过，未执行模型 forward、概率重算、反向或优化器。旧验证文件保留历史口径，新结果以 native_training/ 为准。
