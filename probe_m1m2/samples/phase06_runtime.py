"""Phase 0.6 local transport adapter; official Agent loop stays read-only."""
from pathlib import Path
import copy, datetime, hashlib, json, os, subprocess, sys, threading, time, urllib.request, urllib.error

ROOT = Path('/persist_data/home/weiyu/lanyi/projects/新实验')
REPORT = ROOT/'reports/successful_trajectory_redundancy_phase06'
STORE = Path('/file_storage01/home/weiyu/lanyi')
MODEL = STORE/'models/Qwen3.5-9B'
MODEL_REV = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
MODEL_NAME = 'Qwen/Qwen3.5-9B'
ENV = STORE/'envs/successful_phase05_20261007'
REF = ROOT/'third_party/BrowseComp-Plus'

def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def dump(path,obj):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n')
def http(url,body=None,timeout=1800):
 raw=None if body is None else json.dumps(body,ensure_ascii=False).encode()
 req=urllib.request.Request(url,data=raw,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as r:return r.read()
def gpu_snapshot():
 p=subprocess.run(['nvidia-smi','--query-gpu=index,name,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,capture_output=True)
 return {'utc':utc(),'csv':p.stdout,'exit_code':p.returncode,'allocation_cuda_visible_devices':os.getenv('CUDA_VISIBLE_DEVICES'),'note':'nvidia-smi may list the full node; use allocated physical device IDs, not node-wide maximum'}
class ContextStop(RuntimeError): pass
class LengthStop(RuntimeError): pass
class ObservabilityError(RuntimeError): pass
def free_local_port():
 import socket
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

class Server:
 def __init__(self,folder,context,gpu=None,port=None):
  port=free_local_port() if port is None else port
  self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.context=context;self.port=port;self.url=f'http://127.0.0.1:{port}'
  self.cmd=[str(ENV/'bin/python'),'-u','-m','vllm.entrypoints.openai.api_server','--model',str(MODEL),'--tokenizer',str(MODEL),'--served-model-name',MODEL_NAME,'--host','127.0.0.1','--port',str(port),'--tensor-parallel-size','1','--dtype','bfloat16','--max-model-len',str(context),'--gpu-memory-utilization','0.75','--max-num-seqs','1','--max-num-batched-tokens','8192','--reasoning-parser','qwen3','--enable-auto-tool-choice','--tool-call-parser','qwen3_coder','--language-model-only','--enforce-eager','--no-enable-prefix-caching','--generation-config','vllm']
  self.env=os.environ.copy()
  self.env.update(HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='6',VLLM_CACHE_ROOT=str(STORE/'cache/phase05/vllm'))
  if gpu is not None:self.env['CUDA_VISIBLE_DEVICES']=gpu
  self.samples=[];self.kv_samples=[];self.start=utc();self.t0=time.monotonic();self.log=(self.folder/'server.log').open('w');self.proc=subprocess.Popen(self.cmd,stdout=self.log,stderr=subprocess.STDOUT,env=self.env,start_new_session=True)
  dump(self.folder/'launch.json',{'command':self.cmd,'env':{k:self.env.get(k) for k in ['CUDA_VISIBLE_DEVICES','HF_HUB_OFFLINE','VLLM_CACHE_ROOT']},'started_utc':self.start,'job_id':os.getenv('SLURM_JOB_ID')})
  self.done=False;self.thread=threading.Thread(target=self._sample,daemon=True);self.thread.start()
 def _sample(self):
  while not self.done:
   self.samples.append(gpu_snapshot())
   try:
    metrics=http(self.url+'/metrics',timeout=2).decode();lines=[x for x in metrics.splitlines() if ('cache_usage' in x or 'kv_cache_usage' in x) and not x.startswith('#')]
    if lines:self.kv_samples.append({'utc':utc(),'raw_metric_lines':lines})
   except Exception:pass
   time.sleep(2)
 def wait(self):
  while self.proc.poll() is None:
   try:
    if http(self.url+'/health',timeout=3) is not None:
     models=json.loads(http(self.url+'/v1/models',timeout=3));assert models['data'][0]['id']==MODEL_NAME
     self.ready=utc();self.ready_seconds=time.monotonic()-self.t0
     dump(self.folder/'ready.json',{'ready_utc':self.ready,'startup_seconds':self.ready_seconds,'models':models,'gpu':gpu_snapshot()});return
   except (urllib.error.URLError,TimeoutError,ConnectionError):pass
   time.sleep(5)
  raise RuntimeError(f'vLLM exited {self.proc.returncode}; see {self.folder}/server.log')
 def metrics(self,name):
  try:(self.folder/f'{name}_metrics.txt').write_bytes(http(self.url+'/metrics',timeout=5))
  except Exception as e:dump(self.folder/f'{name}_metrics_error.json',{'error':repr(e)})
 def stop(self):
  import signal
  self.done=True
  if self.proc.poll() is None:
   os.killpg(self.proc.pid,signal.SIGTERM)
   try:self.proc.wait(timeout=120)
   except subprocess.TimeoutExpired:os.killpg(self.proc.pid,signal.SIGKILL);self.proc.wait()
  self.log.close();dump(self.folder/'GPU_TIMESERIES.json',self.samples);dump(self.folder/'KV_CACHE_TIMESERIES.json',self.kv_samples)

def reasoning_field(message):
 # Raw response stays unchanged. vLLM 0.19 uses reasoning; Qwen-Agent schema uses reasoning_content.
 if message.get('reasoning') is not None:return message['reasoning'],'reasoning'
 return message.get('reasoning_content'),'reasoning_content'

def message_dict(x):return x if isinstance(x,dict) else x.model_dump()
def native_tool_function(function):
 f=copy.deepcopy(function)
 if isinstance(f.get('parameters'),list):
  parameters=f['parameters']
  f['parameters']={'type':'object','properties':{p['name']:{k:v for k,v in p.items() if k not in ['name','required']} for p in parameters},'required':[p['name'] for p in parameters if p.get('required',False)]}
 assert isinstance(f.get('parameters'),dict),'Native tool schema requires a JSON Schema object'
 return f
def text_content(x):
 if isinstance(x,str):return x
 return ''.join(i.get('text','') if isinstance(i,dict) else (i.text or '') for i in (x or []))

def native_messages(logical):
 """Lossless legacy FunctionCall -> native tool_calls, with exact response IDs."""
 out=[];pending=[]
 for item in logical:
  m=message_dict(item);role=m['role'];extra=m.get('extra') or {};fc=m.get('function_call')
  if role=='function':
   assert pending,'Unmatched tool result'
   ident,name=pending.pop(0);assert name==m['name'],(name,m['name'])
   out.append({'role':'tool','tool_call_id':ident,'name':m['name'],'content':text_content(m.get('content'))});continue
  if role=='assistant':
   roundid=extra.get('round_id')
   if fc and out and out[-1]['role']=='assistant' and out[-1].get('_round_id')==roundid:
    target=out[-1]
   else:
    target={'role':'assistant','content':text_content(m.get('content')),'_round_id':roundid};out.append(target)
   if m.get('reasoning_content'):
    target['reasoning']=text_content(m['reasoning_content']);target['reasoning_content']=target['reasoning']
   if fc:
    ident=extra['tool_call_id'];target.setdefault('tool_calls',[]).append({'id':ident,'type':'function','function':{'name':fc['name'],'arguments':fc['arguments']}});pending.append((ident,fc['name']))
   continue
  out.append({'role':role,'content':text_content(m.get('content'))})
 for m in out:m.pop('_round_id',None)
 assert not pending,'Missing tool responses before next model call'
 return out

class Recorder:
 def __init__(self,folder,server,tokenizer,context,generation=10000,sampling=None):
  if (Path(folder)/'trajectory.json').exists():raise FileExistsError('Preserve existing raw trajectory; do not overwrite or regenerate')
  self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.server=server;self.tokenizer=tokenizer;self.context=context;self.generation=generation;self.rounds=[];self.events=[];self.guard_attempts=[];self.current=0
  self.sampling=copy.deepcopy(sampling or {'temperature':0.7,'top_p':0.8,'seed':42});self.sampling['max_tokens']=generation
  self.metadata={'job_id':os.getenv('SLURM_JOB_ID'),'model':MODEL_NAME,'model_revision':MODEL_REV,'tokenizer_revision':MODEL_REV,'created_utc':utc(),'service_max_model_len':context,'max_tokens':generation,'sampling':self.sampling,'headroom_tokens':256,'truncation_policy':'NO_SILENT_TRUNCATION_EXACT_GUARD_STOP','evaluation_status':'NOT_EVALUATED_DEBUG_ONLY'}
 def save(self):dump(self.folder/'trajectory.json',{'metadata':self.metadata,'rounds':self.rounds,'tool_events':self.events,'unsent_guard_attempts':self.guard_attempts})
 def call(self,request,logical=None):
  self.current+=1;rid=self.current;rd=self.folder/f'round_{rid:03d}';rd.mkdir(exist_ok=False)
  req=copy.deepcopy(request);req.update(model=MODEL_NAME,stream=False,return_token_ids=True)
  req.setdefault('chat_template_kwargs',{'enable_thinking':True})
  local_messages=copy.deepcopy(req['messages'])
  # Serving 0.19.1 maps reasoning to template reasoning_content. Tools parsed as objects before Jinja.
  for m in local_messages:
   if m.get('reasoning') is not None:m['reasoning_content']=m['reasoning']
   for tc in m.get('tool_calls',[]):
    if isinstance(tc['function'].get('arguments'),str):tc['function']['arguments']=json.loads(tc['function']['arguments'])
  prompt=self.tokenizer.apply_chat_template(local_messages,tools=req.get('tools'),tokenize=False,add_generation_prompt=True,**req['chat_template_kwargs'])
  expected_ids=self.tokenizer.encode(prompt,add_special_tokens=False)
  dump(rd/'logical_messages.json',logical if logical is not None else request['messages']);dump(rd/'raw_request.json',req)
  (rd/'raw_request.body').write_bytes(json.dumps(req,ensure_ascii=False).encode());(rd/'expected_serialized_prompt.txt').write_text(prompt)
  dump(rd/'expected_prompt_token_ids.json',expected_ids)
  record={'round_id':rid,'batch_id':f'B{rid:03d}','full_history':logical if logical is not None else copy.deepcopy(req['messages']),'actor_visible_messages':copy.deepcopy(req['messages']),'raw_request_path':str(rd/'raw_request.body'),'started_utc':utc(),'prompt_truncated':False,'completion_length_stop':False,'truncation':{'occurred':False,'removed_message_ids':[],'removed_tokens':0},'exact_guard':{'actual_local_templated_tokens':len(expected_ids),'max_tokens':req.get('max_tokens'),'context':self.context,'headroom':256},'response_received':False}
  if len(expected_ids)+req.get('max_tokens',self.generation)+256>self.context:
   record.update(round_id=None,attempted_round_id=rid,stop_classification='CONTEXT_LIMIT_STOP',guard_intercepted=True,request_sent=False);self.guard_attempts.append(record);self.save();raise ContextStop('Exact pre-transport context guard')
  record['request_sent']=True;self.rounds.append(record);self.save()
  self.server.metrics(f'round_{rid:03d}_before');t0=time.monotonic()
  try:raw=http(self.server.url+'/v1/chat/completions',req)
  except urllib.error.HTTPError as e:
   (rd/'raw_error_response.body').write_bytes(e.read());record.update(stop_classification='API_ERROR',error_status=e.code);self.save();raise
  (rd/'raw_response.body').write_bytes(raw);response=json.loads(raw);dump(rd/'raw_response.json',response)
  elapsed=time.monotonic()-t0;choice=response['choices'][0];msg=choice['message'];reasoning,reasonkey=reasoning_field(msg)
  actual_ids=response.get('prompt_token_ids');output_ids=choice.get('token_ids');usage=response.get('usage',{})
  actual_prompt=None if actual_ids is None else self.tokenizer.decode(actual_ids,skip_special_tokens=False)
  if actual_prompt is not None:(rd/'actual_serialized_prompt.txt').write_text(actual_prompt)
  if output_ids is not None:(rd/'raw_model_completion.txt').write_text(self.tokenizer.decode(output_ids,skip_special_tokens=False))
  ids_equal=actual_ids==expected_ids if actual_ids is not None else None
  finish=choice.get('finish_reason');tools=msg.get('tool_calls') or []
  stop='GENERATION_LENGTH_STOP' if finish=='length' else ('MODEL_TOOL_STOP' if tools else ('MODEL_FINAL_STOP' if (msg.get('content') or '').strip() else 'EMPTY_MODEL_STOP'))
  record.update(completion_length_stop=finish=='length',response_received=True,finished_utc=utc(),latency_seconds=elapsed,raw_response_path=str(rd/'raw_response.body'),raw_response=response,reasoning_content=reasoning,reasoning_source_field=reasonkey,content=msg.get('content'),tool_calls=tools,finish_reason=finish,stop_classification=stop,prompt_tokens=usage.get('prompt_tokens'),completion_tokens=usage.get('completion_tokens'),reasoning_tokens=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),token_accounting={'serving_reported':usage,'prompt_token_ids':actual_ids,'completion_token_ids':output_ids,'reconstructed_completion_tokens':None if output_ids is None else len(output_ids),'reasoning_field_retokenized_tokens':None if reasoning is None else len(self.tokenizer.encode(reasoning,add_special_tokens=False)),'reasoning_retokenized_is_derived_not_serving_usage':True,'exact_prompt_token_ids_equal':ids_equal,'serialized_prompt_path':str(rd/'actual_serialized_prompt.txt') if actual_prompt is not None else None},guard_intercepted=False)
  if reasoning is not None:(rd/'reasoning.txt').write_text(reasoning)
  self.server.metrics(f'round_{rid:03d}_after');self.save()
  if actual_ids is None or output_ids is None or not ids_equal:raise ObservabilityError(f'Actual token capture/serialization mismatch round {rid}: equal={ids_equal}')
  if finish=='length':raise LengthStop(f'Round {rid} generation budget exhausted; raw result preserved')
  return response
 def tool_start(self,name,args):
  roundrec=self.rounds[-1];ordinal=sum(e['round_id']==self.current for e in self.events)+1
  calls=roundrec['tool_calls'];assert ordinal<=len(calls);tc=calls[ordinal-1];assert tc['function']['name']==name
  event={'event_id':len(self.events)+1,'round_id':self.current,'batch_id':roundrec['batch_id'],'tool_ordinal':ordinal,'tool_call_id':tc['id'],'tool_name':name,'exact_arguments':args,'dispatch_order':len(self.events)+1,'dispatch_utc':utc()};self.events.append(event);self.save();return event
 def tool_end(self,event,result):
  obs=self.folder/f"tool_{event['event_id']:03d}";obs.mkdir(exist_ok=False)
  if isinstance(result,str):(obs/'actor_visible_observation.txt').write_text(result)
  event['actor_visible_observation_path']=str(obs/'actor_visible_observation.txt') if isinstance(result,str) else None
  event.update(return_utc=utc(),return_order=1+len([x for x in self.events if x.get('return_utc')]),exact_result=result)
  ep=self.folder/f"tool_{event['event_id']:03d}.json";dump(ep,event);event['result_path']=str(ep);self.save()
 def render(self):
  lines=['# Phase 0.6 debug trajectory','',json.dumps(self.metadata,ensure_ascii=False,indent=2),'']
  for r in self.rounds:
   lines += [f"## Round {r['round_id']}",'',f"Context tokens: {r.get('prompt_tokens')} / Stop: {r.get('stop_classification')}",'','### Reasoning (verbatim)','',r.get('reasoning_content') or '(empty)','', '### Content (verbatim)','',r.get('content') or '(empty)','']
   for e in self.events:
    if e['round_id']==r['round_id']:lines += [f"### Tool {e['event_id']} / {e['tool_name']}",'', '```json',json.dumps(e,ensure_ascii=False,indent=2),'```','']
  (self.folder/'trace.md').write_text('\n'.join(lines))

def make_native_agent(recorder,function_list):
 from qwen_agent.agents import Assistant
 from qwen_agent.llm.base import BaseChatModel
 from qwen_agent.llm.schema import Message,FunctionCall
 class NativeLocalModel(BaseChatModel):
  def __init__(self):
   super().__init__({'model':MODEL_NAME,'model_type':'phase06_native_local','generate_cfg':dict(recorder.sampling,max_retries=0)})
  def chat(self,messages,functions=None,stream=True,delta_stream=False,extra_generate_cfg=None):
   logical=[message_dict(x) for x in messages];req=dict(recorder.sampling,messages=native_messages(logical),seed=(extra_generate_cfg or {}).get('seed',42),chat_template_kwargs={'enable_thinking':True});assert req['max_tokens']==recorder.generation;assert all(req[k]==v for k,v in recorder.sampling.items())
   if functions:
    req['tools']=[{'type':'function','function':native_tool_function(f)} for f in functions];req['tool_choice']='auto'
   response=recorder.call(req,logical);msg=response['choices'][0]['message'];reasoning,_=reasoning_field(msg);output=[]
   output.append(Message(role='assistant',content=msg.get('content') or '',reasoning_content=reasoning,extra={'round_id':recorder.current,'raw_response_path':recorder.rounds[-1]['raw_response_path']}))
   for tc in msg.get('tool_calls') or []:
    fc=tc['function'];output.append(Message(role='assistant',content='',function_call=FunctionCall(name=fc['name'],arguments=fc['arguments']),extra={'round_id':recorder.current,'tool_call_id':tc['id']}))
   dump(recorder.folder/f'round_{recorder.current:03d}'/'qwen_agent_messages.json',[x.model_dump() for x in output])
   return iter([output]) if stream else output
  def _chat_stream(self,*args,**kwargs):raise NotImplementedError('Use lossless native chat adapter')
  def _chat_no_stream(self,*args,**kwargs):raise NotImplementedError('Use lossless native chat adapter')
  def _chat_with_functions(self,*args,**kwargs):raise NotImplementedError('Native chat override handles functions directly and preserves structured tool calls')
 class ObservedAssistant(Assistant):
  def _call_tool(self,name,args='{}',**kwargs):
   e=recorder.tool_start(name,args)
   try:result=super()._call_tool(name,args,**kwargs)
   except Exception as exc:
    recorder.tool_end(e,{'error':repr(exc)});raise
   recorder.tool_end(e,result)
   if getattr(self.function_map.get(name),'client_id',None) is not None and not e.get('raw_mcp_response_path'):
    raise ObservabilityError('MCP session reconnected or capture absent: do not continue with incomplete raw tool response')
   return result
 bot=ObservedAssistant(llm=NativeLocalModel(),function_list=function_list,system_message='')
 # Capture the complete MCP result before the official client flattens its text blocks.
 from qwen_agent.tools.mcp_manager import MCPManager
 if MCPManager._instance is not None:
  manager=MCPManager()
  client_ids={getattr(f,'client_id',None) for f in bot.function_map.values()}
  for client_id in client_ids:
   if client_id is None:continue
   session=manager.clients[client_id].session;original=getattr(session,'_phase06_original_call_tool',session.call_tool);session._phase06_original_call_tool=original
   async def captured_call_tool(name,arguments=None,*a,_original=original,**kw):
    response=await _original(name,arguments,*a,**kw)
    event=recorder.events[-1];raw=response.model_dump(mode='json',by_alias=True)
    path=recorder.folder/f"tool_{event['event_id']:03d}_raw_mcp_response.json";dump(path,raw)
    event['raw_mcp_request']={'name':name,'arguments':arguments};event['raw_mcp_response_path']=str(path);event['raw_mcp_response']=raw
    docs=[]
    for block in raw.get('content',[]):
     if block.get('type')=='text':
      try:
       obj=json.loads(block.get('text',''));docs.extend(obj if isinstance(obj,list) else [obj])
      except ValueError:pass
    event['retrieved_documents']=[dict(rank=i+1,**d) for i,d in enumerate(docs) if isinstance(d,dict) and 'docid' in d]
    event['retrieved_docids']=[d['docid'] for d in event['retrieved_documents']];recorder.save()
    return response
   session.call_tool=captured_call_tool
 return bot

def run_agent(recorder,messages,function_list):
 out=[];status='NOT_STARTED';bot=None
 try:
  bot=make_native_agent(recorder,function_list)
  from qwen_agent.settings import MAX_LLM_CALL_PER_RUN
  assert MAX_LLM_CALL_PER_RUN==20
  for out in bot.run(messages=messages,seed=42):dump(recorder.folder/'qwen_agent_history_latest.json',out)
  status=recorder.rounds[-1]['stop_classification'] if recorder.rounds else 'NO_MODEL_CALL'
  if status=='MODEL_TOOL_STOP':status='AGENT_SAFETY_CEILING_STOP'
 except (ContextStop,LengthStop) as e:status='CONTEXT_LIMIT_STOP' if isinstance(e,ContextStop) else 'GENERATION_LENGTH_STOP';dump(recorder.folder/'terminal_exception.json',{'type':type(e).__name__,'error':str(e)})
 except Exception as e:
  import traceback
  status='OBSERVABILITY_ERROR' if isinstance(e,ObservabilityError) else 'RUNTIME_ERROR';dump(recorder.folder/'terminal_exception.json',{'type':type(e).__name__,'error':str(e),'traceback':traceback.format_exc()})
 finally:
  recorder.metadata['terminal_status']=status;recorder.save();recorder.render()
 return out,status
