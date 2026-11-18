import unittest
from native_stages import stage_costs
M={'<tool_call>':10,'</tool_call>':11,'<tool_response>':20,'</tool_response>':21}
def event(r=1,c='a',text='seen'):
    return {'round_id':r,'tool_call_id':c,'exact_result':text}
def rnd(r,ids,calls,prompt=None,messages=None,final=False):
    return {'round_id':r,'response_received':True,'tool_calls':[{'id':x} for x in calls],
            'token_accounting':{'completion_token_ids':ids,'prompt_token_ids':prompt or []},
            'actor_visible_messages':messages or [],'finish_reason':'stop' if final else 'tool_calls','content':'answer' if final else ''}
class NativeTests(unittest.TestCase):
    def test_single_and_final(self):
        trace={'rounds':[rnd(1,[2,10,3,11],['a']),rnd(2,[5],[],[20,6,21],[{'role':'tool','tool_call_id':'a','content':'seen'}],True)],'tool_events':[event()]}
        r=stage_costs(trace,M)
        self.assertEqual(r['stages']['R1'],{'generated_tokens':4,'obs_tokens':3})
        self.assertEqual(r['total_generated_tokens'],5)
    def test_parallel_shared_not_duplicated(self):
        trace={'rounds':[rnd(1,[1,1,10,2,11,10,3,11],['a','b'])],'tool_events':[event(),event(c='b')]}
        r=stage_costs(trace,M)
        self.assertEqual(r['shared_tokens'],2)
        self.assertEqual(r['stages']['R1:T1']['generated_tokens'],3)
        self.assertIsNone(r['stages']['R1:T2']['obs_tokens'])
    def test_unfinished_has_cost_not_stage(self):
        r=stage_costs({'rounds':[rnd(1,[1]*10,[])],'tool_events':[]},M)
        self.assertEqual(r['total_generated_tokens'],10);self.assertEqual(r['stages'],{})
    def test_wrong_observation_binding_rejected(self):
        t={'rounds':[rnd(1,[10,3,11],['a']),rnd(2,[2],[],[20,2,21],[{'role':'tool','tool_call_id':'wrong','content':'seen'}])],'tool_events':[event()]}
        with self.assertRaises(ValueError):stage_costs(t,M)
if __name__=='__main__':unittest.main()
