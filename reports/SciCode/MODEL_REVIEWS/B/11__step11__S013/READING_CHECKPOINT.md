# B102 IN_PROGRESS，不计B101

对象SciCode 11__step11/S013，原C→W/W/C/W，3次变化；不是旧BrowseComp、不是上一S011。固定B116剩余清单。原轨迹完整92R已早先读，immutable b5e6428a...。四traj/fourAudit已下载，8SHA与EVIDENCE_INDEX匹配，成本已取，首raw未取/机械未做/正式semanticJSON未写。

U完整三段已读：官方11.5R2[0,1108)实际run_python试从tools import read_code/run_python，被IMPORT_DENIED root tools拒，未执行数值检查；测试写sum K K.T而非TP的sum K.T K，不能说测试通过。R3[0,1396)误归numpy但读到root tools后仍重写同862字符33a3e416...正确GAD；R4[0,1035)accepted后正式同862/33a3。三events参数在Reasoning完整，返回metadata已读；CallID均recovered_1但B002/3/4，不按全局ID去重。P已有完全相同正确draft862/33a3及四prior正式（ket/旧multi_rail/tensor/旧reduce通道），历史32Actor32工具，当前只有1write历史。删除并未移除GAD公式或draft。G为S014/原11.6R1[0,30)strip“Let me understand the problem:”6token，跨子题来源但实际仍11.5R2继续，P空当前前缀，budget10000。G不带未来数学事实。不得只因最终W就倒推U提供独有算法。

## 四条本地step1（官方11.5）全部已读

N1两轮：真实run内联相同GAD，sum K†K=I真通过→formal33a3。N2两轮同正确TP测试通过→formal33a3。N3两轮：run在scipy.linalg.trace ImportError，未数值测试；正确归为测试导入、非算法错后formal33a3。N4一轮：明确accepted仅safety/syntax后直接formal33a3，无run。**四正式都与P和原U同SHA**，功能检验1/2恢复且更有效，3尝试失败、4未做；正式工作四条都有。后续最终分化不能归被删GAD算法产物变化。

## N1已完整读官方11.6、本地step2共23R23事件

R1先说正确连续A/B结构又假设交替qubits，只read空。R2真save47e963ed包含P旧state[i]、旧np.kron.reduce及未初始化rho_output。R3 import output_state拒→R4错怪priorimports/read→R5发现未初始化真savee0bd修。R6 import拒→R7另写selfcontained20dd，但extended起I2多一维且rho+=串行Kraus，不是真独立求和。R8 sys import拒→R9实际inline旧reduce触发AttributeError，没运行新20dd。R10read20dd，R11错称它未初始化（实际另代码），savef446仍extendedI2多维并逐Ki串行。R12实际run旧20dd→4vs8；R13save0958仍I2+K串行，R14save4ec类似；R15真实4vs8。R16识别多起I2却仍保存0c85同问题；R17长手推后save7611更坏每qubit先kronI再kronK；R18 step_11_6 import拒→R19真4vs16。R20终于actualsave0c31用ops[0]起tensor，解决多identity，但Kraus仍串行、交替qubit。R21未新run又退回完全7611（相同SHA）！R22再改783c仅去多额外I、起I2仍多一维；R23未经run正式同783c。不是“所有修稿执行都失败”，多次真run在旧/不同inline，必须标版本。R9Reasoning显示截断675—1600已补，余均完整。

## N1官方11.7、本地step3共7R7事件已读

R1推理曾正确P_A⊗P_B，但R2真实save8703把qubit位置直接设basis_state两个幅度为1，非单一binary全局index。R3 test_code导入拒→R4read→R5真run相同坏算法，m1 trace2/isprojectorFalse/4非零，真实反证。R6长24629（N1_S3_R6精确索引所有独特原句/重复位置已读，截断5502—18159已补）：多次正确辨认qubit号不等basis index、m1应|11>index3，反复又用旧编码state[i]说明，最后形成正确onebit alice/bob index并真run；Return m1trace1/1nonzero、m2trace4/4nonzero。R7随后先疑惑旧Expected1、后来接受新数值，**实际formal1684/5c23007由旧R5错误basis位置代码构成**，不是刚测正确的onebit版；需下一步再次读正式完整code核对，不能按自然语言“正确”记成功提交。当前saved仍8703旧稿（run不修改draft）。

## 待继续

N1剩localstep4/5/6/7（4/9/3/10R）未读；N2—4除首GAD外全部未读。不得提前COMPLETE或计B102。需要读目标题/证据+四firstraw/协议/精确引用/成本并写手动semanticJSON后才封存。

## N1后半已读完：58R58事件全读

measurement formal5c23007已完整再次核对，确实是旧错误basis_state[alice_qubit]=1及[bob_qubit]=1，不是R6run正确onebit；正式与刚测试版本不同。

11.8四轮：先run被空draft拒→write0023（含顶层selftest），实际run同算法二qubit交换trace1，正式c6a去顶层。np.moveaxis(new_axes,range)双half正确，对此不要因目标W一概判错；测试仅swap不足以一般确认。11.9九轮：read空→saveef7用perm+perm重复axes和np.prod(generator)，run import partial_trace拒→改8a4去numpy/改prodloop但axes仍错→run prior_code拒→R6错误地否认自己import，改c1e仍重复axes→R7再次prior_code导入拒→R8错怪注释引用prior，把正文缩短e8dc仍重复axes→R9直接formal676e，没有一次真实运行partial数学。这是测试导入问题促使改算法/注释的具体路径，不是运行失败证明算法本来错。

11.10三轮：entropy7679正确np.where避0*log0；真pure/mixed2/mixed3/diag-zero输出0/1/log2(3)/1，warning可解释且不等于NaN，正式同稿。

11.11十轮：R1read空；R2拟沿用partial且run被未write拒；R3save534d独立收缩调用oldpartial；R4真重复axis失败。R5save744a将moveaxis source4对destination2，含顶层selftest；R6实际run另一长partial前，saved顶层先触发source/destination长度不等，**不能说R6inline长算法真正测过**。R7save d722仅移动bra轴，未对ket同时变换；R8save f2aa改partial接口为keep_sys，[1]保B，但full_perm仅赋前n轴，bra换而ket不换，一般双维不正确。R9真实Bell1、product00=0、maxmixed=-1看似正确（均特殊对称例）；R10用这三例接受并formal b68a同bra-only partial，官方W。不能说没目标测试，也不能把三例pass当普遍正确。存在真实目标数学缺陷/测试覆盖不足，但U的GAD与目标独立，四正式同GAD，早U到最后W唯一因果未知。

N1所有输出截断均已补：R9code675—1600、measurementR2代码2400—2700、R6长索引5502—18159、entropyR2完整重显。N2/N3/N4仍仅step1全读，其余未读。B102仍IN_PROGRESS，不计入101。

## N2已读到目标提交，36R36事件；两个显示边缘片段待再次精确补读

11.6七轮：空read→7068起大identity再kron导致真4vs16；738315改组合但旧reduce、Bob索引减m错，真AttributeError；b056改tensor后6d2d正式未重测。11.7四轮：595b用state[i]且双重idx/idx2求outer，不是one-particle正交projector；tools导入拒后重写再正式旧595b，无数值成功。11.8十一轮：最初复杂索引仅对角且float，真IndexError；castint后非均匀维真越界，模型自写的部分期望也错；INLINE perm+perm真重复axis失败，saved顶层测试同样失败；最后R10两半轴perm+n正确inline实际跑通，R11正式161ff105采用正确版本，不把该例一概说成坏perm。11.9七轮：91f473第一轮trace轴即超界；tools/partial_trace模块导入拒，R5真AxisError axis4；R6认为多次trace使轴变，改00aef不正确reshape和末两轴trace，R7正式未测。R4完整1973已重显补齐。11.10三轮：未write先run被拒，write1620，再无run直接submit；函数eigenvalues>1e-10近似阈值，不能把未执行的selftest记通过。11.11两轮：8d35744调用已提交partial_trace([0],[dimA,dimB])，无目标run直接formal，官方W。真实缺陷在继承错误partial，但GAD四路同稿，不能将后果唯一归因U。

## N3全部24R23事件已读

11.6五轮：构思A/B分开但初稿1846含旧state[i]及scipy.kron.reduce，测试output_state模块导入拒后错误归scipy→改089b np.kron.reduce，直接formal同089b，无数值测试。11.7四轮：c589/77d3用state[i]前m基矢不是onebit；write_code模块导入拒→read→formal，无实际projector测试。11.8六轮：先未write run拒→09ac索引映射→b0a错误itertools.product(*dim)→2317修列表和stride但逐行逐列覆盖Y；R5真实run输出额外非零及PSD False，R6长11954反复把错误输出等同应有四项、又指出测试index4/5期望错，最后把问题只归自写test，正式703b仍逐行逐列覆盖，未修真实PSD反证。R6初次输出尾截断已单轮完整重显。11.9两轮：read空，R2生成10000token/34659字符，持续重复reshape(dim)、trace/sum概念，未完成Call/未write/未正式；N3_S5_R2_EXACT_INDEX保存所有唯一原句及每次重复位置、覆盖True，完整读无省略，末尾确实停在“Let me use a simpler”。step未提交后继续后续子题是源轨迹现状，不补造提交。11.10两轮：entropy4f2a阈值清零，write→formal无run。11.11三轮：read空→19a07独立实现正确dimB×dimB、对k逐项求rho_AB[k*dimB+i,k*dimB+j]与两谱熵，formal dfc4同算法，官方C，无run但函数正确，绕过未完成/坏partial与perm。因此早期多个函数坏、partial长度终止，并不阻止独立目标函数答对；不能按此前尝试失败总数推断目标质量。

## N4全部28R28事件已读

11.6五轮：空read→3f53 selfcontained旧state[i]、np.kron.reduce；solution模块导入拒但错怪scipy，改dbed去scipy；formal又回3f53含scipy.linalg kron，未新run。11.7四轮：4f6f state[i]，previous_code导入拒→同稿重写→formal，无数值测试。11.8十轮：80e perm+perm重复axis，前部非均匀dims ravel也有潜在错。R2–9共8次真实run均在预先加载11.6正式scipy.kron时失败，未到本轮inline算法；模型从R4辨认priorcode但不断改当前测试，未改变前置加载，重复消耗8次。R10称测试环境问题而接受并正式f00c重复axis，未收到实际数学反馈。11.9两轮：9b65/3571依赖坏syspermute，reshape(keep,trace,trace,keep)后sum中间两轴不是partial trace，write→formal无run。11.10四轮：entropy09d7，2次run仍同历史scipy导入失败，formal同稿；明确不是entropy数学被实测否定。11.11两轮：8a0d selfcontained复制坏syspermute和sumpartial，write→formal，无实际目标run，官方W。与N3同样有早期错误，差别在目标N3独立正确求和、N4沿用错误接口，不能把早GAD提交相同却晚W因果写死。

尚需补N2两个边缘片段、四个首raw及原cutrequest/协议/成本/精确引用，才可B102 COMPLETE；当前B101封存数不变。

## B102封存前已完成

N2两个显示边缘已精确重显：11.6R2code[6000,6600)、11.8R1reasoning[7000,7900)；此前相邻范围已读。四个first raw request/response及原step05 round02 request实际SFTP取得。check_objective.py只做原文/SHA/U区间、精确保留状态、请求IDs、同seed响应、后续priorcode来源、Call/Return与预算/成本核算，146POST145events通过。特别逐字符核验四条GAD正式=P正确draft=原U正式，33a3同SHA。原cut即整轮起点，记录suffix57474generation389029Prompt60Actor59events；仍RECONSTRUCTED_CHAR_EXACT非原生边界。G6单列，新generation不含G。

Codex手写独立semanticJSON已写，resolve_evidence实际检查23条精确原文与9源SHA。初版两处引用被检查拒绝（N1CallID录入错误；N1full_perm语句错误），均回原JSON修成实际CallID和for-loop原文后重新通过，不放宽验证。N1目标特殊测试通过与N3正确独立公式反例均保留。后续需发布并核对remote bytes，完成后进度101→102，不提前计数。
