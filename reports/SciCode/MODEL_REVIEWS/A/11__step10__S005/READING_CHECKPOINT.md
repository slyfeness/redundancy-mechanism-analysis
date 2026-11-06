# 11__step10__S005 原新逐路径实际阅读记录（未完成不计数）

原完整11.1—11.10此前逐字段读取。本组重新读原11.2R7完整3287字符及唯一真实run/Return，U不等于正确修复：P已保存68f388...仍tuple/维数错误，且R6真实sys拒；U反复猜隐藏导入/重复ket，不采用实际测试中显式sys原因，改用内联不含sys，才第一次取得m1 4×4与m2广播16/256。它没有改保存草稿，却把‘入口受阻’变成可定位算法失败。原R8据此处理位/party维数（见S004重读），最后entropy独立计分C。

G原R8开头仅“I see the issue.”，本身不含实体、错误数值或算法，只承接已找到问题的立场；完整P中已有失败反馈但未有U才得到的16/256数值。不能把G当新模型自主判断，也不能从该短句推定泄漏了完整修正。具体Token/历史状态待读取实际INPUT细项后记，不凭估计。

四首请求/响应、原INPUT/草稿和prior-code、预算、当前Assistant解析及Call/Return CPU校验4PASS，258Round254事件。四新官方C/C/C/C，轮数分别65/56/66/71，工具63/56/65/70，全部到11.10，期间早期子题可length而目标C。

## NEW1完整65轮63工具已读

11.2只有一轮：G后把sys拒误称numpy拒，猜重复ket；直接submit1526省去当前全部数值验证，正式仍ket(dim,tuple(indices))与dim误用，删的是核验反馈而非事实已修代码。11.3三轮read空、write511单args/scipy.kron，formal换855正确*args/tensor_product双接口（未测）。11.4十二轮先错误嵌入/len(sys)当全部子系统，自主多次写修；sys测试拒误归形参sys变量名改target_sys，subproblem_4导入拒时曾正确认模块不存在但后来又sys。R10真实全/单系统迹过，PauliY float64自写测试TypeError；R11正确定位测试dtype改实数K，五项trace过，formal2485仍多目标同Ki组合不独立，弱测试不证明一般情况。

11.5四轮正确772K，tools导入拒误归numpy/候选code，read后formal772，没有真K†K数值。11.6二十九轮是主要实际纠错：read空→write6363打包旧tuplemulti、旧apply、output错误dim=[2**m]*m。R3真实从code导入可用但multi Invalidinput；R4改tuple成list写6312，R5真扩维16/256；R6已正确提出整数binaryindex写6495，但R7测试又完整定义旧tuple代码，故Invalidinput再次出现；R8补tuple，R9扩维仍在。R10把1Dkron误认为2D导致flatten，write6587还含顶层output测试，R11同扩维；R12本想只测ket，但自动载入candidate的顶层output先失败，probe没执行。R13更改ket零向量kron/reshape，R14扩维变4096；R15想测ket仍被candidate顶层旧output阻断。R16改ket的多bit为二进制pos，R17旧state问题绕过后真正暴露fullK8与rho16不匹配。R18正确重读把2m个2Dqubit区分party维数，实际apply_to_qubit却把整个K列表当矩阵，R19产生(4,16,16)/(16,16,4)错。R20—26又错归kron本身会变高维，改起始因子/flatten/copy，数次实际write没有新run仍沿旧反馈；R21同真实错；R24只想测初态又被候选顶层旧output失败阻断。R27改遍历K但对每K连续覆盖rho而非求和，R28真实trace0，R29说entangled可能trace0正常后formal4473错误。这里不是‘多搜索’，是测试对象、被测代码中的顶层调用、错误归因和数学通道实现持续偏离。最后直接读formal及R10write末尾确认真实顶层state=output_state(...)存在，不猜隐藏状态。

11.7八轮：初2910measurement+自写binaryket在单激发用途正确；measurement/prev_code多次模块导入拒误归numpy或重复ket；去ket写1743，后又write2890含ket，最后formal恢复1743依赖prior output的binaryket。没有真正数值测通过投影；不能按ACCEPTED当功能正确验证。

11.8三轮：write2478新→旧索引映射小端提取错；R2真实|01>交换后仍index1，Y[2,2]=0；R3长30096反复混淆binary位顺序/映射方向至10000length，无新Call/formal。整个R3字面去重读，输出缺口[10931,18864)直接补读。11.9两轮：read空，后长50394重复reshape/独立sum轴与pass草稿至length，无实际write/run/formal；所谓‘实现了partial’只是未执行文本，不算真实功能完成。11.10三轮636正确eigvalsh，真实纯态4.98e-14、mixed1、expected1后正式C。早期代码错误、两个子题无formal均不阻止独立目标entropy C，因此这组C不证明U无用或全程质量维持。

NEW1补读applyR1中间[1800,4960)、sys长R3[10931,18864)；其余完整literal去重记录均保存。

## NEW2完整56轮56工具已读

11.2五轮：G后又把sys拒当不明candidate错误但选择inline真实检验→tuple Invalidinput。R2长8070既考虑bit维数又重新误解kron，最后write2741扩tuple/list，R3测试却重新定义旧ket，仅list/原tuple，仍Invalid。R4改2631 list，R5说test ran successfully但此前仅writeACCEPTED，无新run，formal2609又回旧tuple/list不匹配。该版本直接核对submitted_code确认。没有获得原U的m2扩维数值，但接口测试工作已发生。

11.3两轮正确481 reduce(np.kron)无测试。11.4十一轮：初3103用sqrt(rho.shape[0])推dim、zip(sys,dim)遗漏未选子系统；R2真实single trace1但自写density test条件错误False，firstsubsys4vs2matmulfail；R3改遍历dim却从I2多乘一因子；R4先2x2rho被perfectsquare检查拒。R5长13300重复把sqrt2当2、想象测试为4x4，实际write3505修部分factor但sqrt错误仍在；R6sys拒R7importlib拒R8read；R9inline真Kdim2 vs inferred1，R10长16900仍把rho.shape[0]开平方、假设测试K小于状态，write4367未测，R11formal回3505。R10完整单独重读，R1actualCode独立补读，不留截断。

11.5四轮正确893K，tools导入拒→read→formal，无数值K†K。11.6十五轮：read空，write5193inline旧np.eye(dim)逐bit和同Ki多sys；tools导入拒却错去functools，R5inline真16/256，R6误把双party张量积换逐元素相乘，R7真m1 4/2广播。R8正确binarypos直接构初态，R9m1真trace1，R10m2/m3真trace.19516/.13178382（同Ki多sys导致非保迹，不能称物理正常丢失）。R11据此把output误解释应postselect，额外加project_to_one_particle和归一化，并且实际write回旧逐元素相乘初态；R12m1又4/2失败，R13改kron但np.eye(dim)逐bit仍错；R14只测m1真trace1，R15formal4821带postselection。postselection非当前output子题要求，属于错误反馈解释带来新工作/需求扩张，原题背景后续测量不等于output应在本步投影。R11actualCode[3100,end)与R12—15重读补齐截断。

11.7十一轮：初1850用np.eye(dim)[indices]高级索引→R2m1过/m2 outer8×8与4×4广播。R3改zerosvec[tuple]1933；R4真too many indices；R5循环每bit值写vec[idx]1989，R6m1trace1/m2trace16。R7说trace应4但改回eyetuple并write含顶层测试2258；R8长11900先trace16称对又反证、正确binarypos写2181，R9仍用旧trace反馈错误换vec[k]2148，R10长11900最终inline正确pos真实m2trace4；R11识别4确为应有值却formal回1989的vec[idx]，丢失正确test修复。直接读formal[1200,end)确认。没有用重复想法当新测试，R7/8/9连续write只反复消费R6旧反馈。

11.8四轮：read空、write1463显式old→newindex、真实7项等维swap/3qubit正确，formal同版；异维用原dim重组仍可错，未实际验证一般情况。R1完整另读，其他R2—4在前工具完整可见。11.9两轮1872write/1871formal：虽然计算Y=syspermute，却reshape原X到(rem,trace,trace,rem)，独立np.sum(axis=(1,2))错误，不是真对角trace，无实际测试。11.10两轮739正确eigvalsh筛lambda>1e-15，直接formal，旧官方C保持，无新数值熵测。

重要对照：NEW1当前直接交坏multi，把缺口延后到output29轮；NEW2先当前做5轮接口检查，但正式回旧，output15轮再修改。两者都C不能证明核验无用；目标entropy独立且早期代码质量差异真实。两条尚不足全组裁定，下一NEW3从localstep0 R1读起（66轮65事件），NEW4尚未读；未写MODEL不标COMPLETE。
# NEW3 全部完成阅读（续补，不计整组完成）

- 11.2共18R：最初将sys拒绝误归因于numpy/重复ket，R1/R3/R8实际内联测试仍因tuple输入失败；R9改helper、R10又接受tuple且夹带顶层测试；R12实际移除测试；R13首次测得m1 trace1后m2出现16/256维数错误。R14长推导虽摆动，写入标量binary index；R15/R16改为每bit dim2；R17实际m1/m2均trace约1，R18正式提交相应dim2实现（最后封存前再核对正式代码）。这条与N1/N2未恢复有效修复不同。
- tensor4R：正确迭代kron写入，测试from write_code被拒；将loader拒绝误归因于代码依赖，read后直接submit，无数值测试。
- apply9R：错误以sqrt(rho.shape[0])校验dim，重复from apply_channel被拒→重写tensor而未修正根本维数；R8写2359，R9正式3006不同版本，仍保留sqrt校验与同一Ki作用所有sys，未实际验证。
- GADC6R：正确公式866chars；两次prior_code测试请求被拒，重写/read/submit，未获K†K结果。
- output10R：恢复每bit初始化，但apply采用partydim。R4内联真实4vs2；R5识别2m个dim2，R6sys拒绝后R7却写回旧partydim；R8候选真实仍4vs2。R9改手工逐qubit但只构造m-qubit fullK，仍不匹配2m总系统；R10提交5978旧接口路径，不能称测试通过或修复生效。
- measurement6R：R1 party_proj错误一维；R2模块导入拒绝；R3内联实际nonbroadcast4/4x4；R4正确二维初始化，R5实际m2 shape16、trace4，R6提交相同1245，局部错误→诊断→代码→测试→正式提交链恢复。
- syspermute6R：R1 axes=perm+perm真实重复axis错误，R3正确offset；R4真实测试identity/Bell通过，所谓inverse测试错误地将identity当inverse，打印False；R5误判3qubit全零（原输出其实(0,0)=1）并等价改写；R6正式1121，不能把所有打印False等同代码错误。
- partial_trace1R：60898chars，前12k之后多数逐字重复已索引；无Call、无正式代码，length。不是已经执行多次trace测试。
- entropy6R：eigvalsh+epsilon正确公式；两次测试分别prior_code/entropy模块被拒，读回后正式686，评分C。仅最终entropy正确不验证前序helper质量。

# NEW4 全部71R/70事件已读

11.2共12R：R1实际tuple失败；R2发现tuple/list，R3仍带sys测试被拒；R4实际m1过/m2 16/256；R5错误把kron归二维，R6重测同错；R7长推最终改标量k，R8长推继续错误归因并保存index=k；R9读回，R10推导曾识别2**k但实际又写旧ket(dim,args)。R11测试内联的是标量index=k版本，m1/2/3形状迹均通过，却不是单激发位置。R12正式仍index=k（完整formal再读），不能称恢复正确编码态。

tensor8R：正确迭代kron，write_code/session_code/previous_code三次测试导入拒，等价重写/读回/正式526，无有效数值验证。

apply19R：多余初始I扩维，R4/7/10实际4vs8；R11跳首项使作用于sys0时遗漏K，R12/14 identity通过但测试rho2x2与dim2x2不一致。R15长推在测试错/代码错之间摆动，短暂正确处理idx0；R16/17又回退，R18/19正式1971。没有把某次口头正确诊断等同formal修复。R13–19输出缺口R15[6440,8655)补读。

GADC6R：正确公式1026；两次prior_code测试拒绝，误归numpy依赖，读/提交，无数值结果。

output4R：15777chars从错误index=k初态扩展困惑partydim/bitdim，最终dim=[2]*m而非2m且同Ki多sys；write7262，output_state模块测试被拒，读/正式同版，无真实channel验证。

measurement3R：用index=k构建错误子空间；R1直接run被拒“write_code must succeed”，未执行数值代码；R2写1493，R3正式1349，没有幂等/rank实际结果。

sys11R：axes重复；tools拒、R4真实repeatedaxis；R5 25308chars猜无效perm，等价改写加验证但轴仍错；R6sys拒；R7实际合法[1,0]/[2,3]仍重复axis；R8误当单系统边界加特判；R9实际同错；R10 23400chars曾明确正确offset公式，实际写入交错axes[perm0,perm0+n,...]，不是两半排列；R11 33330chars又返回旧duplicateaxis/输入无效假设，length无Call无formal。输出截断的R5[10647,13006)、R10[11320,12837)与R11整轮已补读。

partial4R：R1 14854chars草拟多套不完整reshape/sum，最终2270错误reshape且独立sum；R2 tools模块拒，读/正式，没有数值测试。R1[9711,12488)已补读。

entropy4R：正确eigvalsh过滤零825；tools测试拒，read/正式，官方C。NEW3/NEW4最终C仍不表示此前代码均正确。

