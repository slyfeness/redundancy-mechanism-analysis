# 真实切点后续成本

|组|干预|续跑|生成降|生成升|生成同/区间跨0|Search降|Search升|Actor降|Actor升|Prompt降|Prompt升|
|---|---|---|---|---|---|---|---|---|---|---|---|
|A|FIRST_SENTENCE|1952|1169|780|3|883|549|876|543|1100|851|
|A|TERMINAL_DROP_NO_ANCHOR|440|178|262|0|16|101|16|101|18|263|
|B|FIRST_SENTENCE|1084|639|445|0|465|515|452|469|529|555|
|B|TERMINAL_DROP_NO_ANCHOR|136|74|59|3|62|53|56|39|64|65|
|OUTSIDE_CURRENT_AB|FIRST_SENTENCE|4|2|2|0|0|2|0|2|1|3|

NATIVE_TOKEN_EXACT与CHAR_EXACT_RETOKENIZED分列保存在COST_AND_RESULT_3616.csv；生成Δ=[new+G−original_high,new+G−original_low]，G只一次；Prompt已含G及实际前缀重放，不另加。仅原生精确为单点；CHAR保守范围不能报伪精确净省。生成减少可来自工作实例/篇幅重组，也可来自无Final提前终止、缺证答复或G答案补偿。每支归因见DECISIONS四条cost_location/quality，不能把全部净差算被删U本体。

Search/Open/Actor/Prompt分项；末纯认知四重建可更短也可更长。这里统计数量分布，不相加独立分支节省。按机制的费用方向见MECHANISM_COST_DIRECTIONS.csv，所有原始值可从逐支账本复算。没有用U字符或Token长度直接代替节省，也没有从不可分离原延迟报精确时延收益。
