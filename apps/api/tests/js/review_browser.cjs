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
  const url=`http://127.0.0.1:${port}/pilot/confirmation`;
  async function start(){server=spawn('.venv/bin/python',['-m','uvicorn','apps.api.tests.review_browser_server:app','--host','127.0.0.1','--port',String(port)],{env:process.env,stdio:'ignore'});for(let i=0;i<600;i++){try{if((await fetch(url)).ok)return;}catch{}await sleep(100);}throw Error('Test server did not start');}
  await start();
  chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${dir}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error('Chrome start timeout: '+log)),60000);chrome.stderr.on('data',v=>{log+=v;const m=log.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}})});
  ws=new WebSocket(endpoint);await once(ws,'open');let next=0,session;const pending=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(pending.has(m.id)){const [ok,bad]=pending.get(m.id);pending.delete(m.id);m.error?bad(Error(JSON.stringify(m.error))):ok(m.result)}});
  const call=(method,params={},attach=true)=>new Promise((ok,bad)=>{const id=++next;pending.set(id,[ok,bad]);ws.send(JSON.stringify({id,method,params,...(attach&&session?{sessionId:session}:{})}));});
  const target=await call('Target.createTarget',{url:'about:blank'},false);session=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;await call('Page.enable');
  async function js(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function until(expression){for(let i=0;i<120;i++){if(await js(expression))return;await sleep(50)}throw Error('Browser timeout: '+expression+' '+await js('document.body.innerText'));}
  async function ready(){await until("document.body.dataset.loaded==='true' && document.querySelector('article select[aria-label=category]') !== null");}
  async function reload(){await js("document.body.dataset.loaded='false'");await call('Page.reload',{ignoreCache:true});await ready();}
  async function check(category,context){await ready();assert.deepEqual(await js("['category','context'].map(f=>document.querySelector('select[aria-label='+f+']').value)"),[category,context]);const current=await js("fetch('/pilot/confirmation/current').then(r=>r.json()).then(r=>Object.values(r.reviews)[0])");assert.equal(current.category.value,category||null);assert.equal(current.context.value,context||null);for(const [field,value] of Object.entries({category,context})){if(value)assert.equal(current[field].field_status,value==='UNKNOWN'?'HUMAN_CONFIRMED_UNKNOWN':'HUMAN_CONFIRMED_VALUE');else assert.ok(['UNREVIEWED','UNRESOLVED'].includes(current[field].field_status));}return current;}
  await call('Page.navigate',{url});await check('','');
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
  const fs=require('node:fs');fs.mkdirSync('data/interim/workspace_ui',{recursive:true});
  async function capture(name){const r=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync('data/interim/workspace_ui/'+name+'.png',Buffer.from(r.data,'base64'));}
  assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false);
  const ax=await call('Accessibility.getFullAXTree');assert.deepEqual(ax.nodes.filter(n=>!n.ignored&&['button','textbox','combobox','link'].includes(n.role?.value)&&!n.name?.value).map(n=>n.role.value),[]);
  await capture('review-individual-desktop');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.equal(await js("document.documentElement.scrollWidth>innerWidth+1"),false,'Narrow review must not overflow the page');await capture('review-individual-mobile');
  await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});

  async function save(category,context){await js(`(()=>{const a=document.querySelector('article');const action=a.querySelector('[aria-label=Action]');action.value='CHANGE';action.dispatchEvent(new Event('change',{bubbles:true}));for(const [f,v] of Object.entries(${JSON.stringify({category,context})})){if(v===null)continue;const s=a.querySelector('select[aria-label='+f+']');s.value=v;s.dispatchEvent(new Event('change',{bubbles:true}));a.querySelector('input[aria-label="Include '+f+'"]').checked=true;}a.querySelector('textarea').value='Deliberate browser test decision';a.querySelector('button[type=submit]').click();})()`);await until("!document.querySelector('article button[type=button]').disabled");await js("document.querySelector('article button[type=button]').click()");await until("document.querySelector('[data-message]').textContent.includes('Saved canonical')");}
  // Partial review must preserve unresolved context, never select UNKNOWN by default.
  await save('OTHER',null);await check('OTHER','');await reload();await check('OTHER','');
  for(const [category,context] of [['OTHER','PERSONAL'],['GROCERIES','PERSONAL'],['MAINTENANCE','PROPERTY'],['TRAVEL','FORESTRY'],['UNKNOWN','UNKNOWN']]){
   await save(category,context);const before=await check(category,context);
   await reload();await check(category,context);
   await js("document.body.dataset.loaded='false'");await call('Page.navigate',{url:'about:blank'});await until("location.href==='about:blank'");
   const history=await call('Page.getNavigationHistory');await call('Page.navigateToHistoryEntry',{entryId:history.entries[history.currentIndex-1].id});await check(category,context);
   const stopped=once(server,'exit');server.kill('SIGTERM');await stopped;await start();await reload();const after=await check(category,context);assert.equal(before.audit_event_id,after.audit_event_id);
  }
  await save('OTHER','PERSONAL');
  if(require('node:fs').existsSync(process.env.BROWSER_BASELINE_HTML||'')){
   await call('Page.navigate',{url:url.replace('/pilot/confirmation','/baseline')});
   await until("document.querySelectorAll('article select').length===3");
   assert.deepEqual(await js("[...document.querySelectorAll('article select')].slice(1).map(s=>s.value)"),['UNKNOWN','UNKNOWN']);
   assert.ok(await js("document.body.innerText.includes('CURRENT: category OTHER; context PERSONAL')"));
   console.log('BASELINE_REPRODUCED: backend OTHER/PERSONAL, original dropdowns UNKNOWN/UNKNOWN');
   await call('Page.navigate',{url});await check('OTHER','PERSONAL');
  }
  await js(`(()=>{const a=document.querySelector('article'),s=a.querySelector('[aria-label=Action]');s.value='CHANGE';s.dispatchEvent(new Event('change'));a.querySelector('[aria-label=category]').value='UNKNOWN';a.querySelector('[aria-label="Include category"]').checked=true;a.querySelector('button[type=submit]').click()})()`);
  await until("document.querySelector('[data-message]').textContent.includes('Refresh the current state')");
  await reload();await check('OTHER','PERSONAL');assert.equal(await js("document.querySelector('[aria-label=Action]').value"),'');
  console.log('REAL_BROWSER_PASS: partial/unresolved, four combinations, true UNKNOWN, reload, back navigation, process restart, accidental reset blocked, dirty reset');
 }finally{ws?.close();for(const p of [server,chrome])if(p&&!p.killed){const done=once(p,'exit');p.kill('SIGTERM');await Promise.race([done,sleep(3000)]);}rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
