# 配对扩展：100 题 × 每模型两次回答

最新用户设置覆盖先前“各跑 4 条”：4B、9B 各 200 条，共 400 条。
采用已去重且排除 test 重叠的 DeepSearch-World 训练池，沿原 dsw-pilot-v1 哈希顺序取前 100 题。
保持原 10 题；前 16 题已有配对记录，每模型只读复用 rep1/rep2 共 32 条；新增 84 题各 168 条。
配对 seed 保留原 20261110 + question_index*8 + repetition_index，重复次数缩减不改变 seed 步长。

## 冻结项

沿 190085/184534：4 个 TP1 vLLM 实例，BF16，65,536 context，每卡显存比例 .75，32 max-num-seqs，CUDA graph/prefix cache。
temperature=1、top_p=1、top_k=0；每次最大生成 10,000 tokens，最大 Actor 调用 20。
8 个轨迹 worker；相同 Wikipedia Search/Open 和 question-only 提示；每模型独立目录。
生成结束停止 Actor，再以 TP4 本地 gpt-oss-120b 判分；沿旧 score.py 提示和请求，不接外部 API。
新任务不运行训练、优化器或发布策略快照。历史文件只读；不重采已有对应 seed。

## 执行与交付

CPU 准备作业 191006 已完成，20 秒，32 条/模型复用的任务、seed、轨迹与判分哈希已核验。
12 个本地测试通过；两模型四卡作业串行依赖，资源 gre/professors、24 CPU、384G、48h，无指定节点。
记录排队、加载、生成、判分和终态；生成失败不伪装为错误答案，判分缺失不填零。
扩展统计准确率、每题 rho、调用与 token 成本、同一套规则重复率；分开报告旧 16 题与新 84 题。
原子条件试拆仍保留原 10 题示范，不能把其人工判断冒充新增 90 题的判断。
公开分支仅提交代码、统计、id、允许的短例子；完整题面、轨迹、原始返回与判分缓存留在 bulk/private。
