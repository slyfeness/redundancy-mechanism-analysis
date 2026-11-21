# SciCode 最终生成配置与旧策略概率自检

- 冻结配置 [scicode_gen_frozen_20261122.yaml](../../configs/scicode_gen_frozen_20261122.yaml)
- YAML SHA-256 `306ea3bdc0c03deee19410f3f4ea7acd965988baa05332fa9ff635015fc72204`
- 生成代码与 RICE 修复提交 `a4ed8f63d04a37cccd8535c200e57cb413c82b40`
- 祝融默认入口 `scripts/scicode_gen.py`。每卡任务池自动补派，每题的全部 rollout 到终态后原子写出整组。CPU 自检作业 `195270` 核对了 96 个计划项的唯一归属及拒绝命令行覆盖。原 20261121 YAML 字节不变。

RICE 修复应用在新发布目录 `releases/hf-old-logprob-20261122/src/ricepo/hf_runtime.py` 第 773 行，变更保存在 [版本化补丁](../../patches/ricepo-old-policy-hf-20261122.patch)。PPO 的 `UpdateItem` 使用 HF 重算值；原轨迹的 vLLM 采样值照常保留。

历史检查点缺失权重文件。最小自检作业 `195279` 复用 3 条已存轨迹，使用现存的冻结基础权重。分别执行旧策略缓存与更新用的前向路径，3,412 个生成 token 上 `new_logprob - old_logprob` 全部为 0，ratio 最小值和最大值均为 1。没有反向传播、优化器更新或新生成。
