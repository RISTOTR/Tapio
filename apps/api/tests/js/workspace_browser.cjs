// Real Chrome, real HTTP, isolated PostgreSQL. No DOM mocks.
const {spawn}=require('node:child_process');
const {mkdtempSync,rmSync,mkdirSync,writeFileSync}=require('node:fs');
const {tmpdir}=require('node:os');
const {once}=require('node:events');
const assert=require('node:assert/strict');
const net=require('node:net');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dir=mkdtempSync(tmpdir()+'/tapio-workspace-browser-');let server,chrome,ws;
 try{
  const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');const port=socket.address().port;await new Promise(r=>socket.close(r));
  let serverLog='';const url=`http://127.0.0.1:${port}/app/ask`;
  async function start(){server=spawn('.venv/bin/python',['-m','uvicorn','apps.api.tests.workspace_browser_server:app','--host','127.0.0.1','--port',String(port)],{env:{...process.env,WORKSPACE_TEST_ROOT:dir},stdio:['ignore','ignore','pipe']});server.stderr.on('data',v=>{serverLog=(serverLog+v).slice(-4000)});for(let i=0;i<600;i++){if(server.exitCode!==null)throw Error('Test server exited: '+serverLog);try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Test server did not start: '+serverLog);}
  await start();
  chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${dir}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error('Chrome start timeout')),20000);chrome.stderr.on('data',v=>{log+=v;const m=log.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}})});
  ws=new WebSocket(endpoint);await once(ws,'open');let next=0,session;const pending=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){const [ok,bad]=pending.get(m.id);pending.delete(m.id);m.error?bad(Error(JSON.stringify(m.error))):ok(m.result)}});
  const call=(method,params={},attach=true)=>new Promise((ok,bad)=>{const id=++next;pending.set(id,[ok,bad]);ws.send(JSON.stringify({id,method,params,...(attach&&session?{sessionId:session}:{})}));});
  const target=await call('Target.createTarget',{url:'about:blank'},false);session=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;await call('Page.enable');
  async function js(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function until(expression){for(let i=0;i<120;i++){if(await js(expression))return;await sleep(50)}throw Error('Browser timeout: '+expression+' '+await js('document.body.innerText'));}

  const shots='data/interim/workspace_ui';mkdirSync(shots,{recursive:true});
  const errors=[];ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)});await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  async function shot(name){await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false}).then(r=>writeFileSync(`${shots}/${name}.png`,Buffer.from(r.data,'base64')))}
  async function access(){
   assert.equal(await js("document.querySelectorAll('main').length"),1);
   assert.equal(await js("document.documentElement.lang"),'en');
   assert.ok(await js("document.querySelector('nav[aria-label=Application] a[aria-current=page]')"));
   assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false,'No page overflow');
   const ax=await call('Accessibility.getFullAXTree');
   const unnamed=ax.nodes.filter(n=>!n.ignored&&['button','textbox','combobox','link'].includes(n.role?.value)&&!n.name?.value);
   assert.deepEqual(unnamed.map(n=>n.role.value),[],'All interactive controls have accessible names');
  }
  await call('Page.navigate',{url});await until("document.querySelector('#question') && window.Tapio");await access();
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.equal(await js("document.activeElement.className"),'skip-link');
  assert.equal(await js("getComputedStyle(document.activeElement).outlineStyle"),'solid');
  await js("document.querySelector('.examples button').click()");assert.ok(await js("document.querySelector('#question').value.includes('forestry')"));
  await shot('ask-desktop');
  await js("document.querySelector('#ask').requestSubmit()");await until("!document.querySelector('#result').hidden");
  assert.ok(await js("document.querySelector('#answer').textContent.includes('€120.50')"));
  assert.ok(await js("document.querySelector('#source-status').textContent.includes('Gmail was not searched')"));
  assert.equal(await js("document.querySelector('#optional').open"),false);await access();await shot('ask-answer-desktop');
  await js("document.querySelector('#optional').open=true");assert.ok(await js("document.querySelector('#transactions').innerText.includes('Example forestry supplier')"));
  assert.equal(await js("document.querySelector('#transactions pre') !== null"),false);
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await access();await shot('ask-mobile');
  await call('Emulation.setDeviceMetricsOverride',{width:680,height:900,deviceScaleFactor:1,mobile:false});await access();
  for(const route of ['/app/import','/app/summary']){await call('Page.navigate',{url:`http://127.0.0.1:${port}${route}`});await until("document.querySelector('main h1')");await access();}
  await call('Page.navigate',{url});await until("document.querySelector('#question') && window.Tapio");await call('Network.enable');await call('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  await js("document.querySelector('#question').value='Forestry expenses in 2025';document.querySelector('#ask').requestSubmit()");await until("document.querySelector('#send').disabled===false && document.querySelector('#status').textContent.length>0");
  assert.equal(await js("document.querySelector('#result').hidden"),true);await call('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  assert.deepEqual(errors,[]);console.log('WORKSPACE_BROWSER_PASS: shell, Ask submission/provenance/evidence, examples, desktop/mobile/intermediate, keyboard focus, accessible names, offline recovery');
 }finally{if(ws)ws.close();if(chrome)chrome.kill('SIGTERM');if(server)server.kill('SIGTERM');await sleep(500);rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
