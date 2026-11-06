# A95 COMPLETE — 先前进度记录保留于下方

四条新路径45轮、44个Call/完整Return均已阅读全文；NEW4温度19147字符345块、161独有块及全部重复位置已读。MODEL_REVIEW.json已由Codex手写保存，56条精确引文、源SHA、四份真实输入和四份成本记录已核验。PROTOCOL_AND_STATE_AUDIT.json逐项核对P、七份历史正式代码、空当前稿、G一次注入与后续仅使用新正式代码。

新增核查：NEW3温度代码漏速度换算和N平均，测试只检查正值，没有独立数值标准；压力代码遗漏*10及PBC，零virial例子不能支持这些条件。NEW4温度无实际Call/正式，长篇自算预期出现十倍错误后反复怀疑已得正确公式；压力始终误除10，工具拒绝反馈被归因于math等并多次改稿，最终forces独立交付正确。四条目标均C不能推出温度/压力完整质量保持，因为目标forces不依赖温度。该反例与A93切点不同：本组P没有216.7错误预期。

成本原后缀24899生成/45933 Prompt/10 Actor/9工具；四新生成12049、6723、10364、18065，G均12单列。仅第二条Prompt/Actor/工具也下降，其余生成下降但Prompt/交互增加。首请求3479=3467P+12G、当前前缀0、预算10000。全部属于RECONSTRUCTED_CHAR_EXACT，不宣称原生ID精确。

以下为阅读中历史快照，已被上述完成状态替代，保留过程不删除。

# A95 IN_PROGRESS — 历史快照

case77step11S014原C→4C。本组不是A93S016同一干预：此处切温度77.9R1@0空稿，P还没有自造216.7预期；U首次SI单位/Avogadro推导并write2206字符fd789，R2前23字符结果反馈属于U。G12=Now let me test it to make sure it works correctly.，来自原R2[23,74)。原全轨迹已在A57/A76/A87/A93读，本次重新读温度R1—2完整原文及实际参数/Return。原R3/4长推错误预期以及后续压力2轮/forces4轮在A93完整读过，保持引用同源文件。

全部四轨迹/原始INPUT/投影/NEW.txt/COMMON费用现已实际复制，但NEW3/4未读，费用/协议尚未核，本组没有MODEL_REVIEW。

NEW1全13轮13Call/Return已完整读完：温度3轮先run被空稿门控拒，随后write/submit5cf3（1393字符）漏J→zJ，KE用kg与m/s算J却直接除0.013806zJ/K，差1e21，没有一次成功温度测试。压力5轮：3699写因子/1e11错误，prior_code导入拒却误认为math重复导入，改0501删math；随后真实inline首稿函数测试N4L10T300得到1.656778224e-13、virial0，自己打印Test passed无独立assert，formal又回3699含math。forces5轮：f1c9正确位移/力式保存，tools导入拒却误np.zeros无import，改5583加numpy；真实inline首稿两粒子非零力±.01747049总0，formal回f1c9。目标C，温度/压力科学错误并未由目标评分反映；两个代码回退是import配置差而非物理修复，不虚构测试接受错误实际力公式。

NEW2全7轮7Call/Return已完整读完：温度3轮先run空稿拒，write/submit6304(1210字符)直接用m*1e21/NA zg与(nm/ps)^2除zJ/K，缺zg·nm²/ps²→zJ的1000因子，科学温度小1000；没有真实成功测试，也未出现原自行216.7打印。压力2轮2023write→4249formal仅尾换行差，实际*10正确，使用dist_v/f_ij，不调用temperature，没有任何压力测试。forces2轮6237write/formal，用dist_v/f_ij、f_i=f_mag/r*r_vec±，没有真实测试，目标C。function guard写r>0在调用f_ij之后，不能夸成重合r0完全保护。

剩余待读：NEW3温度4/压力5/forces4，共13轮13工具；NEW4温度1轮无Call/length、压力7/forces4，共12轮11工具。先逐条全文阅读，长字段用精确块及全部重复位置，不按原4C生成同结论。随后核完整P七正式（原wrap未交），状态/消息历史、G、未来prompt及费用；手写语义，再resolve/refresh/上传读回。不要提前报本组完成。
