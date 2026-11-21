# 训练旧策略 logprob 来源

## SwAP

核对仓库提交 `d1854a0a14842645f33aa2527e229448a2641f33`。`scripts/controller.py:150–156` 启动训练入口 `scripts/train_iteration.py`。

1. `scripts/train_iteration.py:119–120` 建立 FSDP 策略。
2. `scripts/train_iteration.py:129–137` 读取原生 prompt 和 completion token IDs，在第一次 optimizer update 前以前向计算获得 `old[i]`。随后保存各 rank 的旧策略 logprob。
3. `scripts/train_iteration.py:184–189` 将 `old[i]` 传给 PPO loss。

该链路可以在 rollout 端启用 MTP，同时保留 FSDP 的旧策略重算。是否启用 MTP 不改变上述旧策略值的来源。

## RICE/GRPO

核对已封存的运行源 `biology-scale-exec-v1`，对应 `b0ee0bb0f789f803770566572ef8fd1499f14550`。

1. `src/ricepo/vllm_two_stage.py:182–203` 让 vLLM 返回实际生成 token 的标量 logprob，并与生成 IDs 配对。
2. `src/ricepo/contracts.py:128–142` 检查生成 IDs、动作掩码和概率是否对齐，恢复实际采样 logprob。
3. `src/ricepo/hf_runtime.py:749–774` 重算 HF 参考值并对照采样值。构造 `UpdateItem` 时，有 vLLM 采样值就把它用作 PPO 的旧策略值。采样值缺失时才使用 HF 值。
4. `src/ricepo/hf_runtime.py:843–858` 把这些 `UpdateItem` 传入 PPO 更新。

因此，这条链路需要验证 MTP 在实际解码路径返回的概率。沿用该链路 `src/ricepo/probability_check.py:4–12` 的门槛，绝对差均值不超过 0.02、P99 不超过 0.06、最大值不超过 0.12，单位为 nats。

## SciCode 的 MTP 生成路径对照

使用 20 份真实历史的原生 prompt IDs，开关 MTP 各跑生成接口。贪心诊断只用于对齐概率，同一个概率对照点拥有相同的原生前缀。续写分叉后的概率只在重新对齐前缀后比较。保留正式 A/B 采样配置。

计量 20 份输入、1,280 个对齐 token；两端直接输出相同 token 的计量点有 1,271 个。该对照状态为 **FAIL**。

绝对 logprob 差均值 0.0084088694、P99 0.078550577、最大值 0.094997644 nats。

只统计两端实际输出相同 token 的 1,271 个位置时，P99 仍为 0.069706 nats，高于 0.06。

SwAP 仍使用训练端重算。RICE/GRPO 会消费 vLLM 的旧策略采样值，所以应以实际训练模型、采样和精度保留其概率审计。

本次差异超出既定容差，当前证据不支持 RICE/GRPO 直接使用 MTP 返回值当作旧策略概率。
