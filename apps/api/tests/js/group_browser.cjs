// Real Chrome, real HTTP, isolated PostgreSQL. No DOM mocks.
const {spawn}=require('node:child_process');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const {once}=require('node:events');
const assert=require('node:assert/strict');
const net=require('node:net');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const dir=mkdtempSync(tmpdir()+'/tapio-browser-');let server,chrome,ws;
 try{
  const socket=net.createServer();socket.listen(0,'127.0.0.1');await once(socket,'listening');const port=socket.address().port;await new Promise(r=>socket.close(r));
  let serverLog='';const url=`http://127.0.0.1:${port}/pilot/confirmation/groups?plan_id=${process.env.GROUP_TEST_PLAN}`;
  async function start(){server=spawn('.venv/bin/python',['-m','uvicorn','apps.api.tests.group_browser_server:app','--host','127.0.0.1','--port',String(port)],{env:process.env,stdio:['ignore','ignore','pipe']});server.stderr.on('data',v=>{serverLog=(serverLog+v).slice(-4000)});for(let i=0;i<600;i++){if(server.exitCode!==null)throw Error('Test server exited: '+serverLog);try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Test server did not start: '+serverLog);}
  await start();
  chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${dir}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error('Chrome start timeout: '+log)),60000);chrome.stderr.on('data',v=>{log+=v;const m=log.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}})});
  ws=new WebSocket(endpoint);await once(ws,'open');let next=0,session;const pending=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){const [ok,bad]=pending.get(m.id);pending.delete(m.id);m.error?bad(Error(JSON.stringify(m.error))):ok(m.result)}});
  const call=(method,params={},attach=true)=>new Promise((ok,bad)=>{const id=++next;pending.set(id,[ok,bad]);ws.send(JSON.stringify({id,method,params,...(attach&&session?{sessionId:session}:{})}));});
  const target=await call('Target.createTarget',{url:'about:blank'},false);session=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;await call('Page.enable');
  async function js(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function until(expression){for(let i=0;i<120;i++){if(await js(expression))return;await sleep(50)}throw Error('Browser timeout: '+expression+' '+await js('document.body.innerText'));}
  await call('Page.navigate',{url});
  await until("document.body.dataset.loaded==='true'");
  assert.equal(await js("document.querySelectorAll('#groups > article').length"),1);
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  const fs=require('node:fs');fs.mkdirSync('data/interim/workspace_ui',{recursive:true});
  async function capture(name){const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync('data/interim/workspace_ui/'+name+'.png',Buffer.from(r.data,'base64'));}
  assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false);
  const ax=await call('Accessibility.getFullAXTree');assert.deepEqual(ax.nodes.filter(n=>!n.ignored&&['button','textbox','combobox','link'].includes(n.role?.value)&&!n.name?.value).map(n=>n.role.value),[]);
  await capture('review-groups-desktop');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false,'Narrow review must not overflow the page');await capture('review-groups-mobile');
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});

  await js("document.querySelector('#groups article button').click()");
  await until("[...document.querySelectorAll('button')].some(b=>b.textContent==='Apply displayed group')");
  // Hold the real refresh response while focus/poll events arrive. They must
  // share the in-flight load instead of invalidating it and issuing more loads.
  await js(`window.refreshCalls=0;window.refreshGate=new Promise(r=>window.releaseRefresh=r);window.originalFetch=window.fetch;window.fetch=async(...args)=>{if(String(args[0]).startsWith(base+'/cards')){window.refreshCalls++;await window.refreshGate;}return window.originalFetch(...args)}`);
  await js("[...document.querySelectorAll('button')].find(b=>b.textContent==='Apply displayed group').click()");
  await until("window.refreshCalls===1");
  await js("void checkCurrent();void checkCurrent();");
  await sleep(400);
  assert.equal(await js("window.refreshCalls"),1,'focus/poll must not overlap an active refresh');
  await js("window.releaseRefresh()");
  await until("document.querySelectorAll('#groups > article').length===0");
  await until("document.querySelectorAll('#saved-cards select').length===6");
  assert.equal(await js("document.querySelector('#saved-cards select[aria-label=context]').value"),'PERSONAL');
  await js("document.body.dataset.loaded='false'");await call('Page.reload',{ignoreCache:true});
  await until("document.body.dataset.loaded==='true'");
  await until("document.querySelectorAll('#saved-cards select').length===6");
  assert.equal(await js("document.querySelector('#saved-cards select[aria-label=context]').value"),'PERSONAL');
  await js("document.querySelector('#saved').open=true;const a=document.querySelector('#saved-cards article');const select=a.querySelector('select[aria-label=context]');select.value='PROPERTY';select.dispatchEvent(new Event('change'));a.querySelector('input').value='Synthetic browser correction';[...a.querySelectorAll('button')].find(b=>b.textContent==='Preview selected fields').click()");
  await until("[...document.querySelectorAll('#saved-cards button')].some(b=>b.textContent==='Apply displayed changes')");
  await js("[...document.querySelectorAll('#saved-cards button')].find(b=>b.textContent==='Apply displayed changes').click()");
  await until("![...document.querySelectorAll('#saved-cards button')].some(b=>b.textContent==='Apply displayed changes') && document.querySelector('#saved-cards select[aria-label=context]')?.value==='PROPERTY'");
  assert.equal(await js("document.querySelectorAll('#groups > article').length"),0);
  console.log('GROUP_BROWSER_PASS: automatic queue refresh, persisted corrections, reload');
 }finally{if(ws)ws.close();if(chrome)chrome.kill('SIGTERM');if(server)server.kill('SIGTERM');await sleep(500);rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
