"""Synthetic actionable-gate tests; no actual price/dividend source certified."""
import copy,hashlib,json,tempfile,unittest,base64,io
from pathlib import Path
from unittest.mock import patch
import options_evidence as g
import options_path_checks as paths
from test_options_payoff_checks import example_packet
from test_options_evidence import Fixture
import test_options_model_selection as selection_fixture

class PathEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();packet=example_packet();packet['as_of']='2026-10-23T20:01:00Z'
  packet['strategy']['long_leg'].update(expiry='2027-06-17',contract_id='SYNTH270617C00100000')
  for quote in [packet['underlying_quote']['quote'],packet['strategy']['long_leg']['quote']]:quote['timestamp']='2026-10-23T20:00:30Z'
  with patch('test_options_evidence.example_packet',return_value=packet):self.f=Fixture(self.t.name)
  self.b=self.f.record['options_evidence'];self.h=selection_fixture.Tests();self.h.f=self.f;self.h.b=self.b;self.h.prepare()
  self.packet={'version':1,'payoff_packet':self.f.packet,'start_session':'2026-10-23','spot':100,'clock':'XNYS_close_to_close_252','position_mode':'one_contract',
    'simulation':{'method':'gbm','paths':1000,'seed':7,'annual_trading_days':252,'annual_arithmetic_drift':.15,'sigma':.5,'drift_treatment':'explicit_gbm_arithmetic','assumption_source_ref':'synthetic assumed stress, not calibrated','block_size':None},'history':None}
  refs=self.f.pair('paths',self.packet,paths)
  self.path={'route':'simulated_paths','probability_basis':'conditional_assumption_not_calibrated','method_sha256':hashlib.sha256(Path(paths.__file__).read_bytes()).hexdigest(),**refs,
     'origin_artifact_id':'origin','assumptions_artifact_id':'assumptions','replay_manifest_artifact_id':'replay'}
  self.b['model_selection']['path_review']=self.path
  self.f.put('origin-source',{'synthetic_regular_close':100,'session':'2026-10-23'})
  self.f.put('origin',{'subject':'SYNTH','session':'2026-10-23','price_basis':'regular_session_close','observed_at':'2026-10-23T20:00:00Z','available_at':'2026-10-23T20:00:30Z','price':100,'source_ref':'synthetic regular close','source_artifact_id':'origin-source'})
  self.f.put('assumption-source',{'synthetic_assumed_mu':.15,'sigma':.5,'not_calibrated':True})
  self.f.put('assumptions',{'simulation':self.packet['simulation'],'history':None,'available_at':packet['as_of'],'probability_basis':self.path['probability_basis'],'finding':'Explicit synthetic GBM parameters, no actual estimated distribution.','source_artifact_ids':['assumption-source']})
  self.replay()
  document=Path(self.f.arts['report']['path']).read_text().replace('Probability basis: conditional_scenarios_not_calibrated','Probability basis: conditional_assumption_not_calibrated').replace('</body>','<p>Replay: sampled stock paths, not interim option profits; sampling intervals exclude model uncertainty</p></body>')
  document=document.replace('</body>',Path(self.f.arts['replay-plot']['path']).read_text()+'</body>')
  self.f.put('report',document);self.pin()
 def tearDown(self):self.t.cleanup()
 def pin(self):
  self.h.pin();self.f.review['path_probability_finding']='Recomputed conditional paths, not calibrated real-world probabilities.'
  self.f.review['path_review_artifact_ids']=['paths-in','paths-out','origin','origin-source','assumptions','assumption-source','replay','replay-plot']
  self.f.review['path_replay_visual_finding']='Synthetic first seeded path plot inspected, not selected as representative.'
  self.f.review['path_replay_inspection_method']='image_inspection';self.f.refresh()
 def replay(self):
  out=self.f.get('paths-out');v=out['illustrative_paths']['stock_prices'][0];lo=min(v);hi=max(v);points=' '.join(f'{i*500/(len(v)-1):.3f},{200-(x-lo)*180/(hi-lo):.3f}' for i,x in enumerate(v))
  self.f.put('replay-plot','<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 220"><polyline fill="none" stroke="blue" points="'+points+'"/></svg>')
  self.f.put('replay',{'version':1,'input_sha256':out['input_sha256'],'output_sha256':self.f.arts['paths-out']['sha256'],
    'replay_data':{'start_session':out['start_session'],'future_sessions':out['calendar']['future_sessions'],'illustrative_paths':out['illustrative_paths'],'daily_stock_fan':out['daily_stock_fan']},
    'visual_artifact_ids':['replay-plot'],'claim_scope':'sampled_stock_paths_not_interim_option_pnl'})
 def reject(self,pattern):
  with self.assertRaisesRegex(ValueError,pattern):g.validate(self.f.record)
 def test_valid_simulated_binding(self):self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_false_probability_calibration(self):self.path['probability_basis']='calibrated';self.pin();self.reject('conditional assumptions')
 def test_changed_budget(self):
  self.packet['payoff_packet']=copy.deepcopy(self.packet['payoff_packet']);self.packet['payoff_packet']['budget']['amount']='1100';self.f.pair('paths',self.packet,paths);self.replay();self.pin();self.reject('exact payoff')
 def test_wrong_origin_price(self):
  p=self.f.get('origin');p['price']=99;self.f.put('origin',p);self.pin();self.reject('regular-session close')
 def test_wrong_origin_clock(self):
  p=self.f.get('origin');p['observed_at']='2026-10-23T19:00:00Z';self.f.put('origin',p);self.pin();self.reject('regular-session close')
 def test_origin_not_close(self):
  p=self.f.get('origin');p['price_basis']='after_hours';self.f.put('origin',p);self.pin();self.reject('regular-session close')
 def test_future_origin_source(self):
  p=self.f.get('origin');p['available_at']='2026-10-24T00:00:00Z';self.f.put('origin',p);self.pin();self.reject('regular-session close')
 def test_unbound_assumptions(self):
  p=self.f.get('assumptions');p['simulation']['sigma']=.8;self.f.put('assumptions',p);self.pin();self.reject('assumptions/history')
 def test_missing_source(self):
  p=self.f.get('assumptions');p['source_artifact_ids']=[];self.f.put('assumptions',p);self.pin();self.reject('source artifacts')
 def test_replay_wrong_curve(self):
  p=self.f.get('replay');p['replay_data']['illustrative_paths']['stock_prices'][0][0]=200;self.f.put('replay',p);self.pin();self.reject('replay manifest')
 def test_replay_wrong_output_hash(self):
  p=self.f.get('replay');p['output_sha256']='x';self.f.put('replay',p);self.pin();self.reject('replay manifest')
 def test_replay_noplot(self):
  p=self.f.get('replay');p['visual_artifact_ids']=[];self.f.put('replay',p);self.pin();self.reject('visualization artifacts')
 def test_replay_fakeplot(self):
  self.f.put('replay-plot','not a plot');self.pin();self.reject('valid saved PNG or nonempty SVG')
 def test_replay_interim_option_claim(self):
  p=self.f.get('replay');p['claim_scope']='actual option profits';self.f.put('replay',p);self.pin();self.reject('replay manifest')
 def test_reviewer_missing_path_refs(self):
  self.f.review['path_review_artifact_ids']=[];self.f.refresh();self.reject('all path/source/replay')
 def test_reviewer_no_rendered_inspection(self):
  self.f.review['path_replay_inspection_method']='self_asserted';self.f.refresh();self.reject('rendered replay')
 def test_no_visible_replay_scope(self):
  d=Path(self.f.arts['report']['path']).read_text().replace('Replay: sampled stock paths, not interim option profits; sampling intervals exclude model uncertainty','');self.f.put('report',d);self.pin();self.reject('visible report lacks')
 def test_replay_not_embedded(self):
  plot=Path(self.f.arts['replay-plot']['path']).read_text();report=Path(self.f.arts['report']['path']).read_text().replace(plot,'');self.f.put('report',report);self.pin();self.reject('presentation is hidden')
 def test_replay_hidden_embedding(self):
  plot=Path(self.f.arts['replay-plot']['path']).read_text();report=Path(self.f.arts['report']['path']).read_text().replace(plot,'<div hidden>'+plot+'</div>');self.f.put('report',report);self.pin();self.reject('presentation is hidden')
 def test_replay_empty_svg(self):
  self.f.put('replay-plot','<svg></svg>');self.pin();self.reject('nonempty SVG')
 def png(self,hidden=False):
  from PIL import Image,ImageDraw
  old=Path(self.f.arts['replay-plot']['path']).read_text();im=Image.new('RGB',(200,100),'white');draw=ImageDraw.Draw(im)
  values=self.f.get('paths-out')['illustrative_paths']['stock_prices'][0];lo=min(values);hi=max(values)
  draw.line([(i*199/(len(values)-1),99-(v-lo)*98/(hi-lo)) for i,v in enumerate(values)],fill='blue')
  buffer=io.BytesIO();im.save(buffer,format='PNG');data=buffer.getvalue();path=Path(self.f.arts['replay-plot']['path']);path.write_bytes(data);self.f.arts['replay-plot']['sha256']=hashlib.sha256(data).hexdigest()
  image='<img src="data:image/png;base64,'+base64.b64encode(data).decode()+'"'+(' hidden' if hidden else '')+'>'
  report=Path(self.f.arts['report']['path']).read_text().replace(old,image);self.f.put('report',report);self.pin()
 def test_png_visible(self):self.png();self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_png_hidden(self):self.png(True);self.reject('presentation is hidden')
 def test_png_truncated(self):
  path=Path(self.f.arts['replay-plot']['path']);path.write_bytes(b'\x89PNG\r\n\x1a\n');self.f.arts['replay-plot']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();self.pin();self.reject('PNG replay decoder')
 def test_stale_method(self):self.path['method_sha256']='x';self.pin();self.reject('path method')
 def test_changed_computed_output(self):
  p=self.f.get('paths-out');p['status']='calibrated';self.f.put('paths-out',p);self.replay();self.pin();self.reject('recomputation')

if __name__=='__main__':unittest.main()
