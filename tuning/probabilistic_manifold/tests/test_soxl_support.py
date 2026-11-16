from __future__ import annotations
import copy, datetime as dt, hashlib, inspect, json, math, tempfile, unittest
from pathlib import Path
from unittest import mock
import tuning.probabilistic_manifold.core as core
import tuning.probabilistic_manifold.soxl_cli as soxl_cli
import tuning.probabilistic_manifold.soxl_support as soxl
from tuning.probabilistic_manifold.core import FeaturePanelRow, PriceSeries

HERE=Path(__file__).resolve().parents[1]
WORKSPACE=HERE.parents[1]
CONFIG=HERE/"soxl_config.v1.json"
ARTIFACTS=HERE/"artifacts"/"soxl"

def series(symbol,n=500,start=dt.date(2020,1,1),factor=1.001):
    dates=tuple(start+dt.timedelta(days=i) for i in range(n)); prices=[]; value=100.0
    for i in range(n): value*=factor+0.0002*math.sin(i/9); prices.append(value)
    return PriceSeries(symbol,dates,tuple(prices),f"{symbol}.json",hashlib.sha256(symbol.encode()).hexdigest(),n)

def synthetic_panel(n=500,constant=False,missing_origin=False):
    rows=[]
    for i in range(n):
        f={name:(1.0 if constant else float(i+j*i*i/100000)) for j,name in enumerate(soxl.DISTANCE_FEATURES,1)}
        for name in soxl.DIAGNOSTICS: f[name]=None
        if missing_origin and i==n-1: f[soxl.DISTANCE_FEATURES[0]]=None
        rows.append(FeaturePanelRow(dt.date(2025,1,1)+dt.timedelta(days=i),100.0,"era",f))
    rows[-1]=FeaturePanelRow(dt.date(2026,11,5),100.0,"era",rows[-1].features)
    return rows

class ConfigAndFeatureTests(unittest.TestCase):
    def test_checked_in_closed_config(self):
        c=soxl.load_soxl_config(CONFIG)
        self.assertEqual(tuple(c["distance_features"]),soxl.DISTANCE_FEATURES)
        self.assertEqual(tuple(c["informational_diagnostics"]),soxl.DIAGNOSTICS)
    def test_design_parameter_provenance_is_closed_and_disclaims_soxl_validation(self):
        c=soxl.load_soxl_config(CONFIG); provenance=c["design_parameter_provenance"]
        self.assertEqual(provenance,soxl.DESIGN_PARAMETER_PROVENANCE)
        self.assertEqual(provenance["reuse_status"],"shared_method_design_constants_not_independently_validated_for_soxl")
        self.assertIn("not transported from TQQQ",provenance["transport_rule"])
        method=c["method_contract"]; self.assertEqual(method["contract_id"],"leveraged-price-path-support-v1")
        self.assertEqual(method["formula_constants"],soxl.METHOD_CONTRACT_SPEC["formula_constants"])
        self.assertIn("not evidence of SOXL/TQQQ predictive parity",method["claim_limit"])
        bad_hash=json.loads(CONFIG.read_text()); bad_hash["method_contract"]["code_sha256"]["core.py"]="0"*64
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bad-hash.json"; path.write_text(json.dumps(bad_hash))
            with self.assertRaisesRegex(core.DataContractError,"code hash mismatch"): soxl.load_soxl_config(path)
        bad=json.loads(CONFIG.read_text()); bad["design_parameter_provenance"]["reuse_status"]="validated_for_soxl"
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bad.json"; path.write_text(json.dumps(bad))
            with self.assertRaises(core.DataContractError): soxl.load_soxl_config(path)
    def test_unknown_missing_and_source_path_attacks_fail(self):
        base=json.loads(CONFIG.read_text())
        mutations=[]
        x=copy.deepcopy(base); x["extra"]=1; mutations.append(x)
        x=copy.deepcopy(base); del x["origin_date"]; mutations.append(x)
        for attack in ("/etc/passwd","../escape.json","a/../b.json","C:\\escape.json"):
            x=copy.deepcopy(base); x["sources"]["SOXL"]["path"]=attack; mutations.append(x)
        for x in mutations:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/"c.json"; p.write_text(json.dumps(x))
                with self.assertRaises(core.DataContractError): soxl.load_soxl_config(p)
    def test_feature_numerics_and_optional_exact_join(self):
        p=series("SOXL",200); q=series("SOXX",200,factor=1.0005); smh=series("SMH",200,factor=1.0002)
        rows=soxl.build_soxl_feature_panel({"SOXL":p,"SOXX":q,"SMH":smh},p.dates[-1]); r=rows[-1]
        for window in (21,63,126):
            self.assertAlmostEqual(r.features[f"soxl_return_{window}"],p.adjusted_market_prices[-1]/p.adjusted_market_prices[-1-window]-1)
            self.assertAlmostEqual(r.features[f"soxx_return_{window}"],q.adjusted_market_prices[-1]/q.adjusted_market_prices[-1-window]-1)
        logs=[math.log(p.adjusted_market_prices[j]/p.adjusted_market_prices[j-1]) for j in range(len(p.adjusted_market_prices)-21,len(p.adjusted_market_prices))]
        center=sum(logs)/21
        self.assertAlmostEqual(r.features["soxl_realized_vol_21"],math.sqrt(252*sum((x-center)**2 for x in logs)/21))
        downside=[math.log(p.adjusted_market_prices[j]/p.adjusted_market_prices[j-1]) for j in range(len(p.adjusted_market_prices)-63,len(p.adjusted_market_prices))]
        self.assertAlmostEqual(r.features["soxl_downside_semivariance_63"],252*sum(min(x,0)**2 for x in downside)/63)
        self.assertAlmostEqual(r.features["soxl_distance_from_126_high"],p.adjusted_market_prices[-1]/max(p.adjusted_market_prices[-126:])-1)
        expected=r.features["soxl_return_21"]-((1+r.features["soxx_return_21"])**3-1)
        self.assertAlmostEqual(r.features["soxl_vs_3x_soxx_gap_21"],expected)
        self.assertIsNotNone(r.features["smh_return_21"]); self.assertIsNone(r.features["spy_return_21"])
    def test_future_mutation_does_not_change_origin_features(self):
        p=series("SOXL",300); q=series("SOXX",300); origin=p.dates[200]
        before=soxl.build_soxl_feature_panel({"SOXL":p,"SOXX":q},origin)[-1].features
        prices=list(p.adjusted_market_prices); prices[201:]=[x*10 for x in prices[201:]]
        changed=PriceSeries("SOXL",p.dates,tuple(prices),p.path,p.sha256,p.byte_count)
        after=soxl.build_soxl_feature_panel({"SOXL":changed,"SOXX":q},origin)[-1].features
        self.assertEqual(before,after)
    def test_required_exact_join_has_no_forward_fill(self):
        p=series("SOXL",200); q=series("SOXX",200)
        q=PriceSeries(q.symbol,q.dates[:150]+q.dates[151:],q.adjusted_market_prices[:150]+q.adjusted_market_prices[151:],q.path,q.sha256,q.byte_count)
        with self.assertRaisesRegex(core.DataContractError,"no forward fill"): soxl.build_soxl_feature_panel({"SOXL":p,"SOXX":q},p.dates[-1])

class GeometryAndStatusTests(unittest.TestCase):
    def test_purge_126_and_training_only_scaling_calibration(self):
        rows=synthetic_panel(500); training=core.select_support_training_rows(rows,499,soxl.DISTANCE_FEATURES,126)
        self.assertEqual(len(training),374); self.assertEqual(training[-1],rows[373])
        scaler=core.fit_robust_scaler(training,soxl.DISTANCE_FEATURES)
        self.assertNotIn(rows[-1].features[soxl.DISTANCE_FEATURES[0]],scaler.medians.values())
        self.assertGreater(len(core.calibration_k_distances(training,scaler,soxl.DISTANCE_FEATURES,12,21)),0)
    def run_mock_panel(self,panel,**patches):
        active=[mock.patch.object(soxl,"build_soxl_feature_panel",return_value=panel)]
        active += [mock.patch.object(soxl,name,value) for name,value in patches.items()]
        with active[0]:
            with active[1] if len(active)>1 else mock.patch.object(soxl,"ALLOWED_STATUS",soxl.ALLOWED_STATUS):
                return soxl.run_soxl_support(CONFIG,WORKSPACE)[0]
    def test_insufficient_support_is_inconclusive(self):
        p=self.run_mock_panel(synthetic_panel(200)); self.assertIn("insufficient_training_support",p["support_geometry"]["status_reasons"])
    def test_missing_feature_is_inconclusive(self):
        p=self.run_mock_panel(synthetic_panel(500,missing_origin=True)); self.assertIn("origin_missing_required_feature",p["support_geometry"]["status_reasons"])
    def test_zero_mad_is_inconclusive(self):
        p=self.run_mock_panel(synthetic_panel(500,constant=True)); self.assertIn("zero_mad_or_calibration_support_failure",p["support_geometry"]["status_reasons"])
    def test_stale_is_inconclusive(self):
        with mock.patch.object(soxl,"build_soxl_feature_panel",return_value=synthetic_panel(500)), mock.patch.object(soxl,"is_stale",return_value=True):
            p=soxl.run_soxl_support(CONFIG,WORKSPACE)[0]
        self.assertIn("origin_is_stale",p["support_geometry"]["status_reasons"])
    def test_low_ess_is_inconclusive(self):
        with mock.patch.object(soxl,"build_soxl_feature_panel",return_value=synthetic_panel(500)), mock.patch.object(soxl,"dependence_adjusted_ess",return_value=1.0):
            p=soxl.run_soxl_support(CONFIG,WORKSPACE)[0]
        self.assertIn("insufficient_dependence_adjusted_ess",p["support_geometry"]["status_reasons"])
    def test_low_episode_count_is_inconclusive(self):
        with mock.patch.object(soxl,"build_soxl_feature_panel",return_value=synthetic_panel(500)), mock.patch.object(soxl,"nonoverlap_episode_count",return_value=2):
            p=soxl.run_soxl_support(CONFIG,WORKSPACE)[0]
        self.assertIn("insufficient_nonoverlap_episodes",p["support_geometry"]["status_reasons"])
    def test_identity_failure_is_inconclusive(self):
        c=json.loads(CONFIG.read_text()); c["sources"]["SOXL"]["sha256"]="0"*64
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"c.json"; p.write_text(json.dumps(c)); packet,_,_=soxl.run_soxl_support(p,WORKSPACE)
        self.assertEqual(packet["support_geometry"]["status_reasons"],["required_source_identity_failed"])
    def test_status_vocabulary(self):
        self.assertEqual(core.classify_geometry(1,2,3),"inside"); self.assertEqual(core.classify_geometry(2.5,2,3),"edge"); self.assertEqual(core.classify_geometry(4,2,3),"outside")

class ArtifactAndBoundaryTests(unittest.TestCase):
    def test_real_input_bindings_counts_and_smoke(self):
        packet,manifest,prereg=soxl.run_soxl_support(CONFIG,WORKSPACE)
        self.assertEqual(packet["origin_id"],"origin_2026-11-05"); self.assertEqual(packet["panel"]["rows"],4191)
        self.assertEqual(packet["support_geometry"]["training"]["rows"],3939)
        self.assertEqual(len(packet["support_geometry"]["knn"]["neighbors"]),12)
        self.assertFalse(packet["outcomes_accessed"]); self.assertFalse(packet["protected_outcomes_accessed"])
        self.assertFalse(packet["probability_feature_compatible"]); self.assertNotIn("cohort",packet)
        self.assertEqual([x["identity_status"] for x in manifest["sources"]],["passed"]*6)
        self.assertEqual(prereg["packet_cardinality"],"one_origin_only_no_cohort")
    def test_artifact_hash_links_and_canonical_bytes(self):
        pre=(ARTIFACTS/"preregistration.v1.json").read_bytes(); man=(ARTIFACTS/"source-manifest.v1.json").read_bytes(); packet=json.loads((ARTIFACTS/"support-packet.v1.json").read_text())
        self.assertEqual(packet["preregistration_sha256"],hashlib.sha256(pre).hexdigest())
        self.assertEqual(packet["source_manifest_sha256"],hashlib.sha256(man).hexdigest())
        self.assertEqual(pre,core.canonical_json_bytes(json.loads(pre))); self.assertEqual(man,core.canonical_json_bytes(json.loads(man)))
    def test_preregistration_and_packet_publish_identical_no_validation_provenance(self):
        prereg=json.loads((ARTIFACTS/"preregistration.v1.json").read_text()); packet=json.loads((ARTIFACTS/"support-packet.v1.json").read_text())
        self.assertEqual(prereg["design_parameter_provenance"],soxl.DESIGN_PARAMETER_PROVENANCE)
        self.assertEqual(packet["design_parameter_provenance"],soxl.DESIGN_PARAMETER_PROVENANCE)
        manifest=json.loads((ARTIFACTS/"source-manifest.v1.json").read_text())
        self.assertEqual(prereg["method_contract"],packet["method_contract"]); self.assertEqual(packet["method_contract"],manifest["method_contract"])
        self.assertIn("not evidence of SOXL/TQQQ predictive parity",packet["method_contract"]["claim_limit"])
        self.assertIn("not independent SOXL validation",packet["design_parameter_provenance"]["claim_limit"])
        self.assertIn("target-derived",packet["design_parameter_provenance"]["transport_rule"])
    def test_atomic_writer_and_deterministic_canonical_hash(self):
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            root=Path(d); value={"b":2,"a":1}
            first=core.write_canonical_json(root,"one.json",value)
            second=core.write_canonical_json(root,"two.json",{"a":1,"b":2})
            self.assertEqual(first,second); self.assertEqual((root/"one.json").read_bytes(),(root/"two.json").read_bytes())
            self.assertFalse(list(root.glob(".*.tmp.*")))
    def test_no_forbidden_imports_or_support_writer(self):
        support=inspect.getsource(soxl); cli=inspect.getsource(soxl_cli)
        for token in (".outcomes","rolling_outcomes","development_inputs","provider","scheduler","report"):
            self.assertNotIn(f"import {token}",support); self.assertNotIn(f"from {token}",support)
        self.assertNotIn("write_canonical_json",support); self.assertNotIn("open(",support)
        self.assertIn("write_canonical_json",cli)
    def test_no_forbidden_runtime_fields_except_frozen_flags(self):
        packet=json.loads((ARTIFACTS/"support-packet.v1.json").read_text())
        allowed={"outcomes_accessed","protected_outcomes_accessed","probability_feature_compatible"}
        def walk(x):
            if isinstance(x,dict):
                for k,v in x.items():
                    self.assertFalse(k in soxl.FORBIDDEN_OUTPUTS and k not in allowed,k); walk(v)
            elif isinstance(x,list):
                for v in x: walk(v)
        walk(packet)
    def test_generic_loader_preserves_tqqq_wrapper_behavior(self):
        cfg=core.load_config(HERE/"config.v1.json"); spec=cfg["sources"]["TQQQ"]
        self.assertEqual(core.load_bound_price_series(WORKSPACE,"TQQQ",spec),core.load_price_series(WORKSPACE,"TQQQ",spec))

if __name__=="__main__": unittest.main()
