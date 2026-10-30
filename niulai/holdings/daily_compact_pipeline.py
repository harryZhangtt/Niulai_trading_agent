"""One bounded read-only daily command; existing scheduler and Gmail own delivery."""
import argparse,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).parent

def existing_profile(explicit=None):
    candidate=explicit or os.environ.get('NIULAI_PROFILE_DIR')
    path=Path(candidate) if candidate else Path('/root/.config/niulai-tiger-standalone')
    if path.is_symlink():raise ValueError('profile_symlink_rejected')
    if not path.is_dir():raise ValueError('profile_missing')
    return path.resolve()

def preflight(profile):
    import niulai_tiger as n
    with n.profile_lock(profile):
        Session,_=n.sdk_classes(include_quotes=True)
        session=Session(issuer=n.ISSUER,home=str(profile),surface=n.SURFACE,client_name=n.CLIENT_NAME)
        token=session.status();n.validate_token(token)
        if token.remaining_millis()<=30000 and not token.has_refresh_token():raise n.ReadOnlyError('REAUTHORIZATION_REQUIRED')
        return {'ok':True,'authorization_present':True,'quote_consent':set(token.scope.split())==n.QUOTE_SCOPES,
                'cross_run_persistence_verified':False,'network_calls':0}

def last_result(output):
    for line in output.splitlines()[::-1]:
        try:
            value=json.loads(line)
            if isinstance(value,dict):return value
        except ValueError:pass
    return {}

def build_report(out):
    import analytics,build_five_day
    from position_totals import attach_totals
    from render_portfolio import render_daily
    from render_daily_pdf import make
    s=json.loads((out/'sources.json').read_text())
    h=s['evidence']['holdings']['result']
    base=analytics.build({'accountResults':[h]},{'accountResults':[]},json.loads((ROOT/'taxonomy.json').read_text()))
    (out/'metadata.json').write_text(json.dumps(base,default=analytics.serial))
    try:build_five_day.main(out,out/'metadata.json')
    except (AssertionError,KeyError,ValueError,TypeError):
        # Preserve verified holdings/assets even if historical P&L inputs fail.
        from niulai_tiger import require
        require(h.get('ok') and h.get('sourceReadStatus')=='complete','HOLDINGS_INCOMPLETE')
        require(len(base['accounts'])==1,'REPORT_CURRENCY_SCOPE_AMBIGUOUS')
        view=base;day=s['sessions'][-1]['date'];view['latest_completed_session']=day;a=view['accounts'][0]
        a['daily_performance']={'session':day,'status':'unavailable','aggregate_pnl':None,'capital_return_pct':None,
          'positions':[{'symbol':r['symbol'],'pnl':None,'pnl_pct':None} for r in sorted(a['holdings'],key=lambda r:r['symbol'])],
          'note':'当前持仓及资产独立保留；历史成交、公司行动、转仓或行情未通过完整校验，逐股日盈亏未知，未以累计盈亏替代。'}
        attach_totals(view,s,[])
        view=json.loads(json.dumps(view,default=analytics.serial))
        (out/'daily.json').write_text(json.dumps(view,ensure_ascii=False,indent=2,default=analytics.serial))
        (out/'daily.html').write_text(render_daily(view));make(view,out/'daily.pdf')
        return {'status':'rendered_partial','session':day,'coverage':{'holdings':len(a['holdings']),'pnl_verified':0},
          'position_totals':a['position_totals'],'not_broker_net_pnl':True,'email_status':'not_sent','device_delivery':'unconfirmed'}
    summary=json.loads((out/'summary.json').read_text());day=summary['sessions'][-1]['session']
    view=json.loads((out/day/'viewport.json').read_text());rows=json.loads((out/day/'result.json').read_text())['rows']
    attach_totals(view,s,rows)
    (out/'daily.json').write_text(json.dumps(view,ensure_ascii=False,indent=2))
    (out/'daily.html').write_text(render_daily(view).replace('完整持仓与风险总览 ↗','').replace('href="Tiger_Portfolio_Overview_20261026.html"','href="#"'))
    make(view,out/'daily.pdf')
    return {'status':'rendered_partial' if summary['sessions'][-1]['missing'] else 'rendered',
      'session':day,'coverage':summary['sessions'][-1],
      'position_totals':view['accounts'][0]['position_totals'],
      'not_broker_net_pnl':True,'email_status':'not_sent','device_delivery':'unconfirmed'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path)
    p.add_argument('--profile',default=os.environ.get('NIULAI_PROFILE_DIR'))
    p.add_argument('--local-bootstrap',action='store_true',help='explicit manual connection/test only; production restores private store first')
    mode=p.add_mutually_exclusive_group();mode.add_argument('--offline',action='store_true');mode.add_argument('--preflight',action='store_true');p.add_argument('--worker',choices=['check','fetch','build'])
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if a.worker in ('check','fetch'):
        try:
            profile=existing_profile(a.profile)
            if a.worker=='check':print(json.dumps(preflight(profile)));return 0
            import fetch_five_day;fetch_five_day.main(out,1,str(profile));return 0
        except Exception as error:
            import niulai_tiger as n
            code=str(error) if isinstance(error,ValueError) and str(error) in ('profile_missing','profile_symlink_rejected') else n.safe_error(error)
            print(json.dumps({'ok':False,'error':code,'diagnostic':n.safe_diagnostic(error)}));return 2
    if a.worker=='build':
        (out/'result.json').write_text(json.dumps(build_report(out),ensure_ascii=False,indent=2));return 0
    status={'started_at':datetime.now(timezone.utc).isoformat(),'mode':'offline_frozen' if a.offline else 'live_read','steps':[]}
    try:
        if not a.offline and not a.local_bootstrap and not os.environ.get('NIULAI_PROFILE_SESSION_JSON'):raise ValueError('PRIVATE_STORE_REQUIRED')
        if not a.offline:a.profile=str(existing_profile(a.profile))
        if not a.offline and not a.local_bootstrap:
            from private_profile import verify_remote_context
            status['credential_source']=verify_remote_context(Path(a.profile))
        for step in (['build'] if a.offline else ['check'] if a.preflight else ['check','fetch','build']):
            args=[sys.executable,__file__,'--out',str(out),'--worker',step]
            if a.profile:args+=['--profile',a.profile]
            cp=subprocess.run(args,cwd=ROOT,timeout=240,capture_output=True,text=True)
            (out/(step+'.log')).write_text(cp.stdout)
            observed=last_result(cp.stdout)
            status['steps'].append({'stage':step,'exit_code':cp.returncode,'result':observed})
            if cp.returncode:
                status['blocker']=observed.get('error') or ('dependency_process_crash' if cp.returncode<0 else step+'_failed')
                raise RuntimeError(step+' failed; source checkpoint retained')
        status.update(status='preflight_ready',preflight=observed) if a.preflight else status.update(json.loads((out/'result.json').read_text()))
    except (RuntimeError,ValueError,subprocess.TimeoutExpired) as e:
        status.update(status='failed',error_type=type(e).__name__,error=str(e)[:150],email_status='not_sent')
        status.setdefault('blocker',str(e) if isinstance(e,ValueError) else 'stage_timeout' if isinstance(e,subprocess.TimeoutExpired) else 'stage_failed')
    status['ended_at']=datetime.now(timezone.utc).isoformat()
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2))
    print(json.dumps(status,ensure_ascii=False));return 2 if status['status']=='failed' else 0
if __name__=='__main__':raise SystemExit(main())
