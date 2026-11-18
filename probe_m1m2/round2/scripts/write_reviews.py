"""Serialize Codex's direct reviews; no model calls or automatic semantic judging.

Private inspection input is produced by analyze_round2.py; public excerpts are
bounded and checked against original strings. These labels are demonstrations.
"""
import hashlib
import json
import re
from pathlib import Path

O = Path(__file__).resolve().parents[1]
events = json.loads((O/'private/run-190949/private/review_events.json').read_bytes())
atomic = json.loads((O/'atomic_conditions_pilot.json').read_bytes())
idx = {(e['trajectory_id'], e['stage_id']): e for e in events}

def get(prefix, rep, stage):
    return next(e for e in events if e['trajectory_id'].startswith(prefix)
                and e['trajectory_id'].endswith('rep'+str(rep)) and e['stage_id']==stage)

def quote(e, text, docid=None, reasoning=False):
    if reasoning:
        body=e['reasoning']; field='reasoning'
    elif e['tool']=='search':
        body=next(r['caption'] for r in e['tool_result']['results'] if r['docid']==docid)
        field='caption'
    else:
        body=e['tool_result']['text']; field='text'; docid=e['docid']
    assert text in body
    assert len(text.split()) <= (30 if reasoning else 40)
    start=body.index(text)
    return {'stage_id':e['stage_id'],'docid':docid,'field':field,
            'quote':text,'start':start,'end':start+len(text),
            'source_sha256':hashlib.sha256(body.encode()).hexdigest()}

# Judgments below were made after reading the paired queries and available think.
NEAR = {
 ('9c85ac30',2,'R18'):('same_target','仅增加 methods，仍查询同一地区的航空器狩猎方法。'),
 ('f23ca343',1,'R15'):('changed_target','自治市坐标扩大为沿海区域地理与坐标；范围发生变化。'),
 ('9c85ac30',1,'R20'):('changed_target','增加 southern island，进一步限制地理范围。'),
 ('9c85ac30',2,'R15'):('changed_target','湿润与凉爽是不同气候属性，不能因其余词相同就扣分。'),
 ('f23ca343',2,'R12'):('changed_target','新增 coordinates，转向此前查询未明确要求的坐标属性。'),
 ('9c85ac30',1,'R18'):('changed_target','增加年代限制，转向历史时间范围。'),
 ('9e969ef4',2,'R4'):('same_target','均寻找同一刺杀案审判的持续时间；military court 是对象澄清。'),
 ('9c85ac30',2,'R17'):('changed_target','增加 hunting aircraft，新增狩猎手段关系。'),
}

md=['# 重复调用示例','',
    '**[已验证]** 前后参数与间隔直接来自冻结 Stage；**[推断]** S_near 判断由 Codex 阅读后给出，不是金标。',
    '各类按 sha256("round2|"+trajectory_id+"|"+stage_id) 升序取最多 8 个；同一事件可跨类别出现。',
    '间隔只数工具 Stage。S_allseen 的见过集合可由多次历史调用共同构成，配对的一次不代表单独覆盖全部文档。','']
examples=[]
for flag in ['S_exact','S_near','S_allseen','O_exact']:
    selected=sorted((e for e in events if flag in e['flags']),
                    key=lambda e:hashlib.sha256(('round2|'+e['trajectory_id']+'|'+e['stage_id']).encode()).hexdigest())[:8]
    md += ['## '+flag,'']
    if not selected:
        md += ['本批 0 次，无真实例子，不构造替代案例。','']; continue
    for e in selected:
        earlier=idx[e['trajectory_id'],e['earlier_match_stage_ids'][flag][-1]]
        gap=e['stage_index']-earlier['stage_index']-1
        # Only brief actual purpose sentences; semantic verdicts are authored above.
        snippets=[s.strip() for s in re.split(r'(?<=[.!?])\s+',e['reasoning'] or '')
                  if 0<len(s.split())<=30 and re.search(r'(?i)search|find|try|look',s)]
        reason=snippets[0] if snippets else None
        if reason: assert reason in e['reasoning']
        record={'class':flag,'trajectory_id':e['trajectory_id'],'stage_id':e['stage_id'],
                'earlier_stage_id':earlier['stage_id'],'intervening_tool_stages':gap,
                'reason_excerpt':reason}
        md += [f"### {e['trajectory_id']} / {e['stage_id']}",'',
               f"前：`{earlier['stage_id']}` — `{earlier['query_or_docid_start']}`  ",
               f"后：`{e['stage_id']}` — `{e['query_or_docid_start']}`  ",
               f"间隔：{gap} 个 Stage；全部匹配历史：{', '.join(e['earlier_match_stage_ids'][flag])}。",'']
        md += ['推理摘录：'+('“'+reason+'”' if reason else '该轮没有可引用的推理说明。'),'']
        if flag=='S_near':
            key=(e['trajectory_id'][:8],int(e['trajectory_id'][-1]),e['stage_id'])
            decision,note=NEAR[key]; record.update(decision=decision,note=note)
            md += ['**[推断] '+('同一检索目标' if decision=='same_target' else '目标或范围有实质变化')+'：** '+note,'']
        examples.append(record)
md += ['## 抽查小结','',
       '**[推断]** 8 个 S_near 例子中，2 个仍在找同一信息，6 个增加或改变属性、时间或地域范围；这不是总体精确率估计。',
       'S_allseen 只证明 docid 见过，不证明本次摘要逐字相同，也不直接证明查询本身没有必要。','']
(O/'redundancy_examples.md').write_text('\n'.join(md),encoding='utf-8')

def demo(prefix,rep,selection_reason,bindings):
    es=[e for e in events if e['trajectory_id'].startswith(prefix) and e['trajectory_id'].endswith('rep'+str(rep))]
    q=next(q for q in atomic if q['question_id']==es[0]['question_id'])
    return {'trajectory_id':es[0]['trajectory_id'],'source_question_id':q['source_question_id'],
            'selection_reason':selection_reason,'status':'[推断] 示范，不是金标',
            'candidate_bindings':bindings,
            'conditions':[{'condition_id':c['id'],'first_supported_stage':None,'evidence':[],
                           'partial':[],'note':'截至轨迹结束未见足够的工具证据。'} for c in q['conditions']],
            'stage_review':[],'misreadings_or_inference_errors':[]}

def condition(d,cid,supported=None,evidence=None,partial=None,note=None):
    c=next(c for c in d['conditions'] if c['condition_id']==cid)
    c.update(first_supported_stage=supported,evidence=evidence or [],partial=partial or [])
    if note:c['note']=note

insect=demo('47228490',1,'已有判分答对；2 次调用',
            {'G':'Austracris','A':'Austracris guttulosa','S':'候选 Austracris guttulosa，模式种身份未验证',
             'F':'Acrididae','E':None,'U':None})
i1=get('47228490',1,'R1'); i2=get('47228490',1,'R2')
q1=quote(i1,'Austracris includes the spur-throated locust, Austracris guttulosa, which is a significant pest in Australia.','Austracris guttulosa')
q2=quote(i2,'It is an agricultural pest in Queensland, New South Wales, Victoria South Australia and Western Australia.')
q8=quote(i1,'Arcyptera tornosi, the Iberian banded grasshopper, belongs to the family Acrididae, which includes many species of grasshoppers.','Acrididae')
q10=quote(i1,'Austracris guttulosa, commonly known as the spur-throated locust, is a significant pest in Australia.','Spur-throated locust')
condition(insect,'C1','R1',[q1],note='明确属包含该农业害虫候选；不等于证明模式种。')
condition(insect,'C2','R2',[q2],partial=[{'stage_id':'R1','evidence':[q10],
          'note':'第一条摘要称澳大利亚 pest，但未明确农业；另一个管理摘要可作间接线索。'}],note='R2 正文明确 agricultural pest，结合此前澳大利亚定位。')
condition(insect,'C8','R1',[q8],note='明确科包含 grasshoppers。')
condition(insect,'C10','R1',[q10],note='只对候选 S=guttulosa 的俗名成立；S 的模式种角色 C9 仍未证实。')
insect['stage_review']=[{'stage_id':'R1','new_supported':['C1','C8','C10'],'partial':['C2'],
                        'note':'候选物种、属和俗名可连接，缺少属建立者、亚科与模式种关系。'},
                       {'stage_id':'R2','new_supported':['C2'],'partial':[],
                        'note':'农业危害得到明确支持，正文仍没有 type species 断言。'}]
insect['misreadings_or_inference_errors']=[{'kind':'unsupported_role_not_direct_misquote',
 'stage_id':'R2','note':'未发现明确误读返回；答对不代表模式种条件已取证。不能把属包含物种升级为模式种。',
 'propagated_to_next_query':False,'next_query_stage':None}]

foundation=demo('c78a3998',2,'已有判分：提交但答错；6 次调用',
 {'F':'未确定；agent 错把背景实体 Wikimedia Foundation 当作 F',
  'P':'未确定；agent 候选 Jimmy Wales','N':'候选 Wikimedia Foundation','E':'Wikipedia','B':'尚未明确的众包机制'})
f2=get('c78a3998',2,'R2'); f3=get('c78a3998',2,'R3')
fq=quote(f2,'The project was originally funded by Bomis, Wales\'s for-profit business, and edited by a rapidly growing community of volunteer editors.')
condition(foundation,'C13','R2',[fq],note='段落中的 project 明确承接 Wikipedia；这是背景 E 的事实，不能迁移成目标 F 的使命。')
condition(foundation,'C12',partial=[{'stage_id':'R1','evidence':[quote(get('c78a3998',2,'R1'),
 'The Italian Wikipedia is owned and operated by the Wikimedia Foundation, a non-profit organization dedicated to promoting free knowledge.','Wikimedia Foundation')],
 'note':'明确关联 Wikipedia 与非营利主体，但没有明确 encyclopedia 类型断言；不得用常识补全。'}])
shared=quote(f2,'The Wikimedia Foundation provides the technical and organizational infrastructure to enable members of the public to develop wiki-based content in languages across the world.')
for cid in ['C8','C10','C11']:
    condition(foundation,cid,partial=[{'stage_id':'R2','evidence':[shared],
      'note':'公共协作是背景线索；没有把机制 B、创建关系和题述平台完整连接。'}])
wrongmission=quote(f3,"The foundation's mission is collection and distribution of educational knowledge under free licenses or public domain and promised to keep these projects free of charge.")
foundation['alternative_candidate_facts']=[{'stage_id':'R3','entity':'Wikimedia Foundation',
 'evidence':[wrongmission],'note':'该使命在原文真实存在，但未验证这是题述 F，且未满足当地新闻来源条件 C14。'}]
for stage,note in [('R1','百科背景与非营利主体被检索到，目标 F 的身份尚未成立。'),
                   ('R2','取得背景项目的志愿编辑事实；未连接题述创办者、平台与文化领域。'),
                   ('R3','取得错误候选的使命，新闻来源仍缺。'),
                   ('R4','单词 mission 检索到传教站，agent 后续正确识别其无关。'),
                   ('R5','继续读取同一候选的财务、董事与人员信息，未补足目标身份。'),
                   ('R6','调用不存在的 answer 工具，收到错误；之后有 Final，但已有判分为错。')]:
    foundation['stage_review'].append({'stage_id':stage,'new_supported':['C13'] if stage=='R2' else [],'note':note})
foundation['misreadings_or_inference_errors']=[
 {'kind':'entity_role_conflation','stage_id':'R2',
  'reasoning_excerpt':quote(f2,'Therefore, the foundation is Wikimedia.',reasoning=True),
  'note':'把题中的背景百科推成待识别基金会。摘要只支持非营利与百科关联，未支持平台创办者链。',
  'propagated_to_next_query':True,'next_query_stage':'R2','next_query':f2['query_or_docid_start']},
 {'kind':'known_gap_downgraded','stage_id':'R4',
  'note':'推理承认使命没有新闻归属，仍认定候选正确；后续返回错误词义后也不重新验证实体。',
  'propagated_to_next_query':True,'next_query_stage':'R5','next_query':get('c78a3998',2,'R5')['query_or_docid_start']}]

hockey=demo('3b18a3ca',2,'用满 20 次调用而未提交；重复集中轨迹',
 {'P':None,'Q':'暂议 Rod Langway，未确认题述身份','R':'agent 候选 Roman Josi',
  'T':'agent 候选 Norris Trophy，题述奖项身份未建立','E':'候选 NHL All-Star Game'})
h2=get('3b18a3ca',2,'R2'); h3=get('3b18a3ca',2,'R3')
lang=quote(h2,'Rod Langway won the Norris Trophy as the top defenseman in the NHL in both 1983 and 1984.','Norris Trophy')
josi=quote(h2,'Roman Josi won the James Norris Memorial Trophy in the 2019–20 NHL season, becoming the first Swiss player and the first player in Predators\' franchise history to win the award.','James Norris Memorial Trophy')
for cid,note in [('C7','局部候选 Rod Langway 多次获 Norris 成立，但其是否是题述 Q、奖项是否为 T 未建立。'),
                 ('C12','top defenseman 是位置/综合评价，不足以证明题述具体防守奖项就是 Norris。')]:
    condition(hockey,cid,partial=[{'stage_id':'R2','evidence':[lang],'note':note}])
condition(hockey,'C11',partial=[{'stage_id':'R2','evidence':[josi],
  'note':'仅支持候选 Roman Josi 的 2019–20 赛季获奖；题述人物/奖项未建立且年份跨年代。'}])
condition(hockey,'C4',partial=[{'stage_id':'R6','evidence':[quote(get('3b18a3ca',2,'R6'),
 'Bridgestone Arena was the venue for the 2016 NHL All-Star Game, a showcase of top talent in the National Hockey League.','2016 NHL All-Star Game')],
 'note':'有 showcase 和赛事关系，未明确年度属性或题述 P 的第二次出场。'}])
for e in [e for e in events if e['trajectory_id']==hockey['trajectory_id']]:
    n=e['round']
    note={1:'泛搜返回含大量曲棍球信息，agent 后续识别运动项目不符。',
          2:'出现 Norris、Langway 与 Josi 局部事实；题述实体链仍未连接。',
          3:'锁定 Josi 多次获奖的猜测，返回只支持一个获奖赛季与队长身份。',
          4:'加入年份列表，无早期获奖证据。',5:'换成 defense awards，夹杂其他运动。',
          6:'首次该固定查询，出现年度展示赛事的弱线索。'}.get(n,'与 R6 查询和返回完全相同，没有新的候选链支持。')
    hockey['stage_review'].append({'stage_id':e['stage_id'],'new_supported':[],
      'same_return_as':'R6' if n>6 else None,'return_sha256':hashlib.sha256(e['raw_return'].encode()).hexdigest(),'note':note})
    if n>6:
        assert e['raw_return']==get('3b18a3ca',2,'R6')['raw_return']
        assert e['reasoning']==get('3b18a3ca',2,'R6')['reasoning']
hockey['misreadings_or_inference_errors']=[{'kind':'unsupported_candidate_narrowing',
 'stage_id':'R3','reasoning_excerpt':quote(h3,'Roman Josi might have won it multiple times in both periods.',reasoning=True),
 'note':'原摘要只给出一个获奖赛季，推理把未证实的多次获奖假设变为下一步主要方向；不是原文明确说了多次。',
 'propagated_to_next_query':True,'next_query_stage':'R3','next_query':h3['query']},
 {'kind':'unverified_award_identity','stage_id':'R1',
  'note':'调用前已假定奖项为 Norris，随后从未建立题述奖项、三位球员的关系；feature 锚点本身也有冲突。',
  'propagated_to_next_query':True,'next_query_stage':'R2','next_query':h2['query']}]

result={'status':'[推断] 直接阅读示范；不作金标或 Judge 质量验收','author':'codex_direct_reading',
 'additional_model_calls':0,'scope':'仅累计当前及更早工具返回；没有用后续返回补写首次支持。feature/参考答案不是可见证据。',
 'binding_policy':'支持按明确候选绑定记录；局部实体属性不等于候选已满足整个问题。角色未定时保留 partial。',
 'demos':[insect,foundation,hockey],
 'annotation_difficulties':['属包含物种不等于该物种是模式种；答案正确也可能缺少关键关系证据。',
  '背景实体与待求实体必须分开，不能把另一实体的使命迁移到目标。',
  '候选局部事实支持与题述身份确认是两层判断；是否把候选属性记为 supported 必须固定口径。',
  'top defenseman 与 outstanding defensive play 不必等价，赛季也不等同公历年。',
  '缺少关键链时，反复检索不是明确反证；不能写成模型无视已证明的反证。',
  '跨 Stage 代词消解应保留依据；模糊修饰词和有冲突的 feature 不适合直接当分母。']}
for d in result['demos']:
    d['n_conditions']=len(d['conditions'])
    d['n_supported']=sum(c['first_supported_stage'] is not None for c in d['conditions'])
    d['n_partial_only']=sum(c['first_supported_stage'] is None and bool(c['partial']) for c in d['conditions'])
(O/'first_support_demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'example_review_index.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'examples':len(examples),'near_same':2,'near_changed':6,
                  'demos':[(d['source_question_id'],d['n_supported'],d['n_partial_only']) for d in result['demos']]}))
