# S020 实际阅读检查点（未完成，不计入A完成数）

原始11.5 R1–R4、U及共同原始完整前后文已读。机械输入/状态/预算/工具协议四分支共148R/144事件通过，不等于语义完成。

NEW1六子题全部Reasoning、Call、Return已实际阅读；输出截断的output R11/R12、syspermute R1[8674,13109)、partial R1[10044,16576)及R5[6007,7194)均另读原字段补齐。实际31R/29事件。NEW2、NEW3、NEW4尚未完成阅读，禁止先生成确定的整体语义结论。

U是GADC首次实现：P的当前稿空，原四矩阵实现866字符write真实接受。G却说代码已成功写好，属于未来完成状态引导，非P事实；不含四矩阵公式或答案，仍不能视为无引导干预。

NEW1第一轮只说提交，但submit_code参数确实新生成完整656字符四矩阵函数；无当前write或test。实现产物恢复，原write/test行为没有发生，不能把G当成已存在代码。后续output真实负反馈4vs8后，1x1种子修正曾实际保存，但下一次又保存原eye2错误版本，随后同错误重现，另一次修正后仍无成功测试/正式提交；长推及反复接受解释必须按实际版本区分。measurement真实测试成功后提交。syspermute单轮长推无工具无正式稿，纸面测试不能算真实执行。partial两种错误einsum/reshape均有真实反证，后一次非法step_09测试没执行候选，却误归函数import并同稿提交；不是成功验证。entropy两轮write/submit、无真实测试，eigvalsh+正值过滤产物与前面helper独立；最终评分不能认证这些helper。

NEW2已读：GADC7R7事件、output12R12事件、measurement3R3事件、syspermute R1–R10及对应事件。显示截断已补output R2[8939,10061)、sys R6[6334,12224)、sys R10[0,3217)；R9返回另完整读取。sys R11–R26、partial11R、entropy3R未读；NEW3/4未读。当前不得计完成。

NEW2当前GADC先尝试prior_code测试，真实返回write_code must succeed；这直接反驳G的“已经写好”。随后两次write、prior_code入口被拒、read_code、合法内联测试四矩阵及完备性真实通过后正式交811字符稿。这里恢复了U实现并新增原来没成功的数值测试，不能算功能跳过。output将Kraus索引当qubit位置，实际IndexError；R8保存独立组合修正，但R10测试内联旧算法继续报同错，R11再次保存正确组合后R12正式提交又用旧f974稿。应区分实际保存、实际测试、实际提交版本，不解释成正确修订测试失败。measurement真实测试通过并提交。

NEW2 sys截至R10：R1未write先run被拒；R2保存交错轴版本；R3运行内联更早固定4维/数组相加版本而报axes mismatch；R4保存正确分组轴concat，R5却内联交错轴，identity False等确实返回。R6推导发现原测试index61错误、应60，但最后仍保存交错轴。R7再次运行交错轴，多项False；R8/R9/R10持续文字推导与写入，尚无新的成功测试。不能用工具exit0当正确，也不能把旧测试结果归给另一个已保存版本。余下必须逐轮读完再判断。

NEW2现已六子题62R62事件全部读完。sys R11–13合并显示截断的R12用单轮窗口重新完整读取，余下R14–26/partial11R/entropy3R全部未截断。sys R12再次保存分组轴，后又换错误索引映射；R15浮点索引反证→几次int重写→R19/21越界→R22修新维度weight但仍错解码→R23两个basis False→R24正确发现末轴先解码、真实保存→R25所列测试全True→R26交相应逻辑简化稿。实际恢复过程有先错误归因测试、后修具体索引的区别。partial R6与R9：Bell [[.5,0],[0,0]]是实际反证；I4→2I2反而符合未归一化partial trace，模型写的I2预期错误，不能把所有不匹配都认定候选错。R10改reshape后Bell通过但3qubit中间系统仍得到交换矩阵而非2I4，R11只正确识别全trace I4应4的测试预期错误，未解决其余问题就交。entropy实际测试pure0/mixed1/mixed4为2正确，I4为0也符合直接未归一化谱公式；模型却误称I4应2，后仅以exit0/部分测试接受，没再改代码。两类反馈需保留反例，禁止统一“误判全部测试”。

NEW3全部19R18事件、NEW4全部36R35事件现已实际读完。NEW4 output R7及sys R8/R9合并显示截断，分别单轮重读补齐。NEW3 GADC直交实现、measurement准确定位tools入口并真测、sys无正式稿、partial exec拒误归__main__并交、entropy纠正自己Bell Expected1为纯态0；NEW4 GADC直交，output将真实rails1误记rails2，sys保存正确维度/轴但仍跑旧测试，partial保存list修正又正式回交generator旧稿；目标entropy两条均独立谱函数，NEW3真测、NEW4入口拒后交。

MODEL_REVIEW.json由Codex逐项写成，四条功能/判断/动作/成本/反证分别记录。42精确引用及源SHA定位通过，22显式Call ID核对通过，四首请求和完整148R144事件协议/预算/状态复核通过；A进度121/133。原U为首次实现、四条核心代码产物恢复，G虚拟写好状态、独立entropy评分边界、三条生成增加和一条减少均保留。不得据4C称U冗余或全helper质量保持。下一固定A=11__step10__S009。
