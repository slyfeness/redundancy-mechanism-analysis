# S011 阅读检查点（未完成，不计入完成数）

范围：A；11__step10__S011。原始完整路径已读；本次继续 NEW1，其余三条尚未完成，不预填结论。

## 原始 P/U/G

P 已保存 reduce(np.kron,args) 的481字符 tensor 草稿；尚未实际测试。U 覆盖11.3 R2–R9：测试入口 test_tensor 被拒绝后，R3 将其误解释为 functools 不可用，改写成循环；后续 subproblem_11_3 入口仍被拒绝，重复写入；R8 才改为直接内联代码，五项测试真实通过，R9正式提交。原错误返回明确指向测试模块，而非 functools。G 是后继11.4开头 `Let me understand the current subproblem:`，实际新请求仍恢复当前11.3，不恢复未来题目。

## NEW1 已实际阅读

- step0（11.3）R1–R2 全部：R1 `from code import tensor` 测试保留的 reduce 草稿，五项真实返回通过；R2直接提交同一481字符草稿。Call: call_c43e248d1750ce83c41129b8 / call_c3da5cd53c69bbb09728b26b。当前验证及提交功能恢复，省去测试入口误诊后的重写；不能称验证功能不必要。
- step1（11.4）R1–R11 全部：初版将 rho.shape[0] 开平方作为维数；R2真实子系统测试暴露不匹配。R4自写 K=2×2、rho=4×4、sys=None 测试违反完整系统运算尺寸要求；随后反复将这份自写测试视为不可改的要求，尝试改接口解释，继续报错。R9–R11恢复 sys=None 应直接对完整rho施加K的解释并提交，但子系统分支仍保留 sqrt 维数检查；最后提交之后未看到重新测试。独立后续绕路，不证明由U删除造成。
- step2（11.5）R1–R3 全部：从题面公式构造四个GADC Kraus算符，真实测试2×2形状、完备性及gamma/N边界；返回identity=True，随后提交988字符代码。
- step3（11.6）R1–R4 全部：起初设计联合Kraus，read_code，再写5385字符实现；R3从test_output_state导入被拒绝。R4把测试模块入口拒绝归因于候选依赖，重写4723字符实现，转用旧apply_channel；传dim为整数且旧函数按列表处理，尚需读其真实后续而不能推断终态。

下一读取位置：NEW1 step3 R5–R13，随后step4–7；再依次完整读NEW2/3/4。已读完整原文与精确重复位置保留在 LITERAL_READ_REFS_NEW1_* 文件，重复只按逐字一致定位，不做语义筛选。

机械协议预检：4个真实首请求、恢复状态及155轮/150事件已通过；此项不代表语义分析完成。

## 已完成更新

NEW1剩余及NEW2/3/4八子题全部已读；NEW1 47R45事件、NEW2 32R31、NEW3 42R41、NEW4 34R33，共155R150。显示截断另读原字段补全（NEW1 partial R2[12425,17318)、NEW3 output R1[8465,15986)、NEW4 apply R1[8485,11630)、measurement R3–4及partial R3[2387,3729)）。手写MODEL_REVIEW已完成；44逐字引用、21 Call ID、四份首请求及协议复核通过。正式结果与所有限制见MODEL_REVIEW，不以本检查点代替完成判定。
