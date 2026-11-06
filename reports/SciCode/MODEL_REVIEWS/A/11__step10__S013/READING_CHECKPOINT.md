# 11__step10__S013 阅读与分析检查点（未完成，不计进度）

原11.1—11.10此前完整读，当前重新核对U完整2762字符、R1[12960,15722)。U检查已在先前正式稿中的tensor能否使用，提出inline/import选择，并新增sys范围、dim[i]等于Ki维度检查；仍沿用同Ki跨sys算法，无Call/保存/测试。原P已有通道主稿，U只有文字版本。后继G为“Wait, I'm still not sure about the interpretation.”，不提供新事实但引导再次解释。原R1之后重复解释到10000生成Token，无apply正式稿。远端11.10独立entropy不调用这些helper。

四条原始轨迹与实际输入、首请求/响应/IDs已经下载；协议检查154R149事件、4首输入/预算/状态通过，仅是机械，不代表语义完成。

NEW1全部44R43事件已读。apply长推：重新判断tensor可用→inline→改为直接np.kron摆脱依赖；反复提出测试/交稿却无真实Call，长度结束。曾正确写出独立Σi,j，但又改口接受同Ki联合解释。没有恢复U的sys范围/维度检查，依赖确认有重建/替代，不能一标签概括全部U。

NEW1 GADC3轮真实测试gamma=N=.5，检查KK†在此对称参数恰为I，不把它当一般非unital通道保迹判据；四个K本身正确，正式交1064字。

NEW1 output20轮：R1长篇近义承诺后read stub；R2写4556字，m-qubit小K直接乘2m-qubit密度阵；R3exec拒；R4真实4vs2；R5重写仍同问题；R6真同错。R7保存正确全组合及K_A⊗I/I⊗K_B，R8却内联旧版本重定义函数，实际再错4vs2；R9又写first-index固定、Bob也作用Alice，R10仍测旧内联；R11其它错误重写，R12仍测旧；R13写未完成Bob分支，R15又加多余identity；R16内联R13旧版Bob分支真实错。R17/R18最终恢复正确独立全组合嵌入，R19真实m1形状4×4、trace1，R20正式5070字与R18同SHA。明确区分修正版保存与旧版测试覆盖造成错误，不能把返回统归未执行修复。

NEW1 measurement4轮：one_particle_projector用state[k]=1，错误地把前m个计算基当单激发；rank4/shape16恰正确，模型纠正错误rank注释后接受原稿。真实测试没有检验具体投影子空间；不能因为rank通过认定单激发正确。sys6轮：初次空稿测试拒，随后保存正确二维校验稿；下一次测试却重定义旧平坦输入检查，实际报(8,8) expected(64,)。改write正确稿含顶层测试，下一次工具真实打印两套测试，正确输出shape/trace，但错误预期注释保留；最终独立1202字correct offset-axes稿。此为保存/测试版本分离的第二处。

NEW1 partial6轮：写np.sum而非trace，第一次测试因from syspermute导入拒；改inline后实测Bell输出[[.5,.5],[.5,.5]]，旁边打印正确期望对角[[.5,0],[0,.5]]，脚本仍无断言打印All tests passed；下一轮接受并正式回交1614字sum版本。这里反证真正返回，结论被无条件成功文字覆盖，不是没有证据。entropy4轮：正确eigvalsh/epsilon，首次模块入口拒后改内联真测纯/混态，通过后交791字、官方C。

NEW2全部32R32事件已读。apply首轮重新核对tensor可见性、inline、Ki/子系统维度并以假设接受，实际新增dim=None保护，但没有U的sys范围和dim[i]==Ki校验。测试from scipy.linalg import tensor真实ImportError；随后两次sys.path/非法import sys请求被拒，模型错认参数sys与模块冲突，实际write并formal将接口改为systems，未成功数值测试。此为错误反馈解释驱动不必要且破坏约定的接口修改，有原文而非笼统循环。

NEW2 GADC exec被拒后原样交，无数值。output先写num_qubits=rho.shape[0]//2的错误一般实现，非法output_state导入后错怪函数名/代码组织，重写为np.kron(*operators)，Alice传m/Bob传2m的不一致；write_code导入再拒，读后原样交，无数值。measurement正确单激发构造，第一次模块拒，改内联真测shape16、sum4后交。sys先空稿测试拒，然后perm_order=perm+perm重复轴写交，无实际数值。partial大量文字但重复轴与错reshape，测试scipy.linalg.trace不存在而真实ImportError，模型说是pre-existing test setup并原样交，未执行具体trace。entropy先read、write含epsilon1e-300，非法tools导入拒后改函数内numpy，再用真实纯/2×2/3×3/.7-.3测试通过，正式回交最初正确803字版，官方C。

NEW3全部38R36事件已读。apply反复确认tensor存在/inline，维度相等继续假设，未恢复U明确sys范围/维度匹配raise，无Call、长度停。GADC prior_model_code非法导入后read、原样交，无数值。output全组合正确构造后第一次模块拒，误怪itertools改base4枚举；真实m1 shape/trace正常，但测试把min(eigenvalue)接近0误当PSD，打印False。下一轮错误归因Kraus，但只read未改，改为真正eigh>=-tol且换参数再测True后交同一4590字稿；不能称两次间算法修复。measurement正确双方独立single excitation，非法入口后内联真测幂等/trace4通过交。

NEW3 sys10轮：重复轴两次真实ValueError后，R5约17K字符反复坚持[1,0,1,0]是合法4D排列、猜dim测试问题，写仍重复轴；R6终于识别bra轴应+n，R7保存correct full_axes，R9真数值shape/trace测试通过，R10交同1504字正确稿。测试有Bell/索引注释错误及非规范density输入，不把它们当物理金标准；轴修复代码本身有直接定位。partial首read后长推无实际测试却多次说test confirms，首次write语法拒；改1470字仍把16元素reshape2×2，真实报错；改2394字仍漏kept-bra维度并sum，随后R7长推51936字符/10000生成Token，无Call/formal。所有unique字面段与重复位置已读/索引，不把近义承诺当有效新操作。entropy真测试纯/混/3级通过交902字，零小值epsilon，官方C；未归一I2注释错误与数值返回单列，不能称I2是1×1。

NEW4全部40R38事件已读；本组共154R149事件全部读完。apply继续接口可见性/inline、维度相等作为假设，未恢复U两个raise检查，无Call长度停。GADC非法tools入口后内联真实完备性True、正式793字。output先写正确双组全组合；实际测试却内联4^m相关索引、交错A/B旧算法，m1 trace.34/m2 .116906，模型看到错误后先认为4^m已经足够，再在R5正确推到4^(2m)但只read；R6又讨论误认为近1/精度，最终交6260字旧4^m相关索引、无新成功测试。必须分别记录正确文字方案、保存稿、实际测试稿和最后提交稿。

NEW4 measurement正确双方single excitation，但两次非法入口均未数值，读后原稿交；解释中有错误basis例子，不让错误例子覆盖实际正确构造。sys14轮：初始额外维度/交错bra-ket；非法tools测试拒，去掉额外reshape但仍交错；真实identity trace4→2及非对称输入变offdiag；反馈后仍同交错，改4n维又两次cannot reshape16→256；最终941字仍4n维，未真成功。partial错误继承4n维解释，四次写大段未完成/错reshape/sum代码；唯一真测size4不能reshape4×4；末轮47325字符/10000Token反复解释维度和索引、无Call/formal。entropy先空稿测试拒、write正确正特征值筛选、真实多纯混态测试通过，正式646字，官方C。

关键反例与限制：四条目标C都只认证11.10，entropy不调用apply/sys/partial。U两个输入检查均未在当前新代码恢复，但四条都重新处理tensor依赖/维度假设；并非整个U完全消失。不能仅凭4C把输入防护判普遍无用，也不能把后题失败一概归U。生成成本N1/N4确定增加、N2减少、N3区间跨0，Prompt四条都少但不等于整体更省。下一步手写完整MODEL_REVIEW、精确引用、成本及协议核验后才计为完成。
