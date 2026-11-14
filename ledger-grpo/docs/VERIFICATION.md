# 本地验收记录（2026-11-11）

执行环境：Windows、Python 3.12、现有 PyTorch CPU；没有安装新的训练依赖。

| 验证 | 结果 | 能说明什么 |
|---|---|---|
| `python -m unittest discover -s tests -q` | 144 项：143 通过，1 跳过 | 标准轨迹、引用时序、规则、优势公式、掩码、配置路由、CLI、凭据与接口异常的行为 |
| `python -m compileall -q src tests` | exit code 0 | Python 文件均可编译 |
| CLI demo | 6 条合成轨迹，QA 全通过，6 条有效行 | 账本到 token 优势与可审计报告的完整数据流 |
| 数值梯度检查 | 通过 | 工具 token 无策略梯度；冗余正优势在目标位置衰减；错误轨迹方向保留 |
| 真实 Windows DPAPI，临时 dummy key | 7 项凭据测试通过 | 加密往返、无明文落盘、原子替换和损坏检测 |
| verl | 兼容对象与显式 dispatch 测试通过 | 尚不代表真实 Ray/DataProto/GPU 训练验收 |

跳过项是实际 TensorDict 容器测试，原因是本机没有安装可选 `tensordict`。未静默将兼容对象测试称为真实依赖验收。

日志见 `outputs/verification-unittest.txt`；完整合成报告见 `outputs/framework-smoke/`。配对 bootstrap 的自比较命令也已执行，两项差值及区间均为 0，仅用于确认命令行路由。

DeepSeek 真实 API 检查单独记录，不能混入以上单元测试计数。早期终端输入轮次收到 HTTP 401，未得到模型判定；它属于认证失败，不属于案例判错。改用支持 Ctrl+V 的 Windows 密码输入框后，一次认证成功，用用户明确授权的 DPAPI 保存。随后重新读取已保存密钥并再次认证成功，验证后续无需再次输入。

最终结果见 `outputs/deepseek-dialog-20261111/result.json`，状态为 completed，6/6 与预期一致、0 API/格式错误。使用 `deepseek-flash` 非思考模式，总计约 6.82 秒，API 返回用量为输入 2231 tokens、输出 325 tokens。覆盖直接支持、日期不符、主语歧义、同源重复确认、必要独立核验、目标不明确。该用量仅为六次判别调用，不含无生成的认证检查。

本次没有进行模型训练、真实任务准确率比较、GPU/Slurm 作业或多种子实验。六个 API 局部案例全部匹配，只能作为接口和简单行为的检查，不能证明真实长轨迹 judge 的精确率、召回率或跨任务泛化。
