import os,uuid
import concurrent.futures,importlib.util,json,subprocess,sys,unittest,uuid
from pathlib import Path
S=Path(__file__).resolve().parents[1]/'scripts/history.py'
spec=importlib.util.spec_from_file_location('history',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ROOT=Path(os.environ.get('HANDOFF_TEST_ROOT', str(Path.cwd()/'work/history-tests')))/uuid.uuid4().hex[:10];ROOT.mkdir(parents=True)
class HistoryTests(unittest.TestCase):
 def setup_paths(self,name):
  root=ROOT/name;root.mkdir();p=root/'packet.md';p.write_text('# Goal\nDecision with reason and evidence.\n');return root/'archive',p
 def test_retry_is_idempotent_and_source_retained(self):
  a,p=self.setup_paths('retry');x=m.publish(a,p,'one','title','source');y=m.publish(a,p,'one','title','source')
  self.assertEqual(y['total_entries'],1);self.assertTrue(y['already_registered']);self.assertTrue(p.exists());self.assertEqual(Path(x['snapshot']).read_bytes(),p.read_bytes())
 def test_changed_packet_cannot_overwrite_history(self):
  a,p=self.setup_paths('changed');x=m.publish(a,p,'one','title','source');old=Path(x['snapshot']).read_bytes();p.write_text('different')
  with self.assertRaises(ValueError):m.publish(a,p,'one','title','source')
  self.assertEqual(Path(x['snapshot']).read_bytes(),old)
 def test_small_index_retains_all_history(self):
  a,p=self.setup_paths('many')
  for i in range(12):m.publish(a,p,'packet-'+str(i),'title-'+str(i),'source')
  self.assertEqual(len(list((a/'snapshots').glob('*.md'))),12)
  self.assertEqual(len(json.loads((a/'catalog.json').read_text())['entries']),12)
  self.assertEqual((a/'INDEX.md').read_text().count('\n- ['),8)
 def test_manual_index_is_not_overwritten(self):
  a,p=self.setup_paths('manual');a.mkdir();(a/'INDEX.md').write_text('User document')
  with self.assertRaises(ValueError):m.publish(a,p,'one','title','source')
  self.assertEqual((a/'INDEX.md').read_text(),'User document');self.assertFalse((a/'catalog.json').exists())
 def test_concurrent_publication_keeps_all_entries(self):
  a,p=self.setup_paths('parallel')
  def invoke(i):return subprocess.run([sys.executable,str(S),'--archive',str(a),'--packet',str(p),'--packet-id','p'+str(i),'--title','t'+str(i),'--source-thread','source'],capture_output=True,text=True)
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(invoke,range(4)))
  self.assertTrue(all(r.returncode==0 for r in results),str(results));self.assertEqual(len(json.loads((a/'catalog.json').read_text())['entries']),4)
 def test_unknown_catalog_preserved(self):
  a,p=self.setup_paths('unknown');a.mkdir();(a/'catalog.json').write_text('{"personal":"original"}')
  with self.assertRaises(ValueError):m.publish(a,p,'one','title','source')
  self.assertEqual(json.loads((a/'catalog.json').read_text()),{'personal':'original'})
if __name__=='__main__':unittest.main(verbosity=2)
