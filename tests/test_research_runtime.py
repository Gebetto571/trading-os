import json, tempfile, unittest
from pathlib import Path
from trading_os_bridge.research_runtime import ResearchRuntimeError, run_offline
class ResearchRuntimeTests(unittest.TestCase):
 def test_offline_output_isolated(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); f=root/'fixture.json'; f.write_text('{"values":[2,3,5]}'); out=root/'results'/'summary.json'
   r=run_offline(f,out); self.assertEqual((r['sum'],r['intent_count'],r['network_access_count']),(10,0,0)); self.assertTrue(out.is_file())
 def test_effect_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); f=root/'fixture.json'; f.write_text('{"values":[]}')
   with self.assertRaises(ResearchRuntimeError): run_offline(f,root/'results'/'x.json','network')
