# 实验及解释口径

## 覆盖与只读范围

100条原轨迹、646个冻结Stage，2584条计划。631个合法目标各四次，共2524条真实新续跑；15目标共60条未运行原因完整保留。深层机制审阅严格限A272、B68，共340组/1360条，不分析269个OTHER或22个UNCERTAIN目标。15个NOT_RUN也不冒充有续跑结果。

所有Stage边界及原数据、生成结果、既有评价只读。综合文件是新增分析，不重启GPU、Actor、检索器或Judge。原始/新轨迹全文仍在本地RAW和POSTGEN_EVIDENCE_EXPORT，索引提供绝对路径、JSON Pointer、精确引文和SHA。

## 判读的P不是把日志里所有旧推理拼起来

原请求的reasoning_content字段在实际vLLM消息规范化中没有完整进入历史Assistant正文；实际P保留真实可见工具历史与当前Round切点前缀。旧日志曾经写过某判断不等当前分支P仍明示该判断。每条INPUT_AUDIT及实际原生Prompt IDs为输入核对依据。

原966份请求/响应没有原生Token IDs，用户已授权字符精确重建。标记DERIVED_CHAR_EXACT_NO_ORIGINAL_NATIVE_IDS，切点不移动。新生成有真实原生IDs不等原切点可原生精确定位。

## 原新配置不同，不能把单分支差异当纯删除因果

已实际重新读取966份NATIVE/*/R*_request.json：全部temperature=0.7、top_p=0.8、top_k=20、单轮max_tokens=10000。原SAGE运行源码REFERENCE_SOURCE/run_sage_pool.py记录30 Actor、40工具、32000累计生成，并使用Eager/MTP2档位。

本轮用户指定此前冻结吞吐档；续跑Worker固定temperature=1.0、top_p=0.8、top_k=0、repetition_penalty=1.0、n=1，双TP1、8+8、CUDA Graph/Prefix Cache、MTP关闭，最多20 Actor（含历史）、65536上下文及256余量、每轮10000减保留当前前缀。EXECUTION_CODE_FREEZE.json明确original_sampling_not_claimed_equal，且不引入原SAGE额外32000/40工具限制。

因此，原路径与新四支对比同时含采样、运行档位与预算口径差异。四新支之间采用统一冻结档，但仅四个seed也不是统计独立题目。行为链有原文支持不等这些差异已被唯一排除。不能把原新差称严格相同配置下的删除因果效应。

注意logical_actor_request.json是从原始消息继承的逻辑对象，可能仍保留旧0.7/top_k20字段；实际原生ID POST由已封存Worker构造1.0/top_k0请求。不能拿该逻辑投影冒充实际采样。旧BRANCH_TERMINAL中初始status或actor_request_sent字段亦可能停留预检值；真实终态须联合terminal_status、HTTP_RECEIPT、实际响应、native IDs和封存轨迹核对，不能只凭遗留布尔值断言没生成。

## G与末段

FIRST_SENTENCE均ORACLE_ANCHORED。分别看新增实体/事实、已有候选确定性、行动方向、完整后继Reasoning预填及提取异常；没有最终答案数值也可能给关键候选或DocID。G不是新模型自主判断，不把其重复计作新生成Token。

TERMINAL_DROP_NO_ANCHOR没有G，仍是同P自然续写，可能重做原末段甚至多做核查，不是强制让模型跳过该功能。首Stage近从原Question重新起步时也不证明功能成功跳过。

## 结果、证据与成本

C/W/N是实际正式答案状态。无Final为N，不能从Reasoning中的正确猜测补正式答案；UNCERTAIN单列，不强判C。正确主答案不等全部题目条件/解释已有充分证据，也不等所有断言为真。

Return已执行但下一Actor请求未发送，不算模型已经读到或采用。Open limit为字符，不是Token；text_characters元数据是源文长度，不是实际返回窗口。

完整Round可报告真实usage计数差；部分Round只能保守[后续完整轮次, 当前整轮+后续]区间，不能重新编码前缀后伪扣原生生成。P重放、G预填、实际新生成、累计Prompt、Search、Open、Actor分别记账。新Prompt本已含G，不再重复加一次。

独立删除分支的节省不可相加成可实现总体收益。少工具但长生成、少生成但少完成工作、同C但证据变弱各自保留。没有基于这些记录发布严格冗余或纯因果必要性标签。

## 验证等级

机械检查证明字符覆盖、事件配对、引用与SHA、清单和成本可复算。Codex逐组/四路语义审阅与模型跨题链接是研究建议，不是独立研究者人工金标准。target_relation定位U与观察链的关系也不等证明因果。无法解释的退出差异、检索命中原因及题义争议留待研究者审核。
