// Bounded, local browser checks for installed page skill capabilities.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {serve, loadPlaywright, launch} from '../skills/cinematic-ui/scripts/lib.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = path.join(root, 'ui/runtime/expansion-20261102/page-specialists');
const temporary = path.join(output, 'tmp');
fs.mkdirSync(temporary, {recursive:true});
for (const [key, folder] of Object.entries({TMPDIR:'tmp',XDG_CACHE_HOME:'cache',XDG_CONFIG_HOME:'config'})) {
  process.env[key] = path.join(output, folder); fs.mkdirSync(process.env[key], {recursive:true});
}
const work = fs.mkdtempSync(path.join(temporary, 'page browser '));
const site = path.join(work, 'site'); fs.mkdirSync(site);
const fixture = path.join(root, 'ui/tests/fixtures/page-skills');
const config = JSON.parse(fs.readFileSync(path.join(fixture, 'landing-config.json'), 'utf8'));
const edge = structuredClone(config);
edge.brand = 'R&D {window.__SKILL_CANARY=true}';
edge.hero.headline = 'Research ' + 'identifier_'.repeat(30) + ' {1+1} <script>window.__SKILL_CANARY=1</script>';
edge.testimonials = {title:'Synthetic test only',items:[{name:'Fixture',title:'Test',company:'Local',quote:'LongToken'+'X'.repeat(250)}]};
for (const [name,data] of [['landing',config], ['edge',edge]]) {
  const input = path.join(work, name+'.json');fs.writeFileSync(input,JSON.stringify(data));
  const result = spawnSync('python3',['-B',path.join(root,'ui/skills/landing-page-generator/scripts/landing_page_scaffolder.py'),input,'--format','html','--output',path.join(site,name+'.html')],{encoding:'utf8',timeout:15000});
  assert.equal(result.status,0,result.stderr);
}
fs.copyFileSync(path.join(fixture,'cinematic.html'),path.join(site,'cinematic.html'));
fs.mkdirSync(path.join(site,'kit'));fs.copyFileSync(path.join(root,'ui/skills/cinematic-ui/kit/type-fx.js'),path.join(site,'kit/type-fx.js'));
fs.writeFileSync(path.join(work,'sibling.txt'),'SYNTHETIC_PRIVATE_CANARY');
fs.symlinkSync(path.join(work,'sibling.txt'),path.join(site,'escape.txt'));
const server = await serve(site);
let browser;
const receipt = {at:new Date().toISOString(),fixture:'synthetic offline page capability',cases:[],staticServer:{},filmResearch:'unverified',scope:'local Chromium only'};
const hash = (buffer) => createHash('sha256').update(buffer).digest('hex');
try {
  receipt.staticServer.normal = (await fetch(server.origin+'/landing.html')).status;
  receipt.staticServer.malformed = (await fetch(server.origin+'/%E0%A4%A')).status;
  receipt.staticServer.traversal = (await fetch(server.origin+'/%2e%2e%2fsibling.txt')).status;
  receipt.staticServer.symlink = (await fetch(server.origin+'/escape.txt')).status;
  receipt.staticServer.afterMalformed = (await fetch(server.origin+'/landing.html')).status;
  receipt.staticServer.range = (await fetch(server.origin+'/landing.html',{headers:{Range:'bytes=0-9'}})).status;
  assert.deepEqual(receipt.staticServer,{normal:200,malformed:400,traversal:403,symlink:403,afterMalformed:200,range:206});
  const pw = await loadPlaywright(); browser = await launch(pw);
  receipt.browserExecutable = pw.chromium.executablePath().replace(root+'/', '');
  assert.ok(pw.chromium.executablePath().startsWith(path.join(root,'ui/runtime/browsers')));
  for (const width of [320,390,1440]) for (const name of ['landing','edge']) {
    const context = await browser.newContext({viewport:{width,height:900}});
    const page = await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(server.origin+'/'+name+'.html');await page.evaluate(()=>document.fonts.ready);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`${name} overflow at ${width}`);
    assert.equal(await page.locator('h1').count(),1);assert.equal(await page.locator('script').count(),0);
    assert.equal(await page.evaluate(()=>Boolean(window.__SKILL_CANARY)),false);
    await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.matches(':focus-visible')),true);
    await page.getByRole('link',{name:'Find your plan',exact:true}).click();
    assert.equal(new URL(page.url()).hash,'#pricing');assert.equal(await page.locator('#pricing').count(),1);
    assert.equal(await page.evaluate(()=>[...document.querySelectorAll('.btn-primary,.btn-secondary,.btn-white,.nav-cta')].every(el=>{
      const box=el.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(el);
      return box.height>=44 && [...range.getClientRects()].every(line=>line.left>=box.left-1&&line.right<=box.right+1&&line.top>=box.top-1&&line.bottom<=box.bottom+1);
    })),true,'CTA text must remain inside its clickable box');
    assert.deepEqual(errors,[]);await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(output,`${name}-${width}.png`),fullPage:true});
    receipt.cases.push({skill:'landing-page-generator',name,width,overflow:false,keyboardFocus:true,anchor:true,scriptInjection:false,errors});
    await context.close();
  }
  for (const width of [320,1440]) for (const reducedMotion of ['no-preference','reduce']) {
    const context=await browser.newContext({viewport:{width,height:900},reducedMotion});
    const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(server.origin+'/cinematic.html');await page.waitForFunction(()=>window.demo?.ready);await page.evaluate(()=>document.fonts.ready);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,`cinematic overflow at ${width}`);
    await page.locator('[data-step="1"]').focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>window.demo.step),1);
    assert.equal(await page.locator('[data-step="1"]').getAttribute('aria-pressed'),'true');
    for (const step of [2,0,1,2]) await page.locator(`[data-step="${step}"]`).click();
    assert.equal(await page.evaluate(()=>window.demo.step),2);
    await page.evaluate(()=>window.demo.fx.set(.55,3));const first=hash(await page.locator('h1').screenshot());
    await page.evaluate(()=>window.demo.fx.set(.95,9));await page.evaluate(()=>window.demo.fx.set(.55,3));
    assert.equal(hash(await page.locator('h1').screenshot()),first,'type frame must be deterministic');
    if(reducedMotion==='reduce') {
      await page.evaluate(()=>window.demo.fx.set(0,0));const start=hash(await page.locator('h1').screenshot());
      await page.evaluate(()=>window.demo.fx.set(1,12));assert.equal(hash(await page.locator('h1').screenshot()),start,'reduced motion rests at the same frame');
    }
    await page.evaluate(()=>window.demo.fx.still());
    await page.screenshot({path:path.join(output,`cinematic-${width}-${reducedMotion}.png`),fullPage:true});
    await page.evaluate(()=>window.demo.fx.destroy());
    assert.equal(await page.locator('h1').textContent(),'Follow the thread.');assert.deepEqual(errors,[]);
    receipt.cases.push({skill:'cinematic-ui',width,reducedMotion,keyboardStageSelection:true,rapidSelection:true,deterministicType:true,destroyRestoresText:true,errors});
    await context.close();
  }
  receipt.passed = receipt.cases.length === 10;
} catch (error) {
  receipt.passed=false;receipt.error=String(error.stack||error);throw error;
} finally {
  await browser?.close();await new Promise(resolve=>server.server.close(resolve));
  try { await fetch(server.origin+'/landing.html',{signal:AbortSignal.timeout(1000)});receipt.serverClosed=false; }
  catch { receipt.serverClosed=true; }
  fs.writeFileSync(path.join(output,'browser-result.json'),JSON.stringify(receipt,null,2));
  fs.rmSync(work,{recursive:true,force:true});
}
assert.equal(receipt.serverClosed,true);console.log(JSON.stringify({passed:receipt.passed,cases:receipt.cases.length,staticServer:receipt.staticServer,serverClosed:receipt.serverClosed,receipt:path.relative(root,path.join(output,'browser-result.json'))},null,2));
