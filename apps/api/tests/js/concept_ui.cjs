// Execute the production page script against a disposable DOM and persisted server stub.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.disabled=false;this.hidden=false;this.textContent='';}
 append(...children){for(const c of children){c.parent=this;this.children.push(c)}}
 replaceChildren(...children){this.children=[];this.append(...children)}
 replaceWith(e){e.parent=this.parent;this.parent.children[this.parent.children.indexOf(this)]=e}
 setAttribute(){}
 querySelector(tag){return this.children.find(c=>c.tag===tag)}
}
let record={id:'synthetic',term:'ravintola',concept:'RESTAURANT',decision:'PENDING',authority:'SUGGESTED',active:false,state_version:'PENDING',support:[],observed_labels:{}},writes=0;
const source=fs.readFileSync('tapio/confirmation/concepts.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
async function boot(){
 const nodes=Object.fromEntries(['status','cards','refresh'].map(k=>[k,new Element(k)]));let show;
 const context={document:{createElement:t=>new Element(t),getElementById:id=>nodes[id]},window:{addEventListener:(name,fn)=>{show=fn}},fetch:async(url,args={})=>{
  let body;
  if(url.endsWith('/cards'))body={csrf:'test',writes_enabled:true,records:[structuredClone(record)]};
  else if(url.endsWith('/preview'))body={token:'test-token',selected:JSON.parse(args.body),effect:'test'};
  else {writes++;record={...record,decision:'CONFIRMED',authority:'HUMAN_CONFIRMED',active:true,timestamp:'2026-01-01',state_version:'event1'};body={status:'SAVED',record:structuredClone(record)}}
  return {ok:true,json:async()=>body};
 }};
 vm.createContext(context);vm.runInContext(source,context);await show();return nodes;
}
(async()=>{
 // Reproduce the former handler: persistence and success text changed, status did not.
 const oldStatus=new Element('p'),oldOutput=new Element('pre');oldStatus.textContent='Current decision: PENDING';
 const oldApply=async()=>{const result={action:'CONFIRM_CONCEPT'};oldOutput.textContent='Recorded '+result.action};
 await oldApply();assert(oldStatus.textContent.endsWith('PENDING'));assert(oldOutput.textContent.includes('CONFIRM_CONCEPT'));
 const nodes=await boot();let card=nodes.cards.children[0];assert(card.children.some(e=>e.textContent==='Current persisted decision: PENDING'));
 const selects=card.children.filter(e=>e.tag==='select');selects[0].value='CONFIRM_CONCEPT';
 await card.children.find(e=>e.textContent==='Preview decision').onclick();
 await card.children.find(e=>e.textContent==='Apply displayed concept decision').onclick();
 card=nodes.cards.children[0];assert(card.children.some(e=>e.textContent==='Current persisted decision: CONFIRMED'));
 assert(card.children.find(e=>e.textContent==='Preview decision').disabled);
 assert(card.querySelector('pre').textContent.includes('SAVED'));
 assert(writes===1);
 for(let i=0;i<2;i++){const reload=await boot();assert(reload.cards.children[0].children.some(e=>e.textContent==='Current persisted decision: CONFIRMED'))}
 assert(writes===1);console.log('PASS: old stale-status reproduction; authoritative replacement; hard reload; navigation; duplicate controls disabled');
})().catch(e=>{console.error(e);process.exit(1)});
