# B101 IN_PROGRESS，不计入B100

本组SciCode 11__step11/S011，不是上一S009。原C，四新N/N/W/N。原完整92R早先已读不可变SHA b5e6428a...；本轮完整U含两段及两事件重新读。U官方11.4R3@53—2168及R4[0,1802)，P保留R3前53字符“The error shows that `np.kron.reduce` doesn't exist. ”，当前draft3330的85fa...仍有不存在reduce/单sys列表长度错误。历史29Actor29工具。U实际write1948循环kron_reduce（6f4583...）修AttributeError，但未修单sys列表等；下一轮正式submit1643 cf6126...又回np.kron.reduce，没有复测。不是成功的正确性修复。

G为S012/11.5R1[0,30)strip通用“Let me understand the problem:”6Token，跨子问题来源但实际仍在11.4原R3续写，不注入11.5任务包装。四traj/四audit已SFTP取齐，8SHA与索引匹配。成本文件已取。尚未取四首raw及原R3request，尚未机械核验/写正式语义JSON。

## N1当前阅读进度

共71? 需最终按实际POST复核：列表9+4+15+5+14+20+3+1=71，前历史29→100，目标只write无submit而ACTOR_BUDGET_STOP。完整读到本地step6 R10，尚未读R11—20、step7三轮、step8一轮。其他三分支未读。

### local step1 官方11.4 9R8工具已全部读

R1先正确选择循环np.kron且真实write18951876...，同时全dimidentity_list修了长度，但多sys仍同Ki；R2实际inline却旧len(sys)及identity_list[1]→IndexError。R3真实write2259bd00单sys按len(dim)嵌入，其多sys没处理；R4再次inline旧len(sys)→matmul4vs2，没测试新2259。R5误归次序，实际写16576fdd又不存在np.kron.reduce；R6实际触发AttributeError。R7明确识别不存在reduce，实际save1767e421循环+全dim，U核心修复重新实际发生；R8实际run却内联旧reduce，并先用2x2K作用4x4rho/sysNone，真实先matmul4vs2，未测新save。R9万Token35789（N1_S1_R9精确索引所有独特原句及位置已读）先正确识别selftest维度不相容，后在应扩K/测试错之间大量重复，无新Call或正式通道。不能把run旧代码说成最新修复未生效，也不能说所有怪测试都错归因（这次测试本身确有错）。

### local step2 官方11.5 4R4工具全读

正确GAD9133305...write；prior_functions导入拒误归numpy；真实inline给四K且sumK†K=I True；正式同913。

### local step3 官方11.6 15R15工具全读

R1长9760正确讨论独立4^(2m)组合但只read空；R2真实write7884cce7含正确itertools.product组合和P的错误state[i]编码。R3tools导入拒→R4误说write不正确，实际换3190feb1仅两qubitK_i⊗K_j两次作用，不一般m；R5再同tools导入拒。R6真inline2561把K1⊗I_dim⊗K2过大→matmul4vs8。R7save3330358c把两个扩展再tensor使4vs16，含顶层test。R8实际inline别的旧算法，但saved顶层test先触发4vs16，inline根本未执行。R9拟改生成组合并run，但saved顶层同错先失败，不能说新生成路径实测失败。R10save346776ba硬编码四重K组合不按m，带顶层test。R11 inline尚未执行saved顶层就4vs16。R12save30181c5f继续过大K+I，R13save40997cdd尺寸调成K1⊗I_2^(m-1)⊗I_2^(m-1)⊗K2但rho_out=rho又+=重复，带顶层。R14真实stdout先saved trace2.36989，再inline较合理组合却每K覆盖rho_out、从rho.copy加，m1trace1.012/m2trace1.000072；R15以“约1浮点误差”接受，并正式225929de又回K1⊗I_dim⊗K2错误大小未复测。可观察反馈按宽松预期接受与submit版本回退，但最终目标无Final不能假称正式回答错误。

### local step4 官方11.7 5R5工具全读

write110980f2全A×B projector结构对，仍state[i]错误不是onehot；两次prior_functions导入拒，期间actualwrite同稿误怪numpy；最后正式同1109，未真实数值验证。

### local step5 官方11.8 14R14工具全读

read空→write108991c5错误new_axes=perm+perm→真run repeatedaxis；R4怪perm本身重复、实际写1189243b仍同错→R5syspermute导入拒→R6长10668终于认识axis重复来自两half但未+n，改逐索引16401dbe（逆序decode未逆回、np.prod空切片float）；R7prior_subproblem5导入拒，R8实际inline IndexError float。R9save1736ee60把np.prod转int，R10run内联旧float但saved顶层Y先成功打印，inline再失败；R11save1738b295反把cast放indices而不是np.prod，float仍在；R12run又旧同错。R13明确“test still old”但真正save1023662c又回perm+perm并顶层test，无run。R14没有新Return却声称test成功，正式945fe9f同重复轴；不能把write ACCEPTED当数值通过。

### local step6 官方11.9 已完整读R1—R10（10事件）

R1save9347e70f，把D=prod(dim)再total_dim=D**n_sys，误把bra/ket轴当Alice/Bob两个物理Hilbert系统；perm+perm/独立sum/keep_dims列表索引等同时错。R2prior import拒→R3误归numpy/重定义冲突、save2056bc17缩短仍D**n_sys及双sum；R4同prior拒→R5save167253db无perm但D**n_sys/双sum仍在；R6sys.path/current导入拒，未实际运行（且测试rho误标Bell、维度期待也错）。R7再怪numpy，用read确认草稿；R8真正inline简单4x4 state触发Expected16got4。R9文本曾正确说prod(dim)=4，但又解释Alice/Bob重复而改total_dim=D**2，save2152576c。R10真run内联旧53db，Expected16got4仍在。**尚未读后续R11—20，不推断最终partial动作。**

### N1后续补全，71R/69事件已全部读

11.9R11长14023真正辨明dim为全物理子系统尺寸，实际write1917ae57修total_dim=D，但双独立sum/列表索引仍错；R12没有新Return却重解旧shape错误、怀疑测试换dim，actualwrite200660e去shapecheck又留D**n_sys但unused。R13实际run内联OLD53db，又同shape16vs4，未测试修稿。R14—15再次认识D=prod(dim)，save16716fa5及16633377，仍独立sum及dim[keep_indices]。R16真实测试终于过shapecheck但list索引TypeError；R17—18两次实际save完全同16767e30，改listcomp。R19真正run：I4的两个迹均2I是对的，模型注释本来误标|00><00|；Bell返回[[.5,.5],[.5,.5]]应I/2真错，多sysreshape错误也真实。R20万Token44398（N1_S6_R20索引完整独特原句、重复位置，输出截断6789—7838已补）先把I4→2I错当错，再回Alice/Bob各dim错误解释，反复reshape(4,4,4,4)无实际Call或submit。partial无正式。

11.10三轮6685e59滤零熵，真pure0/mixed1/log2(3)通过，误标I3为pure但0公式未归一情况下正确；正式同668。11.11仅1R：推理完整2468正确np.trace0,2草稿，但**实际工具是read_code返回空**，并非write；累计100Actor用完，ACTOR_BUDGET_STOP，目标没有正式submit，官方N。正确思路曾形成但没有转成正式代码；不能将这条解释成提交了错误coherent函数。预算消耗具体来自早通道9轮、output15轮、syspermute14轮、partial20轮（另GAD4/meas5/entropy3/target1）。早U的循环修复已实际恢复后又反复/未提交，与原U正式回旧reduce不同；最终N是可见预算路径，不证明早U唯一必要。

N1全读完成；N2/N3/N4尚未读，B101仍IN_PROGRESS，不计入B100。

## 后续阅读：N2已完整41R38事件

8个子问题全部Reasoning/Call/Return已读；N2_S3_R4、S6_R8/R12、S8_R4精确重复索引各全部独特原句及重复位置已读，S8R4截断3944—5169已补。11.4两轮实际循环修复write后正式1828d8但未测试；11.5真实完整性测试通过。11.6四轮先read再run被拒，保存7683含dim=[2]*m不够2m，实际matmul16vs4，万Token反复未正式。11.7 projector仍state[i]错而非onehot，导入拒后直接正式。11.8手工inverseperm仅二元交换测试合适；真实三元[2,0,1]输出index3而自拟expected6，模型仍称全过正式。11.9十二轮：双独立sum/错误axes，混用4D测试输入与应为2D接口，导入拒误归numpy，真实Bell返回I trace2而应I/2；|000>的正确结果却也被错预期混淆。R8实际save单sum仍错，R10改双sum，R12万Token未提交。11.10熵正确write后导入拒/read/formal无真实数值验证。11.11R2实际保存136627dd包含正确sum_i同索引但sqrt(rho.shape[0])断言错；R3实际inline移去断言且np.trace0,2，Bell约1和I4/4 -1都正确，但自拟Expected0均错；R4万Token后来明确承认公式正确、预期错，却继续反复未submit，GENERATION_LENGTH_STOP，官方N。不是“错误输出导致N”，是正确测试结论未落实正式提交，saved仍错误断言。早U修复已重建，晚目标无依赖通道，不能唯一归因早U。

## N3完整36R35事件已读

11.4四轮：R1长13054在K⊗I/I⊗K及自拟不归一测试间往复，推理提functools.reduce却实际write d993仍np.kron.reduce；R2真实AttributeError；R3真实save fc1cf改functools.reduce；R4正式又回d993旧reduce，无复测。这与原U的“修稿后提交旧稿”同类可见链，不是该功能从未恢复。11.5三轮真KdagK=I双参数测试+正式正确。11.6十轮：先read/run被空draft拒→保存9ad含错误state[i]与dim=[2**m,2**m]，output_state导入拒误归numpy；实际inline旧reduce失败；R6真save loop013a，R7run仍内联旧reduce又失败→R8又save b18循环→R9真实rails1 shape4 trace1→R10formal e0d，同算法rails>1仍错，不能由一个trace测试推全正确。11.7五轮真正onebit indices修编码理解，全A×B projector真rank1/4/9测试后正确正式a031，反例保留。11.8三轮真实手工置换02c总体索引正确；自拟24维index6应解[0,1,2]→13，不是注释2，Return Y[2,2]=0/Y[6,6]=0，R3却虚称到了2。不能把测试预期错判实现错。11.9四轮：read→save7a276未调用syspermute且reshape(keep,traced,traced,keep)/trace1,2有错；Bell两边恰好通过，3qubit实际结果size8不能reshape4,4；R4万Token44224反复归错到reshape总元素（2*4*4*2=64不是256），没有新Call/正式。索引N3_S6_R4所有独特原句及位置已读，截断3440—8453已补。11.10先run因未write拒→save正确zero-filter1b896→formal，无实际成功测试。11.11四轮实际save3ef7含独立i,j双sum错误partial，run因write_code import denied，read同稿后以“accepted”直接formal同3ef，无数值测试。官方W有具体错误partial与未验证提交支持；不能说早channel修复缺失直接造成独立coherent错误。

N4尚未读，首raw/协议未验收，B101仍IN_PROGRESS。

## N4已完整71R70事件

11.4八轮：R1实际save050595正确loop/全dim；R2实际inline旧len(sys)维度4vs2（K本身也不完备，trace2不可归通道算法）；R3save b6bd又回np.kron.reduce→R4真实AttributeError；R5save da479循环但单sys仍len(sys)→R6实际run在scipy.linalg.kron import失败未运行；R7save f8e5循环+全dim→R8formal f630循环，全局U核心修复真实恢复，但无最后数值测试。11.5七轮两个导入拒被错怪numpy/write，后真实KdagK=I后正确formal9ae。11.6六轮：read空→实际save f673（旧错误state[i]、每方同Ki共用所有rails而非独立组合）；sys导入拒后重写相同SHA；真实m2输出trace.235924，R6称“两信道所以trace<1”而接受formal c833（没有后选择，这不是充分性证明）。11.7四轮 projector b9e采用前文错误state[i]而非onehot；导入拒后真测试只数4个非零，无位置校验，却称one-particle正确→formal1fc。11.8四轮save c263中multi_to_linear以int乘list切片然后+=，run导入被拒，read后直接formal fbfa，无真正数值测试。

11.9四十轮39事件，全部原文/参数/返回读完；首9451代码尾6000—9451、R2/R3因显示截断都已补。R1不完整pass/itertools.product(*ints)/错误list乘strides，R2真实TypeError int not iterable，模型错归单元素list不是list。R3—7反复改包裹/非trace索引，但R4/R6运行仍int迭代失败。R8一度识别ints非iterables却改[[dim]]值本身（应range），R9重写又回ints，R10/R12/R15/R20都真同错误。R11/R13/R14/R17—19未有新run也继续说错误persist并重写。R22最终真正选range修复，R23未测试就依据旧Return回退ints；R24怪cached/previous code，R25真旧int错。R26—30再次错误归test位置/作用域，R28真实debug明示traced_dims=[2]且type=list，仍未采用需要range的结论。R31再修range，R32未测又回[[dim]]，R33再次range；R34真实执行终于过product而触发multi_to_linear int+=list，验证不同错误已分开。R35—38连续实际save修strides（无run）；R39真run输出I4→全2，I8→全4，|00>→全1 trace2均有实际错误，源为对remaining linear index按全dim解码再去trace轴，将不同输出行/列挤到同值。R40万Token25461又在I4该I2还是2I2、自拟预期与同索引上往复；部分公式正确但反复错误代入，没Call/正式。N4_S6_R40精确索引全部独特原句/重复位置已读，截断6889—18241已补，绝不能把其中的错误手推当数学事实。11.10两轮entropy2738写后测试import my_functions拒，累计100Actor，无entropy正式也未进入11.11目标，官方N。消耗具体为partial40轮39事件，与早通道修复不是函数依赖的必然链。

四分支共219POST212工具已读；B101仍待首原始请求/响应核对、精确证据记录及封存，不计B100。原切点后成本正确口径63Actor62工具（不是71/70），生成保守[59050,59586]、Prompt400261，G6/P replay4193；此前备忘若出现71为新N1/N4而非原后缀。
