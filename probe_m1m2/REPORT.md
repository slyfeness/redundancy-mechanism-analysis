# LedgerCredit M1/M2 小批量探查

**[已验证] 只读复用 190085 的 DeepSearch-World 4B 轨迹：冻结名单前 10 题，各 rep1/rep2，共 20 条；未采样、未调模型、未训练、未改训练代码。** 本文分三页组织；详细证据在链接文件。原数据位置见 [输入清单](input_integrity.json)，命令见 [commands.log](commands.log)。

## 1. 环境与配置

**[已验证] 实际运行是 Qwen-Agent，不是 veRL Agent Loop。** 当前代码仓库为 `redundancy-mechanism-analysis/ledger-grpo`，含历史 veRL 桥接，参考 commit `81464bb6…`；未找到本项目已启用的 LedgerCredit Agent Loop 配置。另有可读的 veRL **0.5.0 / `8fdc4d3f…`** 源码，仅作静态参考，不能冒充本批运行版本。

[已验证] 策略为 `Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`，路径 `/file_storage01/home/weiyu/lanyi/models/Qwen3.5-4B--851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`，同目录 tokenizer；vLLM 0.19.1、torch 2.10.0、Transformers 5.5.1、tokenizers 0.22.2。四 TP1、T=1、top-p=1、top-k=0、上下文 65,536、每次生成上限 10,000、最多 20 次模型调用、guard 256。模型调用预算不等于工具调用数。[配置](run_config.json)；[源代码位置与哈希](source_audit.json)；[模板原文](chat_template.txt)。

## 2. 交互格式

**[已验证] 单轮为 reasoning + XML 工具调用，工具结果在下一轮 prompt 中；没有 summary 调度证据。** `search(query)` 返回最多 5 条 `{docid,caption,score}`；`open(docid,start=0)` 返回 `{docid,start,text,next_start}`，每段最多 8,000 字符。[定义](tool_schema.json)；[Search/Open 各两条原样返回](samples/tool_return_examples.json)。三组原样消息与原生 ID 导出见 [samples](samples/README.md)。

[已验证] `<think>/</think>` 为 **248068/248069**，`<tool_call>/</tool_call>` 为 **248058/248059**，返回标签为 **248066/248067**：均为独立 added token，但此 tokenizer 文件将它们标成 `special=false`。`<summary>` 为普通文本 **[27,1648,29]**，闭合为 **[510,1648,29]**。`im_start/im_end` 为 248045/248046；完整属性见 [token_protocol.json](token_protocol.json)。本批 summary、answer、plan 标签均为 0；出现的是 function/parameter 协议。`answer` 曾被当作不存在的工具调用，不是合法 Final 标签。

## 3. 模板与训练样本结构

**[已验证] 三轮合成工具对话保留全部历史 think/返回；追加真实 user 消息后，三个旧 think 全部不再渲染。** 依据模板 67–103 行和 [前后对照](samples/template_test.json)、[新 user 对照](samples/template_edge_tests.json)，不是模型推断。

[推断] 可读的 veRL 0.5.0 `tool_agent_loop.py:61–128` 累加生成 mask=1、工具块 mask=0，一轨迹输出一个 `AgentLoopOutput`；`agent_loop.py:323–385` 再 padding 成一行。它的两个默认模板调用在本 tokenizer 的合成测试中报 “No user query found”，不能直接认定兼容。实际旧 HF 链路保存逐调用 segments，仅严格前缀相等才合并；不是这套 veRL 数据结构。

<div style="page-break-after: always;"></div>

## 4. Token 映射

**[已验证] 请求的“实际训练 mask → Stage”验收为 0/20 可验，不能报通过。** 历史推理数据没有持久化 `response_ids/response_mask`；三份 token 导出如实填 null。228 次原生 prompt/completion ID 与服务响应逐一相等，217 次工具 ID/名称/参数/返回对齐；20/20 轨迹的生成分类计数守恒。这里只构建诊断坐标，没有重新分词训练响应。[逐轨迹结果](stage_mapping_check.csv)；[独立核对](verification.json)。

[已验证] 共 89,695 个生成 token，69,074 个可暂挂到单工具 Stage/Final；两条未完成生成占 20,000，另有并行共享部分 621 个，均未强行分配。观测在下一轮原生 prompt 上标 -1，**不是**伪造训练 mask。并行四个工具 Stage 的共享 think 数留空；完整轮级分类另存 [round_token_stats.csv](round_token_stats.csv)。

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

<div style="page-break-after: always;"></div>

## 8. 可复用资产

**[推断] 原生 ID 捕获和工具绑定可以复用，旧阶段坐标不能直接当 veRL 的 response 轴。** 下表为源码阅读结论，相关源哈希见 source_audit.json。

| 代码路径 | 可复用内容与边界 |
|---|---|
| `ledger-grpo/src/ledger_grpo/native_capture.py` | 捕获服务 ID/logprob；不提供完整 Agent Loop mask。 |
| `src/redundancy_judge/parse_stages.py` | 工具事件/原生生成轴；坐标是生成 token 串联，不含工具观测轴。 |
| `ledger-grpo/src/ledger_grpo/native_tool_coordinates.py` | 调用/返回绑定；其返回 offset 辅助函数会重新 tokenize，本次没有用于 T3。 |
| `ledger-grpo/src/ledger_grpo/event_deletion.py`、`event_continuation.py` | 删除/续跑事件绑定；并非新 Stage 的唯一归属策略。 |
| 旧 HF `src/native_spans.py` | 只有 exact native prefix 才合并，保留 action_offsets。 |
| `scripts/index_browsecomp.py:19–22` | TOKEN15 旧删除资产索引；边界口径不同，不能替代一工具一次 Stage。 |

[已验证] 当前模板及记录器没有独立 summary 折叠协议；未发现可直接复用的本任务 summary→可见性状态实现。

## 9. 待确认问题

**[已验证] 以下事实/规则尚未获得指定，未自行选择生产方案：** LedgerCredit 真正要用的 veRL 仓库、commit、Agent Loop 配置及训练 mask 采集位置；一轮多调用的共享思考归属；截断/无 Final 的生成 token 是否成为独立可训练 Stage；summary 是否为拟加入机制；原子条件的关系拆分、模糊限定词与金标证据审核口径。以上均不靠本批猜定。

## 10. 对 M1/M2 设计的影响

**[推断] M1 可沿用原生 ID 与工具事件绑定，但不能只靠标签或重套模板回填优势。** think 开头通常在 prompt 中，额外正文/结束协议也要有归属；须先确定真实训练轴、并行共享与未完成单元策略，再做 mask 全覆盖验收。15 处非严格追加说明历史推理日志不能直接拼成单条训练序列。

**[推断] M2 应分开“历史见过”和“本次实际可见”，并以文档+片段位置/内容哈希记账。** Search/Open 的同 docid 可返回不同页面片段；不可套用旧搜索摘要永远不变的假设。features 可辅助离线拆解，不能当作 agent 已取得的证据。summary 在本批没有观测支撑，设计须另验证。

[已验证] CPU 作业：190301 成功 4s；190302 合成夹具类型错误退出 161s；修正后 190303 成功 64s；独立检查 190306 成功 3s；补充审计 190308 成功 14s；最终原文/哈希复核 190311 成功 9s。全部 0 GPU、0 新模型请求、0 更新；20 份原轨迹前后 SHA 一致。GitHub 交付只新增 `probe_m1m2/`；私有性核验记录见 `github_visibility.json`。超过 5 MB 的原始大文件只列服务器路径，不上传。
