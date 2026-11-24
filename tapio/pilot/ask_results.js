/* Readable retrieved rows and client-side CSV; never changes source records. */
window.TapioAsk={
 rows(data){
  const details=data.optional_details||{}, records=[...(details.transactions||[]),...(data.supporting_records||[])];
  const seen=new Set();return records.map(r=>({
   date:r.booking_date||r.invoice_date||r.date||r.date_from||'',
   description:r.counterparty||r.vendor||r.subject||r.source||'Record',
   amount:r.amount??r.total_eur??(r.metric?.endsWith('_kwh')?r.total:''),unit:r.metric?.endsWith('_kwh')?'kWh':'',currency:r.currency||(r.total_eur!=null?'EUR':''),
   subtotal_eur:r.subtotal_eur??'',vat_eur:r.vat_eur??'',category:r.category||'',context:r.business_context||'',
   status:r.suggestion||r.authority||r.label_authority||(r.source==='Gmail read-only'?'Email evidence':'Source evidence'),
   check:r.check_next||'',reason:r.reason||'',evidence:JSON.stringify(r.supporting_evidence||[]),vat:r.vat_status||'',source:r.source||'Local bank records',
   reference:r.transaction_id||r.reference||r.id||r.source_file||'',raw:r
  })).filter(r=>{const key=JSON.stringify([r.reference,r.date,r.description,r.amount,r.source]);if(seen.has(key))return false;seen.add(key);return true});
 },
 csv(rows){
  const keys=['date','description','amount','currency','unit','subtotal_eur','vat_eur','category','context','status','reason','evidence','check','vat','source','reference'];
  const escape=(value,key)=>{let s=String(value??'');if(/^[\s]*[=+@-]/.test(s)&&!(['amount','subtotal_eur','vat_eur'].includes(key)&&/^-?\d+(\.\d+)?$/.test(s)))s="'"+s;return '"'+s.replaceAll('"','""')+'"'};
  return '\ufeff'+[keys.join(','),...rows.map(r=>keys.map(k=>escape(r[k],k)).join(','))].join('\r\n')+'\r\n';
 },
 comparison(target,value){
  target.replaceChildren();target.hidden=!value;if(!value)return;
  target.append(Tapio.node('h2','Evidence comparison'));
  const wrap=Tapio.node('div');wrap.className='table-scroll';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Document comparison');
  const table=Tapio.node('table'),head=Tapio.node('thead'),tr=Tapio.node('tr');
  const field=Tapio.node('th','Field');field.scope='col';tr.append(field);
  for(const doc of value.documents){const th=Tapio.node('th');th.scope='col';th.append(Tapio.node('strong','Document '+doc.label),Tapio.node('p',doc.filename));tr.append(th)}
  head.append(tr);table.append(head);const body=Tapio.node('tbody');
  for(const row of value.fields){const r=Tapio.node('tr'),th=Tapio.node('th',row.field);th.scope='row';r.append(th,Tapio.node('td',row.a||'Not extracted'),Tapio.node('td',row.b||'Not extracted'));body.append(r)}
  table.append(body);wrap.append(table);target.append(wrap);
  for(const [key,title] of [['differences','Differences'],['documented_facts','Documented facts'],['reasonable_inference','Reasonable inference'],['unresolved_points','Unresolved points']]){
   target.append(Tapio.node('h3',title));const values=value[key]||[];
   if(!values.length){target.append(Tapio.node('p',key==='reasonable_inference'?'No additional inference supported.':key==='unresolved_points'?'No missing comparison fields identified.':'No additional findings from the extracted fields.'));continue}
   const ul=Tapio.node('ul');for(const text of values)ul.append(Tapio.node('li',text));target.append(ul);
  }
 },
 render(target,rows){
  target.replaceChildren();const wrap=Tapio.node('div');wrap.className='table-scroll ask-result-table';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Retrieved result records');
  const table=Tapio.node('table'),head=Tapio.node('thead'),h=Tapio.node('tr');
  for(const label of ['Date','Description / evidence','Amount / quantity','Status / next check']){const th=Tapio.node('th',label);th.scope='col';h.append(th)}head.append(h);table.append(head);
  const body=Tapio.node('tbody');for(const row of rows.slice(0,50)){
   const tr=Tapio.node('tr');tr.append(Tapio.node('td',row.date||'Not recorded'));
   const desc=Tapio.node('td');desc.append(Tapio.node('strong',row.description));
   const detail=Tapio.node('details');detail.append(Tapio.node('summary','Evidence'));const content=Tapio.node('div');Tapio.show(content,row.raw);detail.append(content);desc.append(detail);tr.append(desc);
   const amount=Tapio.node('td',row.amount===''?'Not recorded':Tapio.amount(row.amount)+' '+(row.currency||row.unit));amount.className='num';tr.append(amount);
   const status=Tapio.node('td');status.append(Tapio.node('p',row.status));if(row.context||row.category)status.append(Tapio.node('p',[row.context,row.category].filter(Boolean).map(Tapio.label).join(' · ')));if(row.reason)status.append(Tapio.node('p',row.reason));if(row.check)status.append(Tapio.node('p',row.check));tr.append(status);body.append(tr);
  }table.append(body);wrap.append(table);target.append(wrap);
 }
};
