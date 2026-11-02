#!/usr/bin/env python3
"""Invoke an explicitly installed target-local UI CLI; never install dependencies."""
import argparse
import json
import os
import json
from pathlib import Path
import signal
import subprocess


def plan(tool, project):
    project = Path(project).absolute()
    if not project.is_dir() or project.resolve() != project: raise ValueError('target_project_unsafe')
    binary = project / 'node_modules/.bin' / tool
    if not binary.is_file() or not os.access(binary,os.X_OK) or not binary.resolve().is_relative_to(project): raise ValueError('target_local_tool_missing')
    runtime = project / '.ui-skill-runtime'
    for path in [runtime, runtime/'tmp', runtime/'cache', runtime/'config', runtime/'browsers', runtime/'browser-session']:
        if path.is_symlink() or (path.exists() and not path.resolve().is_relative_to(project)): raise ValueError('target_runtime_unsafe')
    return project, binary, runtime


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('tool',choices=['shadcn','playwright','playwright-cli'])
    p.add_argument('--project',default=os.environ.get('UI_SKILL_PROJECT'));p.add_argument('--describe',action='store_true');args,extra=p.parse_known_args()
    try:
        if not args.project:raise ValueError('target_project_required')
        project,binary,runtime=plan(args.tool,args.project)
        if args.describe:print(json.dumps({'tool':str(binary),'project':str(project),'runtime':str(runtime),'installs_dependencies':False}));return 0
        for path in [runtime,runtime/'tmp',runtime/'cache',runtime/'config',runtime/'browsers',runtime/'browser-session']:path.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(runtime/'tmp'),XDG_CACHE_HOME=str(runtime/'cache'),XDG_CONFIG_HOME=str(runtime/'config'),
            NPM_CONFIG_CACHE=str(runtime/'cache'),NPM_CONFIG_LOGS_DIR=str(runtime/'cache'),PLAYWRIGHT_BROWSERS_PATH=str(runtime/'browsers'),
            PWTEST_DAEMON_SESSION_DIR=str(runtime/'browser-session'),PLAYWRIGHT_MCP_OUTPUT_DIR=str(runtime/'browser-session'))
        if args.tool=='playwright-cli' and 'open' in extra and not any(item.startswith('--config') for item in extra):
            chrome=Path(os.environ.get('CHROME_PATH','/nonexistent')).resolve()
            if not chrome.is_file() or not chrome.is_relative_to(project):raise ValueError('target_local_browser_required')
            configuration=runtime/'browser-config.json';configuration.write_text(json.dumps({'browser':{'browserName':'chromium','launchOptions':{'executablePath':str(chrome),'headless':True}}}))
            extra += ['--config='+str(configuration),'--idle-timeout=30000']
        child=subprocess.Popen([str(binary),*extra],cwd=project,env=env,start_new_session=True)
        try:return child.wait(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=2)
            raise ValueError('target_tool_timeout') from None
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'UI_TOOL_BLOCKED','code':str(error) if isinstance(error,ValueError) else 'target_tool_unavailable'}));return 2


if __name__=='__main__':raise SystemExit(main())
