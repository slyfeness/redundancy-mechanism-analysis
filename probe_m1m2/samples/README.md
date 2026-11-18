# 原始样本与探查衍生物

- [已验证] `traj_1..3_messages.json` 逐轮保留原请求 messages、逻辑历史、assistant 原消息与工具事件；只是增加外层索引，没有改写字段内容。`verification.json` 逐字段对照原轨迹。
- [已验证] `traj_1..3_tokens.json` 保留每轮原生 prompt/completion IDs 及解码文本。顶层 `response_ids`、`response_mask` 为 null，表示历史推理运行未保存整轨训练张量，并不表示没有原生生成 IDs。
- [已验证] 此目录中的 `derived_generation_mask`、`diagnostic_stage_ids`、`diagnostic_observation_spans` 保留初次探查的逐调用坐标。新增的 [native_training](../native_training/) 由自有训练函数直接生成 span、response_mask 和 stage_ids，含三份完整训练输入导出及采样 logprob；它们是 CPU 构造结果，不是 190085 历史训练回执。
- [已验证] `template_test.json` / `template_edge_tests.json` 是合成模板测试，与真实轨迹统计分开。合成工具 arguments 需先转换为对象；原记录器 phase06_runtime.py:136–138 也有这一步。
- [已验证] `*_examples.json` 的 train/train_v1/test 原始行各两条；`selected_dataset_rows.json` 只含选定小批量的源行，不是完整数据集。`tool_return_examples.json` 含 Search/Open 各两条原样回执，`outcome_receipt_examples.json` 含两条已有判分回执，无新增判分。
- [推断] `atomic_condition_examples.json` 的三题拆解是 Codex 示例，不是人工金标、冻结约束或可直接用于 g 的分母。
- [已验证] `prefix_diagnostics.json` 保存全部 15 个非严格 token 追加处的小片段；不能仅凭 token 前缀不同推断历史被删除。
- [已验证] 原始大 trajectory.json 保留在 `input_integrity.json` 所列服务器位置；超过 5 MB 的文件未上传。三组消息/token 导出均分别小于 5 MB。
- [已验证] 失败的 CPU 作业 190302 日志保留；其错误来自合成夹具参数类型，不是实际轨迹/模型运行失败。成功分析为 190303，独立核对为 190306。
