# B89 COMPLETE / 已公开封存（以下旧IN_PROGRESS记录保留为阅读过程）

最终MODEL SHA256 `02047f59bfe719338d274acc2fa4e3a5911903f8763b5eaa0838ac790ea30ad8`，公共MODEL及进度已SFTP上传、原子rename、下载byteexact通过。B89/116，356续跑，2423引文，余27；最近A110，合199/249。

四新全部11子问题已逐字段完整读：N1 30R29事件，N2 42R42事件，N3 38R36事件，N4 51R51事件，合161R158事件。N2长fij、N3长E_tail与temperature均完整精确索引阅读，所有显示截断补读。9源SHA/25引文/4首raw8件、输入1050=1039+G11、空P、首10000/累计100Actor、所有新prior完整代码块和Call/Return/成本CPU PASS。实际P/audit全文已读，无未读部分。

4/4首测空draft拒绝后重建wrap；N3/4真测wrap成功仍最终W。原wrap没提交且最终目标不调用它。N1 forces正径向沿rj-ri加j减i C，N2/3/4反加i减j W；一般守恒和运行成功没有排除方向错。N4被测与最终提交函数又不同。不得把远端方向链倒填为原wrap作用：这是主题起点@0加G重新启动，仍有采样/行动提示替代解释。四次生成减少但N2/3/4 Prompt/Actor/工具增，主要减原wrap错误断言后10K及温度18K，其他新长推导/导入修复增，不归U篇幅。

下一固定B90 `11__step11__S023` 已下载index/U/四新/audit，IN_PROGRESS，不计完成。

固定对象 SciCode100 B类 `77__step11/S001`，原C→C/W/W/W，最终评分77.11 forces。本组删除的是77.1 wrap首次理解与保存，不是前一组77.2距离试测。固定队列B88后本组，不能换短案例。四新、audit、index、U、客观成本均已下载，四trajectory/audit SHA对索引核验。

最新封存B88/116、352续跑、2398精确引文，review SHA d94347e357dff80d50a4ef3d4d50317f7d346ec9cf68b4c9ffa41ce2521c6e5d，公共review/progress读回byteexact。A109/133已通知，与B合197/249、余52。

## 原P/U/后续

P在77.1R1@0，draft/previous/history全部空，历史Actor/工具都是0；G是原R2[49,96) `Let me test it to make sure it works correctly.`，非跨子问题。首输入1050，10000生成、100累计Actor。本组从主问题第一步启动，应检查重启/重采样局限，不能自动说已跳过wrap功能。

U原77.1R1[0,1468)+R2[0,49)，实际write424 np.asarray+np.mod 046991。原R2真正run from code，L2=5时输入[5,0,4]输出[0,0,4]，错误assert期待不变而失败。R3真实30984字符/10000Token length，无Call无提交，反复将L误记10并重新推测5、生成模运算/floor备选但未执行；完整原字符用O_S1_R3_EXACT_INDEX/DISPLAY重新阅读全文（原批量输出截断已修复）。因此原wrap没有进入后续previous。原其它后续与B85/B88同一trajectory已经完整读过；target2314正确C使用dist_v和标量负径向fij，不用wrap。

## N1 已完整读完全部11会话，30轮29事件

77.1 4R：首轮顺G要测试，真实run引用session_storage，但draft空返回write must succeed；R2保存540 floor版367326，不含np.asarray，R3read、R4submit，没有真正wrap数值测试。实际恢复了wrap工作，不是成功跳过。

77.2 3R：np dr=r2-r1逐项round/sqrt771 d39，from code真实4例返回正确，正式交。

77.3 3R：np vector689 1443；__main__实际四例成功，测试文字跨边界期待-8、5.1期待+4.9虽错误，实际返回2和-4.9，R3却称全通过并交。

77.4 3R：首次run未write被拒→write1040 6a49→submit，未实际重跑数值。

77.5 1R：30380字符/10000Token length，无Call、无提交。完整N1_S5_R1_EXACT_INDEX/DISPLAY已读完全部；标量/向量反复、24/r²→24/r→12/r与错误chain-rule系数来回，所有代码块/试测/提交意向均未执行。不可把reasoning里的fij当实际helper。

77.6 E_tail2R：5077字符围绕N²/密度怀疑后按原N²公式write1127 a534+submit。

77.7 P_tail2R：L不进公式，按N²write1118 d373+submit。

77.8 E_pot2R：采用dist/Eij并加E_tail，write1300 b8ef+submit，无测试。列举prior没有fij，与77.5无提交一致。

77.9 temperature3R：把总KE错当单粒子公式，实际1334 5326代码缺/N，inline自印134.705无独立对照，接受提交。

77.10 pressure4R：首reasoning16568字符/7057Token完整读，virial/径向指数反复，单位错1bar=1000zJ/nm³；首run未write拒绝，write2041 7716，自测小输出无独立基准→交。

77.11 forces3R：7667字符推导最终明确正径向是作用在j，write2073 27d6，rj-ri折回，正4eps(12s12-6s6)/r²*dr加j减i，正确方向；inline三粒子真实输出[-24,-24,0]等总力近零，接受正式同版，官方C。未用wrap或缺失的fij，需与N2–4比较，不能用此一条预定机制。

## 尚未读

N2、N3、N4全部。各会话轮数（1-based array对应77.1–77.11）：

- N2：4,3,4,4,4,3,4,4,3,5,4。
- N3：6,4,4,3,4,1,2,5,1,4,4。
- N4：7,7,8,2,7,2,2,4,3,3,6。

下一步从N2 step1开始，不从摘要/最终代码跳读；全部读完再手写正式四分支记录、读成本、下载首raw8件、原生IDs/输入/协议核验、封存。B89仍IN_PROGRESS，不增加B88进度。
