# 四张 A800 的 Actor、Judge 与 FSDP 显存预算

方案 C 首版每卡各放一个 Qwen3.5-9B TP1，并让 gpt-oss-120b TP4 覆盖四卡。按 Actor `0.45`、Judge `0.40` 计算，普通三卡各需 **67.48 GiB**，检索器所在的 GPU 1 需 **82.12 GiB**。GPU 1 超出 PyTorch/CUDA 可见容量 **2.87 GiB**，也超出 `nvidia-smi` 标称整卡容量 **2.12 GiB**。这两项是按历史测量推算的显存预算，方案 C 尚无实跑。四卡 FSDP 需单独使用四张卡，训练前须释放两个推理服务的 GPU 权重和 KV 池，并将检索编码器移回 CPU。

## 计量口径

- 182516 与 181915 的 `HARDWARE.json` 每卡记录 `85,094,825,984 bytes = 79.25073 GiB`，作为保守预算分母。182516 的 `GPU_TIMESERIES.json` 经 `nvidia-smi` 报告 `81,920 MiB = 80 GiB`，其 `memory.used` 是整卡采样值。两者差约 0.75 GiB。
- vLLM `Model loading took … GiB memory` 是加载期间的权重显存变化，`Available KV cache memory` 是初始化给 KV 池计算的预算。KV 使用率是该池内部的已用比例。torch `max_memory_allocated` 和 `max_memory_reserved` 分别记录单进程的张量分配峰值和缓存分配器预留峰值。两个峰值可能出现在不同时间。NVML 整卡峰值另含其他进程及驱动占用。
- `gpu_memory_utilization` 乘以 CUDA 可见总量得到 vLLM 的预算目标。Actor 历史配置在 KV 预算之外另捕获 CUDA 图。运行期预留、工作区、通信和进程基线会使 NVML 采样值高于名义预算，具体差值见下表。

## Qwen3.5-9B Actor 与检索器

182516 的 24 份 Actor 日志覆盖初始模型和五个训练臂，每次四张 A800 各一实例。实际使用 BF16、TP1、65,536 上下文、最多 32 个序列、16,384 个批处理 token、prefix cache、CUDA graphs 和 sleep mode。

| 项目 | 每张卡 | 口径与来源 |
| --- | ---: | --- |
| Actor 权重 | **16.80 GiB** | 24 份 `server.log` 相同，vLLM 模型加载测量 |
| Actor KV 池 | **40.39 GiB，330,528 tokens** | 24 份日志相同，`gpu_memory_utilization=0.75` |
| Actor CUDA 图 | **0.12 GiB** | 每份日志的实际捕获，独立 profiler 估计均为 0.15 GiB |
| 激活、PyTorch 外分配等 profile 余项 | **约 2.25 GiB 合计** | `0.75 × 79.25073 − 16.80 − 40.39`，推算 |
| 单独的 Actor 激活峰值 | **未知** | INFO 日志省略 `torch_peak_increase` 和 `non_torch_increase` 的拆分 |
| GPU 1 检索器 | **14,987 MiB = 14.64 GiB** | `services/retriever/launch.json` 固定物理 GPU 1。182516 前置 NVML 样本显示 Actor 加载前 GPU 1 为 14,987 MiB，其他三卡为 0 MiB |

对 `GPU_TIMESERIES.json` 只取 Actor 服务就绪到 `Sleep mode freed` 前的采样。每个 Actor 对应一张物理卡，GPU 1 数字含已驻留的检索器。采样周期约 2 秒。

| 182516 服务组 | GPU 0 MiB | GPU 1 MiB | GPU 2 MiB | GPU 3 MiB | 四个 Actor 中最大 KV 占用采样 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `services` 初始 Actor | 62,337 | 77,999 | 62,391 | 61,057 | 15.29% |
| `actors-outcome` | 64,047 | **80,437** | 65,435 | 64,031 | 52.50% |
| `actors-trajectory` | 63,921 | 79,607 | 64,419 | 64,097 | **56.05%** |
| `actors-targeted` | 63,803 | 79,709 | 64,475 | 65,751 | 46.39% |
| `actors-shuffled` | 65,447 | 79,633 | 64,683 | 65,429 | 53.89% |
| `actors-uniform` | 65,111 | 80,297 | **65,841** | 64,551 | 44.39% |

普通卡和 GPU 1 的最高采样分别为 **64.30 GiB** 和 **78.55 GiB**，比 `0.75 × 79.25073 + 0.12 GiB` 加各卡检索器占用的名义预算分别高 **4.74** 和 **4.36 GiB**。以各组最后一个 Actor 的 `ready_utc` 向上取整到秒，窗口从 UTC `18:37:19`、`18:58:35`、`19:28:00`、`19:54:38`、`20:28:50`、`20:51:26` 开始，对应的 sleep 截止时刻为 `18:43:02`、`19:11:14`、`19:39:59`、`20:06:51`、`20:41:27`、`21:03:13`。这组窗口将 Actor 采样与随后同一文件中的 FSDP 时段区分开。

历史同卡对照 `cache-ab-181561` 在同款卡上先启动同一检索编码器，前置空闲显存差为 `15,134,610,432 bytes = 14.10 GiB`。Actor `0.50` 时记录 **20.57 GiB / 168,432 token** 的 KV 池、**60,275 MiB** 的整卡峰值和 **99.06%** 的 KV 高水位，336 个历史回放请求中有一次 preemption。Actor `0.75` 时为 **40.39 GiB / 330,528 token**、**78,567 MiB**、**55.05%**，记录零 preemption。这个对照覆盖单 Actor 加检索器，检索编码器在回放中空闲。182516 有实际检索活动。

## gpt-oss-120b Judge

187767 以 vLLM 0.19.1、MXFP4/MARLIN、BF16、eager、131,072 上下文、最多 16 个序列、8,192 个批处理 token、prefix cache 和 NCCL 2.27.5 启动。`model.log` 的模型加载和 KV 显存行只打印了 TP rank 0。四卡中其他 rank 的独立显存测量未见。Judge 已到达 `judge_ready`，作业最终失败发生于之后的审核计划校验。

| 项目 | TP4 历史实测或推算 | TP2 估算（保持 eager） |
| --- | --- | --- |
| 权重 | **17.22 GiB**，rank 0 | **约 34.44 GiB/卡**，按分片减半线性估算。复制权重、分片细节和临时重排峰值未经 TP2 测量 |
| KV 池 | **51.57 GiB**，rank 0，`0.88`。引擎报 **3,003,888 tokens** | 若仍用 `0.88` 且 profile 余项相同，约 **34.35 GiB/卡**，折合约 **100 万 tokens**。若沿用 C 的 `0.40`，总预算 **31.70 GiB** 低于权重估算，无法预留 KV |
| CUDA 图 | **0 GiB**，日志确认 eager 关闭了 CUDA 图和编译 | 保持 eager 时 **0 GiB**。启用图的估计缺少历史数据 |
| 激活与非 KV profile 余项 | **约 0.95 GiB 合计**，`0.88 × 79.25073 − 17.22 − 51.57`。计算假设同样的 CUDA 可见容量 | 取同样余项用于上面的算例。TP2 profile 余项和运行峰值未知 |
| NCCL、CUDA context 与额外工作区 | NCCL 版本实测。逐卡字节未知。初始化通信发生在 vLLM 的初始显存快照之前，部分分配可能在 profile 余项之外 | 未测；用 TP4 实测权重做倍乘时无法估出这部分 |

TP2 的 KV/token 估算使用模型配置的 8 个 KV heads，TP4 分到 2 个，TP2 分到 4 个。36 层中的滑动窗口与全注意力混合影响绝对容量。以 TP4 实际 token/GiB 为锚点，TP2 同样 KV GiB 暂按约一半 tokens 计算。184754、184768、184780、187046、187164、187221 的 TP4 日志均重复报告 R0 的 17.22/51.57 GiB，未发现可直接替代算例的同模型 TP2 记录。

## 四卡 FSDP 独立显存峰值

182516 的五个训练臂各完成 4 rank 的 FSDP 更新，`*/step-0001/OPTIMIZER_RETURNED-rank*.json`、`UPDATE_COMPUTED.json` 和 `CHECKPOINT_PERSISTED.json` 证明返回及持久化。回执里的训练指标不含 allocator 峰值。`PHASES.json` 显示每次更新前先让 Actor sleep，再将检索器 offload 到 CPU，更新后发布 Actor 并恢复检索器。以下峰值取独立 FSDP 历史。

| 历史记录 | PyTorch allocated 峰值 | PyTorch reserved 峰值 | NVML 整卡峰值 |
| --- | ---: | ---: | ---: |
| `grpo-stability-181915/trained-01.json` 至 `trained-08.json` | **81,041,387,520 bytes = 75.48 GiB**，第 7 步 rank 3 | **83,078,676,480 bytes = 77.37 GiB**，第 1 步 rank 3 | 没有引用该阶段的独立采样峰值 |
| `capacity-64k-4r-180954`，4 rank 同时各跑 65,536 tokens、已恢复 AdamW | **75.32 GiB/卡** | **78.33–78.34 GiB/卡** | **79.24–79.25 GiB/卡**，UUID 对齐、1 秒采样 |
| `capacity-64k-4r-offload-180966`，同一批次、长序列选择性激活卸载 | 全批 **64.44–66.23 GiB/卡**，64K 反向 **59.32 GiB/卡** | **约 78.2–78.3 GiB/卡** | **79.15–79.20 GiB/卡**，同样的采样口径 |

181915 的峰值来自 `torch.cuda.max_memory_allocated()` 和 `torch.cuda.max_memory_reserved()`，因此可与 180954 的对应两列比较。即便仅保留 Judge TP4 的 17.22 GiB 权重，叠加 180954 任一张卡已测得的 75.32 GiB FSDP allocated 也达到 **92.54 GiB**。TP2 的权重估算更大。Actor 及检索器需按已验证的相位切换释放 GPU 占用。182516 的 Actor level-2 sleep 曾丢弃权重和 KV，但普通卡仍有约 **0.97 GiB** 整卡占用，训练前仍应核对整卡实际余量。Judge 的释放与恢复机制需要独立验证。

## 方案 C 的名义预算与余量

每卡名义占用是 `(Actor fraction + Judge fraction) × 79.25073 GiB + 0.12 GiB Actor CUDA graph + 检索器`。普通卡检索器项取 0，GPU 1 取 14.63574 GiB。余量以 CUDA 可见总量计。下表 KV 估算保持 vLLM 历史实测的权重及 profile 余项，并按历史实测 token/GiB 比例缩放为近似池容量。

| Judge TP4 | 普通卡 Actor TP1 | GPU 1 Actor TP1 | 普通卡名义总量 / 余量 GiB | GPU 1 名义总量 / 余量 GiB | Judge KV GiB / tokens | 普通卡 Actor KV GiB / tokens | GPU 1 Actor KV GiB / tokens |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.40 | 0.45 | 0.45 | 67.48 / +11.77 | **82.12 / −2.87** | 13.53 / 788k | 16.61 / 136k | 16.61 / 136k |
| 0.38 | 0.45 | 0.40 | 65.90 / +13.35 | **76.57 / +2.68** | 11.94 / 696k | 16.61 / 136k | 12.65 / 104k |
| 0.34 | 0.45 | 0.37 | 62.73 / +16.52 | **71.02 / +8.23** | 8.77 / 511k | 16.61 / 136k | 10.27 / 84k |

第二行的 GPU 1 余量小于历史 Actor 加检索器运行期超出同口径名义预算的 **4.36 GiB**。使用 181561 `0.50` 回放和 182516 的同一 GPU 1 检索器预留口径，差值约 **4.48 GiB**。第三行把约 **4.5 GiB** 的历史运行偏差和另 **1–2 GiB** 的 Judge 未测开销作为灵敏度假设，GPU 1 仍有约 **1.7–2.7 GiB** 的推算余量。Judge 的冷启动峰值、实际运行峰值、逐卡 NCCL 分配和同时调度均待实测。

第三行只提供一次调整的容量候选。降低 Actor KV 池会增加排队或抢占风险。182516 训练 rollout 的最高采样约 **50.5k** 池内 tokens，固定评估达到约 **185.3k**。这些值由历史池容量与表中观测的占用比例相乘得到，包含 prefix cache 的影响。第三行的 **84k** GPU 1 容量估计高于单条 65,536 token 上下文，能否保持历史并发与吞吐须由实际的 admission、KV preemption 和完整 rollout 验证。若要沿用历史训练阶段的容量，需将 Judge 推理与 FSDP 分相运行。

## 证据定位

集群源路径以 `/file_storage01/home/weiyu/lanyi/projects/` 为根。本次读取既有作业记录和日志，并在本机汇总采样。

- Actor、检索器与阶段切换，`ledger-grpo-pilot/runs/pilot-182516/{HARDWARE.json,PHASES.json,services/retriever/launch.json,services/actor*/server.log,actors-*/actor*/server.log,*/actor*/GPU_TIMESERIES.json,*/actor*/KV_CACHE_TIMESERIES.json,*/step-0001/}`。Actor 日志定位词为 `Model loading took`、`Available KV cache memory`、`GPU KV cache size`、`Graph capturing finished`、`Sleep mode freed`。
- Judge，`redundancy-judge-phase1/run-187767/model.log` 第 7、13–22、31、38–39、83–87 行和 `redundancy-judge-phase1/docid-m3-ce9768f14d2e/full-187767.log`。模型结构来自 `/file_storage01/home/weiyu/lanyi/models/gpt-oss-120b/config.json`。vLLM profile 计算及通信初始化顺序来自 `/file_storage01/home/weiyu/lanyi/envs/successful_phase05_20261007/lib/python3.11/site-packages/vllm/v1/worker/gpu_worker.py`。
- Actor 的同卡 KV 对照，`browsecomp-qwen35-9b-grpo-smoke/runs/cache-ab-181561/{RESULT.json,A/server.log,B/server.log}`。
- FSDP，`browsecomp-qwen35-9b-grpo-smoke/runs/grpo-stability-181915/trained-*.json`、`browsecomp-qwen35-9b-grpo-smoke/runs/capacity-64k-4r-180954/`、`browsecomp-qwen35-9b-grpo-smoke/runs/capacity-64k-4r-offload-180966/`，另见对应同名本地容量报告。
