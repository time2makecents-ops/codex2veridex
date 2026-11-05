// Isolated browser integration checks; no signed-in profile or native registration.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {parseArgs} from 'node:util';
const {values} = parseArgs({options: {chrome: {type:'string'}, toolkit: {type:'string'}, output: {type:'string'}}});
if (!values.chrome || !values.toolkit || !values.output) throw new Error('--chrome, --toolkit and --output are required');
const require = createRequire(path.join(path.resolve(values.toolkit), 'package.json'));
const {chromium} = require('playwright');
const {AxeBuilder} = require('@axe-core/playwright');
const root = path.resolve(import.meta.dirname, '..');
const extension = path.join(root, 'chrome_extension');
const output = path.resolve(values.output);
await fs.mkdir(output, {recursive:true});
const testExtension = path.join(output,'fixture-extension');
await fs.cp(extension,testExtension,{recursive:true,errorOnExist:true,force:false});
const testManifest = JSON.parse(await fs.readFile(path.join(testExtension,'manifest.json'),'utf8'));
testManifest.host_permissions = ['https://fixture.test/*'];
// Do not let an isolated test attach to the operator's registered native host.
testManifest.permissions = testManifest.permissions.filter(value=>value!=='nativeMessaging');
await fs.writeFile(path.join(testExtension,'manifest.json'),JSON.stringify(testManifest,null,2));
const context = await chromium.launchPersistentContext(path.join(output, 'isolated-profile'), {
  executablePath:path.resolve(values.chrome), headless:true,
  args:[`--disable-extensions-except=${testExtension}`, `--load-extension=${testExtension}`]
});
let passed = 0;
let report;
try {
  const fixture = await context.newPage();
  await fixture.route('https://fixture.test/**', route => route.fulfill({contentType:'text/html', body:`<!doctype html><html lang="en"><title>Synthetic browser test</title><body>
    <h1>Browser fixture</h1><label>Item title<input id="item"></label><label>Password<input type="password" id="password"></label>
    <label>Verification code<input id="otp" autocomplete="one-time-code"></label>
    <button id="show" onclick="document.getElementById('result').textContent='Details visible'">Show details</button>
    <button id="disabled" disabled>Unavailable</button><p id="result"></p></body></html>`}));
  await fixture.goto('https://fixture.test/');
  const script = await fs.readFile(path.join(extension,'page_operations.js'),'utf8');
  const inject = () => fixture.addScriptTag({content:script});
  const run = (action,args={}) => fixture.evaluate(({action,args}) => globalThis.__veridexPage.run(action,args),{action,args});
  await inject();
  let read = await run('read');
  assert.equal(read.status,'completed');
  assert(!read.observation.elements.some(row => row.type === 'password')); passed++;
  const target = (observation,label) => observation.elements.find(row => row.label === label || row.type === label);
  let field = read.observation.elements.find(row => row.tag === 'input' && row.type === 'text');
  let fill = await run('fill',{...read.observation,target_id:field.target_id,text:'Synthetic vase'});
  assert.equal(fill.status,'completed'); assert.equal(await fixture.locator('#item').inputValue(),'Synthetic vase'); passed++;
  await assert.rejects(run('fill',{...read.observation,target_id:field.target_id,text:'stale'}),/Stale/); passed++;
  read = await run('read');
  const button = target(read.observation,'Show details');
  let click = await run('click',{...read.observation,target_id:button.target_id,expect_text:'Details visible'});
  assert.equal(click.status,'completed'); assert.equal(click.effect_verified,true); passed++;
  read = await run('read');
  const changed = target(read.observation,'Show details');
  await fixture.locator('#show').evaluate(node => node.textContent='Changed target');
  await assert.rejects(run('click',{...read.observation,target_id:changed.target_id}),/Target changed/); passed++;
  read = await run('read');
  const disabled = target(read.observation,'Unavailable');
  await assert.rejects(run('click',{...read.observation,target_id:disabled.target_id}),/disabled/); passed++;
  const otp = read.observation.elements.find(row => row.label === 'Verification code');
  await assert.rejects(run('fill',{...read.observation,target_id:otp.target_id,text:'123456'}),/manual entry/); passed++;
  read = await run('read');
  click = await run('click',{...read.observation,target_id:target(read.observation,'Changed target').target_id});
  assert.equal(click.status,'limited'); passed++;
  const beforeReload = await run('read');
  await fixture.reload(); await inject();
  read = await run('read');
  assert.notEqual(beforeReload.observation.document_id,read.observation.document_id); passed++;
  await assert.rejects(run('click',{...beforeReload.observation,target_id:'t1'}),/Stale/); passed++;
  const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
  const id = new URL(worker.url()).hostname;
  assert.equal(id,'agigaaikljlfallmmpechfbfckbhagbe'); passed++;
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  await popup.getByRole('heading',{name:'Veridex Browser Companion'}).waitFor();
  await popup.screenshot({path:path.join(output,'extension-popup.png'),fullPage:true});
  const a11y = await new AxeBuilder({page:popup}).analyze();
  assert.equal(a11y.violations.length,0,JSON.stringify(a11y.violations.map(row=>({id:row.id,impact:row.impact})),null,2)); passed++;
  await popup.getByLabel('Workspace ID').fill('ws_remembered');
  await popup.getByLabel('Session ID').fill('sess_remembered');
  assert.equal(await popup.getByLabel('Active room (automatic)').isEditable(),false);
  await popup.waitForFunction(async () => (await chrome.storage.local.get('scopeDraft')).scopeDraft?.session_id === 'sess_remembered'); passed++;
  await popup.reload();
  await popup.waitForFunction(() => document.getElementById('session').value === 'sess_remembered');
  assert.equal(await popup.getByLabel('Workspace ID').inputValue(),'ws_remembered');
  assert.equal(await popup.getByLabel('Session ID').inputValue(),'sess_remembered');
  assert.equal(await popup.locator('#connection-settings').evaluate(node=>node.open),false);
  assert.equal(await popup.getByRole('button',{name:'Use this tab'}).isVisible(),true); passed++;
  assert.equal(await popup.evaluate(async () => (await chrome.runtime.sendMessage({type:'status'})).selection),null); passed++;
  await popup.screenshot({path:path.join(output,'extension-saved-settings.png'),fullPage:true});
  // Exercise actual service-worker tab selection and scripting using an in-memory relay.
  // Native registration remains uninstalled; stdio is checked separately in Python.
  const fixtureTab = await worker.evaluate(async () => (await chrome.tabs.query({})).find(tab=>tab.url==='https://fixture.test/').id);
  await worker.evaluate(({tabId}) => {
    port?.disconnect?.();
    selection = null;
    port = {postMessage(message) {
      const waiter = rpcWaiters.get(message.rpc_id);
      rpcWaiters.delete(message.rpc_id); clearTimeout(waiter.timer);
      const reply = message.event?.type === 'claim' ? {execute:true} : {
        selection:message.selection ? {...message.selection,scope:{...message.selection.scope,room:'museum'}} : null
      };
      waiter.resolve(reply); ingest(reply);
    }};
  },{tabId:fixtureTab});
  await fixture.bringToFront();
  const selected = await popup.evaluate(async ()=>chrome.runtime.sendMessage({type:'select',
    scope:{workspace_id:'ws_remembered',session_id:'sess_remembered',room:'Art_Room'}}));
  assert.equal(selected.ok,true);
  assert.equal(selected.selection.scope.room,'museum'); passed++;
  await popup.reload();
  await popup.waitForFunction(()=>document.getElementById('room').value==='museum'); passed++;
  // Host permissions for a synthetic origin are granted through the test context only.
  await worker.evaluate(async () => {
    const command={request_id:'test-read',action:'read',tab_id:selection.tab_id,scope:selection.scope,intent:'Read synthetic fixture'};
    pending.set(command.request_id,command);
    await execute(command,false);
  }); passed++;
  report = {accessibility_violations:a11y.violations.length,extension_id:id,
    browser:context.browser()?.version(),native_registration:false,output};
} finally { await context.close(); }
// Preferences survive browser restart, but they do not grant or restore tab access.
const restarted = await chromium.launchPersistentContext(path.join(output,'isolated-profile'),{
  executablePath:path.resolve(values.chrome),headless:true,
  args:[`--disable-extensions-except=${testExtension}`,`--load-extension=${testExtension}`]
});
try {
  const popup = await restarted.newPage();
  await popup.goto(`chrome-extension://${report.extension_id}/popup.html`);
  await popup.waitForFunction(()=>document.getElementById('session').value==='sess_remembered');
  assert.equal(await popup.getByLabel('Workspace ID').inputValue(),'ws_remembered');
  assert.equal(await popup.getByLabel('Session ID').inputValue(),'sess_remembered');
  assert.equal(await popup.getByLabel('Active room (automatic)').inputValue(),'');
  assert.equal(await popup.evaluate(async ()=>(await chrome.runtime.sendMessage({type:'status'})).selection),null); passed++;
  console.log(JSON.stringify({...report,passed,settings_survive_restart:true,restored_tab_authorization:false},null,2));
} finally { await restarted.close(); }
