# Phase 1.1 证据安全协议迁移

- 新标注的记录版本为 `phase1.1.v2`。模型协议为 `phase1.1.evidence_safety.v2`，写入标注 provenance、缓存键和每条新缓存回执。缓存键仍绑定完整请求、提示词摘要和冻结身份。旧键没有回退路径，旧回执即使位于新版键下也会因缺少协议标识或新版字段被拒绝。原始轨迹输入的 `phase1.v1` 版本继续可读。
- `evidence_update` 顶层增加 `uncertainty_scope`。`uncertain=false` 时该字段为 `null`，可对已定位而状态未知的单行回报 `state=unknown`。`uncertain=true` 时以空 `updates` 并按需附上范围。可局部化的范围要求引用精确覆盖返回全文（外层空白除外），命中已在账本识别的候选和唯一一条冻结约束文本。含多个已知候选或多个约束文本的返回保留为全局风险。范围绑定不足时一律记录全局风险。
- `final_candidate` 请求的答案 `quote`、`anchor` 各有一对原文 Unicode 字符区间。支持独占的简短答案、`Answer:` / `Final answer:` 单一提交标签，及完整 `<answer>…</answer>` 块。可辨认的列表、选项、未决表达、多个提交结构或自由格式续文弃权。候选和锚点的验证坐标保存在 `trajectory_summaries.jsonl` 的 `final_candidate` 中。
- 旧结果仍可读。旧的引文仅在原文唯一定位且可通过相同的完整提交结构校验时可单独验证，并标记为 `legacy.unique_quote`。旧结果不会被重新标注，旧锚点不会自动获信。新版模型响应必须提供全部字段。
- 新 `StageJudgment` 包含 `risk_guard_reason`、`risk_guard_refs`、`pricing_blocked_by_risk`。有风险守卫时，Schema 要求弃权、空计价区间和空计价标签。旧输出未包含这些字段时仍可读。后续使用新协议应以独立目录和授权流程开始，审批需绑定新冻结身份。
