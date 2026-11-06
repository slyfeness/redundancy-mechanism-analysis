# B106 — 11__step7/S001（审阅进行中，不计完成）

对象SciCode100 CODE_STAGE V1.0。官方目标11.7，原W→W/C/C/N。切点实际是11.1R1@0，P只有原题及接口，draft/history/previous均空。U初次解释单基矢/多因子ket并保存numpy实现，含R2前23字符接受反馈，无数值测试或正式提交。G“Let me run a quick test to verify it works correctly for the different cases:”16词元，源S002R2[23,100)，预设已有可测试稿；没有代码或答案，但方向/状态预设明显，ORACLE。

原始SHA6deee3212381b579f68a782d0728247fc7e92f514a60be9080361c2d0d92fb10。本次完整重读11.1十一轮十一事件；其余11.2–11.7在同SHA的S005已完整读（该记录范围/长字段索引可核对），作为同源阅读复用，不能用旧结论代替新路径审阅。原11.1误把main/ket模块入口拒绝解释成numpy禁止，最终正式纯Python list-ket；11.2正确bit索引初稿后退化为vec[rail]/kron而非求和；11.4/11.6长度停；11.7按vec[rail]选错子空间，性质测试未查位置后正式W。测量函数没有调用ket，不能由初次ket删除唯一解释目标变化。

## 已完整读 N1：40Round40events，七个子问题

S1R1 G后先run inline ket，但因draft空被拒“write_code must succeed before run_python”。R2实际write正确numpy-kron；R3测试真实输出正确但自写expected错。R4手算纠正部分expected后再测，R5误认实现有错重新保存相同实质；R6再次错误expected多False；R7逐项手算确认并正式ac86e。U函数重建，原纯list换numpy，不能算绕过。

S2初稿用np.zeros(m)而不是2**m；真实测试from scipy.linalg import trace报ImportError、未到数值算法。R3认定只测试入口错误便正式282b错误广播稿。S3functools/模块import误归因，write/read/formal循环最终正确kron，无数值测试。S4初稿多残留pass，五次write/read重写，终采用同一K同时作用多个sys；scipy.eye测试入口失败，随后inline只看shape/trace，打印All tests passed但未assert正确目标，正式6bad。S5提交GAD正确公式，但对submitted_code进口拒绝误认np限制。S6空read→write输出→误认priorhelpers缺失全量扩写→formal仅output；无数值验证。

S7初稿正确二进制index，但P_single[idx_i,idx_j]=1双循环把不同one-particle态的交叉项也填1。入口prior_code拒绝后误认kron禁用，R3退化成global identity；R5又保存交叉项稿1281。R6真实inline测试旧初稿f498：只打印shape/trace和P²差数组，m2并非幂等，格式`.max()`是字面文本而非计算；没有assert。R7仍称tested且正式提交旧f4981585（不同于当前1281900字符）。最终W。N1尾stdout及R7完整补读，未遗漏。U已经重建，但目标独立错误/测试不足仍在；不能把W保持解释成U没用。

## 已完整读 N2：34Round33events，七个子问题

S1十二轮：R1同样空draft先test被拒；R2save错误kron(identity)/单基矢全零，R3scipy.linalg.kron导入错误；R4改import，R5真实返回错误2D数组。R6长12876全唯一/重复原文已读，N2_S1_R6_EXACT_INDEX；save58c6改flatten position但没有写1。R7全零；R8终于识别没设置position并保存，但R9没有新test仍引用旧失败，回退identity-kron；R10save181e矢量kron修好list但int分支仍全零。R11实测明确单int全零、list正确；R12只讨论list/expected自纠正并正式181e，忽略真实int失败。U部分重建（不是完整原产品）。R6事件代码在第一次显示末尾完整读、R7又精确引用确认。

S2按2**m维但用basis index=i而非1<<i；非法tools进口后inline只测m1shape/trace即提交7445（位置仍错）。S3write正确tensor→不测试formal。S4save同Kjoint与len(sys)==len(dim)错误约束；测试自身语法错误后read，随后prior_subproblem_4_code进口拒绝→直接formal4fe8。S5GAD正确但再次把prior_code拒绝误认numpy问题，重复相同write再formal。

S6两Round：read空，R2长度10000/55930字符，无write/submit。N2_S6_R2_EXACT_INDEX全部唯一和重复出现位置读完：反复讨论逐rail/错误dim=[2]*m及未执行import草稿，末尾重复四句约59次，无实际执行。真实length停不补答案。

S7五轮：R1只读空；R2真正采用bin(i).count('1')==1，单方对角outer后kron，save2790。其自然语言m2位置又说错但保存代码正确；R3exec入口拒绝；R4完整inline同正确代码真实shape/幂等(m1)测试返回；R5正式a903正确measurement，官方C。目标C不依赖有缺陷的ket或未提交的output；不能称删除初始ket改善整题所有子程序。相较N1，关键目标差异是选对basis及只取同态outer，且保留到formal。

## 已完整读 N3：47Round45events，七个子问题

S1首动作实际write而非空draft执行。初稿int分支提前return zeros；main_solution导入拒绝后read，R4修好提前return。R5–12无新数值测试仍反复声称旧错、改写/回退，R9/R10推理和保存逐字符相同。R13主动识别多余write并read，R14formal正确ff4d。U所需正确ket保存功能完整重建（不是说所有后续验证必要）。

S2先误用ket(m,[i])，真实inline m1因广播trace4、m2(16,)/(4,)不匹配；随后单独ket测试正确，仍往返m²/2^(2m)解释，R10说采用2**i却实际传log2(idx)=i，R11回退m²；R12正式997d21455字符，含巨量注释和顶层m1/2/3测试，仍m²错误。N3_S2_R12_EXACT_INDEX全部唯一/重复已读，首次输出截断后原字段[0,8000)、[8000,14000)补读；[14000,end)已在原index输出连续读到末尾，真实Call body已程序验证在此reasoning中精确出现。

S3先np.kron、后scipy.linalg.kron、再inline np测试成功（stdout前有S2正式代码顶层测试，不属于tensor验证），formal正确np循环。S4单Round38674字符长度停、零Call/提交，全部唯一/重复索引已读，只在sys/dim/同Kjoint之间反复解释和计划，无执行。

S5正确GADwrite→exec测试拒绝→formal。S6五Round四events：R1长19147推理识别旧编码m²问题，先read空；R2长23781实际save663c22575字符错误m²/float range/channel组合。R3reasoning为空但生成长度停有完整实际run Call23552字符，全文按N3_S6_R3_CALL_EXACT_INDEX读完；其测试根本没有调用output，只定义函数和截断于注释，stdout的m1/2/3来自旧正式编码顶层。R4长15615真正采用2**i和完整Kraus组合，save6e109120含顶层output测试，未执行；R5又长25544回退m²解释到length，无Call/formal。各长字段唯一/重复索引全读，R1截断小缺口[9380,9680)补读；R2/R4实际工具code均精确包含在对应已读reasoning（机械验证True）。

S7七轮：R1长13430认为ket为bosonic m维、误把输出维数当题目冲突，实际saveea46错误1D P_A并附顶层测试；R2真实run触发P_A outer广播错误，stdout前仍旧编码顶层。R3改2^m维/pos=2**(m-1-i)/只同态outer，saveff104。R4只read，无新test；R5却引用从未返回的4/16/64 rank1旧值，认为应改顺序，实际保存2312仍同correctpos，无实质错误修正。R6真实完整inline正确代码，stdout包含旧m²编码、当前保存测量测试、inline测量测试三组；后两组rank1/4/9。R7formal757c3811保留correctpos及对角outer，官方C。认知文字多次错不等于最终实际代码错；目标函数不调用ket，不能证明早期U是C变化的必要原因。

## 已完整读 N4：37Round35events，七个子问题

S1R1先run被空draft拒绝；R2write standard_basis全零；R3真全零输出；R4说修好却保存相同实质；R6终于设置j=1，R7又说没设置并read，R8真实输出simpleint正常，但dim=int,args=[1,0]仅返回长度3而非9，R9仍接受并formal e0ec。U仅部分重建，丢掉一类tensor接口。

S2初稿用ket(rails,positions)且最终idx=i*dim_B+i，工具入口test_ket/importlib/current_code拒绝被误认numpy/scipy限制；多次write/read改import，R11formal6615（不是最后b0f9）。无有效编码测试。S3真实__main__ tensor测试多例成功并formal。S4两工具后R3长度10000/50762chars无Call/formal；全部唯一/重复已读，首次index中央截断[10800,17900)补读，包含reshape占位/未执行embed草稿，不能当实际算法操作。

S5GAD真实from code测试返回完备性True后formal。S6full组合Kraus但额外除numcombinations；write c78e后output_state入口拒绝→错误归因函数内import，重写7b6e→相同非法import再拒→read→formal7781，实际把kraus_combo_2改成整份kraus_combos_2，未数值执行，不猜测试会过。

S7唯一Round10000tokens/66108chars，零Call/保存/正式提交，全文唯一/重复索引读完，首次显示缺口[7150,9600)补读。前段从全部one-particle转为first position的陈述，后段115次重复两句话；没有可执行测量产物。GENERATION_LENGTH_STOP实际37Actor，非100Actor预算耗尽。N结局不能认定算法返回错误值。

## 机械核对完成

四actualfirst raw request/response及original Round1 request已取原封存文件。B106_PROTOCOL_CHECK验证8源SHA/U字段区间/Call原文一致、P空初始状态、16G来源、四seed独立、1384输入IDs(1368P+16G)、max10000、随后prior code只来自本分支正式提交；158实际POST153事件逐一配对；后缀成本逐分支复算PASS。没有运行任何候选代码或模型。语义记录由Codex手写，统计脚本不生成结论。
