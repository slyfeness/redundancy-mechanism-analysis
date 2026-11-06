# S008执行检查点：原路径及NEW1全读，NEW2—4未读

本轮目标仍全部A133+B116=249组；本组未COMPLETE、不计A127。上一组S006已全完成并发布回读，A126/B103=229组916条。原始数据不变，无GPU/新评分。

## 原始P/U/Z/G

共享原11.1—11.10已完整读过，本组重读U全文、真实R9测试Return、实际冻结INPUT当前prefix/draft及R10局部后继。
U11.2 R10[279,2192)，1913字符，纯推理，反复核对m1/2的非零位置，在5/10和错误6/7/15之间摇摆，最后接受实现。代码状态未改变。P当前279字符已说m2 trace1/sum2正确、m1底右格符合|11>；真实R9原run用标量[1.]逐qubit生成正确基矢，m1/2/3形状与trace均成功。保存draft f91a788ae170f8e997d009c2498cd601f794776ebfd7f2a1b938ea06127cd800是正确版本，不是S006时的错误draft。
G原S009同R10[2192,2288)：Wait, actually the sum of all elements should be Tr(ρ) * Tr(I) = 1 * dim = dim for a pure state. 这句数学说法错误；并非新正确事实或修复。P已接受sum2，但G又打开疑虑。须单列误导风险，不能把所有新怀疑归删除U；ORACLE_ANCHORED。
原后续反复讨论sum/trace，最终区分总元素和不须1并交正确实现。靶11.10 entropy独立，不依赖multi，官方4C不能认证每个中间函数。

## 来源及输入

EVIDENCE_INDEX四branch均V7；四trajectory及INPUT SHA逐个相符。最初按trajectory raw_request中的/dev/shm旧路径抓取失败，是本地取件方法误用临时路径，非原件丢失。随后根据官方index的封存branch目录下载全部16个首请求/响应/逻辑输入/解析流，成功，无重新运行。
verify_saved_case_protocol.py四PASS：总240轮236真实工具事件。cut真实11.2 R10@279，基础6551+保留71=6622，G30，首输入6652，首生成9929；边界RECONSTRUCTED_CHAR_EXACT，无移动切点。
四新轮次/事件：NEW1 52/51、NEW2 38/38、NEW3 64/61、NEW4 86/86。只有NEW1已完成实际语义阅读，不能把protocol通过当全部语义读完。

## NEW1完整52轮51事件阅读

1. multi1轮：沿G先误以sum应4/16，继而根据状态结构接受sum2，手算0/15等位置仍错；直接submit1601字，全文核对保留P正确标量[1.]构造，无新测试。认知位置审议部分重现但无需改代码，最终并非因错误手算而实际改坏。
2. tensor8轮：*args逐kron实现正确；三次from main导入实际IMPORT_DENIED root main，却反复归numpy/函数内import，改写正确函数/删空参校验、read、最后401字正式。无一次数值测试真正执行。
3. apply6轮：首3980草稿含死代码、同Ki到多个sys（独立通道不完整）。run scipy.linalg.kron ImportError，换合法内联得到float加到int zeros_like真实cast错误；正确诊断dtype，保存float64版2616，read后直接交，未复测修正。完整系统与子系统维度检查以及多目标通道仍未全面验证。
4. GADC5轮：正确四K863稿，prior_code导入拒；换内联却检查KK†（非保迹必要条件）。N=.5得到I，gamma1N1得到diag(0,2)，模型错误解释为物理边界/给定公式问题，最后选择信任题面同稿交。算法仍正确，检验判据错误，不以假False指称正确函数坏。
5. output6轮5事件：R1正确说dim应覆盖2m，但R2实际6023稿仍dim=[2]*m；m1真实4vs2失败；R4又保存5701稿却仍原m维，R5真实同错；R6完整49163字符/10000Token反复讨论维度推断和待修，未write/submit。正确判断出现过但未进入实际参数。
6. measurement14轮14事件：正确独立Alice/Bob投影理论，实际basis=np.zeros(dim)后kron导致零且维度增。连续subproblem7导入拒被错误归numpy，改写多次仍同错；R10终于合法内联真m1(2,2)对(4,4)失败。R11文字承认零向量错误，却actualwrite1627仍同零向量；R12 sys加载拒；R13read，R14用理论预期m1rank1/m2rank4宣称正确并同坏稿交。不能把预期rank当真实Return。
7. sys5轮5事件：np.ndindex遍历、按正确后缀维度计算perm_matrix，2470稿数学上合理；两次run从syspermute导入被拒，无数值结果；read后同稿交。测试草稿有|101>索引写4等错误，但未执行，不误记反例。
8. partial3轮3事件：首17631字实际write塞入大量推导式注释/死代码，先X_permuted.reshape(维度乘积只有D)对D²本就错，后还X.reshape(dim,dim)、未定义product_traced等；run合法代码入口实际因scipy.linalg.kron导入在调用前失败，无数值。模型据“测试入口问题”直接交2334稿，完整核对：省掉syspermute，traced_bra/traced_ket独立双循环、结果[bra_flat,traced_ket_flat]索引也不对应正确输出；无修复测试。
9. entropy4轮：先空draft run被拒，write747谱mask后真实pure0/mixed1/diag(.7,.3).881290899与手算相符，同稿交C。这一独立成功不证明前面output/partial完成。

## 原文显示覆盖

GADC4—5/output1—3混合读取一次截断，完整重读output1—2已补齐；GADC部分本来完整。sys3—5/partial1—3混读截断，缺失位于partialR1 write参数[约4000,14398)，已直接全文补code[3900,14517)，其余reasoning/call/returns全可见。没有NEW1剩余显示缺口。逐次字段位置由LITERAL_READ_REFS_NEW1保存，完全重复段引用原已读位置，非语义删选。

## 下一步

NEW2从step0 R1开始完整38轮38事件，然后NEW3、NEW4。成本COMMON已取回尚未分析；不提前填机制/成本或MODEL COMPLETE。旧S006已经封存不要重做。
