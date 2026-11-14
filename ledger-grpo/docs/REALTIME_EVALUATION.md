# 实时观测与效果判读

本轮先做单次更新的链路试验。训练代码、优化器提交、检查点落盘、Actor
权重发布和固定题集评测分别验收；一个环节成功不代表后续环节成功。

## 正在记录什么

- 训练结果：独立结果 judge 的正确率、正常完成率；未知判分单独列出。
- 有效信号：完整同题组、预算失败保留数、排除组、QA 回退组、有效策略
  token、非零优势 token、两种目标实际不同的 token 数。
- 过程标签：R1/R2、grounding 及覆盖率。当前只给符合过程奖励条件的组
  标注，不能把该条件样本的冗余比例当作全部轨迹的冗余率。
- 优化器：全局 token-mean loss、策略熵、裁剪前梯度范数、实际 Adam
  step、正负优势 token 数、HF 与 vLLM 采样概率偏差及 TIS 截断比例。
- 成本：生成 tokens、工具调用、judge 请求与返回的 token 用量、各阶段
  墙钟时间、Slurm 分配时间。失败和截断样本仍计入生成成本。
- 交付状态：每 rank 的 optimizer 返回、完整 checkpoint 分片、验证过的
  推理快照、四个 Actor 的权重/生成探针。

未测量值保持 `null`。本实现每批只更新一次，以同一次前向的 detached
logprob 作为旧策略分母；PPO ratio=1、clip fraction=0 是结构结果，不能
拿来证明学习稳定。TIS 比较的是 HF 与实际采样器的概率，也不能冒充
相对冻结参考策略的 KL。指标应保留估计方法，参见
[CleanRL 官方指标定义](https://docs.cleanrl.dev/rl-algorithms/ppo/#explanation-of-the-logged-metrics)。

## 如何比较效果

固定 16 道评测题，每题 8 条采样；评测题排除旧训练使用的全部 160 个
问题 ID。它是本轮独立预留的探索性题集，不称为官方重新划分的 train/test。
比较更新前与更新后、以及目标确实不同的两个训练臂。相同题、相同预算、
相同检索环境和采样种子日程均保持。

修订版同时比较定向计价、同轨迹打乱和均匀计价。定向与打乱先审计逐轨迹
价格集合，再报告扣分覆盖 token 数与逐 token 扣分之和。均匀计价也报告
这两个量，因为相同标称单价可能对应不同覆盖率。固定题集同时查看完全重复
事件、未标记事件成本、预算截断率和明确放弃率，以区分减少重复与提前停止。

结果 Judge 缺判时，正确率和其配对区间保持空值，另报覆盖率与已知判分所能
约束的最好、最坏范围。思考长度在服务端用量缺失时从保存的思考文本重分词，
单独显示估计值及轮次覆盖。

### 必要缺口闭合率

先仅根据题面冻结每题必要的证据要求。复核者检查轨迹终止时的候选和真实可见
观测。证据支持同一候选且符合该项要求时记 `closed`，已查明记录中仍缺证据时
记 `open`，证据歧义、复核缺失或记录不足时记 `unknown`。`closed` 需要来源
引用。这个指标可以用于没有结果判分的轨迹，也可以用于完整预算截断记录中能
辨识的当前候选。

`requirements.json` 是题目 ID 到 `{缺口 ID: 描述}` 的映射。`reviews.json` 包含
`evaluation_sha256`、`requirements_sha256`、`protocol_id` 和 `checks`。每条
check 含 `task_id`、`sample_id`、`gap_id`、`verdict`，闭合时另附
`evidence_refs`。同一轨迹内各缺口等权，同一题内各样本等权，最后各题等权。
缺判时展示覆盖率与上下界，配对点估计和 bootstrap 区间保持空值。上下界只
约束当前固定题集。

```powershell
python -m ledger_grpo audit-gaps --evaluation latest/EVAL-targeted.json --requirements requirements.json --reviews reviews.json --output gap-audit/EVAL-targeted.json
python -m ledger_grpo compare-events --baseline gap-audit/EVAL-outcome.json --candidate gap-audit/EVAL-targeted.json --output gap-delta.json
```

监控从 `gap-audit/EVAL-<arm>.json` 读取闭合率，并校验该文件绑定的原评测摘要。
已审查数显示为 `已判 n/N`，其中 `N` 是固定评测所有样本的必要缺口总数。`compare-events`
校验两臂使用同一要求清单与复核协议。

### 独立检索片段复测

`scripts/audit_retrieval_overlap.py` 对冻结留出集重新检查原生检索返回。
先核对各臂的题目、采样 seed、原始轨迹身份和基线回执。某片段需要通过
调用 ID 和返回原文绑定到更早已执行的调用，并实际进入收到模型响应的请求，
才计为已见。同一批并行调用之间没有先后可见性。文档标识相同而片段不同，
仍计为新片段。

结果记录每条轨迹的全旧片段调用、新参数且全旧片段调用、混合新旧片段调用，
以及解析覆盖率。脚本使用题级配对 bootstrap 比较定向组与各对照。片段重合
是检索诊断。语义相关性、必要性和 R1/R2a 的计价资格仍由独立标注和干预检验。

将报告保存为镜像目录下的 `RETRIEVAL_OVERLAP_AUDIT.json`。监控页只在报告
中的评测摘要 SHA-256 匹配时显示该臂的均值和覆盖率。

### 已观察到的预算内成功率

`scripts/summarize_success_by_budget.py` 用冻结的盲评回执将每条轨迹的答对判定
与工具调用数、生成 token 数绑定。给定成本上限，只有已答对且实际成本不超过
上限的轨迹计为成功。分母包含固定题集的全部采样，成本或判定缺失时报告界限。
这项回顾分析没有在预算达到上限时中断或重跑轨迹。比较区间为按题配对的逐点
bootstrap，同一训练种子内使用。

182516 的定向、纯结果、轨迹级三组在 10 次工具调用内分别观察到 35、34、42
份正确提交，在 15 次内分别为 41、36、45 份，每组均为 128 条轨迹。15 次时
定向减纯结果为 +3.91 个百分点，95% 逐点区间为 [−0.78, +9.38]。
在 8,000 个生成 token 内，三组分别为 41、37、44 份正确提交。
报告与图见 `outputs/pilot-182516/SUCCESS_BY_BUDGET.json` 和
`outputs/pilot-182516/SUCCESS_BY_BUDGET.png`。

按题目聚合，再做配对 bootstrap，报告准确率差和平均生成 token 差的区间。
8 条同题采样不是 8 个独立任务；一个训练种子也不支持跨训练随机性的
置信区间。训练批次正确率不替代固定题集评测。单次更新不支持收敛或
准确率非劣结论。这一报告原则参考
[Agarwal 等，NeurIPS 2021](https://arxiv.org/abs/2108.13264)。

若 Ledger 与 Outcome 的优势张量及有效 mask 逐 token 完全相同，只执行
一次等价目标更新。另一臂标记为未重复执行，绝不捏造第二臂的评测结果。
这种情况说明当前过程门控回退，不能写成“已经证明方法有效/无效”。

## 已观察到的预检问题

旧严格规则在 8 个历史批次仅保留 1、3、2、0、3、5、3、5 个同题组，
每批原有 16 组。用户已批准新的 `outcome_only` 预算失败策略；日志完整的
预算失败仍是 complete=false/outcome=0，但可保留结果梯度，其组过程项关闭。
未知停机、工具故障和日志缺失不因此变有效。

第一次 8 条真实轨迹预检：最终候选解析 0/8，QA 4/8，过程项整组回退。
修复自由文本提交解析后的第二次：候选解析 8/8，QA 6/8，剩余两条为 JSON
格式错误；过程项仍整组回退，两种优势完全相同。候选文字格式不一致时
grounding 保持未知，不能把未匹配当作证据不足惩罚。

上述两次旧客户端的 token 用量只累计成功解析的响应，是已观测下界。
后续客户端已修正为先累计服务端 usage，再验证生成内容；网络失败而
没有返回 usage 的调用仍无法从本地凭空计费。

## 查看

`python -m ledger_grpo.observability metrics.jsonl --output monitor.html --watch`
仅刷新本地 HTML。`collect_pilot_monitor.py` 可把下载的审计/预检摘要转为
同一事件格式。它们不会提交作业、调用模型或创建定时自动化。
