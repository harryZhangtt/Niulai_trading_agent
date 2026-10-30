import tempfile
import unittest
from pathlib import Path
from niulai_state import init, record_run, get_run, normalize_alerts, decimal_price, validate_config, StateError

class RunRecords(unittest.TestCase):
    def test_scoped_notification_policies_required(self):
        p={'config_revision':3,'alert_authority':'price_alert_studio_D1',
           '_meta':{'user_timezone':'Asia/Shanghai','session_timezone':'America/New_York'},
           'schedules':[{'role':'existing_summary','automation_id':'saved','enabled':True,'runtime_slot_grace_minutes':60}],
           'notifications':{'configuration_managed':True,'transport':'native_scheduled_task_output','policies':{
            'existing_summary':{'enabled':True,'read_only':True,'notify_on_quiet_days':True,'windows':['today','3d','7d','10d']}}}}
        self.assertTrue(validate_config(p)['valid'])
        import copy
        bad=copy.deepcopy(p);bad['notifications']['policies']={}
        with self.assertRaises(StateError):validate_config(bad)
        for key,value in [('read_only',False),('notify_on_quiet_days','yes'),('windows',['all_history'])]:
            bad=copy.deepcopy(p);bad['notifications']['policies']['existing_summary'][key]=value
            with self.assertRaises(StateError):validate_config(bad)
    def test_unsupported_delivery_and_bad_grace_rejected(self):
        p={'config_revision':3,'alert_authority':'price_alert_studio_D1',
           '_meta':{'user_timezone':'Asia/Shanghai','session_timezone':'America/New_York'},'schedules':[],
           'notifications':{'configuration_managed':True,'transport':'unverified_site_sender','policies':{}}}
        with self.assertRaises(StateError):validate_config(p)
        p['notifications']['transport']='native_scheduled_task_output'
        p['schedules']=[{'role':'draft','enabled':False,'runtime_slot_grace_minutes':True}]
        with self.assertRaises(StateError):validate_config(p)
    def test_configuration_guards(self):
        p={'config_revision':1,'alert_authority':'price_alert_studio_D1','_meta':{'user_timezone':'Asia/Shanghai','session_timezone':'America/New_York'},'schedules':[],'draft_alerts':[{'enabled':False}]}
        self.assertTrue(validate_config(p)['valid'])
        for change in [{'config_revision':True},{'alert_authority':'local'},{'draft_alerts':[{'enabled':True}]},{'schedules':[{'role':'daily','enabled':True}]}]:
            with self.assertRaises(StateError):validate_config(dict(p,**change))
    def test_unsupported_restrictions_fail_closed(self):
        p={'id':'ac15eb79-3932-4eca-995f-122a22a8850a','ticker':'SNPS','threshold':'395.85','direction':'below','enabled':True}
        for key,value in [('session','regular_only'),('oneShot',True),('expiresAt','2026-11-01T00:00:00Z'),('currency','CNY')]:
            with self.assertRaises(StateError):normalize_alerts([dict(p,**{key:value})])
    def test_weekly_configuration_guards(self):
        w={'enabled':True,'tail_fraction':'0.20','universe_source':'research_catalog.securities',
           'return_basis':'split_and_distribution_adjusted_close','model_availability_gate':True}
        p={'config_revision':2,'alert_authority':'price_alert_studio_D1',
           '_meta':{'user_timezone':'Asia/Shanghai','session_timezone':'America/New_York'},
           'schedules':[{'role':'weekly_thesis_review','enabled':True,'automation_id':'saved-id'}],
           'research':{'weekly_review':w}}
        self.assertTrue(validate_config(p)['valid'])
        for change in [{'tail_fraction':'NaN'},{'tail_fraction':True},{'tail_fraction':'0.51'},
                       {'universe_source':'all_alerts'},{'return_basis':'raw_close'},{'model_availability_gate':False}]:
            with self.assertRaises(StateError):validate_config({**p,'research':{'weekly_review':{**w,**change}}})
    def test_decimal_equivalent_formatting(self):
        self.assertEqual(decimal_price('395.8500'),'395.85')
        self.assertEqual(decimal_price('1000.00'),'1000')
        self.assertEqual(decimal_price('0.0001000'),'0.0001')
    def test_idempotent_run_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);init(root)
            p={'id':'daily:2026-10-19:r1','kind':'daily_price_watch','status':'completed',
               'started_at':'2026-10-19T19:55:00Z','finished_at':'2026-10-19T19:56:00Z',
               'event_ids':[],'delivery_state':'no_notification_requested'}
            self.assertTrue(record_run(root,p)['recorded'])
            self.assertTrue(record_run(root,p)['idempotent'])
            self.assertEqual(get_run(root,p['id'])['run'],p)
            with self.assertRaises(StateError):record_run(root,{**p,'event_ids':['different']})
    def test_reject_unproven_delivered_status(self):
        with tempfile.TemporaryDirectory() as d:
            init(d)
            with self.assertRaises(StateError):record_run(d,{'id':'x','kind':'watch','status':'delivered','started_at':'x','finished_at':'x'})

if __name__=='__main__':unittest.main()
