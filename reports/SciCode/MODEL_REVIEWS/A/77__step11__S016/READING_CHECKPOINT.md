# A93 阅读完成与引用核验

原轨迹77__step11和当前四新，不能混同77__step3。原U温度77.9 R3[121,18643)、R4[0,22212)，前121字符已经认定216.7应为正确预期。原测试m18.015真实2166.707、错误216.7由模型自行打印，没有assert/官方预期；U不产生这项首次错误接受。R3原样writefd789，R4末次finish length10000但外层记MODEL_NO_TOOL_STOP，两者保真。

阅读全文完成：NEW1 7轮6工具、NEW2 9轮8工具、NEW3 8轮7工具、NEW4 10轮9工具；合34轮30Call/完整Return。长重复字段由read_exact_field_blocks保留全部独有块和所有发生位置阅读，不将重复位置当新工具。NEW1温度25178字符218独有块；NEW2 47685字符23独有块；NEW3 23361字符259独有块；NEW4温度R2 22752字符208独有块；原R3/R4也已全部读取。全部压力、forces代码/参数/Return完整读完。

NEW1 m28.0134替换原18.015没有实际新测试依据，温度9954Token无Call/正式。压力实际*1000错，真实sum check同数无单位独立证据；forces真全零非相互作用样例，正式同稿C。

NEW2 温度重复单位解释9954Token无Call/正式。pressure*1e-11错，sys入口拒却改math，真manual复用同错换算，正式回首稿。forces exec拒后声称不应run而直接正式C。

NEW3 温度反向配m1.801未纠正预期，9954Token无Call/正式。pressure actual*10正确，prior_code拒→read→正式，没有成功数值测；forces exec拒后直接正式C。

NEW4 温度原样writefd789→R2长推10000length无formal，原U失败排错/重存实际完整恢复。pressure*10正确，sys拒误math→重写→formal回含math初稿（仅换行差）。forces真实inline全零测试后sameformalC，覆盖仅非相互作用情形。

完整INPUT4份与投影字段一致：历史25Actor24工具、七份已提交代码、当前fd789草稿及两个历史工具、P121字符、G31字符7Token来源精确。后续actual prompt未补入原/新未提交温度，forces只含本分支新pressure正式。旧8742reasoning字符按原服务不转发，不冒称其全部仍对模型可见。四新事件ID/参数/Return一一配对，未真实重执行任何工具。

MODEL_REVIEW由Codex阅读后手写；resolve已验证51引文、5轨迹及4完整INPUT来源SHA和4成本记录。费用非原生精确保守区间；G7单列，Prompt不重复加。这里4C只代表冻结forces目标，不代表全套辅助题完成/质量保持。待研究者审阅，不宣称独立人工金标准。
