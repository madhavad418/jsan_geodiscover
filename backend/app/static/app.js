const $=(s,r=document)=>r.querySelector(s);const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const state={token:localStorage.getItem('gd_token'),user:null,projects:[],project:null,summary:null,sample:[],map:null,cityId:Number(localStorage.getItem('gd_city'))||null,cities:[]};
/* One city filter shared by every view. `null` means all cities. */
const cityQuery=(sep='?')=>state.cityId?`${sep}city_id=${state.cityId}`:'';
function cityStrip(){
  if(!state.cities.length)return '';
  const total=state.cities.reduce((a,c)=>a+(c.records||0),0);
  return `<div class="city-strip">
    <button class="city-chip${state.cityId?'':' active'}" onclick="setCity(0)">All cities<span>${total}</span></button>
    ${state.cities.map(c=>`<button class="city-chip${state.cityId===c.id?' active':''}" onclick="setCity(${c.id})" title="${esc(c.basis==='BENCHMARK_STUDY'?'Benchmark study':'Uploaded workbook')}">${esc(c.name)}<span>${c.records||0}</span></button>`).join('')}
    <a class="button small outline city-add" href="#scraping">+ Add a city</a>
  </div>`;
}
function basisNote(d){
  if(!d||!d.basis)return '';
  const label=d.basis_label||'';
  return `<div class="basis-note">${tag(d.basis.replace(/_/g,' '),d.basis==='BENCHMARK_STUDY'?'green':d.basis==='PORTFOLIO'?'blue':'amber')}<span>${esc(label)}${d.note?` — ${esc(d.note)}`:''}</span></div>`;
}
window.setCity=function(id){
  state.cityId=id?Number(id):null;
  if(state.cityId)localStorage.setItem('gd_city',state.cityId);else localStorage.removeItem('gd_city');
  state.summary=null;VL.cityId=state.cityId;VL.filters={search:'',provider:'',status:''};
  route();
};
function toast(message){const n=document.createElement('div');n.className='toast';n.textContent=message;$('#toastRoot').appendChild(n);setTimeout(()=>n.remove(),3500)}
async function api(path,options={},raw=false){const headers={...(options.headers||{})};if(state.token)headers.Authorization=`Bearer ${state.token}`;if(options.body&&!(options.body instanceof FormData)&&!headers['Content-Type'])headers['Content-Type']='application/json';const res=await fetch(`/api/v1${path}`,{...options,headers});if(res.status===401){logout();throw new Error('Session expired. Please sign in again.')}if(!res.ok){let e;try{e=await res.json()}catch{e=await res.text()}throw new Error(e.detail||e.message||String(e))}if(raw)return res;return res.status===204?null:res.json()}
function pageHead(title,text,actions=''){return `<div class="page-head"><div><h2>${esc(title)}</h2><p>${esc(text)}</p></div><div class="head-actions">${actions}</div></div>`}
function tag(text,type='gray'){return `<span class="tag ${type}">${esc(text)}</span>`}
function metric(label,value,note,primary=false){return `<div class="metric ${primary?'primary':''}"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`}
function demoStrip(s){return `<div class="demo-strip"><div><strong>${esc(s.study.customer)}</strong><span>${esc(s.study.geography)} · Source: ${esc(s.study.source_workbook)}</span></div>${tag('DEMONSTRATION EVIDENCE','green')}</div>`}
async function login(e){e.preventDefault();$('#loginError').innerHTML='';try{const d=await api('/auth/login',{method:'POST',body:JSON.stringify({email:$('#email').value,password:$('#password').value})});state.token=d.access_token;state.user=d.user;localStorage.setItem('gd_token',state.token);await enterApp()}catch(err){$('#loginError').innerHTML=`<div class="alert error">${esc(err.message)}</div>`}}
function logout(){localStorage.removeItem('gd_token');Object.assign(state,{token:null,user:null,projects:[],project:null,summary:null,sample:[]});$('#appView').classList.add('hidden');$('#loginView').classList.remove('hidden')}
async function enterApp(){if(!state.user)state.user=await api('/auth/me');state.projects=await api('/projects');state.project=state.projects[0];if(!state.project)throw new Error('No customer demo project is available. Run bootstrap.py.');$('#userName').textContent=state.user.full_name;$('#userRole').textContent=state.user.role.replaceAll('_',' ');
try{state.cities=(await api(`/cities/${state.project.id}`)).cities.map(c=>({id:c.id,name:c.name,region:c.region,records:c.total_records}))}catch{state.cities=[]}
if(state.cityId&&!state.cities.some(c=>c.id===state.cityId)){state.cityId=null;localStorage.removeItem('gd_city')}
$('#loginView').classList.add('hidden');$('#appView').classList.remove('hidden');route()}
async function getSummary(){
  if(!state.summary)state.summary=await api(`/executive/${state.project.id}/summary${cityQuery()}`);
  if(state.summary.cities)state.cities=state.summary.cities;
  return state.summary;
}
/* Metrics can be genuinely unavailable for a city with no comparison run. */
const num=v=>v===null||v===undefined?'—':v;

async function overview(){const [s,cost]=await Promise.all([getSummary(),api(`/costs/denpasar?project_id=${state.project.id}${cityQuery('&')}`)]);const h=s.study.headline,c=s.study.coverage;$('#content').innerHTML=`
${pageHead('Executive Overview',`What the current ${esc(s.study.geography)} programme proves, what remains to validate, and the customer decision it supports.`,`<a class="button outline" href="#comparison">See proof</a><a class="button primary" href="#sample">Open priority sample</a>`)}
${cityStrip()}${basisNote(s)}
${demoStrip(s)}
<div class="hero"><div><p class="eyebrow inverse">CURRENT POC OUTCOME</p><h2>${s.comparison_available?`${num(h.grab_inventory)} Grab POIs compared against ${num(h.google_inventory)} Google POIs`:`${num(h.records_total)} businesses loaded for ${esc(s.study.geography)}`}</h2><p>${esc(s.story.customer_message)}</p></div><div class="hero-number"><strong>${num(h.tier1_direct_probe_candidates)}</strong><span>PRIORITY DIRECT-PROBE CANDIDATES</span></div></div>
<div class="metrics">${metric('Matched pairs',num(h.total_matched_pairs),s.comparison_available?`${num(h.sweep_matches)} sweep + ${num(h.probe_recovered_matches)} recovered`:'No comparison run for this city')}${metric('Tier 1 candidates',num(h.tier1_direct_probe_candidates),'Direct reciprocal probe evidence',true)}${metric('Tier 2 leads',num(h.tier2_area_supported_leads),'Area-supported; direct probe pending')}${metric('Possible pairings',num(h.possible_pairings),s.comparison_available?'Held for entity-resolution review':'Needs a comparison run')}${metric('Grab unresolved',num(h.grab_unresolved),'Excluded from gap counts')}${metric('Google unresolved',num(h.google_unresolved),'Excluded from gap counts')}${metric('Contactability',`${num(h.contactability_pct)}%`,'Enrichment is the next workstream')}${metric('Customer release',num(h.customer_release_ready),'Correctly blocked until QA')}</div>
<div class="panel"><div class="panel-title"><h3>One customer story</h3>${tag('SIMPLE 5-STEP FLOW','blue')}</div><div class="flow"><div class="flow-step"><b>01</b><strong>Collect</strong><span>Authorised Grab and Google extracts</span></div><div class="flow-step"><b>02</b><strong>Compare</strong><span>${s.comparison_available?'Name, address and coordinate signals':'Comparison run not yet done for this city'}</span></div><div class="flow-step"><b>03</b><strong>Prioritise</strong><span>${num(h.tier1_direct_probe_candidates)} direct-probe candidates</span></div><div class="flow-step"><b>04</b><strong>Validate</strong><span>Contact, activity, 16 checks and QA</span></div><div class="flow-step"><b>05</b><strong>Release</strong><span>Only approved Gold/Silver records</span></div></div></div>
<div class="grid-2"><div class="panel"><h3>What the POC proves today</h3><div class="guardrails">${s.story.current_scope.map(x=>`<div class="guardrail pass"><span>${esc(x)}</span><b>PROVEN</b></div>`).join('')}</div></div><div class="panel"><h3>What we do not claim today</h3><div class="guardrails">${s.story.not_claimed_today.map(x=>`<div class="guardrail block"><span>${esc(x)}</span><b>BLOCKED</b></div>`).join('')}</div></div></div>
<div class="grid-2"><div class="panel"><h3>Coverage context</h3>${c?`<div class="cost-list"><div class="cost-row"><span>Grab tiles completed</span><b>${c.grab_tiles_done}/${c.grab_tiles_planned}</b></div><div class="cost-row"><span>Google tiles completed</span><b>${c.google_tiles_done}/${c.google_tiles_planned}</b></div><div class="cost-row"><span>Google run status</span><b>BUDGET-LIMITED</b></div></div><p>${esc(c.coverage_statement)}</p>`
:`<div class="cost-list"><div class="cost-row"><span>Businesses loaded</span><b>${num(h.records_total)}</b></div><div class="cost-row"><span>Validated</span><b>${num(h.validation_completed)}</b></div><div class="cost-row"><span>Scraped</span><b>${num(h.scraped_records)}</b></div></div><p>No tiled discovery sweep has been run for ${esc(s.study.geography)}. These figures come from the uploaded workbook and the validation work done on it so far.</p>`}</div><div class="panel"><h3>Decision requested from customer</h3><p>Approve a focused Strong 10/25 validation sprint. JSAN will enrich contact and activity evidence, complete the full Google-exclusion checklist, run independent QA and return a release-ready sample.</p><a class="button primary" href="#pack">Review customer pack</a></div></div>`}

async function comparison(){const [s,p]=await Promise.all([getSummary(),api(`/executive/${state.project.id}/comparison-proof?limit=10${cityQuery('&')}`)]);const h=s.study.headline;
const parts=[h.total_matched_pairs,h.tier1_direct_probe_candidates,h.tier2_area_supported_leads,h.possible_pairings].map(v=>v||0);const total=parts.reduce((a,b)=>a+b,0)||1;
$('#content').innerHTML=`
${pageHead('Comparison Proof','Explainable Grab-versus-Google results without overstating unverified candidates.',`<a class="button outline" href="#map">View map</a>`)}
${cityStrip()}${basisNote(p)}${demoStrip(s)}
${p.comparison_available?'':`<div class="alert warning"><strong>No comparison run for ${esc(s.study.geography)}.</strong> This city was loaded from a workbook, so there are no scored Grab-versus-Google pairs to show. The tier counts below come from the evidence method recorded on each row.</div>`}
<div class="metrics">${metric('Confirmed matches',num(h.total_matched_pairs),p.comparison_available?'Cross-provider relationships':'Comparison run required')}${metric('Tier 1 direct probe',num(h.tier1_direct_probe_candidates),'Priority validation queue',true)}${metric('Tier 2 area support',num(h.tier2_area_supported_leads),'Lead queue; probe required')}${metric('Possible pairings',num(h.possible_pairings),p.comparison_available?'Manual review queue':'Comparison run required')}</div>
<div class="panel"><h3>Outcome mix</h3><div class="funnel">${parts[0]?`<div class="matched" style="width:${parts[0]/total*100}%">${parts[0]}</div>`:''}${parts[1]?`<div class="tier1" style="width:${parts[1]/total*100}%">${parts[1]}</div>`:''}${parts[2]?`<div class="tier2" style="width:${parts[2]/total*100}%">${parts[2]}</div>`:''}${parts[3]?`<div class="review" style="width:${parts[3]/total*100}%">${parts[3]}</div>`:''}</div><div class="legend"><span><i style="background:#2a6c9e"></i>Matched</span><span><i style="background:#13835d"></i>Tier 1</span><span><i style="background:#b97816"></i>Tier 2</span><span><i style="background:#7d8c95"></i>Possible pairings</span></div></div>
<div class="panel" style="margin-top:14px"><div class="panel-title"><h3>Highest-confidence match examples</h3>${tag('EXPLAINABLE SIGNALS','blue')}</div>${p.rows.length?`<div class="table-shell"><table class="table"><thead><tr><th>Grab vs Google</th><th>Score</th><th>Distance</th><th>Method</th><th>Decision</th></tr></thead><tbody>${p.rows.map(r=>`<tr><td><div class="compare-pair"><div class="poi"><strong>${esc(r.grab.name)}</strong><span>${esc(r.grab.address)}</span></div><div class="pair-arrow">↔</div><div class="poi"><strong>${esc(r.google.name)}</strong><span>${esc(r.google.address)}</span></div></div></td><td><span class="score-pill">${Number(r.match_score||0).toFixed(1)}</span></td><td>${r.distance_m==null?'—':`${Number(r.distance_m).toFixed(0)} m`}</td><td>${esc(r.method||'Weighted comparison')}</td><td>${tag(r.kind||'MATCHED','green')}</td></tr>`).join('')}</tbody></table></div>`:`<p class="muted">No scored pairs for this city. Run a Grab-versus-Google comparison to populate this table.</p>`}</div>
<div class="grid-3"><div class="panel"><h3>Name signal</h3><p>Normalised business names and alternate spelling evidence.</p></div><div class="panel"><h3>Location signal</h3><p>Address similarity and coordinate distance prevent false matches.</p></div><div class="panel"><h3>Review control</h3><p>Possible and unresolved results stay outside the incremental claim.</p></div></div>`}

async function sample(){const [s,d]=await Promise.all([getSummary(),api(`/executive/${state.project.id}/sample?limit=10${cityQuery('&')}`)]);state.sample=d.records;$('#content').innerHTML=`
${pageHead('Priority Sample',`The strongest ${d.count} records from the ${d.available_tier1} Tier-1 direct-probe candidates in ${esc(s.study.geography)}. These are validation candidates—not released POIs.`,`<button class="button outline" onclick="downloadPack()">Download customer workbook</button>`)}
${cityStrip()}${demoStrip(s)}
${d.records.length?'':`<div class="alert info">No Tier-1 direct-probe candidates in ${esc(s.study.geography)} yet. Rows qualify once a direct probe has been recorded against them.</div>`}
<div class="alert warning"><strong>Customer-safe status:</strong> ${esc(d.guardrail)} Each record still needs category confirmation, active contact, recent activity, complete Google exclusion and independent QA.</div>
<div class="sample-grid">${d.records.map(r=>`<article class="sample-card" onclick="openSample(${r.rank})"><div class="sample-head"><div class="rank">${r.rank}</div><div class="sample-name"><strong>${esc(r.business_name)}</strong><span>${esc(r.address)}</span></div>${tag('TIER 1','green')}</div><p>${esc(r.evidence_reason||'Direct-probe evidence retained.')}</p><div class="readiness" title="Discovery evidence complete; validation gates pending"><span class="done"></span><span></span><span></span><span></span><span></span></div><div class="sample-footer"><span>Discovery evidence complete · 4 validation gates pending</span><b>View evidence →</b></div></article>`).join('')}</div>
<div class="grid-2"><div class="panel"><h3>Strong 10 objective</h3><p>Produce a compact sample in which every record has a confirmed salon category, precise coordinates, active contact, recent activity, full Google-exclusion evidence and independent QA.</p></div><div class="panel"><h3>Strong 25 scale-up</h3><p>Use the same evidence standard across 25 records after the customer confirms the preferred category and release format.</p></div></div>`}
window.openSample=function(rank){const r=state.sample.find(x=>x.rank===rank);if(!r)return;$('#modalRoot').innerHTML=`<div class="modal-backdrop" onclick="if(event.target===this)closeModal()"><div class="modal"><div class="modal-head"><div><p class="eyebrow">PRIORITY VALIDATION CANDIDATE #${r.rank}</p><h2>${esc(r.business_name)}</h2>${tag('NOT YET CUSTOMER READY','amber')}</div><button class="modal-close" onclick="closeModal()">×</button></div><div class="modal-body"><div class="detail-grid"><div class="detail"><label>Address</label><strong>${esc(r.address)}</strong></div><div class="detail"><label>Coordinates</label><strong>${r.latitude}, ${r.longitude}</strong></div><div class="detail"><label>Evidence method</label><strong>${esc(r.evidence_method)}</strong></div><div class="detail"><label>Best Google-side score</label><strong>${r.best_score??'No comparable result'}</strong></div><div class="detail"><label>Probe query</label><strong>${esc(r.probe_query||'Retained in source evidence')}</strong></div><div class="detail"><label>Current status</label><strong>${esc(r.current_status)}</strong></div></div><div class="alert info"><strong>Evidence reason:</strong> ${esc(r.evidence_reason)}</div><h3>Required before customer release</h3><ol class="action-list">${r.next_actions.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div></div></div>`};window.closeModal=()=>$('#modalRoot').innerHTML='';

async function mapView(){const s=await getSummary();$('#content').innerHTML=`${pageHead('Coverage Map',`A clean geographic view of ${esc(s.study.geography)} — matched POIs and the incremental evidence tiers.`,`<a class="button outline" href="#sample">Open sample</a>`)}${cityStrip()}${demoStrip(s)}<div class="map-controls"><button data-layer="current" class="active">All current evidence</button><button data-layer="matched">Matched</button><button data-layer="tier1">Tier 1</button><button data-layer="tier2">Tier 2</button></div><div class="map-wrap"><div id="map" class="map-canvas"></div><div class="map-legend"><span><i style="background:#2a6c9e"></i>Matched</span><span><i style="background:#13835d"></i>Tier 1</span><span><i style="background:#b97816"></i>Tier 2</span><span><i style="background:#7d8c95"></i>Not probed</span></div></div>`;$$('[data-layer]').forEach(b=>b.onclick=()=>{$$('[data-layer]').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderMap(b.dataset.layer)});renderMap('current')}
async function renderMap(layer){const data=await api(`/executive/${state.project.id}/map.geojson?layer=${layer}${cityQuery('&')}`);if(state.map){state.map.remove();state.map=null}if(typeof maplibregl==='undefined'){$('#map').innerHTML='<div class="map-fallback"><div><strong>Map library could not load.</strong><p>Connect to the internet to display the basemap. Coordinates remain available in the workbook.</p></div></div>';return}state.map=new maplibregl.Map({container:'map',center:[115.215,-8.65],zoom:11.5,style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]}});state.map.addControl(new maplibregl.NavigationControl(),'top-right');state.map.on('load',()=>{state.map.addSource('points',{type:'geojson',data,cluster:true,clusterRadius:42});state.map.addLayer({id:'clusters',type:'circle',source:'points',filter:['has','point_count'],paint:{'circle-color':'#173f5d','circle-radius':['step',['get','point_count'],15,20,20,80,26]}});state.map.addLayer({id:'cluster-label',type:'symbol',source:'points',filter:['has','point_count'],layout:{'text-field':['get','point_count_abbreviated'],'text-size':10},paint:{'text-color':'#fff'}});state.map.addLayer({id:'points',type:'circle',source:'points',filter:['!', ['has','point_count']],paint:{'circle-radius':6.5,'circle-stroke-color':'#fff','circle-stroke-width':1.5,'circle-color':['match',['get','layer'],'MATCHED','#2a6c9e','TIER 1 · DIRECT PROBE','#13835d','TIER 2 · AREA SUPPORTED','#b97816','#7d8c95']}});state.map.on('click','points',e=>{const p=e.features[0].properties;new maplibregl.Popup().setLngLat(e.features[0].geometry.coordinates).setHTML(`<strong>${esc(p.business_name)}</strong><br><small>${esc(p.address||'')}</small>${p.city?`<br><small>${esc(p.city)}</small>`:''}<br><br>${tag(p.layer,p.layer.startsWith('TIER 1')?'green':p.layer==='MATCHED'?'blue':p.layer==='NOT PROBED'?'gray':'amber')}`).addTo(state.map)});if(data.features.length){const bounds=new maplibregl.LngLatBounds();data.features.forEach(f=>bounds.extend(f.geometry.coordinates));state.map.fitBounds(bounds,{padding:48,maxZoom:13})}})}

async function cost(){const [s,d]=await Promise.all([getSummary(),api(`/costs/denpasar?project_id=${state.project.id}${cityQuery('&')}`)]);const a=d.actual_run,p=d.strong_25_plan,f=d.full_city_plan,m=v=>`$${Number(v||0).toFixed(2)}`;$('#content').innerHTML=`
${pageHead('Cost & Scale',`A simple cost story for ${esc(s.study.geography)}: provider API consumption is small; research, evidence and QA create the customer value.`)}
${cityStrip()}${demoStrip(s)}
${d.actual_run_available?'':`<div class="alert info">No discovery run has been recorded for ${esc(s.study.geography)}. The plans below are scaled from the ${d.records_in_scope} records loaded for it.</div>`}
<div class="cost-band"><div class="cost-card"><span class="cost-label">${d.actual_run_available?'Actual Google usage':'Recorded Google usage'}</span><strong>${a.google_nearby_calls} calls</strong><p>${d.actual_run_available?'Recorded Nearby Search Pro requests in the benchmark run.':'No discovery run recorded for this city yet.'}</p></div><div class="cost-card featured"><span class="cost-label">Gross list estimate</span><strong>${m(a.google_global_list_cost)}</strong><p>Global list-rate equivalent before applicable free usage, credits and account aggregation.</p></div><div class="cost-card"><span class="cost-label">Full city API estimate</span><strong>${m(f.global_list_cost)}</strong><p>Indicative Google consumption to work all ${d.records_in_scope} records. Grab/AWS and social costs remain account-specific.</p></div></div>
<div class="grid-2"><div class="panel"><h3>Strong 25 effort plan</h3><div class="cost-list"><div class="cost-row"><span>Google Text Search</span><b>${p.google_text_search_calls} calls</b></div><div class="cost-row"><span>Google Place Details</span><b>${p.google_place_detail_calls} calls</b></div><div class="cost-row"><span>Research and enrichment</span><b>${p.research_hours} hours</b></div><div class="cost-row"><span>Independent QA</span><b>${p.qa_hours} hours</b></div><div class="cost-row"><span>PM and packaging</span><b>Enter JSAN rate card</b></div></div><h4 style="margin-top:14px">Full ${esc(s.study.geography.split(',')[0])} plan (${d.records_in_scope} records)</h4><div class="cost-list"><div class="cost-row"><span>Research and enrichment</span><b>${f.research_hours} hours</b></div><div class="cost-row"><span>Independent QA</span><b>${f.qa_hours} hours</b></div></div></div><div class="panel"><h3>Commercial message</h3><p>The customer is not buying API calls. The customer is buying incremental POIs that are researched, evidenced, independently reviewed and safe to use.</p><div class="alert info">Final customer pricing = provider consumption + research/enrichment + QA + PM/evidence packaging + contingency and margin.</div></div></div>
<div class="grid-3"><div class="panel"><h3>Current sample</h3><p>Technology cost is controlled by call caps, field masks and a defined geography.</p></div><div class="panel"><h3>Five-city pilot</h3><p>Scale the same method after the Strong 10/25 quality standard is accepted.</p></div><div class="panel"><h3>National programme</h3><p>Move to scheduled discovery, production infrastructure and negotiated provider pricing.</p></div></div>`}

async function pack(){const s=await getSummary();const bench=!!s.bundled_pack;$('#content').innerHTML=`${pageHead('Customer Pack',`The concise material to use in today’s customer discussion for ${esc(s.study.geography)}. Detailed operational modules remain internal.`,`<button class="button primary" onclick="downloadPack()">Download executive workbook</button>`)}
${cityStrip()}${basisNote(s)}${demoStrip(s)}
<div class="pack-hero"><div><p class="eyebrow">RECOMMENDED CUSTOMER ARTEFACT</p><h3>${bench?'GeoDiscover Executive Customer Sample v5':`GeoDiscover Customer Pack — ${esc(s.study.geography.split(',')[0])}`}</h3><p>${bench?'Five easy-to-read sheets: executive summary, Strong 10, Strong 25 work queue, cost and scale, and methodology/limitations.':'Generated from this city’s current data: executive summary, priority candidates, the full work queue, and method and limitations.'}</p></div><button class="button primary" onclick="downloadPack()">Download XLSX</button></div>
<div class="grid-2"><div class="panel"><h3>What is included</h3><div class="deliverable-list"><div class="deliverable"><b>1</b><div><strong>Executive Summary</strong><span>Current metrics, safe claim and customer decision</span></div></div><div class="deliverable"><b>2</b><div><strong>Strong 10 Preview</strong><span>Priority validation candidates with evidence reasons</span></div></div><div class="deliverable"><b>3</b><div><strong>Strong 25 Work Queue</strong><span>Owner, validation status and release gates</span></div></div><div class="deliverable"><b>4</b><div><strong>Cost & Scale</strong><span>API consumption, human effort and commercial formula</span></div></div><div class="deliverable"><b>5</b><div><strong>Method & Limitations</strong><span>Coverage context and claim controls</span></div></div></div></div><div class="panel"><h3>What to say</h3><div class="alert info">“JSAN compared 400 Grab POIs with 562 Google POIs, identified 53 matched pairs and created a priority queue of 39 direct-probe candidates. We are seeking approval to take the strongest 10–25 through enrichment, full Google exclusion and independent QA.”</div><h3>What not to say</h3><div class="alert error">“JSAN has already confirmed 178 active salons absent from Google.”</div></div></div>
<div class="panel"><h3>Release gate</h3><div class="flow"><div class="flow-step"><b>1</b><strong>Category</strong><span>Customer-approved salon scope</span></div><div class="flow-step"><b>2</b><strong>Contact</strong><span>Phone, WhatsApp, web or social</span></div><div class="flow-step"><b>3</b><strong>Activity</strong><span>Recent operational evidence</span></div><div class="flow-step"><b>4</b><strong>Google exclusion</strong><span>All 16 checks completed</span></div><div class="flow-step"><b>5</b><strong>Independent QA</strong><span>Maker-checker approval</span></div></div></div>`}
window.downloadPack=async function(){try{
  const res=await api(`/executive/${state.project.id}/download/customer-pack${cityQuery()}`,{},true);
  const cd=res.headers.get('content-disposition')||'';
  const name=(cd.match(/filename="?([^"]+)"?/)||[])[1]||'GeoDiscover_Executive_Customer_Sample_v5.xlsx';
  const blob=await res.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);toast(`${name} downloaded`)
}catch(e){toast(e.message)}};

window.downloadCityValidation=async function(cityId){try{
  const city=(state.cities||[]).find(c=>c.id===cityId)||(SCR.cities||[]).find(c=>c.id===cityId);
  const res=await api(`/validation/${state.project.id}/cities/${cityId}/xlsx`,{},true);
  const cd=res.headers.get('content-disposition')||'';
  const name=(cd.match(/filename="?([^";]+)"?/)||[])[1]||`GeoDiscover_${city&&city.name?city.name:'City'}_Validation.xlsx`;
  const blob=await res.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);toast(`${name} downloaded`)
}catch(e){toast(e.message)}};

async function future(){const [s,d]=await Promise.all([getSummary(),api(`/executive/${state.project.id}/future-modules`)]);const list=x=>`<ul>${x.map(v=>`<li>${esc(v)}</li>`).join('')}</ul>`;$('#content').innerHTML=`${pageHead('Future Scale','A clear separation between what is demonstrated now and what is activated after customer alignment.')}${demoStrip(s)}<div class="roadmap"><div class="roadmap-stage current"><p class="eyebrow">NOW</p><h3>Customer capability demonstration</h3>${list(d.current_demo)}</div><div class="roadmap-stage next"><p class="eyebrow">NEXT</p><h3>Strong 10/25 validation sprint</h3>${list(d.phase_2_after_customer_alignment)}</div><div class="roadmap-stage future"><p class="eyebrow">LATER</p><h3>Production and national scale</h3>${list(d.future_scale)}</div></div><div class="panel" style="margin-top:14px"><h3>Recommended sequencing</h3><p>Do not add more customer-facing modules before the Strong 10/25 sample is approved. First prove a small number of records deeply; then scale geography, sources and automation.</p></div>`}

/* ---------- Validation Layer ---------- */
const VL={schema:null,mode:'validation',jobId:null,job:null,cities:[],cityId:null,records:[],summary:{},providers:[],file:null,total:0,filters:{search:'',provider:'',status:''},editing:null,draft:{},error:''};
const vlRecord=id=>VL.records.find(r=>r.id===id);
/* A validator may record a presence ("Yes") or a note instead of a URL, so only
   real links become anchors. */
const vlLink=v=>{
  if(!v)return '<span class="vl-empty">—</span>';
  if(!/^https?:\/\//i.test(v))return vlCell(v);
  const shown=v.replace(/^https?:\/\//,'');
  return `<a href="${esc(v)}" target="_blank" rel="noopener" title="${esc(v)}">${esc(shown.slice(0,28))}${shown.length>28?'…':''}</a>`;
};
const vlCell=v=>{const t=v===null||v===undefined||v===''?'':String(v);return t?`<span title="${esc(t)}">${esc(t.length>42?t.slice(0,42)+'…':t)}</span>`:'<span class="vl-empty">—</span>'};
function vlCheckCell(r,f){const v=r[f.key];const link=r[f.link_key];
  if(v==='YES')return `<div class="vl-check"><span class="tag green">YES</span>${link?vlLink(link):'<span class="vl-empty">no link</span>'}</div>`;
  if(v==='NO')return '<span class="tag gray">NO</span>';
  return '<span class="vl-empty">Not answered</span>'}

async function validation(){
  if(!VL.schema)VL.schema=await api('/validation/schema');
  VL.cityId=state.cityId;
  const d=await api(`/validation/${state.project.id}/records${cityQuery()}`);
  if(d.cities)state.cities=d.cities.map(c=>({...c,basis:(state.cities.find(x=>x.id===c.id)||{}).basis}));
  Object.assign(VL,{mode:'validation',jobId:null,job:null,cities:d.cities,records:d.records,summary:d.summary,providers:d.providers,file:d.source_file,total:d.total,editing:null,draft:{},error:''});
  renderValidation();
}
window.vlCity=id=>setCity(id);
async function scrapeData(jobId){
  if(!VL.schema)VL.schema=await api('/validation/schema');
  const id=jobId||VL.jobId||SCR.lastJobId;
  if(!id){$('#content').innerHTML=`${pageHead('Scrape Data','Processed city results.')}<div class="alert info">No scrape run selected yet. Add a city under <a href="#scraping">Cities &amp; Scraping</a>, choose <strong>Scrape city</strong>, then <strong>View</strong>.</div>`;return}
  const d=await api(`/scraping/jobs/${id}/records`);
  Object.assign(VL,{mode:'scrape',jobId:id,job:d.job,records:d.records,summary:d.summary,providers:d.providers,file:d.source_file,total:d.total,editing:null,draft:{},error:''});
  SCR.lastJobId=id;
  renderValidation();
}
function vlFiltered(){const f=VL.filters,t=f.search.trim().toLowerCase();
  return VL.records.filter(r=>{
    if(f.provider&&r.provider!==f.provider)return false;
    if(f.status&&r.validation_status!==f.status)return false;
    if(t&&!`${r.business_name||''} ${r.address||''} ${r.provider_place_id||''}`.toLowerCase().includes(t))return false;
    return true});
}
function renderValidation(){
  const s=VL.schema,rows=vlFiltered(),sum=VL.summary,scrape=VL.mode==='scrape';
  const cols=1+s.source_fields.length+s.check_fields.length+s.link_fields.length+s.text_fields.length+2+(scrape?1:0);
  const opt=(v,cur,label)=>`<option value="${esc(v)}"${cur===v?' selected':''}>${esc(label)}</option>`;
  const j=VL.job;
  $('#content').innerHTML=`
${scrape
  ?pageHead('Scrape Data',`Processed results for ${VL.file||'the uploaded workbook'}. Columns the providers could prove are filled in; everything else is left empty with the reason recorded. Edit and save exactly as in the validation layer.`,`<a class="button outline" href="#scraping">Back to jobs</a>`)
  :pageHead('Validation Layer','Every city’s workbook in one editable layer. Pick a city to work through it on its own, or stay on All cities to see the whole programme. Mark each directory presence Yes or No, attach the supporting link, and save the row in place.',`${VL.cityId?`<button class="button primary" onclick="downloadCityValidation(${VL.cityId})">Download updated XLSX</button>`:''}<a class="button outline" href="#scraping">Manage cities</a>`)}
${scrape
  ?`<div class="demo-strip"><div><strong>${esc((j&&j.city)||VL.file||'—')}</strong><span>Job #${j?j.id:'—'} · ${VL.total} records · ${j?j.fields_filled:0} column values filled across ${j?j.records_with_findings:0} records</span></div>${tag(j?j.status:'—',j&&j.status==='COMPLETED'?'green':'amber')}</div>`
  :cityStrip()}
<div class="metrics">${metric(scrape?'Records in this city':'Records in view',VL.total,scrape?'Rows processed for this city':VL.cityId?`Rows loaded for ${esc((VL.cities.find(c=>c.id===VL.cityId)||{}).name||'this city')}`:`Across ${VL.cities.length} cit${VL.cities.length===1?'y':'ies'}`)}${metric('Completed',sum.COMPLETED||0,'All six presence checks answered',true)}${metric('In progress',sum.IN_PROGRESS||0,'Partly answered; finish the remaining checks')}${metric('Not started',sum.PENDING||0,'No presence check answered yet')}</div>
<div class="vl-toolbar">
  <input id="vlSearch" class="vl-search" type="search" placeholder="Search business name, address or place ID" value="${esc(VL.filters.search)}">
  <select id="vlProvider">${opt('',VL.filters.provider,'All providers')}${VL.providers.map(p=>opt(p,VL.filters.provider,p)).join('')}</select>
  <select id="vlStatus">${opt('',VL.filters.status,'All statuses')}${s.statuses.map(v=>opt(v,VL.filters.status,v.replace('_',' '))).join('')}</select>
  <span class="vl-count">${rows.length} of ${VL.total} shown</span>
</div>
<div class="table-shell vl-shell"><table class="table vl-table">
<thead>
  <tr class="vl-groups">
    <th colspan="${s.source_fields.length+1}"><span>DISCOVERY EVIDENCE (READ-ONLY)</span></th>
    <th colspan="${s.check_fields.length}" class="vl-group-edit"><span>PRESENCE CHECKS (YES / NO + LINK)</span></th>
    <th colspan="${s.link_fields.length+s.text_fields.length}" class="vl-group-edit"><span>LINKS, CONTACT &amp; NOTES</span></th>
    <th colspan="${scrape?3:2}" class="vl-group-edit"><span>STATUS</span></th>
  </tr>
  <tr>
    <th>City</th>
    ${s.source_fields.map(f=>`<th>${esc(f.label)}</th>`).join('')}
    ${s.check_fields.map(f=>`<th class="vl-th-edit">${esc(f.label)}</th>`).join('')}
    ${s.link_fields.concat(s.text_fields).map(f=>`<th class="vl-th-edit">${esc(f.label)}</th>`).join('')}
    ${scrape?'<th class="vl-th-edit">Scrape result</th>':''}
    <th class="vl-th-edit">Status</th><th class="vl-th-edit"></th>
  </tr>
</thead>
<tbody>
${rows.length?rows.map(r=>`
  <tr class="${VL.editing===r.id?'vl-active':''}">
    <td><strong>${esc(r.city||'—')}</strong></td>
    ${s.source_fields.map(f=>`<td>${vlCell(r[f.key])}</td>`).join('')}
    ${s.check_fields.map(f=>`<td>${vlCheckCell(r,f)}</td>`).join('')}
    ${s.link_fields.map(f=>`<td>${vlLink(r[f.key])}</td>`).join('')}
    ${s.text_fields.map(f=>`<td>${vlCell(r[f.key])}</td>`).join('')}
    ${scrape?`<td>${vlScrapeCell(r)}</td>`:''}
    <td>${tag(r.validation_status.replace('_',' '),r.validation_status==='COMPLETED'?'green':r.validation_status==='IN_PROGRESS'?'amber':'gray')}</td>
    <td><button class="button small ${VL.editing===r.id?'secondary':'outline'}" onclick="vlEdit(${r.id})">${VL.editing===r.id?'Editing':'Edit'}</button></td>
  </tr>
  ${VL.editing===r.id?`<tr class="vl-edit-row"><td colspan="${cols}"><div id="vlEditor"></div></td></tr>`:''}`).join('')
:`<tr><td colspan="${cols}"><div class="vl-none">No records match the current filters.</div></td></tr>`}
</tbody></table></div>`;
  const search=$('#vlSearch');
  search.oninput=e=>{clearTimeout(VL._t);const v=e.target.value;VL._t=setTimeout(()=>{VL.filters.search=v;renderValidation();$('#vlSearch').focus()},220)};
  $('#vlProvider').onchange=e=>{VL.filters.provider=e.target.value;renderValidation()};
  $('#vlStatus').onchange=e=>{VL.filters.status=e.target.value;renderValidation()};
  if(VL.editing)renderVlEditor();
}
function vlSizeEditor(){const host=$('#vlEditor'),shell=$('.vl-shell');if(host&&shell)host.style.width=shell.clientWidth+'px'}
function renderVlEditor(){
  const host=$('#vlEditor');if(!host)return;
  vlSizeEditor();
  const s=VL.schema,d=VL.draft,r=vlRecord(VL.editing);
  const check=f=>{const v=d[f.key]||'';
    return `<div class="vl-field${v==='YES'?' vl-field-open':''}">
      <label>${esc(f.label)}</label>
      <select onchange="vlSetCheck('${f.key}',this.value)">
        <option value=""${v?'':' selected'}>— not answered —</option>
        <option value="YES"${v==='YES'?' selected':''}>Yes</option>
        <option value="NO"${v==='NO'?' selected':''}>No</option>
      </select>
      ${v==='YES'?`<input type="url" class="vl-link-input" placeholder="Paste the supporting link (required)" value="${esc(d[f.link_key]||'')}" oninput="vlField('${f.link_key}',this.value)">
      <small class="vl-hint">Marked Yes — a link is required before this row can be saved.</small>`:v==='NO'?`<small class="vl-hint">Marked No — no link needed.</small>`:''}
    </div>`};
  const plain=f=>`<div class="vl-field"><label>${esc(f.label)}</label>${f.multiline
    ?`<textarea rows="3" oninput="vlField('${f.key}',this.value)" placeholder="Optional">${esc(d[f.key]||'')}</textarea>`
    :`<input type="text" value="${esc(d[f.key]||'')}" oninput="vlField('${f.key}',this.value)" placeholder="Optional">`}</div>`;
  host.innerHTML=`
    <div class="vl-editor-head">
      <div><p class="eyebrow">EDITING ROW ${r.source_row} · ${esc(r.provider||'')}</p><h3>${esc(r.business_name||'Untitled record')}</h3><p class="muted">${esc(r.address||'No address in the workbook')}</p></div>
      <div class="head-actions"><button class="button outline small" onclick="vlCancel()">Cancel</button><button class="button primary small" onclick="vlSave()">Save row</button></div>
    </div>
    ${VL.error?`<div class="alert error">${esc(VL.error)}</div>`:''}
    <h4 class="vl-section">Directory presence checks</h4>
    <div class="vl-fields">${s.check_fields.map(check).join('')}</div>
    <h4 class="vl-section">Links, contact and notes</h4>
    <div class="vl-fields">${s.link_fields.concat(s.text_fields).map(plain).join('')}</div>
    <div class="vl-editor-foot"><span>${r.updated_at?`Last saved ${new Date(r.updated_at).toLocaleString()} by ${esc(r.updated_by_email||'—')}`:'Not saved yet'}</span><button class="button primary small" onclick="vlSave()">Save row</button></div>`;
}
window.vlEdit=function(id){
  if(VL.editing===id){VL.editing=null;VL.draft={};VL.error='';return renderValidation()}
  const r=vlRecord(id);if(!r)return;
  VL.editing=id;VL.error='';VL.draft={};
  VL.schema.check_fields.forEach(f=>{VL.draft[f.key]=r[f.key]||'';VL.draft[f.link_key]=r[f.link_key]||''});
  VL.schema.link_fields.concat(VL.schema.text_fields).forEach(f=>{VL.draft[f.key]=r[f.key]||''});
  renderValidation();
  $('#vlEditor')?.scrollIntoView({block:'nearest'});
};
window.vlCancel=function(){VL.editing=null;VL.draft={};VL.error='';renderValidation()};
window.vlField=function(key,value){VL.draft[key]=value};
window.vlSetCheck=function(key,value){
  VL.draft[key]=value;
  const f=VL.schema.check_fields.find(x=>x.key===key);
  if(f&&value!=='YES')VL.draft[f.link_key]='';
  renderVlEditor();
};
window.vlSave=async function(){
  const id=VL.editing;if(!id)return;
  const missing=VL.schema.check_fields.find(f=>VL.draft[f.key]==='YES'&&!String(VL.draft[f.link_key]||'').trim());
  if(missing){VL.error=`${missing.label} is marked Yes — add the supporting link before saving.`;return renderVlEditor()}
  try{
    const saved=await api(`/validation/records/${id}`,{method:'PUT',body:JSON.stringify(VL.draft)});
    const i=VL.records.findIndex(r=>r.id===id);if(i>-1)VL.records[i]=saved;
    VL.summary=VL.records.reduce((a,r)=>{a[r.validation_status]=(a[r.validation_status]||0)+1;return a},{PENDING:0,IN_PROGRESS:0,COMPLETED:0});
    VL.editing=null;VL.draft={};VL.error='';
    renderValidation();toast(`Saved ${saved.business_name||'record'} · ${saved.validation_status.replace('_',' ')}`);
  }catch(e){VL.error=e.message;renderVlEditor()}
};
const SCR_STATUS_TAG={OK:'green',NOT_FOUND:'gray',BLOCKED_BY_SITE:'red',UNREACHABLE:'red',ROBOTS_DISALLOWED:'amber',ERROR:'red'};
function vlScrapeCell(r){
  const f=r.scrape_findings||{},keys=Object.keys(f);
  if(!keys.length)return `<span class="vl-empty">${esc((r.scrape_state||'not processed').toLowerCase())}</span>`;
  const found=keys.filter(k=>f[k].status==='OK').length;
  return `<button class="button small outline" onclick="vlFindings(${r.id})">${found?`${found} source${found>1?'s':''} found`:'nothing found'} · why</button>`;
}
window.vlFindings=function(id){
  const r=vlRecord(id);if(!r)return;
  const f=r.scrape_findings||{};
  $('#modalRoot').innerHTML=`<div class="modal-backdrop" onclick="if(event.target===this)closeModal()"><div class="modal"><div class="modal-head"><div><p class="eyebrow">SCRAPE EVIDENCE · ROW ${r.source_row}</p><h2>${esc(r.business_name||'')}</h2><p class="muted">${esc(r.address||'')}</p></div><button class="modal-close" onclick="closeModal()">×</button></div><div class="modal-body">
  <p class="muted">Each provider is listed with what it concluded. A column is only filled when a provider proved a value; otherwise the reason it stayed empty is shown here.</p>
  <div class="guardrails" style="margin-top:14px">${Object.keys(f).map(k=>`<div class="guardrail"><span><strong>${esc(f[k].label||k)}</strong><br><small class="muted">${esc(f[k].note||'')}</small>${f[k].source_url?`<br>${vlLink(f[k].source_url)}`:''}</span>${tag((f[k].status||'').replace(/_/g,' '),SCR_STATUS_TAG[f[k].status]||'gray')}</div>`).join('')||'<p class="muted">This row has not been processed yet.</p>'}</div>
  </div></div></div>`;
};

/* ---------- Cities & Scraping ---------- */
const SCR={jobs:[],cities:[],totals:{},sources:null,lastJobId:null,uploadMsg:'',poll:null};
function scrStopPoll(){if(SCR.poll){clearInterval(SCR.poll);SCR.poll=null}}
async function scraping(){
  const [c,j]=await Promise.all([api(`/cities/${state.project.id}`),api(`/scraping/${state.project.id}/jobs`)]);
  SCR.cities=c.cities;SCR.totals=c.totals;SCR.jobs=j.jobs;
  state.cities=c.cities.map(x=>({id:x.id,name:x.name,region:x.region,records:x.total_records}));
  renderScraping();
  if(!SCR.sources){api('/scraping/sources').then(d=>{SCR.sources=d.sources;if(location.hash.startsWith('#scraping'))renderScraping()}).catch(()=>{})}
  scrSyncPoll();
}
async function scrRefresh(){
  const [c,j]=await Promise.all([api(`/cities/${state.project.id}`),api(`/scraping/${state.project.id}/jobs`)]);
  SCR.cities=c.cities;SCR.totals=c.totals;SCR.jobs=j.jobs;renderScraping();
}
function scrSyncPoll(){
  scrStopPoll();
  if(SCR.jobs.some(j=>j.status==='RUNNING')){
    SCR.poll=setInterval(async()=>{
      if(!location.hash.startsWith('#scraping'))return scrStopPoll();
      try{await scrRefresh();if(!SCR.jobs.some(j=>j.status==='RUNNING'))scrStopPoll()}catch{scrStopPoll()}
    },2000);
  }
}
function renderScraping(){
  const src=SCR.sources,t=SCR.totals||{};
  const jobTag=s=>tag(s,s==='COMPLETED'?'green':s==='RUNNING'?'blue':s==='FAILED'?'red':s==='CANCELLED'?'gray':'amber');
  const running=id=>SCR.jobs.some(j=>j.city_id===id&&j.status==='RUNNING');
  $('#content').innerHTML=`
${pageHead('Cities & Scraping','Load one workbook per city. Each upload is appended to the same tables, so every city is validated and scraped on its own while the Validation Layer can still show the whole programme together.')}
<div class="metrics">${metric('Cities loaded',SCR.cities.length,'Each with its own workbook')}${metric('Records total',SCR.cities.reduce((a,c)=>a+c.total_records,0),'Across every city',true)}${metric('Completed',t.COMPLETED||0,'All six presence checks answered')}${metric('Not started',t.PENDING||0,'No presence check answered yet')}</div>

<div class="panel"><div class="panel-title"><h3>Add a city workbook</h3>${tag('SAME FORMAT AS VALIDATION LAYER','blue')}</div>
  <div class="scr-upload">
    <input type="text" id="scrCity" class="scr-city" placeholder="City (e.g. Ubud)" list="scrCityList">
    <datalist id="scrCityList">${SCR.cities.map(c=>`<option value="${esc(c.name)}">`).join('')}</datalist>
    <input type="text" id="scrRegion" class="scr-region" placeholder="Region (optional)">
    <input type="file" id="scrFile" accept=".xlsx,.xlsm">
    <button class="button primary" id="scrUploadBtn" onclick="scrUpload()">Append workbook</button>
  </div>
  <p class="muted">Rows are read with the same column handling as the bundled workbook, including the shifted rows for businesses never probed. Re-uploading a city refreshes its discovery columns and never duplicates a business or overwrites a saved answer.</p>
  <div id="scrUploadMsg">${SCR.uploadMsg||''}</div>
</div>

<div class="panel" style="margin-top:14px"><h3>Cities</h3>
${SCR.cities.length?`<div class="table-shell"><table class="table"><thead><tr><th>City</th><th>Records</th><th>Validation progress</th><th>Scraped</th><th>Workbooks</th><th></th></tr></thead><tbody>
${SCR.cities.map(c=>{const done=c.summary.COMPLETED||0,prog=c.summary.IN_PROGRESS||0,pct=c.total_records?Math.round(done/c.total_records*100):0;return `<tr>
  <td><div class="poi"><strong>${esc(c.name)}</strong><span>${esc([c.region,c.country].filter(Boolean).join(' · '))}</span></div></td>
  <td>${c.total_records}</td>
  <td style="min-width:180px"><div class="scr-bar"><span style="width:${pct}%"></span></div><small class="muted">${done} done · ${prog} in progress · ${c.summary.PENDING||0} not started</small></td>
  <td>${c.scraped_records}/${c.total_records}${c.last_job?`<br><small class="muted">last job #${c.last_job.id} · ${c.last_job.fields_filled} values</small>`:''}</td>
  <td><small class="muted">${esc((c.source_files||[]).join(', ')||'—')}</small></td>
  <td><div class="scr-actions">
    <button class="button small outline" onclick="scrOpenCity(${c.id})">Validate</button>
    <button class="button small outline" onclick="downloadCityValidation(${c.id})">Download XLSX</button>
    <button class="button small primary" onclick="scrRunCity(${c.id})" ${running(c.id)?'disabled':''}>${running(c.id)?'Scraping…':'Scrape city'}</button>
    <button class="button small outline" onclick="scrDeleteCity(${c.id},'${esc(c.name)}')">Delete</button>
  </div></td></tr>`}).join('')}
</tbody></table></div>`:'<p class="muted">No city loaded yet. Add one above.</p>'}
</div>
<div class="panel" style="margin-top:14px"><div class="panel-title"><h3>What the providers can reach right now</h3>${src?tag(`${Object.values(src).filter(s=>s.status==='OK').length}/${Object.keys(src).length} AVAILABLE`,'blue'):tag('CHECKING…','gray')}</div>
  ${src?`<div class="guardrails">${Object.keys(src).map(k=>`<div class="guardrail"><span><strong>${esc(src[k].label)}</strong><br><small class="muted">${esc(src[k].note)}</small></span>${tag((src[k].status||'').replace(/_/g,' '),SCR_STATUS_TAG[src[k].status]||'gray')}</div>`).join('')}</div>
  <div class="alert info">Columns are only written when a provider proves a value. Anything a provider could not reach or match is left empty, and the reason is stored against the row — open <strong>why</strong> in the Scrape Data tab to see it.</div>`
  :'<p class="muted">Checking which providers respond…</p>'}
</div>
<div class="panel" style="margin-top:14px"><h3>Scrape runs</h3>
${SCR.jobs.length?`<div class="table-shell"><table class="table"><thead><tr><th>City</th><th>Rows</th><th>Status</th><th>Progress</th><th>Filled</th><th>Run by</th><th></th></tr></thead><tbody>
${SCR.jobs.map(j=>`<tr>
  <td><div class="poi"><strong>${esc(j.city||j.file_name)}</strong><span>Job #${j.id}${j.current_business?` · now: ${esc(j.current_business)}`:''}</span></div></td>
  <td>${j.total_records}</td>
  <td>${jobTag(j.status)}${j.error?`<div class="vl-empty" title="${esc(j.error)}">${esc(j.error.slice(0,40))}…</div>`:''}</td>
  <td style="min-width:170px"><div class="scr-bar"><span style="width:${j.percent}%"></span></div><small class="muted">${j.processed_records}/${j.total_records} · ${j.percent}%</small></td>
  <td>${j.fields_filled} values<br><small class="muted">${j.records_with_findings} rows</small></td>
  <td><small class="muted">${esc(j.created_by_email||'—')}</small></td>
  <td><div class="scr-actions">
    ${j.status==='RUNNING'
      ?`<button class="button small secondary" onclick="scrCancel(${j.id})">Cancel</button>`
      :`<button class="button small primary" onclick="scrStart(${j.id})">${j.processed_records?'Re-run':'Start'}</button>`}
    ${j.processed_records?`<button class="button small outline" onclick="scrView(${j.id})">View</button>`:''}
    ${j.status!=='RUNNING'?`<button class="button small outline" onclick="scrDelete(${j.id})">Delete</button>`:''}
  </div></td></tr>`).join('')}
</tbody></table></div>`:'<p class="muted">No scrape run yet. Use <strong>Scrape city</strong> above.</p>'}
</div>`;
}
window.scrUpload=async function(){
  const file=$('#scrFile'),city=$('#scrCity').value.trim(),region=$('#scrRegion').value.trim();
  if(!city)return toast('Enter the city this workbook covers');
  if(!file.files||!file.files[0])return toast('Choose an .xlsx workbook first');
  const btn=$('#scrUploadBtn');btn.disabled=true;btn.textContent='Appending…';
  try{
    const body=new FormData();body.append('file',file.files[0]);body.append('city',city);
    if(region)body.append('region',region);
    const r=await api(`/cities/${state.project.id}/upload`,{method:'POST',body});
    SCR.uploadMsg=`<div class="alert info"><strong>${esc(r.city.name)}</strong>: ${r.added} new record${r.added===1?'':'s'} appended${r.refreshed?`, ${r.refreshed} refreshed`:''}${r.skipped?`, ${r.skipped} blank row(s) skipped`:''}. Use <strong>Scrape city</strong> below, or open it in the Validation Layer.</div>`;
    await scrRefresh();
    toast(`${r.city.name}: ${r.added} appended, ${r.refreshed} refreshed`);
  }catch(e){SCR.uploadMsg=`<div class="alert error">${esc(e.message)}</div>`;renderScraping()}
};
window.scrRunCity=async function(cityId){
  try{
    const job=await api(`/scraping/${state.project.id}/jobs?city_id=${cityId}`,{method:'POST'});
    await api(`/scraping/jobs/${job.id}/start`,{method:'POST'});
    toast(`Scraping ${job.city||''} — ${job.total_records} records`);
    await scrRefresh();scrSyncPoll();
  }catch(e){toast(e.message)}
};
window.scrOpenCity=function(cityId){
  state.cityId=cityId;localStorage.setItem('gd_city',cityId);state.summary=null;VL.cityId=cityId;
  location.hash='#validation';
};
window.scrDeleteCity=async function(cityId,name){
  try{const r=await api(`/cities/${state.project.id}/${cityId}`,{method:'DELETE'});
    if(VL.cityId===cityId)VL.cityId=null;
    toast(`${name} removed (${r.records_removed} records)`);await scrRefresh()}
  catch(e){toast(e.message)}
};
window.scrStart=async function(id){
  try{await api(`/scraping/jobs/${id}/start`,{method:'POST'});toast('Processing started');
    await scrRefresh();scrSyncPoll()}
  catch(e){toast(e.message)}
};
window.scrCancel=async function(id){
  try{await api(`/scraping/jobs/${id}/cancel`,{method:'POST'});toast('Cancelling after the current record');await scrRefresh()}
  catch(e){toast(e.message)}
};
window.scrDelete=async function(id){
  try{await api(`/scraping/jobs/${id}`,{method:'DELETE'});toast('Run deleted');
    if(SCR.lastJobId===id)SCR.lastJobId=null;await scrRefresh()}
  catch(e){toast(e.message)}
};
window.scrView=function(id){SCR.lastJobId=id;location.hash=`#scrape/${id}`};

window.vlReimport=async function(){
  try{const r=await api(`/validation/${state.project.id}/reimport`,{method:'POST'});toast(`${r.workbook}: ${r.imported} new, ${r.updated} refreshed`);await validation()}
  catch(e){toast(e.message)}
};

const views={overview,comparison,sample,map:mapView,cost,pack,future,validation,scraping,scrape:scrapeData};const titles={overview:'Executive Overview',comparison:'Comparison Proof',sample:'Priority Sample',map:'Coverage Map',cost:'Cost & Scale',pack:'Customer Pack',future:'Future Scale',validation:'Validation Layer',scraping:'Cities & Scraping',scrape:'Scrape Data'};
async function route(){const [v,param]=(location.hash||'#overview').slice(1).split('/');if(v!=='scraping')scrStopPoll();$$('#nav a,.sidebar nav a').forEach(a=>a.classList.toggle('active',a.dataset.view===v));$('#pageTitle').textContent=titles[v]||'Executive Overview';try{await(views[v]||overview)(param)}catch(e){$('#content').innerHTML=`<div class="alert error">${esc(e.message)}</div>`}}
async function start(){$('#loginForm').onsubmit=login;$('#logout').onclick=logout;window.onhashchange=route;window.addEventListener('resize',()=>{if(VL.editing)vlSizeEditor()});if(state.token){try{await enterApp()}catch{logout()}}}
start();
