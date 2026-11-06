# S007 模型逐路径阅读检查点（历史逐步笔记；最终以MODEL_REVIEW.json为准）

最终核对更正：四条续跑235轮、233工具事件均已完整阅读，39条精确引用核验通过。NEW3的R5临时函数测试正确，但R6正式1736字符代码回退为np.eye(dim)逐位kron的错误版本，不能说正式产物恢复。下文“R6正式1736代码恢复U核心产物”是此前阅读笔记中的误判，由正式代码全文复核纠正。NEW4也已完整阅读：最初保存1484字符正确函数，测试却执行旧错误函数，随后改回错误版本；正式1688字符仍错误。最终目标熵函数C不认证此前辅助函数。具体四路判断、版本差异、成本及限制均已逐项手写于MODEL_REVIEW.json。

本记录由 Codex 实际阅读原文后直接撰写。原轨迹已完整阅读；本轮再次核对 U/P/G。四份实际首请求和状态协议已由只读程序核验，235 Round、233 Call/Return，不代表语义审阅完成。

## 原 U 与引导

U 位于原11.2 R8[5729,8655)、R9[0,54)、R10[0,279)，含 E008 write_code 与 E009 run_python。关键不只是确认单激发基矢：R8 的解释代码仍有零向量初始化问题，但实际 E008 写入改为标量1的正确构造，E009真实数值测试显示m1为4×4的|11><11|、m2为16×16且迹1。U使此前错误草稿变成实际保存且测试过的正确版本。G为“Let me verify the state structure more carefully. For m=1:”，原R10[279,337)，14 Token；指向m1复核，m1对象已在P，不含被删测试结果。P6598、P+G6612、首请求max8110。

## NEW1 已完整阅读70R/70工具（官方C）

11.2四轮：R1保存1199字符错误零向量代码；R2内联测试有裸|0>语法错误；R3临时定义标量1正确函数，真实m1/m2测试成功；R4正式提交却用[1,0]作初始向量，额外增加一个qubit。知识、测试函数与最终提交三个状态不一致。不能以R3成功认定正式产物正确恢复。

tensor九轮，多次导入不存在的prior/current模块被拒；一度误解为numpy/functools不允许。最后提交tensor(args)列表接口，未验证可变实参。apply三轮错误重复扩维、多目标同Ki；测试被scipy.linalg.eye导入阻断，仍提交。GADC四轮，真实内联测试正确并提交。output五轮，文字谈4^(2m)组合，代码却仅16种K1⊗K2，不适用一般m；导入失败后改写再提交旧版本。measurement六轮重复额外qubit初始化，测试被拒，未数值验证。syspermute五轮，交错行列轴，Bell矩阵实际变成I4，日志打印“All tests passed”后接受，不能当正确测试。

partial_trace三十轮：R5/R7重复轴报错→R8修正列轴偏移；R9/R11 Bell给全0.707矩阵，之后修正测试归一化仍全0.5。R13有真正AssertionError，R14–18反复重推；R18已说必须k=l，却写独立求和/reshape错误。R19显示2×4错误维度及独立手工I矩阵，R20一度把后者当正确依据。R21/23仍区分手工正确I/2与函数全0.5；R24保留错误einsum，R25再次失败；R26终于把ikjl改ikjk；R27同一执行中当前候选测试正确、随后旧代码里的顶层测试又打印错误。R28已经识别前后版本混杂，R29却又长篇重推并改成等价的ijkj；R30未再run就宣称全部通过，正式提交1921字符。30轮消耗具体落在修复轴映射、错误收缩及混合测试结果解释，不归为被删multi的必然作用。entropy四轮：先run被要求write、写正确eigvalsh、真实0/1/2测试、提交，官方目标C由此有直接支持。

## NEW2 已完整阅读51R/51工具（官方W）

11.2三轮：R1临时标量1函数真实m1/m2正确，但另打印一个未更新辅助变量为零；R2先误判为主函数问题，随后正确区分，改用1<<k直接基矢，真实m2非零索引5/10。R3虽文字有1-based/二进制混淆，正式1590字符代码正确，核心U产物恢复。

tensor十二轮：可变实参基本正确；多次prior/test_current导入被拒，一度误认为numpy问题，后认出测试接口，但未真正成功测试，提交401。apply十二轮：R1长20153字符混合多种不完整方案，把单通道独立多目标当复合Ki；R2scipy.linalg.kron失败；R3sys导入拒；R5简化3349但错误要求len(sys)==len(dim)，R6真实调用候选在sys=[0],dim=[2,2]失败；R7却归因为dim不是list，未修正必要条件；R8导入sys拒，R9误说参数sys命名冲突，最后3585仍错误并提交。GADC两轮正确公式无实测。output三轮R1长泛化重复论述，R2写入不存在的scipy.linalg.tensorprod，并将每qubit维数错误用dim=2**m；R3直接提交7896。measurement两轮用basis[k]而非basis[1<<k]，未测试就提交。

syspermute六轮：混合进制展开/重构在非均匀dim下错误；三次run均在先前output的tensorprod导入失败，未执行当前测试；反复把错误说为测试程序问题而未修正已提交依赖，提交2067。partial六轮同样被prior tensorprod阻断，另有sys导入拒；当前用sum轴1,2不是对角迹，最后3612错误提交。entropy五轮公式eigvalsh、正值截到1e-15；先run-before-write拒，写523后run又因prior tensorprod失败，read后仍提交。官方W不能归因于multi未恢复；需要保留既有评价的失败细目和依赖污染这一替代解释，不自行改旧评分。

## 待完成

NEW3全58R/57工具已完整阅读；NEW4全56R/55工具尚未阅读。NEW3中超长R被工具输出截断处均重新单独读取，另精确补读11.2R2[14594,15325)及11.4R7[5949,11151)，没有以截断内容作全读。

## NEW3 全路径（官方C）

multi六轮：R1写1558额外qubit；R2长篇反复混淆单粒子子空间m与全空间2^m、ket(dim,list)；实际run仍误把每qubit当dim=2^m，m2 16/256广播失败。R3已经说每qubit应二维，实际write1890仍np.eye(dim)逐位相乘，R4再次失败。R5通过1<<k→bits→整数索引构造正确向量，真实m2(5,5)/(5,10)/(10,5)/(10,10)均0.5；R6正式1736代码恢复U核心产物。tensor四轮先run-before-write，写可变实参482，真实np.kron一致测试，提交。

apply七轮六工具：最初sqrt(len(rho))错误及np.kron.reduce不存在；R3scipy.linalg.kron导入失败，R4内联测试真实prod(dim)4与sqrt(len(rho))2异常；R5却判断测试把2×2用于两qubit，未改sqrt错误。R6自写K=[diag(1,.5)]并错误断言trace1，真实0.625；R7围绕sys=None与归一化长篇循环直到length，没有正式apply提交。GADC三轮公式与真实完备性测试正确。

output四轮：正确4^(2m)独立组合，但代码内重定义错误的multi（np.eye(dim)逐位kron），覆盖了11.2已修正版本；R2import旧scipy.linalg.kron失败；R3只测m1真实shape4trace1，R4提交3905。不能把m1通过扩展为m>1版本正确。measurement七轮同样np.eye(dim)[bit]多次扩维错误；tools/current_subproblem_code导入反复拒，改写仍未修正算法，最终1190提交。

syspermute十四轮：R1run-before-write；R2/3重复轴，R4用旧索引低位优先解码但高位优先编码，另list高级索引不合法。R6真实TypeError；R7说修正却仍保留；R8/9逐步修复权重语法。R10测试打印目标位置0却“All tests passed”；R11读到了0并调试得i6→old[0,0,1]，R12长篇反复混淆dim[2]=3/4、预期10/12与解码，实际复测仍目标0；R13先正确识别应高位优先解码，却再次接受低位优先约定，写1614；R14正式提交回旧1615，未再验证。partial十轮：前期prior工具导入拒，R7内联真实Bell返回全0.5矩阵；R8/R9认识应只对角收缩却实际sum/einsum仍错误；R10反而改口说保留相干项是正确的、原期待I/2是错，正式2693版本无新test。entropy三轮eigvalsh+epsilon正确，真实0/1/0.881290899测试，提交716；官方C有目标直接证据，不能代表早期所有helper正确。

下一步从NEW4 localstep0开始完整阅读，核对正式代码、真实切点成本和精确引用后才写COMPLETE模型裁定。
