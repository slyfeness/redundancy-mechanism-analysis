# 77__step12__S008｜B113阅读记录

对象SciCode100/CODE_STAGE V1.0，B112已封存，不重复发布其进度。当前组原N→W/N/W/W，三次状态变化不是正确性改善。

同源原77十二子问题全轨迹此前已读，本组重读77.4完整实际prompt/P、U三个字段与完整三事件。U原77.4R2[40,1025)、R3[0,1324)、R4[0,1115)。已有976字符E_ij草稿SHA19cb438f；尝试from E_ij导入遭拒，改inline真正运行输出0.0615234375与0，随后正式提交同代码。P在R2只保留前40字符，11历史Actor/工具、三个正式前置函数、当前一个acceptedwrite。G跨到77.5首句要求f_ij，不是原77.5prompt。原历史reasoning未转入实际模板的局限保留。

四条新路径所有9子问题Reasoning/content、完整参数、Return、正式代码和终态均已读：N1 39轮39事件；N2 31轮30事件；N3 40轮40事件；N4 24轮24事件。原始文件8SHA一致。N3 force R1第一次展示有截断，额外原文[18000,29416)读取补齐；其余无已知输出缺口。

- N1：77.4read原代码→E_ij导入test拒绝→直接formal同代码，无数值验证。force scalar/vector长推导，actualtest中dot>0为False，sys复查遭拒，随后换x轴自洽检查为True并正式同f740a2。Etail/Ptail实际复算同公式；Epot先prior_subproblems导入test拒绝、又向candidate加入同禁用import再拒绝，后inline实际有限值后提交。温度先未write即run遭拒，R3却声称test已运行；最终真实randomtest温度0.9843后提交正确SI公式。pressure实际只核对kinetic，virial很大归参数、正式无PBC代码。forces真实计算后tester越界IndexError，正确识别为测试自身错误后提交。77.12写12531/测试tracebackimport拒绝→另写9919→实际inline样例只shape/打印pass→正式8106又把m_kg_particle放入tau_T>0内；没有真正位置推进，F单位转换漏1e-12，未验证这些关键逻辑，W。
- N2：G先在77.4写f_ij覆盖Eij，sys导入test拒绝，read后明确识别当前要求Eij而不是force，R4恢复原976/R5正式；未重新数值test。force三次write/x轴返回，真实打印力后接受。Etail20112字符反复N/N²/density问题，最后N²无L写/交，无真实test；Ptail写/交。Epot测试sys拒绝后重写/交。温度漏N但无测试直接交。pressure长19095字符符号推导→正确*10保存；test tools导入拒绝→重写*10；实际inline测试却采用/1e11、x-onlyforce，正式又换V_L*1e-25巨大单位错版，非同一程序验证。forces无真实测试；77.12唯一24413字符/10000Token反复单位推导，未发Call，N。
- N3：77.4忽略G错向，直接Eij测试sys拒绝→短版等价写→inline真正输出截止/势阱/近截止→正式原976，测试功能恢复。force29416字符反复梯度/接口，最后run先于write遭拒；后写vectorf616e，tools导入readtest拒绝→真正read→实际向量test后交。Etail18836字符N²、N/L³方案摇摆，保存rho=N/L³，真实打印后交；Ptailsolution导入拒绝误归因math→numpy写→inline math实际运行→formal原math。Epot actualnan识别周期重合，改测试9而非10，不改candidate；formal有限值版本。温度八轮：保存漏N版，inline又漏J/zJ；两次实际极小值→补1e21修复→错误expected差1000引发再算/改v输入→v1=481.0896/v.79=300.248→正式正确。pressure与forces都无PBC但简单测试通过。77.12写7026，加速度直接F/kg漏转换、eta^(1/3)与L*eta不一致；exec测试拒绝后直接formal7025，W。
- N4：77.4readP中Eij后直接交原976，未test；forcevector1223，exec测试拒绝误归因内层numpy→删import写/交1195，无数值；Etail/PtailN²无L并增加rc<=sigma返回0，均直接提交；Epot无尾项直接交；温度先run未write拒绝，write后实际ones三分量=1444.47而wrongexpected481，误认为重复转换改写等价1500，再read/交；实际公式正确，额外消耗来自错误期望。pressure/forces含PBC直接交，无test。目标写7561，实际a=F*1e-24/kg（比所需1e-27大1000），barostat后v_xyz缩放未用于返回v_half，未测试直接交7560，W。

CPU检查B113_PROTOCOL_CHECK.json PASS：134实际POST、133配对事件；所有首请求与响应/Token IDs、P＋G一次、9992首预算、11历史额度、分支独立seed、后续prior代码均来自本分支、原U精确映射及成本复算。切点RECONSTRUCTED_CHAR_EXACT，原后缀生成区间[31675,32181]，累计Prompt113248、Actor31、工具30。G19另列，P2246，首输入2265。

待：Codex手写语义JSON/引用定位与封存。本组尚未计入B完成数，不能只凭阅读记录声称完成。
