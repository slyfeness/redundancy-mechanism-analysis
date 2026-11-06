# B99 IN_PROGRESS — 尚不计入B98

对象SciCode11__step11/S008，目标11.11而U在11.3R4@0。原C，四新W/C/W/W。9源SHA中的四trajectory/四audit已核对，原trajectory与前面各组相同；U两个Reasoning及两事件真实测试/提交已读。P当前tensor564字符8e7e8f...已保存两次（前3当前Call都是write），历史25Actor/25工具。U混合vector/matrix四组真实测试后正式同稿；向量输出1D，不以通用“通过”证明docstring2D契约。原目标正确直接np.trace0,2独立于tensor。

G只有Let me understand the problem:（6Token），原S009/11.4R1[0,30)，跨子问题但没有具体新实体/事实/任务方向。P_current空，base3012，实际3018，max10000；原渲染未转发3044字符历史reasoning，需逐原请求核验披露。未下载首raw/未统一协议成本验收。

## N1 已完整读完45轮45工具

9子问题11.3—11.11，完整Reasoning、tool code与Return均通过read_exact_diffs逐字段阅读；截断缺口S2R1[4700:8100)、S4R2[4800:17219)、S4R8[8800:14000)、S7R1[1380:2850)分别补读。

- 11.3 2R：重新判断*args，实际测试vector/matrix/3vector并与np.kron比True，正式原5648e7...；U真实功能完全恢复，删后未跳过。
- 11.4 3R：长11639字符推导，实际write42414a4...仅sys首项，run前两identity成功后自己测试N未定义NameError；明确归测试而接受同稿正式，无多sys证明。
- 11.5 5R：963e2c...正确GAD；subproblem_5_code导入拒后误归numpy→移除numpy写943917...；随后内联真正completenessI及4K值通过，正式回含numpy963同e2c...。有效修复/测试反例。
- 11.6 10R：Read空→长22186推导含完整组合与逐qubit计划，实际save491846a...逐qubit独立channel（初态仍旧state[i]）。R3实际测试却内联按整体4维而非逐qubit版本，matmul16vs8；R4save583200e...扩K但还带top-level test；R5run又内联旧未扩K，stdout先出现saved顶层测试shape/trace成功，之后真正本次旧inline仍matmul错，不可只看stdout判pass。R6save57177329...误把syslist应用同Ki且dim_sys仅两项；R7Read旧，R8长18119推导后save405746a8...全4**m组合、原state[i]；R9实际run同完整稿，两个同样shape/trace输出（saved+test顶层），成功；R10正式3923852f...去顶层测试。维度问题实际通过改全组合缓解，不证明编码正确。
- 11.7 4R：12894939...仍i*2**m+j而非onehot，reason来回匹配/非匹配候选但最终错误编码；subproblem_7导入拒，Read后误归numpy又正式同稿，无实际projector结果。
- 11.8 3R：11973763...syspermute perm+perm重复轴；run自己scipy.linalg.tensorproduct不存在ImportError，认为只测试错误便正式同错稿。没有实际执行transpose值。
- 11.9 5R：write2006839...正trace1,3但依赖badperm；真实inline测试先repeated axis。R3/R4实质认出重复轴又恢复“perm+perm正确”，长11143推导改einsum aija（本身错），write1688ecbd...仍调用badperm，直接正式，无再测。
- 11.10 4R：831e5e...eigvalsh非负+epsilon；prior_model_code导入拒误归numpy，移除import保存811b206...，正式回831，同算法，无真实entropytest。
- 11.11 7R：Read空→write685ab68...调用badpartial。真实Bell test repeated axis，R4长6321说修syspermute却write完全相同685；R5长15806反复einsum/轴讨论，多次出现正确ijik->jk又改错误ktkt->k，仅write同685。R6宣称完整修helper实际只write684同调用版（末尾换行差异），R7正式同6846e4b...，W。反馈已识别但没有进入实际保存/正式依赖修复。

N1具体链：早期tensor测试重建且正式不变；晚期真实依赖错误→已识别重复轴→多轮只改口头推导/相同调用包装→正式保留坏helper→W。原早U到晚期独立算法的唯一因果桥未知。N2/N3/N4尚未读完，不写COMPLETE或机制标签。

## N2 已完整读完63轮63工具

全部9子问题真实Reasoning、Call/code、Return及正式提交读完。S7R2长17518字符中截断[1100:14500)补读；S7R4实质run参数18095字符单轮完整再次读取；S7R5—R8完整另读以补之前大批截断。没有未读缺口。

- 11.3 6R：main导入拒→误归numpy并write544209...去import→prev_subproblems导入拒→Read→真正内联tensor四组vector/matrix/single测试成功→正式回原5648e7...。U真实测试/接受/正式功能恢复，结果C；测试恢复不独自区分本组W/C。
- 11.4 4R：write4898c6c...同Ki应用多sys（非独立组合）；scipy.linalg.eye导入失败后真实内联三例，fulltrace1/singletrace1/bothtrace0.5，仍说passed并正式3833dfe...，没有处理非保迹证据。目标最终C不认证该helper正确。
- 11.5 8R：1297bf0...正确GAD，两个subproblem_5_code导入拒→反复移除/加回numpy，实际先测np.kron(K.T,K)误当K†K而4x4减2x2失败；明确纠正为K.T@K，下一真实I检查True，正式10286a9...。测试方法纠正真实生效反例。
- 11.6 6R：两次Read空（第二把编码代码传read无保存作用）→write50801b7...完整4**m组合tensor(*ops)，复制旧错state[i]；output_state导入拒→实际内联m1 shape4/trace1成功→正式same。通过维度/trace不证明物理编码。
- 11.7 7R：思维在各方单激发/全局单激发混杂→save3353389...错误m×m全1P_A/m×mI P_B，sys路径导入拒；改799528...为m×m I⊗I（维度仍错）→再次同sys拒→Read→正式同799。没有真实projector数值，更不因目标C当已验证。
- 11.8 8R：write1144373...错误reshape/两轴；subproblem8导入拒→save1156d717...更错reshape→exec测试拒→实际inline旧1144报axes mismatch→write133672db...新reshape有额外dim0、axes交错；真实candidate import运行报reshape16进6维→误读dim为4子系统→正式11539bbc...仍额外totaldim与n轴，无实际成功。
- 11.9 17R：R1长9999推导Read空，R2长17518后save20347e67...带额外totaldim/sum，两真实run分别badperm reshape/本体reshape失败；R5改去totaldim实际run但n轴transpose失败；R6长解释继续实际同n轴失败；R7长7226推导修改的是测试内联syspermute但partial仍n轴，仍失败；R8debug真运行返回I/4被变成rank1样矩阵却说syspermute works（可见反馈未正确采用）。R9debugpartial直接显示new_axes[0,3]后报axes mismatch。R10save2395e5a...把new_order与n+order交错；R11实际test又内联旧n轴再次失败。R12长12043明确推导成完整两半new_order+[n+order]并真实save22351605...，不再依赖syspermute；R14实际前三I/Bell测试对，Test4返回正确2×2却误期望4×4失败。R15正确指出测试期望错，write225542ad...含numpy；R16真实又沿用相同错期望，仍先三通过/第四shape错；R17据题目维度正确接受并正式同2255。实际算法是reshape(dim+dim)→两半轴→reshape keep,trace,keep,trace→transpose0,1,3,2→trace1,2，最终正确摆脱错误syspermute。多次口头“我懂了”直到R12才真正改入待提交代码。
- 11.10 3R：903560...eigvalsh+epsilon，真实pure/mixed等测有效；所谓Bell其实对角混合态结果1，被口头误称最大纠缠熵正确，但函数代码本身合理，正式same。
- 11.11 4R：write9279d52...调用已修正partial_trace，第一次sys导入测试拒→第二次实际使用|00>+|01>乘积态误称纠缠态，结果约0，接受并正式same，官方C。不能称其实际Bell测试通过，但正式helper数学正确且官方C。

N2与N1最有信息的对照：两者都重做同tensor测试并正式原564稿；晚期N1知错却只重写调用包装仍依赖坏perm，N2经17轮真实把轴修正落到partial_trace正式实现并摆脱坏perm，目标同样调用helper却C。不能把这种晚期恢复/正式采用的差异全归早期tensorU必要性。N3/N4未读，不计本组完成。

## N3 已完整读完43轮43工具

全部9子问题/43轮43事件完整读；首次S2R1 write11444字符被截的[1800:3600)单独补读，无未读缺口。

- 11.3 2R：真实tensor三组vector/matrix测试输出正常，但打印expected shape(2,2)/(2,2,2)与真实1D/2D不符，没有assert，仍说alltests并正式原5648e7...。U功能恢复，部分接口检验仍弱。
- 11.4 7R：save114443c94...复杂embed多sys混合，prior_code导入拒两次；误归numpy/复杂helper，Read后save33703b87...只支持单sys；内联另一简化版真测试full/singletrace1、第三自造非TP Kraustrace2，仍passed；正式16323b33...只支持单sys。第三trace2本身不证明代码错，因为测试K不是TP，须保留区别。没有多sys成功验证。
- 11.5 4R：109492b...正确GAD；run测试竟含from the current code语法错被拒，Read后正式同稿，无实际completeness。
- 11.6 5R：Read空→save78727233...复制ket/statei/tensor/single-syschannel/GAD，output把m个qubit当整体2**m而只应用2×2K；output_state导入拒→声称自包含实际save同7872→正式same，没有数值，m>1显式维度不匹配风险。
- 11.7 4R：run-before-write拒→save1360c57...只sum_i matching i/i，且state[i]而非onehot→真实testm2rank2/幂等True（题目应rank4）；把自己预期m当正确，正式same。证据是真输出，正确性接受错误。
- 11.8 5R：run-before-write拒→save126347a...把X保2D配4axes→真实axes mismatch；save37274567...改dim+dim但perm+perm重复轴还含top-leveltests；未复测便正式1208800d...同重复轴、去test。
- 11.9 4R：save2050c919...badperm+reshape(dim_keep+dim_trace)仅D元素承载D²矩阵，本身错误；prior_model_code导入拒→去numpy save202902b...→正式2049911...加回，无实际值。
- 11.10 4R：run-before-write拒→6526d78...→真实五测pure0/mixed1/log3/eigen[.8,.2]正确→正式same，反馈采用正例。
- 11.11 8R：Read空，首run只是计划未write被拒（Bell S_AB=1/coherent0的reason期望本身错）→save8831366...callingpartial→save4897b94...复制badperm和partial及entropy→sysimport测试拒→save47009b61...调顺序（同badhelper）；R7真实run内联DIFFERENT独立版本np.sum(axes0,2)，Bell输出0而expected1；R8明确恢复正确Bell熵/应1，但又猜“partial其实正确，可能造Bell错”，实际正式4522743...返回早先坏helper（perm+perm重复轴、D元素reshape），不是修过inline sum的版本。官方W。必须区分当前saved/testinline/formal三者；不把运行exit0当通过题目值。

N3链：早期tensor验证/正式恢复→晚期可区分Bell反证已真实返回且明确识别→错误定位为可能输入造态→正式恢复未验证旧helper→W。与N2真实修正入正式形成反例对照，但早期删除的独有影响仍未知。N4尚未读完，本组不COMPLETE。

## N4 完整读完52轮49工具

全部9子问题，S6R15长37036字符通过精确重复索引所有独特原句/出现位置完整阅读，无截断；S2R2长41477此前也补读完成。另N1实际POST43但round条目45，须以request_sent真值核对，不把占位当Actor。

11.3实际tensor5类输出后正式同5648e7，U功能恢复。11.4 R2万token设计各种joint/sequential channel后length，未write/submit。11.5正确GAD真实completeness通过正式。11.6 m**4与4**m混淆、初态仍state[i]，m2测试恰数量相同通过后正式；不证明编码。11.7 projector错误pos越界，实际m2 IndexError后R6在纯草稿识别onehot却又回state[i]，无工具/正式。

11.8 15R14工具：badperm+perm保存；syspermute/tools/syspermute_code非法导入多次，误归numpy反复重写同稿；R9真正inline repeatedaxis→R10明确两半轴并实际write1093 eb310...正确+n偏移。R11工具IMPORT_DENIED却被R12误读为重复perm问题，实际write3066 a8b7...回badperm，R13再次1096 73b7...badperm，R14 candidate实际repeatedaxis；R15万token反复轴方案而length无正式。关键是正确修复确实一度写入，又被非数值导入反馈错误归因撤回，并非从未想出+n。

11.9 13R：11.8未正式故P不含syspermute，R1 explicitly看不到，run-before-write拒→write2557 c7df...错interleavedreshape；R3长6057 syntax拒；R4save4478 789...重复轴和测试；R5/R6 inline提出替代但saved顶层先失败，不能认为测试内联已执行；R7read确认旧稿。R8save3327 d7...stillbad，R9inline旧仍fail；R10save4277 243...两半轴，对于单trace可用但多trace未更新轴；R11 saved顶层前三数值true、第四AxisError，部分执行不能算全通过；R12声称修多trace实际save5045 e30...回旧badperm；R13正式2610 831...来自早先badperm不是正确两半轴。

11.10 4R712 2389...entropy实际4例通过正式。11.11 3R首test-before-write拒（所谓Bell矩阵非密度矩阵，不能算值证据），R2save3178 4e9...内复制正式badpartial→R3无再测同稿提交W。U tensor全部恢复；晚期修复曾写入但后来错误归因回退、实际正式坏helper并用入目标，能定位W路径。早期tensor测试删除到晚期此失效的唯一因果桥仍未知。

成本口径更正：cut_char=0的原请求63118 Token是整个实际生成后缀记录，区间[63118,63118]，不是此前笔记假设的[62531,63118]；仍RECONSTRUCTED_CHAR_EXACT，不能冒充native精确节省。
