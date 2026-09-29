import os,uuid
import importlib.util,json,unittest
from pathlib import Path
ROOT=Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd()/'work/handoff-tests')))/uuid.uuid4().hex
ROOT.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('context_check',str(Path(__file__).resolve().parents[1]/'scripts/context_check.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def compact(n):return {'type':'compacted','payload':{'window_id':'window-'+str(n),'message':'not retained'}}

class ContextTests(unittest.TestCase):
 def write(self,name,rows,tail=b''):
  p=ROOT/(name+'.jsonl');p.write_bytes(b''.join((json.dumps(x)+'\n').encode() for x in rows)+tail);return p
 def test_no_early_notice(self):
  for n in [0,1]:
   p=self.write('early'+str(n),[compact(i) for i in range(n)])
   self.assertFalse(m.advisory(p,'early'+str(n))['remind'])
 def test_dedupe_and_later_reminder(self):
  state=ROOT/'state';tid='dedupe-20260912-v1'
  # Isolated state path kept for evidence; repeated test runs use a fresh directory.
  import uuid
  state=state/str(uuid.uuid4())
  p=self.write('two',[compact(1),compact(2)])
  self.assertTrue(m.advisory(p,tid,state_dir=state,claim=True)['remind'])
  self.assertFalse(m.advisory(p,tid,state_dir=state,claim=True)['remind'])
  p=self.write('three',[compact(i) for i in range(1,4)])
  self.assertFalse(m.advisory(p,tid,state_dir=state,claim=True)['remind'])
  p=self.write('four',[compact(i) for i in range(1,5)])
  self.assertTrue(m.advisory(p,tid,state_dir=state,claim=True)['remind'])
  p=self.write('other-thread',[compact(1),compact(2)])
  self.assertTrue(m.advisory(p,'other-thread',state_dir=state,claim=True)['remind'])
  receipts=list(state.glob('*.json'));self.assertEqual(len(receipts),2)
  self.assertNotIn('not retained',''.join(p.read_text() for p in receipts))
 def test_ui_events_and_duplicates_are_not_counted(self):
  rows=[compact(1),compact(1),{'type':'event_msg','payload':{'type':'item_completed','item':{'type':'ContextCompaction'}}}, {'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'compacted'}]}}]
  p=self.write('duplicates',rows)
  self.assertEqual(m.count_compactions(p)[0],1)
 def test_partial_tail(self):
  p=self.write('partial',[compact(1)],b'{"type":"compacted"')
  r=m.advisory(p,'partial');self.assertEqual(r['observed_compactions'],1);self.assertTrue(r['partial_tail']);self.assertFalse(r['remind'])
 def test_malformed_retains_verified_lower_bound(self):
  p=self.write('malformed',[compact(1),compact(2)],b'not json\n')
  r=m.advisory(p,'bad');self.assertEqual(r['status'],'partial');self.assertTrue(r['remind']);self.assertIn('至少',r['message'])
 def test_no_id_duplicate_record(self):
  record={'type':'compacted','timestamp':'2026-09-12T00:00:00Z','payload':{'message':'same'}}
  p=self.write('no-id',[record,record])
  self.assertEqual(m.count_compactions(p)[0],1)
 def test_exact_thread_lookup(self):
  home=ROOT/'home';folder=home/'sessions/2026/09/12';folder.mkdir(parents=True,exist_ok=True)
  (folder/'rollout-date-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl').write_text('')
  self.assertIsNotNone(m.find_transcript(home,'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'))
  self.assertIsNone(m.find_transcript(home,'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'))
  self.assertIsNone(m.find_transcript(home,'../../other'))

if __name__=='__main__':unittest.main(verbosity=2)
