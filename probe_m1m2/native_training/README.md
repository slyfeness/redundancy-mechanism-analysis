# 自有生成器训练输入与掩码核对

本目录对应 CPU 作业 190723（3 分 20 秒，COMPLETED/0:0，4 CPU、24G、0 GPU）。只复用 190085 已有 20 条轨迹；没有重新采样、判分、模型 forward、反向或参数更新。

## 证据范围

- `field_inventory.json`：20 条轨迹实际存在的 token、采样 logprob、文本与原始响应字段；整轨训练 mask、HF old logprob 没有历史持久化记录。
- `native_training_summary.json`：20/20 原生输入/掩码验收、17/20 Stage 完整归属、35 个最大 span、106188 个零掩码位置。
- `call_training_alignment.json`：228 次调用与 span/训练轴位置逐一关联；每次动作开始前的整个 prefix 必须等于实际采样 prompt IDs，动作 IDs 和 logprob 也必须逐项相同。
- `traj_1..3_training_tokens.json`：实际 CPU 准备函数输出的完整 span、action_offsets、采样 logprob、response_mask、stage_ids 与生成文本解码。不能当作 190085 曾经训练的证明。span 之间各有自己的 prompt；拼接后的 mask 是分配优势的坐标，不是一个跨 span 模型输入。
- `roundtrip_diagnostic.json`：3 条轨迹、56 次生成的额外 decode→encode 诊断，54 次完全一致，2 次不一致。没有用重分词结果替换任何训练 ID。原生采样 prompt 与记录器采样时渲染 IDs 为 56/56 一致。
- `training_source_audit.json` / `source_refs/`：实际加载的 qualified-source 训练函数及冻结后端的原文、路径、SHA。三个关键文件 hf_native、browsecomp_adapter、hf_pilot_train 与当前仓库文本一致（换行符规范化后比较）；原始执行字节以源 SHA 为准。

## 怎样核对掩码

1. 用真正的 `native_trajectory` 从原始响应取逐调用 IDs/logprob，再调用 `native_turn_layout`，不重新分词生成动作。
2. 与冻结后端 `action_records(merge=True)` 对照每个 span 的 prompt、completion、action_offsets、logprob，全部一致。
3. 逐调用验证动作保持原来的整个因果前缀；所有动作位置 mask=1，span 中新增的上下文位置 mask=0。另检查每轮原生 prompt 里的工具返回块：位于 prompt 中的部分不会成为 loss target；进入 completion 轴间隙的部分必须为 0。
4. 调真正的 `prepare_native_records`，检查交给训练器的 record 与上面的 span 一致，并核对训练器构建 input_ids/目标 positions 的表达式。接口测试用明确标记的合成有效行/优势张量，未做损失计算，未给真实题组赋训练资格。
5. 另把一行设为无效，核对整条轨迹从 records 和有效 token 分母中排除，不能残留动作。

`stage_ids=-1` 代表训练 completion 轴中的零掩码上下文；`null` 是尚未定规则的生成 token，不能混为 -1：一条轨迹的并行共享思考/协议共 621 token，另两条未完成生成共 20000 token。

## old logprob 与备选桥

| 项目 | 主线自有训练链路 | veRL 备选适配代码 |
|---|---|---|
| 输入 | 原生 calls 按 exact prefix 合成一个或多个 span；每个 span 独立 forward | 接收外部构建好的 DataProto 和 `[B,T] response_mask`，不构建 Agent Loop 序列 |
| 掩码 | action_offsets → 二值分配轴 → 选定 action positions；再按有效行屏蔽 | 保留 ledger_response_mask，乘有效行 mask 并写回优势 |
| 概率 | vLLM q 为实际生成 token 的采样概率；单步 PPO old 为更新前 HF forward detach，q 用于 TIS | 此桥不负责原始 token/logprob 采集；不能据桥代码声称训练已接入 |
| 启用 | 检索到 hf_pilot_controller → hf_pilot_train 的训练入口 | 仅显式 register_verl_bridge / VERL_USE_EXTERNAL_MODULES 才注册；本项目训练脚本无启用调用，文档示例和测试不等于运行 |

这是已执行的 CPU 输入构造验收。190085 是采样评测作业，没有可对照的历史训练 forward/old HF 概率；本次也没有重新执行它们。单步 detach-old 的正确性前提是整批梯度累计后只做一次更新，不能直接用于多次更新/多 epoch。4B 正式训练部署、完整奖励门控和跨 rank 数值行为仍需后续独立验收。

## 复现

控制脚本为 `../scripts/probe_native_training.py` 与 `native_training.sbatch`；使用 `transfer_native_training.sftp` 上传，再按 `../commands.log` 的 sbatch 命令提交。新作业写 `probe_m1m2/native_training-<JOBID>/`，不得覆盖 190723 或 190085。原轨迹与执行源码前后 SHA 均在作业内核对一致。
