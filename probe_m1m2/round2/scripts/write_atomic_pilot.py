"""Serialize Codex's directly authored pilot conditions; not model extraction.
Feature indices below are 1-based insertion order in the frozen feature map.
No source prompt or dataset row is included in the public output.
"""
import collections,hashlib,json,unicodedata
from pathlib import Path
O=Path(__file__).resolve().parents[1]
P=O.parent
rows=json.loads((P/'samples/selected_dataset_rows.json').read_bytes())
ids=list(dict.fromkeys(x.rsplit('__rep',1)[0] for x in json.loads((P/'selection.json').read_bytes())['ids']))
# Each condition: variable-bound claim, feature index or None, sufficient evidence,
# optional ambiguity note. These are authored by reading all ten original prompts.
MANUAL={
28596:({'R':'山脉','I':'岛屿','H':'狩猎方法'},'H 在 R 的流行程度达到高峰的十年',[
('R 位于 I 的北部海岸',1,'地理资料明确连接 R、I 与北部海岸方位','原 feature 是 northern West Coast，并不等于整个岛的北海岸。'),
('I 是南方的岛屿',1,'资料给出 I 的南方位置或南岛身份','southern 的参照系未定义。'),
('R 气候凉爽',1,'地理资料明确说 R 气候凉爽'),('R 气候湿润',1,'地理资料明确说 R 气候湿润'),
('R 的地形崎岖',None,'资料描述 R 的崎岖地貌'),('H 使用航空器',2,'狩猎方法资料明确其使用航空器'),
('H 在 R 被用于狩猎',2,'资料直接把该狩猎方法定位到 R'),
('H 在 R 曾显著流行',None,'当地历史资料明确记载 H 的流行','流行与实际作业量的高峰不一定相同。'),
('H 因适应崎岖地形的效率而流行',None,'当地资料直接说明流行与地形适应效率之间的原因关系','不能仅凭直升机能飞越地形推断因果。')]),
193660:({'P':'文学人物','C':'出生城市','D':'争议地区','N':'题述国家','L':'N 的最大城市','U':'大学','W':'作家组织','M':'回忆录的译本'},'P 所译 M 的书名及该译本出版年份',[
('P 出生于 C',1,'人物资料明确写 P 的出生地 C'),('C 是 D 的首府',1,'地区资料明确写 D 的首府是 C'),
('D 位于高加索',1,'地理资料明确把 D 放在高加索'),('D 的地位有争议',1,'资料明确说明 D 的争议地位','地位和首府称谓可能依时代或立场变化。'),
('P 出生于二十世纪中叶',1,'人物资料提供可落入该时段的出生日期','中叶没有唯一数值区间。'),
('P 是 U 的教授',2,'人物或大学资料明确 P 的教授职位'),('U 是一所主要大学',2,'可靠资料明确 U 的主要或重要大学地位','major 不是可机械确定的排名阈值。'),
('U 位于 L',2,'大学地址资料明确其所在城市 L'),('L 是 N 的最大城市',2,'城市资料明确最大城市关系','最大按人口还是面积未定义。'),
('P 是 W 的成员',3,'人物或组织资料明确成员关系'),('W 是 N 的全国性作家组织',3,'组织资料明确全国范围与作家性质'),
('P 翻译了 M',4,'书目或人物资料明确该译作与译者 P 的关系'),
('M 讲述一个美国亚美尼亚家庭的经历',4,'作品简介明确家庭身份与叙述对象'),
('M 的家庭经历涉及亚美尼亚种族灭绝',4,'作品简介直接说明相应历史经历'),
('M 于二十一世纪初出版',4,'译本书目列出出版年份','原著年份与译本年份不同，不能替换。'),
('M 的出版地是 N 的首都',4,'译本书目给出出版地且资料建立其首都身份','题目 country 指代靠上下文；feature 把 memoir 写为 novel。')]),
230779:({'F':'基金会','P':'创办者','D':'文化领域','W':'在线平台','M':'协作筹资机制','B':'更广义机制','N':'非营利主体','E':'共享百科资源'},'当地知名新闻来源对 F 首要使命的表述',[
('P 创办 F',1,'基金会或可靠报道直接写创办者 P'),('F 致力于推进 D',2,'基金会宗旨或报道明确其目标领域 D'),
('P 创建在线平台 W',3,'平台或报道直接连接 W 与创建者 P'),('W 采用 M 筹资',4,'平台说明直接写使用的筹资机制'),
('W 服务于 D 的创作者',4,'平台资料明确目标用户及所属领域'),('W 帮助创作者绕过传统融资障碍',4,'报道明确该平台解决的融资障碍'),
('M 属于更广义的 B',5,'定义性来源明确两机制的包含关系','众筹与众包不能仅凭名称相近认定。'),
('B 汇集公众资源',5,'定义性来源说明资源由公众贡献'),('B 可用于多种目标',5,'定义性来源说明用途不局限一种目标','various objectives 较泛。'),
('非营利主体 N 使用 B',6,'具体来源说明 N 实际采用 B'),('N 通过 B 创建 E',6,'资料明确 N、机制 B 与产物 E 的关系','Wikipedia 是资源/项目，不必然是法律上的非营利主体。'),
('E 是在线百科全书',6,'资源介绍说明 E 为在线百科'),('志愿者向 E 贡献知识',6,'资源介绍明确志愿贡献机制'),
('对 F 的使命回答需有当地新闻来源依据',None,'可核验的当地新闻报道直接表述 F 使命','prominent/local 未指定媒体或地域；不是答案排版要求。')]),
255548:({'C':'城市','N':'国家','E':'政治暴力事件','P':'上校','K':'政变','V':'副总统','T':'军事审判'},'审判 T 的持续时间',[
('C 位于 N 的东南部',1,'地理资料明确 C 相对 N 的东南位置'),('C 是港口城市',1,'地理资料明确港口城市身份'),
('N 位于南亚',1,'地区资料明确 N 属于南亚'),('E 发生于 C',1,'历史资料明确事件地点'),
('E 发生于五月下旬',1,'事件日期明确落在五月下旬'),('E 发生于二十世纪八十年代初',1,'历史资料提供符合该时段的年份','early 没有严格范围。'),
('E 引发政治权力交接',None,'历史叙述明确 E 与继任之间的因果'),('P 是上校',2,'人物或事件资料明确军衔'),
('P 参与政变 K',2,'资料明确 P 的政变参与关系'),('K 失败',2,'历史叙述明确政变未成功'),
('P 在 K 后不久死亡',2,'死亡日期与政变日期或相对时间有明确证据','shortly 的时间尺度未指定。'),
('V 在 E 之前担任副总统',3,'历史资料明确事发时副总统身份'),('V 在 E 后成为代理总统',3,'历史资料明确继任时间与代理身份'),
('T 由军事法庭审理',None,'案件资料明确审理机构为军事法庭'),('T 审理 E 的参与者',None,'案件资料明确被告与 E 的关系'),
('T 在较短时间内结束',None,'资料给出审判起止或时长','relatively quickly 是定性说法，时长目标另列 answer_relation。')]),
279034:({'B':'乐队','G':'音乐类型','A':'专辑','S':'录音室','C':'城市','U':'大学'},'B 为何对 A 采用现场录音且少量后期叠录',[
('B 属于 G',1,'音乐资料明确 B 的类型归属'),('G 具有激烈节奏',1,'类型介绍明确节奏特征'),
('G 具有情绪化人声',1,'类型介绍明确人声特征'),('A 是 B 的专辑',1,'作品资料明确乐队与专辑关系'),
('A 获得评论界好评',1,'乐评或可靠资料明确评价','critically acclaimed 无统一阈值。'),
('A 在 S 录制',2,'录音资料明确录音室'),('S 位于 C',2,'录音室资料明确城市'),('C 位于南加州',2,'地理资料明确城市区域'),
('C 是海滨城市',2,'地理资料明确沿海位置'),('C 以海滩闻名',2,'城市介绍明确海滩声誉','famous/beautiful 属主观修饰。'),
('U 位于 C',2,'大学地址明确所在城市 C'),
('U 是著名大学',2,'可靠资料明确 U 的声誉','prestigious 没有阈值。'),
('A 的录制持续数周',2,'录制资料给出周数或起止时间'),('A 录制于二十一世纪初',2,'录制时间明确符合时段','不能用发行年直接替代录制年。'),
('A 被视为 G 的代表作品',3,'类型评论明确其代表性','defining work 属评价。'),
('B 对 A 使用现场录音',None,'录制资料明确 live recording'),('B 对 A 尽量减少叠录',None,'录制资料明确 minimal overdubs'),
('B 希望录音保留现场表演的能量',None,'乐队或制作人说明明确能量目标','题面已给出原因线索，存在答案泄漏式重述。'),
('B 希望录音保留现场表演的激情',None,'乐队或制作人说明明确情感目标','与上一条件近义但题面并列；粒度需后续确定。')]),
320819:({'M':'自治市','T':'主镇','S':'州','R':'沿海区域','U':'邻近城镇','P':'美国艺术家'},'M 行政边界的极端经纬度，而非中心点坐标',[
('M 位于墨西哥的 S 州',1,'行政资料明确自治市所属州与国家'),('S 位于墨西哥南部',1,'地理资料明确州的南部位置'),
('T 是 M 的主镇或行政中心',2,'行政资料明确中心城镇'),('T 与 M 同名',2,'行政资料明确自治市与中心镇名称相同'),
('M 位于沿海区域 R',3,'地理资料明确 M 与 R 关系及 R 沿海身份'),
('M 以自然景观闻名',None,'当地介绍明确自然景观声誉','宽泛宣传性描述。'),('M 具有文化遗产声誉',None,'当地介绍明确文化遗产','文化遗产范围未指定。'),
('R 以海滩闻名',None,'区域资料明确海滩声誉','声誉没有阈值。'),('R 有历史遗址',None,'资料明确 R 内的历史遗址'),
('U 在 M 附近',4,'地图或地理资料明确邻近关系','nearby 未给距离；feature 并未证明邻近。'),
('U 以银矿业闻名',4,'城镇资料明确银矿业'),('P 来自美国',4,'人物资料明确美国身份'),
('P 是艺术家',4,'人物资料明确艺术职业'),('P 促成 U 银业复兴',4,'历史资料明确其因果贡献'),
('U 银业复兴发生于二十世纪',4,'历史资料明确复兴时段','采矿与银匠工艺复兴不完全等同。')]),
338424:({'T':'城镇','C':'县','G':'gmina','V':'省','B':'省会','P':'宫殿','Q':'广场','H':'历史人物','F':'森林'},'T 所在省 V 的名称',[
('T 位于波兰东北部',None,'地理资料明确东北部位置'),('T 是 C 的行政中心',1,'行政资料明确县治关系'),
('T 是 G 的行政中心',1,'行政资料明确 gmina 中心关系'),('T 位于 V',1,'行政资料明确所属省'),
('B 是 V 的省会',2,'行政资料明确省会关系'),('宫殿 P 位于 B',4,'宫殿资料明确城市'),
('P 被称为波兰凡尔赛',4,'资料明确该别称'),('广场 Q 位于 B 的中心',5,'城市资料明确广场位置'),
('Q 以历史人物 H 命名',5,'地名来源资料明确命名对象','feature 原 key 只提广场名称，不直接说明人物身份。'),
('森林 F 位于 V',3,'地理资料明确森林在省内','跨国森林不能误写为完全属于 V。'),
('F 是 UNESCO 世界遗产',3,'遗产资料明确该森林的世界遗产身份')]),
351873:({'G':'昆虫属','A':'农业害虫','S':'模式种','E':'昆虫学家','U':'亚科','F':'科'},'G 的模式种 S 的科学名称',[
('G 包含害虫 A',1,'分类资料明确 A 属于 G'),('A 是澳大利亚农业害虫',1,'农业或物种资料明确地域与害虫性质','不能仅凭在澳大利亚出现推断危害农业。'),
('E 描述建立 G',3,'分类资料明确属的命名或描述作者'),('E 是著名昆虫学家',3,'人物资料明确职业和声誉','prominent 没有量化阈值。'),
('G 描述建立于二十世纪初',3,'分类文献明确年份'),('G 属于 U',2,'分类资料明确属与亚科关系'),
('U 属于 F',2,'分类资料明确亚科与科关系'),('F 包含蝗虫或蚱蜢',2,'分类介绍明确科的动物范围'),
('S 是 G 的模式种',1,'分类资料明确使用 type species 或等价模式种声明','feature key 只说包含该物种，并未直接证明模式种身份。'),
('S 的俗名是 spur-throated locust',1,'物种资料直接连接科学名与俗名','不能默认题中的农业害虫 A 与模式种 S 必然同一，需要证据连接。')]),
383526:({'N':'岛国','R':'北部区域','V':'河流','B':'海湾','S1':'溪流一','S2':'溪流二','I':'目标岛屿'},'位于 V 入海口以东的岛屿 I 的名字',[
('N 是岛国',3,'国家资料明确岛国身份'),('R 位于 N 北部',3,'地理资料明确区域与国家方位'),
('N 以生物多样性闻名',3,'资料明确该国家的生物多样性声誉','known for 属宽泛描述。'),
('N 以文化遗产闻名',3,'资料明确文化遗产声誉','rich/cultural heritage 未指定对象。'),
('V 位于 R',3,'河流资料明确区域'),('V 对当地自然景观有显著贡献',1,'地理或生态资料明确景观作用','significantly 难以二元核实。'),
('V 流入 B',2,'河流资料明确河口与海湾'),('V 与 S1 汇合',2,'水系资料明确第一条支流的汇合'),
('V 与另一条不同的 S2 汇合',2,'水系资料明确第二条独立溪流的汇合','两溪的汇合点是否都在河口未必明确。'),
('I 位于 V 入海口以东',None,'地图或地理资料直接给出目标岛与河口的相对位置')]),
437922:({'P':'当代后卫','Q':'较早时代球员','R':'最终所问球员','E':'年度展示赛事','T':'防守奖项'},'R 获 T 的年份集合',[
('P 是冰球后卫',1,'球员资料明确位置'),('P 多次获得技能方面的荣誉',1,'荣誉记录明确至少两次','具体荣誉是否就是 T，题面没有完全说清。'),
('P 第二次参加 E',1,'赛事资料明确第二次入选或出场','named to 与实际 appearance 不完全等同。'),
('E 是职业冰球年度展示赛事',1,'赛事资料明确项目、职业性质与年度举办'),
('P 第二次参加 E 是近期事件',1,'有明确年份且与题目写作时间相符','recently 缺少题目参考日期。'),
('Q 的时代早于 P',2,'球员生涯资料给出先后时代'),('Q 多次获得 T',2,'获奖名单明确 Q 至少两次获 T'),
('P 的荣誉与 Q 的 T 属同类',None,'题目所指荣誉来源明确相同奖项或类别','同一奖项与同一类别不能混用。'),
('R 是与上述人物不同的球员',3,'题目消歧或获奖记录能确定 R 的指代','feature key 写的是 P，却映射成 different player，明显锚点不一致。'),
('R 在二十一世纪一十年代初获得 T',3,'同一奖项的名单明确 R 与早期年份','feature key 的 2019–20 起始无法直接支持此条件。'),
('R 在二十一世纪一十年代末获得 T',3,'同一奖项名单明确 R 与末期年份','赛季名与公历年份口径可能不同。'),
('T 奖励出色防守表现',None,'奖项定义明确防守表现为评选对象')])}

out=[]
by_id={hashlib.sha256(' '.join(unicodedata.normalize('NFKC',r['prompt']).casefold().split()).encode()).hexdigest():r for r in rows}
assert set(by_id)==set(ids)
for qid in ids:
    row=by_id[qid]
    variables,relation,conditions=MANUAL[row['id']]
    keys=list(json.loads(row['fuzzed_features']))
    cs=[]
    for i,item in enumerate(conditions,1):
        text,feature,evidence,*ambiguity=item
        cs.append({'id':f'C{i}','description':text,'feature_key':keys[feature-1] if feature else None,
                   'feature_index':feature,'source':'fuzzed_features' if feature else 'prompt_only',
                   'sufficient_support':evidence,'ambiguous':bool(ambiguity),'ambiguity':ambiguity[0] if ambiguity else None})
    out.append({'question_id':qid,'source_question_id':row['id'],'question_sha256':hashlib.sha256(row['prompt'].encode()).hexdigest(),
                'variables':variables,'conditions':cs,'answer_relation':relation,
                'ambiguities':[{'condition_id':c['id'],'note':c['ambiguity']} for c in cs if c['ambiguous']],
                'status':'inference_demo_not_gold','author':'codex_direct_reading','additional_model_calls':0})
(O/'atomic_conditions_pilot.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
allc=[c for q in out for c in q['conditions']]
summary={'questions':len(out),'conditions':len(allc),'feature_linked':sum(c['feature_key'] is not None for c in allc),
         'prompt_only':sum(c['source']=='prompt_only' for c in allc),'ambiguous_conditions':sum(c['ambiguous'] for c in allc),
         'per_question':[{'question_id':q['question_id'],'source_question_id':q['source_question_id'],
                          'conditions':len(q['conditions']),'feature_linked':sum(c['feature_key'] is not None for c in q['conditions']),
                          'prompt_only':sum(c['source']=='prompt_only' for c in q['conditions']),
                          'ambiguous':sum(c['ambiguous'] for c in q['conditions'])} for q in out],
         'note':'feature linkage is an anchor, not proof or gold; vague constraints retained and marked rather than silently removed'}
for k in ['feature_linked','prompt_only','ambiguous_conditions']:summary[k+'_fraction']=summary[k]/len(allc)
(O/'atomic_conditions_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='per_question'},ensure_ascii=False))
