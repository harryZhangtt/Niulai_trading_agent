#!/usr/bin/env python3
"""Build a portable candidate below ui/portable or ui/runtime; never install it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[2]
AREA=ROOT/'ui/portable'
SUPPORTED_NAMES=frozenset({'ui-skill-router','harry-ui-skill-set'})
TEXT={'.md','.py','.mjs','.js','.sh','.html','.txt'}
DISABLED={'hallmark/scripts/install.mjs','hallmark/scripts/install-hook.mjs','hallmark/scripts/lint-hook.mjs','hallmark/scripts/picture.mjs'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def require(ok,code):
 if not ok:raise ValueError(code)

def output_name(relative):return str(relative).replace('SKILL.md','GUIDE.md')

def rewrite_markdown(value,source,destination,mapping):
 def link(match):
  target=match.group(1).strip('<>');parts=urlsplit(target)
  if parts.scheme or not parts.path:return match.group(0)
  selected=(source.parent/unquote(parts.path)).resolve()
  if selected not in mapping:return match.group(0)
  new=os.path.relpath(mapping[selected],destination.parent).replace(os.sep,'/')
  if parts.fragment:new+='#'+parts.fragment
  return ']('+new+')'
 value=re.sub(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)',link,value)
 value=value.replace('SKILL.md','GUIDE.md')
 value=value.replace('python3 ui/tools/run.py','python3 "${BUNDLE_ROOT}/scripts/tools.py"')
 value=value.replace('ui/AGENTS.md',"the target repository’s AGENTS.md").replace('ui/ROUTING.md','the router’s ROUTING-CARD.md')
 value=value.replace('docs/deployment/frontend.md','${BUNDLE_ROOT}/references/EXECUTION.md')
 value=value.replace('ui/runtime/','<target-project>/.ui-skill-runtime/').replace('ui/verification',"the target repository’s explicit local UI toolchain")
 for name in sorted(json.loads((ROOT/'ui/catalog.json').read_bytes())['skills'],key=len,reverse=True):
  value=value.replace('ui/skills/'+name, '${BUNDLE_ROOT}/experts/'+name)
 return value

def adapt_script(value,relative):
 value=value.replace('SKILL.md','GUIDE.md')
 if relative in DISABLED:
  return "#!/usr/bin/env node\nthrow new Error('PORTABLE_DISTRIBUTION_SCRIPT_DISABLED: installer, hook or package-reference authoring is not a target-project helper');\n"
 if relative=='hallmark/scripts/theme.mjs':
  require(value.count('function buildIndex() {')==1,'hallmark_index_adapter_source_changed')
  value=value.replace('function buildIndex() {', "function buildIndex() {\n  throw new Error('PORTABLE_PACKAGE_READ_ONLY: rebuild theme indexes in the maintained source package');",1)
 if relative=='hallmark/scripts/capture.mjs':
  value=re.sub(r"const roots = .*?;\n", "const roots = [process.env.HALLMARK_PUPPETEER].filter(Boolean);\n", value,count=1)
  value=re.sub(r"const globalRoot = .*?\n", '',value,count=1)
  value=re.sub(r"if \(!puppeteer\) \{ const g = await globalRoot\(\);.*?\n", '',value,count=1)
  value=re.sub(r"const CHROMES = .*?;\n", "const CHROMES = [process.env.CHROME_PATH];\n",value,count=1)
  value=re.sub(r"const findChrome = .*?\n", "const findChrome = () => CHROMES.find((x) => x && existsSync(x)) || null;\n",value,count=1)
  value=value.replace('local, global or HALLMARK_PUPPETEER','explicit target-local HALLMARK_PUPPETEER')
 if relative=='cinematic-ui/scripts/lib.mjs':
  a=value.index('/** Use this workspace');b=value.index('/** Launch',a)
  value=value[:a]+'''/** Require explicit target-local dependencies; no source-workspace or global fallback. */
export async function loadPlaywright() {
  const project = process.env.UI_SKILL_PROJECT && fs.realpathSync(process.env.UI_SKILL_PROJECT);
  if (!project) throw new Error('UI_SKILL_PROJECT_REQUIRED');
  const modulePath = fs.realpathSync(process.env.UI_SKILL_PLAYWRIGHT || path.join(project, 'node_modules/@playwright/test/index.mjs'));
  const chrome = process.env.CHROME_PATH && fs.realpathSync(process.env.CHROME_PATH);
  if (!modulePath.startsWith(project + path.sep) || !chrome || !chrome.startsWith(project + path.sep)) throw new Error('TARGET_LOCAL_BROWSER_REQUIRED');
  return await import(pathToFileURL(modulePath).href);
}

'''+value[b:]
  value=value.replace('headless: !headed, args','headless: !headed, executablePath: process.env.CHROME_PATH, args')
 if relative=='design-md-chrome/scripts/extract.mjs':
  value=value.replace("const ui = path.resolve(skill, '../..');\nconst workspace = path.dirname(ui);", "let workspace;\nlet ui;")
  value=value.replace("try {\n  if (process.argv.length", "try {\n  workspace = process.env.UI_SKILL_PROJECT && await realpath(process.env.UI_SKILL_PROJECT);\n  ui = workspace;\n  if (process.argv.length",1)
  value=value.replace("  const runtime = path.join(ui, 'runtime');", "  if (!workspace) throw new Error('TARGET_PROJECT_REQUIRED');\n  const runtime = path.join(workspace, '.ui-skill-runtime');")
  value=value.replace("path.join(ui, 'verification/node_modules/@playwright/test/index.mjs')", "process.env.UI_SKILL_PLAYWRIGHT || path.join(workspace, 'node_modules/@playwright/test/index.mjs')")
  value=value.replace("  const { chromium } = await import(pathToFileURL(process.env.UI_SKILL_PLAYWRIGHT || path.join(workspace, 'node_modules/@playwright/test/index.mjs')));", "  const modulePath = await realpath(process.env.UI_SKILL_PLAYWRIGHT || path.join(workspace, 'node_modules/@playwright/test/index.mjs'));\n  if (!modulePath.startsWith(workspace + path.sep)) throw new Error('TARGET_LOCAL_DEPENDENCY_REQUIRED');\n  const { chromium } = await import(pathToFileURL(modulePath));")
  value=value.replace("  browser = await chromium.launch({ headless: true, timeout: 15000 });", "  const chrome = process.env.CHROME_PATH && await realpath(process.env.CHROME_PATH);\n  if (!chrome || !chrome.startsWith(workspace + path.sep)) throw new Error('TARGET_LOCAL_BROWSER_REQUIRED');\n  browser = await chromium.launch({ headless: true, executablePath: chrome, timeout: 15000 });")
  value=value.replace("'GUIDE.md'), generatedSkill", "'GENERATED-GUIDE.md'), generatedSkill")
  require('const modulePath = await realpath(' in value and "if (!modulePath.startsWith(workspace + path.sep))" in value,'design_md_dependency_adapter_source_changed')
  require(value.index('workspace = process.env.UI_SKILL_PROJECT')>value.index('try {'),'design_md_error_boundary_adapter_source_changed')
 return value

def build(destination,name='ui-skill-router'):
 require(name in SUPPORTED_NAMES,'unsupported_bundle_name')
 destination=Path(destination).absolute();require(destination.resolve()==destination and any(destination.is_relative_to(base) for base in (AREA,ROOT/'ui/runtime')) and not destination.exists() and not destination.is_symlink(),'candidate_destination_rejected')
 destination.parent.mkdir(parents=True,exist_ok=True)
 stage=Path(tempfile.mkdtemp(prefix='.build-',dir=destination.parent));records={};mapping={};excluded=[]
 try:
  catalog=json.loads((ROOT/'ui/catalog.json').read_bytes())
  for expert_name in catalog['skills']:
   for source in (ROOT/'ui/skills'/expert_name).rglob('*'):
    require(not source.is_symlink(),'source_symlink_rejected')
    if not source.is_file():continue
    rel=source.relative_to(ROOT/'ui/skills')
    if '__pycache__' in rel.parts or source.suffix=='.pyc' or source.name=='.DS_Store':continue
    mapping[source.resolve()]=stage/'experts'/output_name(rel)
  for source in (ROOT/'ui/upstream').rglob('*'):
   if source.is_file():
    require(not source.is_symlink(),'source_symlink_rejected')
    rel=source.relative_to(ROOT/'ui/upstream');path_name=str(rel)
    if source.suffix=='.md':path_name=path_name[:-3]+'.txt'
    mapping[source.resolve()]=stage/'provenance/upstream'/path_name
  authored={ROOT/'ui/catalog.json':stage/'catalog.json',AREA/'ROUTING-CARD.md':stage/'ROUTING-CARD.md',
   AREA/'templates/entrypoint.md':stage/'SKILL.md',AREA/'templates/EXECUTION.md':stage/'references/EXECUTION.md',
   AREA/'templates/resolve.py':stage/'scripts/resolve.py',AREA/'templates/tools.py':stage/'scripts/tools.py',
   AREA/'verify.py':stage/'scripts/verify.py',AREA/'manage.py':stage/'scripts/manage.py'}
  for source,target in ((AREA/'INTENT-CARD.md',stage/'INTENT-CARD.md'),(AREA/'templates/activate.py',stage/'scripts/activate.py'),(AREA/'templates/session.py',stage/'scripts/session.py'),(AREA/'templates/openai.yaml',stage/'agents/openai.yaml')):
   if source.is_file():
    require(not source.is_symlink(),'source_symlink_rejected');authored[source]=target
  for source,target in {**mapping,**authored}.items():
   raw=source.read_bytes();current=raw;changes=[];target.parent.mkdir(parents=True,exist_ok=True)
   if source in mapping and source.suffix=='.md' and target.suffix=='.md':
    current=rewrite_markdown(raw.decode(),source,target,mapping).encode()
   elif source in mapping and source.suffix in {'.mjs','.js','.py','.sh'}:
    relative=str(source.relative_to(ROOT/'ui/skills')) if source.is_relative_to(ROOT/'ui/skills') else ''
    current=adapt_script(raw.decode(),relative).encode()
   elif source in authored and source.suffix in {'.md','.yaml'}:
    current=re.sub(r'\b(?:ui-skill-router|harry-ui-skill-set)\b',name,raw.decode()).encode()
   target.write_bytes(current);target.chmod(0o644)
   records[str(target.relative_to(stage))]={'sha256':sha(current),'source_path':str(source.relative_to(ROOT)),
      'source_sha256':sha(raw),'adapted':current!=raw}
  source_provenance=json.loads((ROOT/'ui/upstream/sources.lock.json').read_bytes())
  index=[]
  for expert_name,item in catalog['skills'].items():
   guide=stage/'experts'/expert_name/'GUIDE.md';front=guide.read_text().split('---',2)[1]
   description=re.search(r'^description:\s*(.*)$',front,re.M)
   index.append({'name':expert_name,'role':item['role'],'guide':'experts/'+expert_name+'/GUIDE.md','description':description.group(1).strip('"') if description else ''})
  indexraw=encoded(index);(stage/'references/EXPERTS.json').write_bytes(indexraw);records['references/EXPERTS.json']={'sha256':sha(indexraw),'source_path':'generated from canonical skill metadata','adapted':True}
  manifest={'schema_version':1,'name':name,'version':'portable-candidate-2.0.0','catalog_source_sha256':sha((ROOT/'ui/catalog.json').read_bytes()),
   'routing_card_sha256':sha((stage/'ROUTING-CARD.md').read_bytes()),'expert_count':len(catalog['skills']),'decision_count':len(catalog['decisions']),
   'repositories':source_provenance['repositories'],'files':dict(sorted(records.items())),
   'adaptations':['Internal entrypoints renamed GUIDE.md; only router is discoverable.',
    'Target-repository commands and explicit local browser/dependency prerequisites replace source-workspace assumptions.',
    'Distribution installers/hooks and package-reference authoring disabled; original source identities retained.',
    'No globals, dependency installation, active MCP/hooks, source-workspace symlink or runtime state included.']}
  (stage/'manifest.json').write_bytes(encoded(manifest))
  from verify import verify
  errors=verify(stage);require(not errors,'candidate_verification_failed:'+json.dumps(errors[:12]))
  os.rename(stage,destination)
  return {'candidate':str(destination),'files':len(records),'experts':len(catalog['skills']),'decisions':len(catalog['decisions']),
   'manifest_sha256':sha((destination/'manifest.json').read_bytes()),'card_sha256':manifest['routing_card_sha256'],'bytes':sum((destination/p).stat().st_size for p in records)}
 finally:
  if stage.exists():shutil.rmtree(stage)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--name',choices=sorted(SUPPORTED_NAMES),default='ui-skill-router')
 args=parser.parse_args();print(json.dumps(build(args.output,args.name),indent=2))
