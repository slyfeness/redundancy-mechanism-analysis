# verl v0 接口与验收边界

本包提供可调用的 CPU 张量适配器和显式加载的 verl v0 桥接。**本机未安装 verl、Ray 训练栈或 TensorDict；本轮没有启动模型，也没有进行真实 verl 训练。** 测试使用真实 PyTorch 与本包优势计算，DataProto/注册表仅以轻量兼容对象代替。测试通过不代表分布式训练验收通过。

## 已核对的官方源码

接口目标固定为官方提交 `81464bb6d35cbb43962be42b0088a591e7020f21`，不跟随可变 `main` 推定兼容性。

- [core_algos.py](https://github.com/volcengine/verl/blob/81464bb6d35cbb43962be42b0088a591e7020f21/verl/trainer/ppo/core_algos.py)：支持字符串 estimator 注册；标准 GRPO 会先对 token reward 求和。
- [ray_trainer.py](https://github.com/volcengine/verl/blob/81464bb6d35cbb43962be42b0088a591e7020f21/verl/trainer/ppo/ray_trainer.py)：自定义 estimator 默认拿不到完整 batch/non_tensor_batch，额外传入两者仅针对内置 GDPO。因此仅注册 `span_grpo` 不足以接通 span 数据。
- [verl/__init__.py](https://github.com/volcengine/verl/blob/81464bb6d35cbb43962be42b0088a591e7020f21/verl/__init__.py)：支持 `VERL_USE_EXTERNAL_MODULES` 显式导入模块。本包使用该入口，不修改安装目录中的文件。
- [v1/trainer_base.py](https://github.com/volcengine/verl/blob/81464bb6d35cbb43962be42b0088a591e7020f21/verl/trainer/ppo/v1/trainer_base.py)：TransferQueue 按字段白名单读取。v1 另有多输出 session 合并逻辑，本桥接**不支持 v1**。
- [continuous_token.py](https://github.com/volcengine/verl/blob/81464bb6d35cbb43962be42b0088a591e7020f21/verl/utils/tokenizer/continuous_token.py)：原生生成 token 为 1，工具/上下文及额外插入边界 token 为 0。必须传递 rollout 原生 mask，不能用 attention_mask 代替。

## 批次契约

在完整同题采样组和完整训练 batch 上调用，不能在微批次或各 rank 切片后分别归一化。以下张量须与原生 `response_mask` 使用相同设备、批次顺序和 response token 坐标。

| 位置 | 字段 | 形状与含义 |
|---|---|---|
| `data.batch` | `outcome_scores` | `[B]`，独立结果验证器给出的二元真值；绝不从 token reward 推断 |
| `data.batch` | `response_mask` | `[B,T]`，只标记策略实际生成 token |
| `data.batch` | `span_redundancy` | `[B,T]`，已处理重叠的冗余置信度掩码 |
| `data.batch` | `grounding_scores` | `[B]`，取证分量 |
| `data.batch` | `span_deviation` | `[B,T]`，已聚合权重、严重度和置信度的偏差惩罚 |
| `data.batch` | `process_valid` | 可选 `[B]`；过程标签不可信时整题组回退结果奖励 |
| `data.batch` | `training_valid` | 可选 `[B]`；无效轨迹会使整题组退出训练 |
| `data.non_tensor_batch` | `uid` 或 `task_id` | 长度 B 的非空字符串；必须代表同一题目的组 ID，不能每条 rollout 使用独立组 ID |

结果写入 `advantages`、`returns`；原始 mask 克隆保存为 `ledger_response_mask`。训练 mask 改为原始 mask 乘以 `valid_rows`；诊断写入 `data.meta_info["ledger_grpo"]`。上游须显式采集这些元数据作为日志，本包没有隐式日志上传。

全批无有效行时抛出 `NoValidTrainingRows`，在写入优势和进入 optimizer 前阻止继续执行。生产 runner 必须捕获此异常并补采样/跳过整个更新，不能吞掉异常后继续更新。部分无效行目前保留形状、清零 mask：必须用 **`actor_rollout_ref.actor.loss_agg_mode=token-mean`**；生产 runner 应进一步去掉无效题组并补齐 batch，核验各 rank 和 microbatch 不会得到全零 mask。不能仅依靠本插件处理这些调度问题。

## 两种显式入口

普通 `import ledger_grpo` 和 `import ledger_grpo.verl_adapter` 都不会修改 verl。

1. 通用调用，无需安装 verl：

```python
from ledger_grpo.verl_adapter import apply_to_batch, NoValidTrainingRows

# data 是带 batch、non_tensor_batch、meta_info 的 DataProto 或兼容对象。
config = {"ledger_span": {"process_enabled": False}}
try:
    data = apply_to_batch(data, config)
except NoValidTrainingRows:
    # 由 runner 补采样；本 batch 不进入 optimizer。
    raise
```

`config` 可为本包 `AdvantageConfig`、带 `ledger_span` 的 algorithm 配置，或带 `algorithm.ledger_span` 的完整配置。未知参数报错。`process_enabled=False` 是默认结果预热；通过校准后再显式启用。完整配置可同时检查 v1 和 loss 模式；仅收到 algorithm 配置时看不到 actor 设置，因此 runner 仍须校验 loss 模式。

`ledger_span` 还接受桥接专用的 `control` 和 `seed`；这两项不会进入 `AdvantageConfig`。`control` 默认 `targeted`，可选 `uniform`（同额均匀分配）、`shuffle`（同轨迹策略 token 的偏移置换）、`trajectory`（只保留轨迹级优势）。对照在完整优势计算之后应用，使用已剔除无效行的 mask，并同步写入 `advantages` 和 `returns`。元数据记录 `control` 与 `control_seed`。`seed` 是非负 64 位整数；当前 shuffle 不保留连续 span、标签或 turn 边界，不能作为原方案中完整的“打乱 span”对照。仅传 `AdvantageConfig` 时采用默认 targeted；选择对照须使用 `ledger_span` 映射。

2. 已安装兼容 verl 的环境中，显式安装进程内桥接：

```python
from ledger_grpo.verl_adapter import register_verl_bridge
register_verl_bridge(trainer_api="v0")
```

安装是幂等的，只路由 `span_grpo`，其他 estimator 原样委托给原函数。未知函数签名、注册冲突及 v1 调用直接报错。独立调用注册表里的 estimator 必须提供完整 `payload`；缺失时不会悄悄退化为标量奖励。

也可在包已位于 Python 搜索路径时使用以下环境变量，供官方初始化入口加载：

```bash
export VERL_USE_EXTERNAL_MODULES=ledger_grpo.verl_plugin
```

PowerShell 中对应为：

```powershell
$env:VERL_USE_EXTERNAL_MODULES = 'ledger_grpo.verl_plugin'
```

Ray TaskRunner 是另一个进程；必须把同一环境变量与包路径传入其 `runtime_env.env_vars`，或在那里显式安装。只在本地 driver 导入一次不足以证明 worker 已安装。下列是合并到现有配置的接口片段，**不是可直接提交的训练作业**：

```yaml
trainer:
  use_v1: false
actor_rollout_ref:
  actor:
    loss_agg_mode: token-mean
algorithm:
  adv_estimator: span_grpo
  ledger_span:
    process_enabled: false
    control: targeted
    seed: 0
ray_kwargs:
  ray_init:
    runtime_env:
      env_vars:
        VERL_USE_EXTERNAL_MODULES: ledger_grpo.verl_plugin
        PYTHONPATH: /absolute/path/to/ledger-grpo/src
```

保留原有 Python 搜索路径；上面的路径须替换为实际包位置。`ledger_span` 使用 OmegaConf 映射传入，不要求修改上游 `AlgoConfig`。若调用方主动转换成上游严格 dataclass，须在调用方扩展配置类型并保留该字段，不能静默丢弃。

## 真实训练前仍须完成的验收

- 在固定 verl 提交的真实 DataProto 上验证注册、字段往返和形状；确认 TaskRunner 中加载的是本桥接。
- 在真实 tokenizer/AgentLoop 返回上核对 turn → 原生 token 区间；覆盖工具返回、边界 token、截断与多轮重排。
- 由 runner 在 optimizer 前处理无效题组、全零微批次和补采样，并核验 actor loss 与 KL 的分母。
- 用已有获准环境做最小更新后，核对梯度只覆盖策略 token，冗余 span 没有被重新求和广播；验证已有 uniform/token-shuffle/trajectory 路由，再另行实现并比较保留连续 span 的打乱对照。
- v1 需要另外实现 TransferQueue 字段传递、session 合并与 trainer 方法接入；本版本明确拒绝该路径。

以上尚未实跑；加载插件、通过 stub 测试与完成训练验收是三个不同状态。
