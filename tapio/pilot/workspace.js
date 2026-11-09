
window.Tapio={
 amount(value){return String(value).replace(/(\.\d{2}\d*?)0+$/,'$1')},
 label(value){if(value===null||value===undefined||value==='')return 'Unresolved';return String(value).replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase())},
 node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n},
 value(value){
  if(value===null||value===undefined)return this.node('span','Not available');
  if(Array.isArray(value)){const box=this.node('div');if(!value.length)box.append(this.node('p','None recorded'));for(const item of value){const row=this.node('div');row.className='evidence-item';row.append(this.value(item));box.append(row)}return box}
  if(typeof value==='object'){const dl=this.node('dl');dl.className='record-fields';for(const [key,item] of Object.entries(value)){if(item===undefined)continue;dl.append(this.node('dt',this.label(key)));const dd=this.node('dd');dd.append(this.value(item));dl.append(dd)}return dl}
  return this.node('span',typeof value==='boolean'?(value?'Yes':'No'):String(value));
 },
 show(target,value){target.replaceChildren(this.value(value))},
 fields(parent,rows,suggestionTitle="Proposed"){const wrap=this.node('div');wrap.className='table-scroll';const table=this.node('table');const head=this.node('thead'),tr=this.node('tr');for(const title of ['Field','Current decision',suggestionTitle]){const th=this.node('th',title);th.scope='col';tr.append(th)}head.append(tr);table.append(head);const body=this.node('tbody');for(const row of rows){const tr=this.node('tr');for(const item of row)tr.append(this.node('td',this.label(item)));body.append(tr)}table.append(body);wrap.append(table);parent.append(wrap)},
 changes(parent,changes){parent.replaceChildren();this.fields(parent,Object.entries(changes||{}).map(([field,v])=>[field,v.old,v.new]));if(!Object.keys(changes||{}).length)parent.append(this.node('p','No classification changes.'));},
 preview(parent,changes,unchanged=[]){this.changes(parent,changes);if(unchanged.length)parent.append(this.node('p','Unchanged: '+unchanged.map(v=>this.label(v)).join(', ')));},
 error(message){const text=String(message||'');if(/^[A-Z_0-9 :.-]+$/.test(text))return 'This action could not be completed. Refresh the current state and preview your selection again.';return text}
};

document.addEventListener('DOMContentLoaded',()=>{for(const link of document.querySelectorAll('.review-nav a'))if(link.pathname===location.pathname)link.setAttribute('aria-current','page')});
