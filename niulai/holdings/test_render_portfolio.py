import unittest
import render_portfolio as r

class RenderingTests(unittest.TestCase):
    def fixture(self):
        holdings=[{'symbol':'<script>','name':'A & B','sector':'芯片','subindustry':'存储','marketValue':'100','quantity':'2','marketPrice':'50','averageCost':'40','unrealizedPnl':'20','dailyPnl':None,'weight_pct':100,'daily_leverage':None,'underlying':'<test>','source_refs':['https://example.test/?a="x"']}]
        return {'generated_at':'2026-10-25T17:00:00Z','accounts':[{'label':'账户 1','account_type':'STANDARD','currency':'USD','metrics':{'nav':200,'cash':100,'positions_value':100,'cash_pct':50,'positions_nav_pct':50,'other_net_assets_pct':0,'unrealized_pnl':20,'daily_pnl':None},'holdings':holdings,'top_gainers':holdings,'top_losers':[],'sector_breakdown':[{'name':'芯片','value':100,'pct':100,'unrealized_pnl':20}],'notes':['query time not price time']}]}
    def test_all_rows_render(self):
        d=self.fixture();d['accounts'][0]['holdings']*=45
        h=r.render_full(d);self.assertEqual(h.count('data-symbol='),45)
    def test_escape_input(self):
        h=r.render_full(self.fixture());self.assertIn('&lt;script&gt;',h);self.assertNotIn('<script></b>',h)
    def test_no_external_requests(self):
        h=r.render_full(self.fixture());self.assertNotIn('<script src=',h);self.assertNotIn('<link ',h);self.assertNotIn('fetch(',h)
    def test_unknown_is_not_zero(self):
        self.assertEqual(r.fmt(None),'—');self.assertEqual(r.fmt('0'),'0.00');self.assertEqual(r.mult(None),'—')
    def test_daily_does_not_mislabel_unrealized(self):
        h=r.render_daily(self.fixture());self.assertNotIn('持有期浮盈贡献',h);self.assertNotIn('持有期未实现盈亏',h);self.assertIn('逐证券日盈亏',h);self.assertIn('待补',h)
    def test_paper_excluded_from_daily(self):
        d=self.fixture();d['accounts'].insert(0,{'label':'PAPER SECRET','account_type':'PAPER','holdings':[{'symbol':'TEST'}],'metrics':{}})
        h=r.render_daily(d);self.assertNotIn('PAPER SECRET',h);self.assertIn('账户 1',h)
    def test_negative_cash_no_donut(self):
        h=r.balance_chart({'cash_pct':-10,'positions_nav_pct':110,'other_net_assets_pct':0});self.assertNotIn('<svg',h);self.assertIn('-10.0%',h)
    def test_partial_balance_no_donut(self):
        self.assertNotIn('<svg',r.balance_chart({'cash_pct':50,'positions_nav_pct':50,'other_net_assets_pct':None}))
    def test_date_uses_client_timezone(self):
        self.assertIn('20261026',r.report_names(self.fixture())[0])
    def test_tiny_value_not_zero(self):
        self.assertEqual(r.fmt('0.000001'),'<0.01');self.assertEqual(r.fmt('-0.000001'),'−<0.01'.replace('−','-'))
    def test_zero_and_short_format(self):
        self.assertEqual(r.fmt('-1200.2'),'-1,200.20');self.assertEqual(r.fmt(20,signed=True),'+20.00')
    def test_daily_print_css(self):
        h=r.render_daily(self.fixture());self.assertIn('@page{size:A4 landscape',h);self.assertNotIn('<script>',h)

    def test_counter_zero_does_not_replace_daily_unknown(self):
        d=self.fixture();a=d['accounts'][0]
        a['broker_counters']={'securities_today_pnl':0,'query_at':'2026-10-25T17:42:36Z','status':'source_counter_not_aligned_to_completed_session'}
        a['historical_nav']=[{'date':'2026-10-22','nav':100,'flow_adjusted_nav_change':None}]
        d['latest_completed_session']='2026-10-23'
        h=r.render_daily(d)
        self.assertIn('周日券商 today 计数 0.00',h)
        self.assertIn('不能替代 2026-10-23 盈亏',h)
        self.assertIn('待补',h)
        self.assertNotIn('当日盈利贡献 · 前 5',h)
    def test_history_only_plots_provided_dates(self):
        a={'historical_nav':[{'date':'2026-10-22','nav':127000,'deposit':0,'withdrawal':0,'flow_adjusted_nav_change':-6000}]}
        h=r.history_chart(a)
        self.assertIn('2026-10-22',h);self.assertNotIn('2026-10-23',h)
        self.assertIn('纵轴局部缩放',h)
    def test_classification_asof_not_quote_refresh(self):
        d=self.fixture();d['classification_asof']='2026-10-25'
        h=r.render_full(d)
        self.assertIn('分类最近核验：2026-10-25',h)
        self.assertIn('行情刷新不代表分类与杠杆来源重新核验',h)

    def test_target_session_is_separate_from_query_date(self):
        d=self.fixture();d['latest_completed_session']='2026-10-23'
        h=r.render_daily(d)
        self.assertIn('目标交易日 2026-10-23（盈亏待补齐）',h)
        d['accounts'][0]['metrics']['daily_pnl']=0
        h=r.render_daily(d)
        self.assertIn('目标交易日 2026-10-23',h)
        self.assertIn('（盈亏待补齐）',h)  # An unaligned legacy metric is not enough.


    def test_daily_verified_zero_is_valid(self):
        d=self.fixture();d['latest_completed_session']='2026-10-23'
        d['accounts'][0]['daily_performance']={'session':'2026-10-23','status':'verified','aggregate_pnl':0,'positions':[{'symbol':'<script>','pnl':0}]}
        h=r.render_daily(d);self.assertNotIn('（盈亏待补齐）',h);self.assertIn('1/1',h)
    def test_stale_daily_rejected(self):
        d=self.fixture();d['latest_completed_session']='2026-10-23'
        d['accounts'][0]['daily_performance']={'session':'2026-10-22','status':'verified','aggregate_pnl':999,'positions':[{'symbol':'<script>','pnl':999}]}
        h=r.render_daily(d);self.assertNotIn('+999.00',h);self.assertIn('0/1',h)
    def test_bar_directions_unknown_and_scope(self):
        h=r.signed_bars([{'name':'P','value':100},{'name':'N','value':-100},{'name':'U','value':None}])
        self.assertEqual(h.count('class="pnlrow"'),3);self.assertEqual(h.count('<i style='),2)
        self.assertIn('left:0.0%;width:50.0%;background:#ce435a',h)
        self.assertIn('left:50%;width:50.0%;background:#13826d',h)
    def test_daily_no_lifetime_values(self):
        d=self.fixture();d['accounts'][0]['metrics']['unrealized_pnl']=987654321
        h=r.render_daily(d);self.assertNotIn('987,654,321',h)
    def test_all_daily_rows_render_without_cap(self):
        d=self.fixture();d['accounts'][0]['holdings']=[dict(d['accounts'][0]['holdings'][0],symbol='T'+str(i)) for i in range(45)]
        h=r.render_daily(d);self.assertEqual(h.count('class="pnlrow"'),45);self.assertIn('0/45',h)
    def test_daily_currency_and_paper_isolation(self):
        d=self.fixture();d['latest_completed_session']='2026-10-23'
        a=d['accounts'][0];a['daily_performance']={'session':'2026-10-23','status':'partial','aggregate_pnl':None,'positions':[{'symbol':'<script>','pnl':12}]}
        d['accounts'].append({'account_type':'PAPER','daily_performance':{'session':'2026-10-23','status':'verified','aggregate_pnl':999999}})
        h=r.render_daily(d);self.assertIn('+12.00',h);self.assertNotIn('999,999',h);self.assertIn('（盈亏待补齐）',h)
    def test_same_symbol_contracts_show_canonical_sum_once(self):
        d=self.fixture();a=d['accounts'][0];d['latest_completed_session']='2026-10-23'
        a['holdings']=[{'symbol':'ABC','contractId':'1','sector':'X'}, {'symbol':'ABC','contractId':'2','sector':'X'}, {'symbol':'MISSING','contractId':'3','sector':'Y'}]
        a['daily_performance']={'session':'2026-10-23','status':'partial','aggregate_pnl':None,'positions':[{'symbol':'ABC','sector':'X','pnl':15}]}
        view=r.daily_view(d,a)
        self.assertEqual(view['total'],2);self.assertEqual(view['known'],1)
        self.assertEqual(view['rows'],[{'name':'ABC','sector':'X','value':15,'pnl_pct':None},{'name':'MISSING','sector':'Y','value':None,'pnl_pct':None}])
        self.assertEqual(r.render_daily(d).count('class="pnlrow"'),2)
    def test_duplicate_canonical_rows_are_unknown(self):
        d=self.fixture();d['latest_completed_session']='2026-10-23';a=d['accounts'][0]
        a['daily_performance']={'session':'2026-10-23','status':'partial','positions':[{'symbol':'<script>','pnl':10},{'symbol':'<script>','pnl':20}]}
        v=r.daily_view(d,a);self.assertEqual(v['total'],1);self.assertEqual(v['known'],0)
    def test_scope_requires_explicit_pagination_evidence(self):
        d=self.fixture();a=d['accounts'][0]
        self.assertIn('账户全量/分页完整性未核实',r.render_daily(d))
        self.assertIn('账户全量/分页完整性未核实',r.render_full(d))
        a['quality']={'whole_portfolio_verified':True,'pagination_completeness_verified':True}
        self.assertIn('账户全量/分页完整性已核实',r.scope_note(a))
    def test_explicit_historical_fallback_date_and_basis(self):
        d=self.fixture();a=d['accounts'][0];d['latest_completed_session']='2026-10-23'
        a['daily_performance']={'session':'2026-10-22','selectedPerformanceSession':'2026-10-22','preferred_session':'2026-10-23','status':'partial','aggregate_pnl':-6217.72,'aggregate_basis':'account_history_daily','position_population':'current_snapshot_not_historical_roster','positions':[{'symbol':'<script>','pnl':None}]}
        h=r.render_daily(d);self.assertIn('实际盈亏日期 2026-10-22',h);self.assertIn('优先交易日 2026-10-23 未齐',h);self.assertIn('-6,217.72',h)
        self.assertIn('非逐仓 RTH',h);self.assertIn('不是 2026-10-22 历史持仓名单',h);self.assertIn('0/1',h)
        self.assertIn('日 P&amp;L · 2026-10-22',r.render_full(d))
    def test_fallback_preference_mismatch_cannot_promote_stale_value(self):
        d=self.fixture();a=d['accounts'][0];d['latest_completed_session']='2026-10-23'
        a['daily_performance']={'session':'2026-10-22','selectedPerformanceSession':'2026-10-22','preferred_session':'2026-10-24','status':'partial','aggregate_pnl':-6217.72}
        self.assertIsNone(r.daily_view(d,a)['aggregate'])
    def test_fallback_never_imports_current_positions_as_history(self):
        d=self.fixture();a=d['accounts'][0];d['latest_completed_session']='2026-10-23'
        a['daily_performance']={'session':'2026-10-22','selectedPerformanceSession':'2026-10-22','preferred_session':'2026-10-23','status':'partial','aggregate_pnl':-10,'position_population':'current_snapshot_not_historical_roster','positions':[{'symbol':'<script>','pnl':999}], 'sectors':[{'sector':'X','pnl':999}]}
        v=r.daily_view(d,a);self.assertEqual(v['known'],0);self.assertEqual(v['sectors'],[]);self.assertEqual(v['aggregate'],-10)
    def test_snapshot_hash_order_independent(self):
        self.assertEqual(r.snapshot_hash({'a':1,'b':2}),r.snapshot_hash({'b':2,'a':1}))
        self.assertIn(r.snapshot_hash(self.fixture()),r.render_daily(self.fixture()))

if __name__=='__main__':unittest.main()
