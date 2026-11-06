# B90 IN_PROGRESS — 不计入完成

对象SciCode B `11__step11/S023`，原C→W/W/N/W；U在11.8 syspermute排错，最终评分11.11 coherent_inf_state，勿混成11.10 entropy（A组近邻是11step10）。

已下载index、完整U、四新trajectory/audit。尚未正式手写MODEL_REVIEW、取首raw8件/成本、协议seal，B仍89/116。

## 本轮已经实际重读的原始证据

原input audit完整非original_request/state概要、draft全文、original_request.messages[1]完整15305字符（题目、依赖、七份prior、当前11.8题与接口）；消息角色/字段长度；P_current163字符、state历史71Actor71工具、空?不是空draft，实际e1ccc05对角映射1720。G原11.8R9[23,56) `Let me debug this more carefully.`，7Token，实际8788=base8748+33保留+7G，first9967，累计100Actor。必须进一步机械核对每个audit全文、actual首req/resp，不能只凭概要PASS。

原11.8 R1—R15全部Reasoning/content、Call参数、Return已完整重读。初次U文件JSON重复包装显示截断不作为全文读取，后改read_exact_diffs真实源R1—15补全。原R14显示3Token截断已用O_S8_R14_EXACT_INDEX/DISPLAY全部逐项读回，16284字符SHA715acd04417f0f2f6ae41c23f8de5cff42342862b109c2f496ed74fbac3339b5。

原P：R1长9214明确索引数学、但首run空draft拒；R2write1720对角且decode用temp%dim[j]，newindices未实际perm；R3read；R4说修非对角但实际写回同SHA；R5真正run返回单位阵非单位、Y00=0。切点R6@163已经保留“只复制对角、应置换全部”的诊断。

U R6[163,2749)再次说双行列，实际write2117仍只复制对角，decode%dim且未perm；R7[0,441)明确双oldrow/oldcol，真实write3976加入双循环，但仍decode%dim和未perm；R8整段run，返回identityFalse、Y00=0、Y4[4,1]=0。U只有部分修复，不是修成功。

原后续R9实际加入permuted_indices，decode仍错；R10继续写带测试版；R11run返回identityFalse但2qubit对称例True；R12trace显示old_idx1→[0,0,1]new1，模型错误期待1→4；R13改自测psi12，仍错误期待新dim[3,2,4]的|1,0,0>flat12（实际8），保存测试代码；R14长反复断言测试索引错/实现对，最后只测2qubit，执行混合stdout里仍有之前3维失败，2qubit通过；R15据2qubit通过接受并submit2000 SHA5d796c，decode temp%dim仍错。

原11.9 R1—4全部Reasoning、Call/Return读完：read空draft→write3652 d70c7f内联错误decode的partial_trace→实际另inline用syspermute但把16元素reshape(2,2)异常→R4 53630字符10000Token无Call无提交，反复reshape/trace意向。完整O_S9_R4_EXACT_INDEX/DISPLAY已全文精确重复去重读取，SHA19e25086414827059ce86020000a1d1e0ea8516a43c51a08e2ccf104701425f9，覆盖到最后53630。

原11.10全3R3事件读：eigvalsh+maximum1e-15 write804、真实entropy_test三例输出、同版submit fe61；无syspermute依赖。
原11.11全4R4事件读：明确S(B)-S(AB)，自行reshape(dimA,dimB,dimA,dimB) trace0/2，write1805；试测prior_model导入拒（Bell构造错误未运行），write999删多余entropy后最终又submit1805 SHA533c，官方C。没有调用syspermute或未提交partial_trace；不能将U修复直接当目标必须依赖。

## 历史开工时元数据（以下“未读”为当时状态，按文末更新为准）

N1 arraysteps11.8—11.11：17,7,2,2轮，28总；N2 7,6,4,3=20；N3 27,2=29，尚未最终提交N；N4 20,1,2,6=29。不要把下载/概要当完成。

下一实际工作从N1 step1 R1开始，完整读四条各会话与事件，再成本、手写语义、首raw协议与seal。另一对话最近A110，B89，合199/249余50；不提前更新B90。

## 续读实况：N1、N2、N3全文完成；N4尚未读

对象再次核对为SciCode100 B116，本例11__step11/S023；不是BrowseComp，也不是A邻近11step10。B完成数仍89，当前未封存。

N1全28R28事件已逐段完整读回。11.8 R1/3/5等反复写对角版；R6 inline双循环skipzero但未保存；R16保存双循环，R17实际submit回旧对角1883 e461。11.9 R1 import拒，R2/3保存1751 ab93的partialtrace，np.sum轴1/3而非trace；R5真实测试test2预测错误（X[2,2]其实|10>，模型称|01>）；不能将该测试不符都归因helper。R6/7长21624/22433字符已用N1_S2_R6/R7_EXACT_INDEX和DISPLAY全部读回；R6write2994内联，R7正式submit回1751 ab93。11.10两轮无测试submit617；11.11两轮write/submit787，实际调用partial_trace，官方W。原11.11直接reshape/trace不调用helper，新路径改依赖坏helper，不能将U已修成功作为前提。

N2全20R20事件已读。11.8 R1已双循环但无permdigits+decode%dim；R4加入permdigits；R5真实identityFalse但2qubit交换例成功；R6长9853推导错误改cumprod，R7submit回R4思路2038 900f，decode仍错。11.9首次import拒→内联helper3889；partial_trace用einsum('ijkl->ij')非trace，无真正test。11.10真实entropy五例后提交。11.11write5228 1ebc内联badhelper；R2真实Bell0、mixed-1.5（注释期望mixed0也错），R3明确把这两个结果解释成正确并submit同版，官方W。

N3全29R29事件已读（11.8 27R+11.9 2R）。注意R1实际已经双循环，不是对角；R2另inline退回对角。R3再次写双循环；R4/6/7又退回对角；R10双循环skipzero；R11真实只有零态恢复、identityFalse，其余仍错；R12改错误测试idx1→12；R14真实debug打印old4→[0,0,0]，R15首次定位temp%dim导致进位丢失，write1877用直接(old_idx//cumprod)%dim；R16/17改成temp%cumprod（1927 7b21），R18又错误改cumprod，R19测试仍失败；R20恢复正确helper但改测试为错误idx6/3；R21改正测试，R22又写回错误测试；R23真实identityTrue但因测试idx6/3其余零。R24长25835字符初显截断，已用N3_S1_R24_EXACT_INDEX/DISPLAY全覆盖读回，SHA dcad371bfa4f56cc7458a8470eefafb0de556ea462cee3c0e0a98697eb89bfdc。R24反复将正确decode否定又接受，没有新执行；最后write3570正确helper+正确测试；R25只改注释write3638，R26真实全部五例通过；R27submit1927 7b21。11.9 R1write1496 trace轴1/3正确结构，R2run试import sys被拒，没有执行测试；累计100Actor终止，无target11.11，官方N。工作确有恢复并最终在自测支持下提交helper，仍耗尽后续额度，不能称“没重建U所以无答案”。

下一步N4全29R/28事件，再成本、9源精确引用、actual首raw8、协议机械检查与手写MODEL_REVIEW封存。当前不是完成状态。

## B90已正式封存
N4全部29R28事件读完。11.8 doubleloops恢复但decode%dim未修；R16/17长字段精确索引全读；11.9 34382字符length无Call未提交，完整索引全读。目标R5真实inline同一i trace测试Bell1/mixed-1，R6正式submit换未测试idx_map全行列求和版，官方W。成本取回并重算。26引用、9源SHA、四actual首请求响应8件、106R105事件协议PASS；公共review/progress实际上传读回逐字节相同。MODEL SHA 2d3cbec290a2d0c68020af93b0cd3cec94499eca807bdb5277fbf476cb4507eb。B90/116，360续跑2449引用，余26；下一80__step7__S005。
