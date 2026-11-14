# 删除记录与事件标签校准

现有表能筛查正确性变化的方向。B⁺ 候选要求原轨迹答对，四个可比续跑
至少三个变为失败。B⁻ 候选要求原轨迹失败，至少三个续跑答对。W 与 N
互换另记为结束状态变化。

| 数据及干预 | 可比四次的分组 | B⁺ 候选 | B⁻ 候选 |
|---|---:|---:|---:|
| SAGE 首句引导 | 289 | 17 | 24 |
| SAGE 末段无引导 | 51 | 0 | 3 |
| SciCode 首句引导 | 221 | 36 | 14 |
| SciCode 末段无引导 | 28 | 2 | 0 |

来源是 SAGE 的 `ALL1360_COST_AND_OUTCOME.csv` 和 SciCode 的
`BRANCH_RESULTS_AND_COSTS.csv`。按 stage 单元和干预分组，要求四个不同
重复编号、一个共同原状态。BrowseComp-Plus 当前 `ALL2450_BRANCH_INDEX.csv`
的正式记录每个 stage、每种干预各一次，共 2,003 个首句引导单元和 212
个末段无引导单元。

再次核对原表后，SAGE 的 1,360 条续跑均使用 `DERIVED_CHAR_EXACT_NO_ORIGINAL_NATIVE_IDS`，
SciCode 的 996 条续跑均使用 `RECONSTRUCTED_CHAR_EXACT`。两表的删除目标分别由
`unit_id` 和 `case_id` 标识。BrowseComp-Plus 的 `INPUT_AUDIT.json` 也显示切点
属于原 stage 起点，首句条件另注入下一 stage 的引导。归档的 B⁺/B⁻ 候选可用于
挑选后续审查样例。当前三个归档均没有同时满足同一工具事件的已核对绑定及四次
可比续跑的记录，因此这些计数无法用于计算新识别器的 B⁺ 标记率。

启用 R1/R2a 价格需要把 stage 和新识别器的具体事件对应起来，并独立审查
引导泄漏、重做和多副本替代。人工精确率的分母是人工已判定的被标记事件。
B⁺ 标记率的分母是全部匹配的 B⁺，B⁺ 污染率的分母是有可比删除结果的
被标记事件。`audit-events` 同时输出两种覆盖率和原始计数。

校准输入每行记录 `case_id`、`label`、`prediction`、`human_verdict`、
`original_correct`、`guide_confounded`、`deletions`。`deletions` 内每条含
`condition_id`、`repetition_id`、`comparable` 和 `correct`。独立人工结论
允许 `uncertain`，标签也允许弃权。校准输出绑定输入文件 SHA。

计价用的输入还需要 `trajectory_sha256` 和 `event_id`。每条声称可比的续跑
需要 `intervention_scope: single_tool_event`、`target_trajectory_sha256` 和
`target_event_id`，后两个字段对应原事件。跨事件、整段 stage 和未对齐的历史
续跑可以作为诊断证据，`comparable` 填 `false`。同一轨迹、事件和标签只计一次。

```powershell
python -m ledger_grpo audit-events --for-pricing --cases reviewed-event-cases.jsonl --output calibration.json
```

将输出写入阶段配置的 `semantic_calibration`，在实际执行主机上使用可读取的
绝对路径。训练入口校验清单 SHA-256，并从清单重算三项比例。人工精确率至少
0.90，B⁺ 标记率和 B⁺ 污染率至多 0.05。分母为空时保持未知，相关标签的正价格
无法启用。归档检查和接口测试尚未形成可以启用 R1 或 R2a 的实测报告。

通用 `score-events` 与实跑入口共用这项校验。两类价格默认均为零。显式启用
时，可传 `--semantic-calibration calibration.json`。校验通过的信用张量
保存所用校准清单的摘要。纯结果、均匀计价和零价预热无需语义标签校准。
首批八个工程样本导出时带 `calibration_scope: engineering`。审计照常报告
这批样本的诊断数据。正价校验拒绝含工程样本的标签校准清单，即使样本内
的三项比例碰巧达到阈值。

CPU 182743 用共享校验后的计价器复算冻结的 182516 训练批。五组原始优势
张量、有效策略 mask 和扣分回执均与已保存结果完全一致。原生事件成本复算
报告也与上一版逐字节一致，见
`outputs/pilot-182516/SHARED_PRICING_GATE_REPLAY.json`。

## 单事件删除的成对输入

BrowseComp-Plus 适配器以目标返回第一次进入模型请求的位置切分。对照
前缀必须逐 token 重现冻结记录中的模型输入。删除前缀从该请求移除目标
工具调用和匹配的返回，保留该次返回之前生成的思考、同轮其他调用和返回、
以及全部更早的消息。两个条件沿用原问题和工具模板，均从切点重新生成
后续内容。无已发送后继请求的末轮事件缺少可比前缀。

续跑时每个事件用四个固定的采样种子，每个种子同时用于保留和删除条件。
两条件使用同一策略快照、检索索引、续跑轮次上限和上下文限制。续跑按
原任务结果规则独立评分，同时记录目标查询重做、其他来源补证和预算耗尽。
历史定义下的 B⁺/B⁻ 仍可报告。保留条件至少三次复现原正确性时，才把
四个删除结果纳入 B⁺/B⁻ 指标。其余事件保留配对结果及未纳入原因。
人工精确率需要独立判定，删除结果也须保留跨样本和同题重复的层级。

`scripts/audit_event_deletion_prefixes.sbatch` 在冻结训练批上核验两套
前缀，报告绑定原轨迹 SHA-256、事件 ID、续跑轮次及两份原生 prompt ID
摘要。这个入口用于验证干预输入，续跑结果由后续实跑提供。

CPU 作业 182698 用冻结 Qwen3.5-9B tokenizer 复核了 182516 的 32 条训练
轨迹。261 批已进入后继模型请求的调用共 317 个事件，全部重现保留条件的
原生 prompt ID 并构造出删除条件。226 个来自单调用轮次，可与当前 R1/R2a
的事件级映射对齐。14 个末轮事件未进入后继模型请求。报告与既有原生坐标
审计的轨迹摘要、事件 ID 和续跑轮次逐项一致。报告位于
`outputs/pilot-preflight-20261111/EVENT_DELETION_PREFIXES.json`。
这些计数是可构造干预输入的覆盖率，后续仍需成对生成、评分及独立标注。

## 续跑与校准输入

`scripts/run_event_deletion_branch.py` 用已审计的轨迹 ID、事件 ID、条件
和种子连接同一 Slurm 作业内的 Actor 与检索服务。它按原采样配置和剩余轮次
预算逐轮重新生成，核对模型收到的原生 prompt ID，记录正常提交、预算终止
及目标查询重做。`BRANCH_RESULT.json` 包含前缀摘要、轨迹摘要和运行环境
摘要，运行环境摘要绑定 Actor 权重指纹、检索端口、作业 ID 及预算。

独立结果评分以 `BRANCH_RESULT.json` 文件 SHA-256 为键记录布尔结果。
`--cases` 提供独立人工标签、原轨迹正确性及八个分支回执路径。汇总要求
同一事件、同一环境、保留和删除各四条且种子逐一匹配。完整预算终止计失败，
故障和缺失判定保持未解析。汇总输出可交给现有计价审计。

```powershell
python scripts/assemble_event_calibration.py --audit EVENT_DELETION_PREFIXES.json --cases reviewed-cases.json --grades branch-grades.json --output paired-cases.jsonl
python -m ledger_grpo audit-events --for-pricing --cases paired-cases.jsonl --output calibration.json
```

CPU 作业 182707 从每条有可比前缀的原轨迹选择最早一个事件，回放保留条件。
31 条轨迹逐项重现了 261 次模型请求、290 次后续检索和终止状态，包含 23 次
正常提交、8 次上下文预算终止。报告位于
`outputs/pilot-preflight-20261111/EVENT_CONTINUATION_REPLAY.json`。
合成八分支的文件级测试通过了汇总到原计价审计的流程。真实的两条件重新
生成及评分仍待实跑。

## 首批校准样本与盲评

CPU 作业 182710 从 226 个有完整前缀的单调用事件冻结 8 个工程样本。
四道训练题各取较早和较晚的一个事件，同一题的两个事件来自不同轨迹。
选择只使用任务 ID、原生事件坐标和固定种子，排除 16 道固定留出题。
八个事件覆盖续跑起始轮次 4 至 14。每个事件四个种子，每个种子各跑
保留和删除一次。两个种子先跑保留，另两个先跑删除，顺序预先冻结。
共 32 对、64 条计划分支，当前只核验了清单。

`outputs/pilot-preflight-20261111/event-calibration-182710/BLIND_REVIEW.html`
包含原问题、调用前可见记录及目标调用和返回。可用同目录的
`BLIND_VERDICTS_TEMPLATE.json` 记录独立判定和消息引用。只向审查者提供
盲评页与模板。计划文件绑定盲评包、训练批、留出拆分和生成配置的摘要。
首批八个样本用于检查流程，正式校准仍需能覆盖正判、负判及必要事件的样本。

```powershell
python scripts/run_event_deletion_plan.py --plan PLAN.json --audit EVENT_DELETION_PREFIXES.json
```

默认只检查清单及输出执行顺序。实际使用 `--execute` 时需提供已就绪的
同作业 Actor、检索端口、原采样目录、模型和新输出目录。入口按冻结顺序
逐条执行，并核对每条回执的前缀、事件、条件和种子。

## 零价语义诊断

`scripts/diagnose_semantic_events.py` 独立于训练执行，R1/R2a 价格为零时
也可记录事件级预测。入口核对计划、原轨迹和原生工具坐标。指定已有的
Judge 凭据时，按训练所用的语义规则独立分析到目标事件为止的前缀，沿用
运行配置中的证据编码。调用前缀上的判定不会影响训练奖励或其请求预算。
每个标签输出 positive、negative 或 uncertain，并附原因。解析失败、语义
核对未执行或无法对应单一工具事件时保留 uncertain。R2b 的确切重复仍优先。

默认只读取已归档的过程报告。CPU 182714 在同一八事件清单上核对了全部
原生坐标。R1 有 1 个已评估负判和 7 个未知。R2a 有 8 个未知，其中 7 个
缺少通过验证的前缀，1 个前缀可用但当时未开启 R2a 语义核对。结果在
`outputs/pilot-preflight-20261111/event-calibration-182710/ARCHIVED_SEMANTIC_PREDICTIONS.json`。
这次回放没有发出新 Judge 请求，也没有用于启用计价。

## 冻结清单到计价审计

`scripts/frozen_event_calibration.py` 将计划、盲评包、人工评审、语义判定、
原生训练批与分支回执绑定到同一事件。人工评审须引用对应盲评前缀中的消息。
结果评分只处理与 `trajectory.json` 中最后一次实际提交相同的答案。提供
`--execution`、`--private-plan` 和已有的 Judge 凭据后，沿用原试验的结果
Judge；成功回执可用 `--reuse-from` 复用。任务参考答案只进入结果评分。

输出 `PAIRED_CASES.jsonl` 可供计价审计读取。未齐四对的事件保留评审状态，
删除结果保持空。B⁺ 事件缺少语义判定时，B⁺ 标记率保持未知。语义核对已执行
并主动弃权的事件仍保留其弃权状态。归档语义报告用于核验绑定，生成的计价
行以未知记录这些旧判定。

CPU 182715 使用八个真实事件及原任务输入验证了清单、盲评包和旧过程报告的
绑定。64 条续跑尚无实际回执，人工评审也未导入，三项计价指标均为空。
预检结果位于 `outputs/pilot-preflight-20261111/event-calibration-182710/CALIBRATION_PREFLIGHT.json`。

## 同作业续跑入口

`scripts/launch_event_calibration.sbatch` 复用 182516 的四 Actor 与检索启动
流程。服务就绪并通过生成探针后执行 64 条分支。四个 Actor 各处理两个事件，
每个事件的八条分支在同一个 Actor 上按冻结顺序运行。不同事件可并行。每条
分支使用独立工作目录，成功回执按实际完成顺序落盘。读回时按原计划索引绑定
评分，失败事件保留未完成状态，其他事件的成功回执仍可使用。

CPU 182721 使用集群已安装环境核验了冻结后端和记录器的导入、生成配置、
64 条分支的分配，以及 105/104 字节的两项 IPC 路径。本机用同一清单和模拟
分支传输核对了全部 64 条回执，四个 Actor 各 16 条。报告为
`outputs/pilot-preflight-20261111/event-calibration-182710/LAUNCH_PREFLIGHT.json`。
这次只完成 CPU 预检。续跑作业仅生成分支，结果评分和训练更新各有独立入口。

### 四卡续跑 182887

Slurm 分配了同节点的四张 A800。排队约 1 秒，批作业运行 26 分 6 秒。
服务初始化 623.57 秒，四个生成探针耗时 2.73 秒。续跑阶段执行了
911.47 秒，服务在 7.28 秒内关闭。作业终态为 `FAILED (1:0)`。

独立 CPU 作业 182899 逐条核验了冻结计划、配对种子、实际采样参数、
前缀 token、模型请求和响应、工具调用及返回，以及落盘摘要。64 条计划
分支中有 56 条通过核验，覆盖 7 个事件的 28 对。优化器更新次数为 0。

| 条件 | 正常提交 | 上下文预算终止 | 轮次预算终止 | 工具调用 | 生成 token |
|---|---:|---:|---:|---:|---:|
| 保留 | 22 | 6 | 0 | 126 | 47,744 |
| 删除 | 25 | 0 | 3 | 126 | 43,463 |

E002 的首条删除分支在第 11 轮生成了未注册的 `answer` 工具调用。
当时的续跑校验提前退出，执行器依照事件边界跳过该事件剩余 7 条分支。
本地续跑入口现已沿用原采样器的工具不存在反馈，真实检索仍需核对 MCP
回执。新回归测试覆盖了未注册工具反馈的再注入和重复调用 ID 的拦截。
本机共运行 303 项测试，302 项通过，1 项跳过。修复尚待 GPU 实跑。

正式正确性评分仍待 DeepSeek 余额恢复。作业结束后的官方余额检查
182907 返回 `False`。原始回执、CPU 核验、Slurm 作业记录和故障证据位于
`outputs/pilot-preflight-20261111/event-calibration-182710/live-182887/`。

## SAGE 和 SciCode 的语义诊断

`prepare-sampler-grpo --emit-process-traces` 接受 `process_frames`。每个
采样条目按 SAGE 的单轨迹或 SciCode 的子问题顺序提供约束列表，约束原文
必须出现在对应阶段的首轮用户消息中。适配器导出 `PROCESS_TRACES.jsonl`
和 `PROCESS_EVENT_BINDINGS.jsonl`，并把两者的摘要写入原生批次。轨迹可交给
`analyze`，随后 `diagnose-sampler-events` 将报告与原生工具事件逐一绑定。

SAGE 的证据来自已进入实际模型请求的检索片段和文档读取。SciCode 按子问题
维护独立账本，可保留已核对的草稿、测试标准输出和错误输出。模型自写测试
的运行结果不等于官方测试通过。未送入后继模型请求的返回不进入证据账本。
语义诊断单独输出，已有 `EVENT_ROWS.jsonl` 继续用于原计价流程。

CPU 作业 182739 用冻结 Qwen tokenizer 复核了两套合成原生格式日志。SAGE
的近义检索判定绑定到目标工具事件的 `[51, 69)` token 区间，计价标签为空。
SciCode 的同版本草稿重复读取保留 R2b，语义诊断标记为精确重复优先。报告
位于 `outputs/pilot-preflight-20261111/SAMPLER_PROCESS_VERIFICATION.json`。
真实跨任务采样、语义校准和策略更新仍待验证。

## 续跑与本地校准入口

补跑使用 `launch_event_calibration.sbatch <源码> --resume-from <旧运行>/branches`。
入口核对冻结计划和旧回执的摘要，只调度未完成的完整事件。同一事件的保留和
删除条件继续在同一 Actor 上执行。读取多个运行时，按原计划恢复评分索引，
无需复制旧轨迹。每个 `--execution` 对应一个分支目录，顺序为旧运行在前。

四卡作业 183352 按原计划补完 E002 的 8 条，Slurm 终态 `COMPLETED (0:0)`，
用时 14 分 2 秒。第 11 轮再次出现 `answer` 调用，第 12 轮实际请求包含
同一调用 ID 及原采样器的工具不存在反馈。CPU 183353 核验新增 8 条的
原生交互与摘要。CPU 183357 按冻结顺序合并两次回执，64 个摘要均唯一，
得到 8 个事件、32 对、55 份正常提交。回执在
`outputs/pilot-preflight-20261111/event-calibration-182710/resume-183352/`。

`diagnose_semantic_events.py --judge-base-url <同作业本地接口> --judge-model <模型名>`
用已有的约束提取、证据账本与规则运行 R1/R2a。输出包括事件身份、标签、
弃权原因和模型用量。输入只到目标事件为止。本地 Judge 使用去重的证据编码，
保留原文和引用 ID。运行 `local_event_calibration.sbatch <源码> <补跑作业号>`
可加载现有 gpt-oss-120b，也可用第三个参数指定 Qwen3-32B。它读取两次
续跑的回执，并在 `LOCAL_DIAGNOSTIC_VERDICTS.jsonl` 保存本地答案判别及请求摘要。
本地判别与正式判分各自有回执，正式校准输入只从正式判分获取正确性。

本地 Judge 作业 183354 在发现部署包缺少语义诊断依赖后停止。完整源码经
CPU 183357 核对，冻结在 `20261112-calibration-workflow-v2`。四卡作业
183358 随后加载 gpt-oss-120b，正常结束，用时 28 分 37 秒。8 个工程
事件中，R1 和 R2a 各有 3 个负判、5 个弃权。55 份正常提交均有本地
布尔判分，回执逐项绑定原计划索引和分支摘要。结果与输入状态保存在
`resume-183352/LOCAL_DIAGNOSTIC_RESULT.json` 和
`resume-183352/LOCAL_CALIBRATION_INPUT_STATUS.json`。

正式样本通过 `freeze_event_calibration.sbatch <源码> --calibration-selection <清单>`
冻结。清单是由 `sample_id` 和 `event_id` 对象组成的 JSON 数组。
冻结前按审查协议选择覆盖必要动作、非冗余核验和候选冗余的样本，
保留选样规则和分层信息。脚本核对原生事件坐标与留出题边界，
绑定清单摘要，为每个事件固定四对种子，导出盲评包与模板。
本批八个工程事件的计划保留工程范围。正式样本另行冻结与运行。
CPU 183359 用一个真实事件验证了该入口，实际导出四对种子和摘要绑定的
盲评模板。正式校准仍待选样、独立标注与正式正确性评分。

余额恢复后，使用 CPU 入口 `frozen_event_calibration.sbatch <源码>`，
附上各个 `--execution`、对应 `--predictions` 和已有 `--key-file`。
独立盲评完成后附 `--review`。使用新计划时同时传入对应的 `--plan`
和 `--packet`。入口核对盲评、语义判定、正式正确性和事件摘要，
以 `PAIRED_CASES.jsonl` 交给 `audit-events --for-pricing`。
人工标签或正式结果缺失时，相关指标保留未知。
