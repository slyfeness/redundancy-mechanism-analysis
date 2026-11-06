# 77__step12__S006：B112候选，尚未完成，不计入进度

当前对象SciCode100/CODE_STAGE V1.0。B111=77__step12__S005已封存；B进度111/116，444续跑、3059引用。其publish不可重复运行。

本组EVIDENCE_INDEX/U及四组trajectory/INPUT_AUDIT已由SFTP取回，8SHA匹配。原始77.12源SHA仍bae16b3a444a4f7e995e5426824ab72fa6a7941daf0087770230340a3a8cb404。同源原全轨迹此前已完整读，本次重新完整读U三个reasoning字段、三个工具事件及完整P/G状态。

U：原77.3 R2[0,1139)、R3[0,1390)、R4[0,75)，尝试dist_v样例、IMPORT_DENIED/prior_subproblems、误解释成numpy导入问题、等价重写并正式提交。原示例[9,9,9]到[0,0,0]期望负号与dr=r2-r1包裹不一致，但该测试未真正运行，不能当实测失败。

截点(2,1,0)，77.3R2@0；P有已接受向量dist_v574字符SHA4f0ea971…，前两正式wrap/dist代码，历史7Actor/7工具，当前history仅原R1成功write。无历史工具重执行。

G：`The user wants me to implement the Lennard-Jones potential with truncation and shifting. Let me understand the requirements:`，取自下一子问题77.4R1[0,124)，明确跨子问题行动方向；首请求仍是77.3而不是恢复77.4prompt。该G对当前dist_v测试目标错向，须逐条检查真实采用。

筛选N→W/W/W/N，3次状态变化，不是正确率改善。

本组新路径阅读进度：
- N1仅local1（official77.3）两轮/两事件已完整读。R1受G转去推导并实际run_python测试`lj_potential`的能量/力，而非dist_v；测试正常打印0.0163/-24等，rc及超过rc为0。R2称测试成功，却正式提交原先已有dist_v574字符；因此实际测试对象与被宣称/正式提交对象不同。尚未读local2–10。
- N2/N3/N4尚未阅读，不能形成确定的功能重建/机制标签。

待继续：获取首请求/响应、原77.3R2真实请求、客观成本；核对协议和分支状态；模型手写四路径语义后resolve/封存。当前未生成正式语义判定，也未更新B完成数。

## 后续实际阅读已补齐

N1、N2、N3、N4各10个local step全部Reasoning、content、真实Call/完整可见Return已由Codex阅读（精确重复片段按此前同字段原文坐标承接，未省略不同部分）。N1 35/35、N2 36/36、N3 37/37、N4 52/51，末轮无Call，不能补成52。

- N1：先实际测试lj_potential、再以成功为由提交P中dist_v；77.5向量力，77.6/7尾项N²无L；温度真正测试与手算吻合；pressure先f_ij局部名冲突实测UnboundLocalError、改名后实际数值；forces实际总和测试；77.12加速度换算1e-12且pressure无PBC，实际样例盒长15651462804.614542仍仅按shape宣告通过，正式提交该实现，官方W。
- N2：先被G引向LJ并覆盖当前dist_v，IMPORT_DENIED/dist后改成自包含lj_potential_force并正式交错函数。force采用x方向；Etail将tester导入失败归到candidate/math，后来提交又恢复内层math。Epot实际样例；温度实际手算；pressure无PBC。77.12mass使用1e21而非正确单位系数，sys测试遭拒；随后inline且tau_T=tau_P=0的弱测试正常返回大速度，再提交，官方W。
- N3：G先写LJ，随后真正inline测试dist_v并提交正确向量；force写equal-components、实测后改vector、最后又正式提交equal-components。温度先漏1e24得到极小值并test自身NameError，后补1e24，sys导入再遭拒，改写后提交先前正确换算版。pressure/foces测试导入遭拒，分别改写/提交，没有真正数值验证。77.12写7600，a_m/s²到nm/ps²误用1e-3，thermostat负号、barostat省gamma；exec测试遭CALL_DENIED后直接submit7589，官方W。
- N4：G先写LJ能量再写力，多次read与误归因，R8真正inline测试dist_v+LJ，R9正式提交包含向量dist_v的三函数；目标功能恢复但开销增加。77.5反复IMPORT_DENIED，真实test返回近距float/远距array，认定两者都正确后提交。77.6实际复算同公式接受；Epot14轮中write_code/prior_code/sys导入反复遭拒，多次read，直到R12删去不允许import的inline真实输出，随后save/submit。温度完整单位推导后真实数值正确；pressure不测试；forces真实总和测试。77.12唯一一轮10000Token/36800字符，反复调整热压控制顺序/单位，产生多个未执行草稿及测试意向，无write/run/submit，真实length停止N。不能把这些草稿写成已运行。

区分：N→W/W/W/N是三次有正式目标提交但错误，不是三次改善。当前U属于77.3，评分目标77.12。四路径均改变后续多个子问题；不能把目标错误唯一归因于被删dist_v测试。
