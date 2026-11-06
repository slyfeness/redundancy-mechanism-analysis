# 11__step10__S024 阅读检查点

2026-11-04：已阅读全文原始11题上下文及本次11.7 R1 U、后续11.7–11.10；四条NEW全部读取完毕（17/15/23/38轮，共93轮92工具事件）。精确相同段落只复用逐字位置引用，首次不同内容、Call完整参数和完整Return均已阅读。NEW4部分迹37235字符用87种逐字块和全部发生区间还原阅读全文，真实length且无Call、无提交。尚未完成MODEL_REVIEW前不计为已完成案例。

U是首次构造measurement：两方独立单激发局部投影的张量积，write cf9290...；P当前draft为空，G却说“The code has been written successfully.”。不是S025的已有正确草稿验证。G7Token只有完成状态，无算法，但状态与P不符。

NEW1直接submit同一rail i,i投影，错误缩小允许子空间；无measurement测试。NEW2直接submit同一i、其他位用I、np.kron.reduce，未真实运行；静态问题不能伪称实际发生异常。NEW3先run被write门控拒，继而重建独立i,j正确投影，实际测rails1/2秩及幂等/Hermitian后提交。NEW4直接submit独立i,j正确投影，没有measurement测试；注释说same position但实际代码双循环，按代码判断。

NEW1 syspermute真实修正D²断言后，第三测试用8x8态配dim[2,2]失败，未复测却说passed；partial_trace错布局(K,T,T,K)，Bell对称弱测试过；entropy导入被拒后未实测仍交正确目标。

NEW2 syspermute实际extraD reshape错误重复返回，但最终归因于并不存在的dim[2,2,2,2]测试并交未修版；partial_trace同样额外轴且只transpose保留轴，scipy.kron导入失败未数值检验；entropy真实纯态/混态/3级/.7-.3测试通过后交正确目标。

NEW3 measurement实质完整重建，随后syspermute版本切换、测试索引错误，未成功数值检验即交；partial_trace导入sys被拒误疑参数名sys，重命名后又因prior_code导入失败改内联；R7真实测试输入并不是自己说的标准态，输出[[1,0],[0,2]]和trace8被错误期望驱动返工。R8写新稿6fbc...，R9却交回最初9eb...（对X而非已重排Y求和）；entropy真实非对角及混/纯态通过。

NEW4 syspermute32轮：多次发现权重应suffixprod又写回prefixprod；测试还多次把三系统perm用于两系统identity，反馈混杂实现错误与坏测试。R7曾写直接transpose可用核心但未测试即覆盖。R27首次exit0但前两检查仍False；R28改suffixprod后未run，R29又读旧输出误归flat_to_multi，R30再改回正确flat_to_multi和suffixprod。R31真实四个等维测试均True，R32正式交56227...，不能说始终没用反馈。随后partial_trace10000Token纯拟议重复无执行/无提交，entropyrun-before-write被拒后补write、真实0/1/2测试、submit正确目标。

四次官方目标entropy均C，核心都直接eigvalsh/eigh与log2，不调用measurement、syspermute、partial_trace。不得用目标C认证中间辅助题正确；这组也不是四次都跳过构造。真实记录新生成10768/13479/22504/64938；原切点后39003。前3降低、NEW4增加25935生成，主要变化在后继syspermute和partial_trace，不能全归被删U；G与采样因素保留，非原生精确边界。
