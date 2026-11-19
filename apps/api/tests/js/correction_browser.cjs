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
  async function start(){server=spawn('.venv/bin/python',['-m','uvicorn','apps.api.tests.correction_browser_server:app','--host','127.0.0.1','--port',String(port)],{env:{...process.env,WORKSPACE_TEST_ROOT:dir},stdio:['ignore','ignore','pipe']});server.stderr.on('data',v=>{serverLog=(serverLog+v).slice(-4000)});for(let i=0;i<600;i++){if(server.exitCode!==null)throw Error('Test server exited: '+serverLog);try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Test server did not start: '+serverLog);}
  await start();
  chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${dir}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error('Chrome start timeout')),20000);chrome.stderr.on('data',v=>{log+=v;const m=log.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}})});
  ws=new WebSocket(endpoint);await once(ws,'open');let next=0,session;const pending=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){const [ok,bad]=pending.get(m.id);pending.delete(m.id);m.error?bad(Error(JSON.stringify(m.error))):ok(m.result)}});
  const call=(method,params={},attach=true)=>new Promise((ok,bad)=>{const id=++next;pending.set(id,[ok,bad]);ws.send(JSON.stringify({id,method,params,...(attach&&session?{sessionId:session}:{})}));});
  const target=await call('Target.createTarget',{url:'about:blank'},false);session=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;await call('Page.enable');
  async function js(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function until(expression){for(let i=0;i<1200;i++){if(await js(expression))return;await sleep(50)}throw Error('Browser timeout: '+expression+' '+await js('document.body.innerText'));}

  const shots='data/interim/ask_corrections';mkdirSync(shots,{recursive:true});
  const errors=[];ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text)});await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  async function shot(name){await js('window.scrollTo(0,0)');const metrics=await call('Page.getLayoutMetrics');await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}}).then(r=>writeFileSync(`${shots}/${name}.png`,Buffer.from(r.data,'base64')))}
  async function access(){
   assert.equal(await js("document.querySelectorAll('main').length"),1);
   assert.equal(await js("document.documentElement.lang"),'en');
   assert.ok(await js("document.querySelector('nav[aria-label=Application] a[aria-current=page]')"));
   assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false,'No page overflow');
   const ax=await call('Accessibility.getFullAXTree');
   const unnamed=ax.nodes.filter(n=>!n.ignored&&['button','textbox','combobox','link'].includes(n.role?.value)&&!n.name?.value);
   assert.deepEqual(unnamed.map(n=>n.role.value),[],'All interactive controls have accessible names');
  }

  await call('Page.navigate',{url});await until("document.querySelector('#question') && window.Tapio");
  await js("document.querySelector('#question').value='Change Synthetic queue shop transaction 15/01/2025 to category OTHER and business context FORESTRY';document.querySelector('#ask').requestSubmit()");
  await until("document.querySelectorAll('#correction input[type=radio]').length===35");
  assert.equal(await js("document.querySelector('#correction input:checked')"),null);
  await js("document.querySelector('#correction input').click();Array.from(document.querySelectorAll('#correction button')).find(b=>b.textContent==='Preview correction').click()");
  await until("document.querySelector('#correction table')");
  assert.ok(await js("document.querySelector('#correction table').textContent.includes('FORESTRY')"));
  await access();await shot('ask-correction-desktop');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await access();
  await js("document.querySelector('#correction table').scrollIntoView()");
  const picture=await call('Page.captureScreenshot',{format:'png'});writeFileSync('/tmp/tapio-correction-mobile.png',Buffer.from(picture.data,'base64'));
  await js("Array.from(document.querySelectorAll('#correction button')).find(b=>b.textContent==='Confirm and apply correction').click()");
  await until("document.querySelector('#correction').textContent.includes('Correction saved.')");
  assert.deepEqual(errors,[]);console.log('CORRECTION_BROWSER_PASS: resolve, multiple selection, preview, explicit apply, desktop/mobile and accessible names');
 }finally{if(ws)ws.close();if(chrome)chrome.kill('SIGTERM');if(server)server.kill('SIGTERM');await sleep(500);rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
