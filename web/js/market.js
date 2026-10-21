// Maintenance marketplace: 3 listed companies within 10 km quote, the owner chooses, the company proves the job with a photo,
// reports problems with a photo or voice note, and tenant + owner rate them. Plus the public pages for maintenance companies.
import { $, $$, act, ago, api, confirmBox, esc, fdate, fdt, go, icon, modal, pickFiles, R, R2, route, state, toast, LOGO } from './core.js';
import { page } from './shell.js';
import { nav, footer } from './public.js';

const A = { auth: true };
const ISSUES = [['extra_work', 'Extra work needed', 'money'], ['parts', 'Waiting for parts', 'cal'], ['no_access', "Couldn't get in", 'key'],
  ['safety', 'Safety concern', 'alert'], ['other', 'Something else', 'chat']];
const CRIT = [['quality', 'Quality of work'], ['punctuality', 'On time'], ['price_score', 'Fair price'], ['communication', 'Communication']];

export const starsRow = (v, size = '') => `<span class="stars ${size}" title="${v || 0}/5">${'★'.repeat(Math.round(v || 0))}${'☆'.repeat(5 - Math.round(v || 0))}</span>`;
const badge = (ok, txt) => ok ? `<span class="pill ok">${icon('check')}${txt}</span>` : '';

// ------------------------------------------------------------------ ticket blocks
export function marketBlocks(t, u) {
  const c = t.can, out = [];
  const open = t.quotes.filter(q => ['shortlisted', 'submitted'].includes(q.status) && (q.kind || 'quote') === 'quote');
  const asked = t.quotes.filter(q => (q.kind || 'quote') === 'quote');
  if ((c.approve || c.compare) && open.length) {
    const lo = Math.min(...open.map(q => q.amount)), best = open[0];
    out.push(`<div class="card stack"><div class="row"><h3 class="grow">${icon('clip')} ${c.approve ? 'Choose a company' : 'Quotes – waiting for the owner'}</h3><span class="pill">${open.length} of ${asked.length} quoted</span></div>
      <p class="small muted">${c.approve ? 'Sent to listed companies within 10 km of the property. Compare price, rating and distance – your choice books the job.' : "The owner chooses. AVA has reminded them; you'll be notified when they pick."}</p>
      <div class="qgrid">${open.map(q => `<div class="qcard ${q === best ? 'best' : ''}">${q === best ? '<span class="pill ok qtag">AVA pick</span>' : q.amount === lo ? '<span class="pill info qtag">Lowest price</span>' : ''}
        <a href="#/pro/${q.contractor_id}" class="qname">${esc(q.company || q.contractor_name)}</a>${q.applied ? '<span class="tiny muted">Asked to quote from the job map</span>' : ''}
        <div class="row small">${starsRow(q.rating)} <b>${q.rating ? (+q.rating).toFixed(1) : 'New'}</b><span class="muted">(${q.reviews})</span></div>
        <div class="amt">${R2(q.amount)}</div>
        <div class="qfacts"><span>${icon('pin')}${q.distance_km != null ? q.distance_km + ' km away' : '–'}</span><span>${icon('cal')}${q.eta_days || '?'} day${q.eta_days === 1 ? '' : 's'}</span><span>${icon('tool')}${q.jobs_done || 0} jobs on AVA</span>${q.years ? `<span>${icon('star')}${q.years} yrs in business</span>` : ''}</div>
        <div class="row wrap" style="gap:4px">${badge(q.vetted, 'Vetted')}${badge(q.insured, 'Insured')}</div>
        ${q.notes ? `<p class="small muted">“${esc(q.notes)}”</p>` : ''}${q.file ? `<a class="small" href="${esc(q.file)}" target="_blank">${icon('doc')}Quote document</a>` : ''}
        ${c.approve ? `<button class="btn ${q === best ? 'primary' : ''} block" data-aq="${q.id}">Choose ${esc((q.company || q.contractor_name).split(' ')[0])}</button>` : ''}</div>`).join('')}</div>
      ${asked.length > open.length ? `<p class="tiny muted">${asked.length - open.length} compan${asked.length - open.length === 1 ? 'y has' : 'ies have'} not quoted yet${t.quote_deadline ? ' – quotes close ' + fdt(t.quote_deadline) : ''}.</p>` : ''}
      ${!c.approve && ['pm', 'admin'].includes(u.role) ? `<button class="btn sm" id="nudge">${icon('bell')}Remind the owner</button>` : ''}</div>`);
  } else if (t.status === 'quoting' && asked.length && u.role !== 'contractor') {
    out.push(`<div class="card stack tight"><h3>${icon('clip')} Quotes requested</h3><p class="small muted">Sent to ${asked.length} listed compan${asked.length === 1 ? 'y' : 'ies'} within 10 km. ${t.quote_deadline ? 'Quotes close ' + fdt(t.quote_deadline) + '.' : ''}</p>
      ${asked.map(q => `<div class="row small"><a class="grow" href="#/pro/${q.contractor_id}">${esc(q.company || q.contractor_name)}</a><span class="muted">${q.distance_km ?? '–'} km</span>${q.rating ? `<span>★ ${(+q.rating).toFixed(1)}</span>` : ''}<span class="pill ${q.status === 'requested' ? '' : 'ok'}">${q.status === 'requested' ? 'Waiting' : 'Quoted'}</span></div>`).join('')}</div>`);
  }
  const vars = t.quotes.filter(q => q.kind === 'variation' && q.status === 'variation');
  vars.forEach(v => out.push(`<div class="card stack" style="border-color:var(--warn)"><h3>${icon('money')} Extra work requested: ${R2(v.amount)}</h3><p>${esc(v.notes || '')}</p>${v.file ? `<img src="${esc(v.file)}" data-zoom="${esc(v.file)}" style="max-width:260px;border-radius:10px">` : ''}
    ${c.variation ? `<div class="row"><button class="btn" data-var="${v.id}" data-acc="0">Decline</button><button class="btn primary" data-var="${v.id}" data-acc="1">Approve extra work</button></div>` : '<p class="small muted">Waiting for the owner to approve.</p>'}</div>`));
  if (c.complete || c.schedule || c.issue) {
    const mine = u.role === 'contractor';
    out.push(`<div class="card stack jobcard"><h3>${icon('tool')} ${mine ? 'Your job' : 'Job'}</h3>
      ${c.schedule ? `<div class="row wrap"><input class="input" type="datetime-local" id="when" style="max-width:240px" value="${(t.scheduled_for || '').slice(0, 16)}"><button class="btn" id="book">${icon('cal')}${t.scheduled_for ? 'Rebook' : 'Book time'}</button>${c.start && t.status !== 'in_progress' ? `<button class="btn" id="start">On site – start</button>` : ''}</div>` : ''}
      <div class="bigbtns"><button class="bigbtn ok" id="done">${icon('camera')}<b>Job done</b><span>Take the 'after' photo – that's it</span></button>
        <button class="bigbtn warn" id="issue">${icon('alert')}<b>Report an issue</b><span>Photo or voice note – AVA tells the right people</span></button></div>
      ${mine ? `<p class="tiny muted">Payment is made from the AVA trust account ${'2'} days after the job is confirmed – the tenant has 72 h to object, otherwise it confirms itself.</p>` : ''}</div>`);
  }
  if (c.close) {
    out.push(`<div class="card stack"><h3>Is it fixed?</h3>${(t.after_photos || []).length ? `<div class="thumbs">${t.after_photos.map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" style="width:120px;height:90px">`).join('')}</div>` : ''}
      <p class="small muted">${u.role === 'tenant' ? "If you're happy, you don't need to do anything – it closes itself in 72 hours. Rate them now to help other owners choose." : 'Confirm and rate, or reopen.'}</p>
      ${rateForm()}<div class="row"><button class="btn" id="reopen">Not fixed</button><span class="spacer"></span><button class="btn primary" id="close">Confirm fixed</button></div></div>`);
  } else if (c.rate && !t.review) {
    out.push(`<div class="card stack"><h3>${icon('star')} Rate ${esc(t.contractor?.company || 'the company')}</h3>${rateForm()}<button class="btn primary" id="sendrate">Submit rating</button></div>`);
  } else if (t.review) {
    out.push(`<div class="card row small">${icon('check')}You rated this job ${starsRow(t.review.rating)}${t.review.status === 'pending' ? ' <span class="pill warn">being checked</span>' : ''}</div>`);
  }
  return out.join('');
}

const rateForm = () => `<div class="rate"><div class="row"><span class="small" style="width:120px"><b>Overall</b></span><span class="stars big" data-k="rating">${[1, 2, 3, 4, 5].map(i => `<span data-r="${i}">☆</span>`).join('')}</span></div>
  ${CRIT.map(([k, l]) => `<div class="row"><span class="small muted" style="width:120px">${l}</span><span class="stars mid" data-k="${k}">${[1, 2, 3, 4, 5].map(i => `<span data-r="${i}">☆</span>`).join('')}</span></div>`).join('')}
  <textarea class="input" id="rv" rows="2" placeholder="What went well, what could be better? (optional)"></textarea></div>`;

function readRate(root) {
  const o = { review: $('#rv', root)?.value || '' };
  $$('[data-k]', root).forEach(g => o[g.dataset.k] = +(g.dataset.val || 0) || undefined);
  return o;
}

export function bindMarket(t, u, reload) {
  const id = t.id;
  $$('[data-aq]').forEach(b => b.onclick = async () => {
    const q = t.quotes.find(x => x.id == b.dataset.aq);
    if (!await confirmBox('Choose this company', `${esc(q.company || q.contractor_name)} at ${R2(q.amount)}. They're booked immediately, the tenant is told and the others are thanked. The cost comes off the next rent payout.`, 'Choose')) return;
    await act(b, () => api.post(`/api/tickets/${id}/approve`, { quote_id: q.id }), 'Booked – company and tenant notified'); reload();
  });
  $('#nudge')?.addEventListener('click', async () => { await api.post(`/api/tickets/${id}/event`, (() => { const f = new FormData(); f.set('text', 'Reminder: the quotes are in – please choose a company so the repair can go ahead.'); return f; })()); toast('Owner reminded'); });
  $$('[data-var]').forEach(b => b.onclick = async () => { await act(b, () => api.post(`/api/tickets/${id}/variation/${b.dataset.var}`, { accept: b.dataset.acc }), b.dataset.acc === '1' ? 'Extra work approved' : 'Declined'); reload(); });
  $('#book')?.addEventListener('click', async () => { if (!$('#when').value) return toast('Pick a date and time', true); await act($('#book'), () => api.post(`/api/tickets/${id}/status`, { status: 'scheduled', scheduled_for: $('#when').value }), 'Booked – tenant notified'); reload(); });
  $('#start')?.addEventListener('click', async () => { await act($('#start'), () => api.post(`/api/tickets/${id}/status`, { status: 'in_progress' })); reload(); });
  $('#done')?.addEventListener('click', () => doneFlow(t, u, reload));
  $('#issue')?.addEventListener('click', () => issueFlow(t, reload));
  $$('.rate [data-k]').forEach(g => $$('[data-r]', g).forEach(s => s.onclick = () => { g.dataset.val = s.dataset.r; $$('[data-r]', g).forEach(x => x.textContent = +x.dataset.r <= +s.dataset.r ? '★' : '☆'); }));
  $('#close')?.addEventListener('click', async () => { const r = readRate(document); await act($('#close'), () => api.post(`/api/tickets/${id}/close`, r), r.rating ? 'Thanks for rating!' : 'Closed'); reload(); });
  $('#sendrate')?.addEventListener('click', async () => { const r = readRate(document); if (!r.rating) return toast('Tap the stars to rate', true); await act($('#sendrate'), () => api.post(`/api/tickets/${id}/review`, r), 'Thanks for rating!'); reload(); });
  $('#reopen')?.addEventListener('click', async () => { await act($('#reopen'), () => api.post(`/api/tickets/${id}/status`, { status: 'reopen', note: $('#rv')?.value || 'Not fixed' }), 'Re-opened – the company has been told'); reload(); });
}

// one tap → camera → submit. Price and note are optional.
async function doneFlow(t, u, reload) {
  const files = await pickFiles({ capture: 'environment' });
  if (!files.length) return u.role === 'contractor' ? toast("Take a photo of the finished work to complete the job", true) : null;
  const m = modal({ title: 'Job done', body: `<div class="thumbs" id="ap">${files.map(f => `<img src="${URL.createObjectURL(f)}" style="width:96px;height:96px">`).join('')}<button class="add" type="button" id="aa">${icon('camera')}</button></div>
    <div class="cols form"><label class="field"><span>Final amount (R)</span><input class="input" type="number" step="1" id="cc" value="${t.cost || ''}"></label></div>
    <label class="field"><span>Note (optional)</span><input class="input" id="cn" placeholder="e.g. Replaced cartridge, tested – no leaks"></label>
    <p class="tiny muted">The photo is the proof of completion. The tenant and owner see it straight away; the job confirms itself after 72 h unless the tenant reports a problem.</p>`,
    foot: `<button class="btn primary lg block" id="ok">${icon('check')}Submit</button>` });
  $('#aa', m).onclick = async () => { const more = await pickFiles({ capture: 'environment' }); files.push(...more); $('#ap', m).insertAdjacentHTML('afterbegin', more.map(f => `<img src="${URL.createObjectURL(f)}" style="width:96px;height:96px">`).join('')); };
  $('#ok', m).onclick = async () => {
    const fd = new FormData(); fd.set('cost', $('#cc', m).value); fd.set('note', $('#cn', m).value); files.forEach(f => fd.append('photos', f));
    await act($('#ok', m), () => api.post(`/api/tickets/${t.id}/complete`, fd), 'Done – photo sent to tenant and owner'); m.close(); reload();
  };
}

function issueFlow(t, reload) {
  let kind = 'extra_work', audio = null, rec = null, chunks = [];
  const files = [];
  const m = modal({ title: 'Report an issue', body: `<div class="issuekinds">${ISSUES.map(([k, l, ic], i) => `<button type="button" data-k="${k}" aria-pressed="${i === 0}">${icon(ic)}<span>${l}</span></button>`).join('')}</div>
    <div class="row wrap"><button class="btn" type="button" id="ph">${icon('camera')}Photo</button><button class="btn" type="button" id="mic">${icon('chat')}<span>Record voice note</span></button><span id="recst" class="small muted"></span></div>
    <div class="thumbs" id="ip"></div><audio id="aud" controls class="hide" style="width:100%"></audio>
    <label class="field"><span>Short description (or just record a voice note)</span><textarea class="input" id="it" rows="2"></textarea></label>
    <div class="cols form" id="xtra"><label class="field"><span>Extra cost (R)</span><input class="input" type="number" step="1" id="xc"></label></div>
    <div class="cols form hide" id="eta"><label class="field"><span>Back on site</span><input class="input" type="datetime-local" id="et"></label></div>
    <p class="tiny muted" id="hint"></p>`, foot: `<button class="btn primary block" id="ok">Send</button>` });
  const HINT = { extra_work: 'The owner gets your photo and price and approves in one tap. Keep working on the approved scope until then.', parts: 'The tenant is told when you will be back.',
    no_access: 'The tenant is asked to pick a new time straight away.', safety: 'The portfolio manager and owner are alerted immediately.', other: 'Your portfolio manager gets the note.' };
  const setKind = k => { kind = k; $$('.issuekinds button', m).forEach(b => b.setAttribute('aria-pressed', b.dataset.k === k)); $('#xtra', m).classList.toggle('hide', k !== 'extra_work'); $('#eta', m).classList.toggle('hide', k !== 'parts'); $('#hint', m).textContent = HINT[k]; };
  $$('.issuekinds button', m).forEach(b => b.onclick = () => setKind(b.dataset.k)); setKind(kind);
  $('#ph', m).onclick = async () => { const f = await pickFiles({ capture: 'environment' }); files.push(...f); $('#ip', m).innerHTML = files.map(x => `<img src="${URL.createObjectURL(x)}">`).join(''); };
  $('#mic', m).onclick = async () => {
    if (rec && rec.state === 'recording') { rec.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      rec = new MediaRecorder(stream); chunks = [];
      rec.ondataavailable = e => chunks.push(e.data);
      rec.onstop = () => { stream.getTracks().forEach(x => x.stop()); audio = new Blob(chunks, { type: rec.mimeType || 'audio/webm' }); const a = $('#aud', m); a.src = URL.createObjectURL(audio); a.classList.remove('hide'); $('#mic span', m).textContent = 'Record again'; $('#recst', m).textContent = 'Voice note ready'; };
      rec.start(); $('#mic span', m).textContent = 'Stop recording'; $('#recst', m).textContent = '● Recording…';
    } catch (_) { toast('Microphone not available – type a note instead', true); }
  };
  $('#ok', m).onclick = async () => {
    const fd = new FormData(); fd.set('kind', kind); fd.set('text', $('#it', m).value);
    if (kind === 'extra_work' && $('#xc', m).value) fd.set('extra_cost', $('#xc', m).value);
    if (kind === 'parts' && $('#et', m).value) fd.set('eta', $('#et', m).value);
    files.forEach(f => fd.append('photos', f));
    if (audio) fd.append('audio', new File([audio], 'voice.' + ((audio.type || '').includes('ogg') ? 'ogg' : (audio.type || '').includes('mp4') ? 'm4a' : 'webm'), { type: audio.type }));
    await act($('#ok', m), () => api.post(`/api/tickets/${t.id}/issue`, fd), 'Sent – AVA has told the right people'); m.close(); reload();
  };
}

// ------------------------------------------------------------------ map of companies around the property + extend range
const TILE = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const dotIcon = (cls, txt = '') => window.L.divIcon({ className: '', html: `<span class="cpin ${cls}">${txt}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] });

export function mapCard(t) {
  if (!t.map) return '';
  const m = t.map, inR = m.companies.filter(c => c.active && c.distance_km <= m.radius), asked = t.quotes.filter(q => (q.kind || 'quote') === 'quote').length;
  const none = !asked && !t.contractor_id;
  return `<div class="card stack ${none ? 'alertcard' : ''}"><div class="row wrap"><h3 class="grow">${icon('map')} Companies near ${esc(t.property.suburb || 'the property')}</h3><span class="pill">${m.radius} km range</span></div>
    ${none ? `<p><b>No listed ${esc((t.trade || 'maintenance').toLowerCase())} company within ${m.radius} km yet.</b> ${m.next ? `The nearest is within ${m.next} km – extend the range and AVA sends the request straight away.` : 'There is no listed company for this trade further out either – assign one directly.'}</p>` :
      `<p class="small muted">${asked} compan${asked === 1 ? 'y' : 'ies'} asked to quote · ${inR.length} listed within ${m.radius} km.</p>`}
    <div id="tmap" class="tmap"></div>
    <div class="row wrap small legend"><span><span class="cpin home"></span>Property</span><span><span class="cpin asked"></span>Asked to quote</span><span><span class="cpin on"></span>Listed</span><span><span class="cpin off"></span>Not active</span></div>
    ${t.can.widen && m.steps.length ? `<div class="row wrap"><span class="small"><b>Extend range:</b></span>${m.steps.map(k => `<button class="btn sm ${k === m.next ? 'primary' : ''}" data-widen="${k}">${k} km</button>`).join('')}</div>` : ''}</div>`;
}

export function bindMap(t, reload) {
  if (!t.map || !$('#tmap')) return;
  const L = window.L, m = t.map, P = [t.property.lat, t.property.lng];
  const map = L.map('tmap', { scrollWheelZoom: false }).setView(P, 11);
  L.tileLayer(TILE, { attribution: '© OpenStreetMap' }).addTo(map);
  L.circle(P, { radius: m.radius * 1000, color: '#1ba3a0', weight: 2, fillOpacity: .07 }).addTo(map);
  if (m.next) L.circle(P, { radius: m.next * 1000, color: '#1ba3a0', weight: 1, dashArray: '6 6', fill: false }).addTo(map);
  L.marker(P, { icon: dotIcon('home', '⌂') }).addTo(map).bindPopup(esc(t.property.title));
  const pts = [P];
  m.companies.forEach(c => {
    if (c.lat == null) return;
    const cls = c.asked ? 'asked' : c.active ? 'on' : 'off';
    L.marker([c.lat, c.lng], { icon: dotIcon(cls) }).addTo(map).bindPopup(`<b>${esc(c.company || c.name)}</b><br>${c.distance_km} km · ${c.rating ? '★ ' + c.rating + ' (' + c.reviews + ')' : 'no reviews yet'}<br>${c.asked ? 'Asked to quote' + (c.quote_status && c.quote_status !== 'requested' ? ' – quoted' : '') : c.active ? (c.distance_km <= m.radius ? 'Listed – in range' : 'Outside the range') : 'Listing not active'}<br><a href="#/pro/${c.id}">Profile</a>`);
    if (c.asked || c.distance_km <= (m.next || m.radius)) pts.push([c.lat, c.lng]);
  });
  const circ = L.circle(P, { radius: (m.next || m.radius) * 1000 });
  circ.addTo(map); map.fitBounds(circ.getBounds().extend(L.latLngBounds(pts)), { padding: [10, 10] }); map.removeLayer(circ);
  $$('[data-widen]').forEach(b => b.onclick = async () => {
    const r = await act(b, () => api.post(`/api/tickets/${t.id}/widen`, { radius: +b.dataset.widen }));
    toast(r.sent ? `Range extended to ${r.radius} km – sent to ${r.companies.join(', ')}` : `Still nobody within ${r.radius} km${r.next ? ' – try ' + r.next + ' km' : ''}`, !r.sent);
    reload();
  });
}

// ------------------------------------------------------------------ contractor workspace
export async function contractorHome() {
  const pg = page('My jobs');
  const d = await api.get('/api/dashboard');
  const p = d.market || {}, rt = p.rating || {};
  const until = p.sub_until, days = until ? Math.round((new Date(until) - new Date()) / 864e5) : -1;
  pg.innerHTML = `${!d.profile?.approved ? `<div class="card" style="border-color:var(--warn)"><b>Your company is being vetted.</b> <span class="muted">AVA checks CIPC registration, ID and references – usually within 2 working days. You'll then get requests within ${d.radius} km.</span></div>` : ''}
    <div class="subcard ${days < 0 ? 'off' : days <= 5 ? 'soon' : ''}"><div><span class="small">AVA maintenance listing · ${R(d.fee)}/month</span><b>${days < 0 ? 'Not active – you are not receiving requests' : `Active until ${fdate(until)}`}</b>
      <span class="small">${days < 0 ? 'Renew to start receiving repair requests near you again.' : `Repair requests within ${d.radius} km of your base come straight to your phone.`}</span></div>
      <button class="btn ${days < 0 ? 'cta' : ''}" id="renew">${icon('money')}${days < 0 ? 'Activate' : 'Pay next month'}</button></div>
    <div class="kpis"><div class="kpi"><span>Quote requests</span><b>${d.rfqs.length}</b></div><div class="kpi"><span>Active jobs</span><b>${d.jobs.length}</b></div>
      <div class="kpi"><span>Your rating</span><b>${rt.avg ?? '–'}</b><small>${rt.n || 0} reviews</small></div><div class="kpi"><span>Win rate</span><b>${p.quoted ? Math.round(100 * p.won / p.quoted) + '%' : '–'}</b><small>${p.won || 0} of ${p.quoted || 0} quotes</small></div>
      <div class="kpi"><span>Work completed</span><b>${R(d.earned)}</b></div></div>
    ${d.open_nearby ? `<a class="card row" href="#/app/jobs" style="color:inherit;text-decoration:none;border-color:var(--brand-2)">${icon('map')}<span class="grow"><b>${d.open_nearby} open repair${d.open_nearby === 1 ? '' : 's'} near you</b><span class="small muted" style="display:block">Jobs in your area and trade that still need a company – apply to quote.</span></span><span class="btn sm primary">Browse jobs</span></a>` : ''}
    <div class="card flush"><div class="card-head"><h3>New requests near you</h3></div><div class="list">${d.rfqs.map(q => `<a class="li" href="#/app/ticket/${q.ticket_id}"><span class="dot ${q.priority === 'Urgent' ? 'bad' : ''}"></span><span class="grow"><span class="title">${esc(q.title)}</span><span class="small muted">${q.ref} · ${esc(q.suburb)}${q.distance_km != null ? ' · ' + q.distance_km + ' km' : ''} · closes ${fdt(q.quote_deadline)}</span></span><span class="btn sm primary">Quote</span></a>`).join('') || `<div class="muted">No open requests. You'll get a notification the moment a repair within ${d.radius} km needs your trade.</div>`}</div></div>
    <div class="card flush"><div class="card-head"><h3>Jobs</h3></div><div class="list">${d.jobs.map(t => `<a class="li" href="#/app/ticket/${t.id}"><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted">${t.ref} · ${esc(t.address)}${t.scheduled_for ? ' · ' + fdt(t.scheduled_for) : ''}</span></span>${t.status === 'in_progress' || t.status === 'scheduled' ? `<span class="btn sm">${icon('camera')}Done</span>` : ''}</a>`).join('') || '<div class="muted">No active jobs.</div>'}</div></div>
    ${d.snags.length ? `<div class="card flush"><div class="card-head"><h3>Snags assigned to you</h3><a class="btn sm" href="#/app/snags">All</a></div><div class="list">${d.snags.slice(0, 6).map(s => `<a class="li" href="#/app/snags/${s.property_id}"><span class="grow"><span class="title">${esc(s.ref)} · ${esc(s.title)}</span><span class="small muted">${esc(s.ptitle)} · due ${fdate(s.due_date)}</span></span></a>`).join('')}</div></div>` : ''}`;
  $('#renew').onclick = () => subscribe(d.fee);
}

async function subscribe(fee) {
  const m = modal({ title: 'AVA maintenance listing', body: `<p>Receive repair requests within 10 km of your base and quote from your phone.</p>
    <div class="seg" id="mo">${[[1, '1 month'], [3, '3 months'], [12, '12 months']].map(([v, l], i) => `<button data-v="${v}" aria-pressed="${i === 0}">${l} · ${R(fee * v)}</button>`).join('')}</div>`, foot: '<button class="btn cta" id="ok">Pay now</button>' });
  let months = 1; $$('#mo button', m).forEach(b => b.onclick = () => { months = +b.dataset.v; $$('#mo button', m).forEach(x => x.setAttribute('aria-pressed', x === b)); });
  $('#ok', m).onclick = async () => {
    const r = await act($('#ok', m), () => api.post('/api/contractor/subscribe', { months }));
    if (r.mode === 'payfast') { const f = document.createElement('form'); f.method = 'post'; f.action = r.url; Object.entries(r.fields).forEach(([k, v]) => { const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.append(i); }); document.body.append(f); f.submit(); return; }
    const x = await act($('#ok', m), () => api.post('/api/contractor/subscribe/simulate/' + r.payment_id), 'Payment received (test mode)');
    m.close(); toast('Listing active until ' + fdate(x.sub_until)); go('#/app?r=' + Date.now());
  };
}

route('/app/profile', async () => {
  const pg = page('Company profile', { actions: `<a class="btn sm" href="#/pro/${state.user.id}">${icon('eye')}Public page</a>` });
  const d = await api.get('/api/dashboard');
  const p = d.market || {};
  pg.innerHTML = `<div class="grid2" style="align-items:start"><form class="card form" id="pf"><h3>Business details</h3>
      <div class="cols"><label class="field"><span>Trades</span><input class="input" name="trades" value="${esc((p.trades || []).join(', '))}"></label><label class="field"><span>Call-out fee (R)</span><input class="input" name="callout_fee" type="number" value="${p.callout_fee || 0}"></label></div>
      <div class="cols"><label class="field"><span>Years in business</span><input class="input" name="years" type="number" value="${p.years || ''}"></label><label class="field"><span>CIPC registration</span><input class="input" name="registration" value="${esc(p.registration || '')}"></label><label class="field"><span>B-BBEE level</span><input class="input" name="bee_level" value="${esc(p.bee_level || '')}"></label></div>
      <label class="check"><input type="checkbox" name="insured" ${p.insured ? 'checked' : ''}>Public liability insurance</label>
      <label class="field"><span>Website</span><input class="input" name="website" value="${esc(p.website || '')}"></label>
      <label class="field"><span>About your company</span><textarea class="input" name="bio" rows="3">${esc(p.bio || '')}</textarea></label>
      <h3>Where you work</h3><label class="field"><span>Base address</span><input class="input" name="base_address" value="${esc(p.base_address || '')}"></label>
      <div id="bmap" style="height:240px;border-radius:10px;overflow:hidden"></div><input type="hidden" name="lat" value="${p.lat || ''}"><input type="hidden" name="lng" value="${p.lng || ''}">
      <p class="tiny muted">Tap the map to move your base. You receive requests for properties within 10 km of it.</p><button class="btn primary">Save</button></form>
    <div class="stack">${reviewsBlock(p, true)}</div></div>`;
  const L = window.L, map = L.map('bmap').setView([p.lat || -25.77, p.lng || 28.24], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(map);
  let mk = p.lat ? L.marker([p.lat, p.lng]).addTo(map) : null, ring = p.lat ? L.circle([p.lat, p.lng], { radius: 10000, color: '#1ba3a0', fillOpacity: .08 }).addTo(map) : null;
  map.on('click', e => { $('[name=lat]').value = e.latlng.lat.toFixed(5); $('[name=lng]').value = e.latlng.lng.toFixed(5); mk ? mk.setLatLng(e.latlng) : (mk = L.marker(e.latlng).addTo(map)); ring ? ring.setLatLng(e.latlng) : (ring = L.circle(e.latlng, { radius: 10000, color: '#1ba3a0', fillOpacity: .08 }).addTo(map)); });
  $('#pf').onsubmit = async e => { e.preventDefault(); const o = Object.fromEntries(new FormData(e.target)); o.insured = e.target.insured.checked ? 1 : 0; await act($('#pf button.primary'), () => api.put('/api/contractors/' + state.user.id, o), 'Saved'); };
  bindReplies();
}, A);

function reviewsBlock(p, canReply = false) {
  const r = p.rating || {}, n = r.n || 0, dist = p.distribution || {};
  return `<div class="card stack"><div class="row top"><div><div style="font:600 40px var(--f-head);line-height:1">${r.avg ?? '–'}</div>${starsRow(r.avg, 'big')}<div class="small muted">${n} review${n === 1 ? '' : 's'}</div></div>
      <div class="grow stack tight" style="margin-left:18px">${[5, 4, 3, 2, 1].map(i => `<div class="bars"><div class="b" style="grid-template-columns:22px 1fr 30px"><span class="small">${i}★</span><div class="track"><i style="width:${n ? 100 * (dist[i] || 0) / n : 0}%;background:#e0a400"></i></div><span class="small muted">${dist[i] || 0}</span></div></div>`).join('')}</div></div>
    <div class="critgrid">${CRIT.map(([k, l]) => `<div><span class="small muted">${l}</span><b>${r[k === 'price_score' ? 'price' : k] ?? '–'}</b></div>`).join('')}</div></div>
  <div class="card flush"><div class="card-head"><h3>Reviews</h3></div><div class="list">${(p.reviews || []).map(v => `<div class="stack tight"><div class="row small">${starsRow(v.rating)}<b>${esc(v.author || 'Verified customer')}</b><span class="pill">${v.author_role === 'landlord' ? 'Owner' : 'Tenant'}</span><span class="spacer"></span><span class="muted">${fdate(v.created_at)}</span></div>
      ${v.text ? `<div>${esc(v.text)}</div>` : ''}${v.reply ? `<div class="reply"><b>Reply from the company:</b> ${esc(v.reply)}</div>` : canReply ? `<div class="row"><input class="input" placeholder="Reply publicly…" data-reply="${v.id}"><button class="btn sm" data-send="${v.id}">Reply</button></div>` : ''}</div>`).join('') || '<div class="muted">No reviews yet – every completed job asks the tenant and owner to rate you.</div>'}</div></div>`;
}
function bindReplies() {
  $$('[data-send]').forEach(b => b.onclick = async () => { const v = $(`[data-reply="${b.dataset.send}"]`).value.trim(); if (!v) return; await act(b, () => api.post(`/api/reviews/${b.dataset.send}/reply`, { reply: v }), 'Reply posted'); b.closest('.row').outerHTML = `<div class="reply"><b>Reply from the company:</b> ${esc(v)}</div>`; });
}

// ------------------------------------------------------------------ public: directory, profiles, join
const pubShell = inner => nav('pros') + inner + footer();

route('/pros/join', async () => {
  const s = await api.get('/api/pros/stats');
  $('#app').innerHTML = pubShell(`<section class="hero" style="min-height:0"><div class="bgimg" style="background-image:url('https://images.unsplash.com/photo-1581578731548-c64695cc6952?auto=format&fit=crop&w=2000&q=70')"></div><div class="shade"></div><div class="in">
      <span class="pill jac" style="width:max-content;background:rgba(27,163,160,.18);color:#7fe0dc">${icon('tool')} For maintenance companies</span>
      <h1>Repair jobs near you,<br><em>straight to your phone.</em></h1>
      <p class="lead">List your company on AVA for <b>${R(s.fee)} a month</b>. When a rental within ${s.radius} km needs your trade, you're one of 3 companies asked to quote. The owner chooses – on price, rating and distance. No lead fees, no commission.</p>
      <div class="row wrap"><a class="btn cta lg" href="#signup">Start ${s.trial_days}-day free trial</a><a class="btn lg" style="background:transparent;color:#fff;border-color:rgba(255,255,255,.4)" href="#/pros">See listed companies</a></div></div></section>
    <section class="section"><div class="wrap"><h2>How it works</h2><div class="steps" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
      <div class="step"><h3>A tenant reports a problem</h3><p class="muted">AVA's AI works out the trade and urgency and finds the 3 best listed companies within ${s.radius} km.</p></div>
      <div class="step"><h3>You quote from your phone</h3><p class="muted">See photos, the suburb and the deadline. Send a price and how many days you need – 30 seconds.</p></div>
      <div class="step"><h3>The owner chooses</h3><p class="muted">Owners compare price, rating, distance and your track record. Win the job and you're booked immediately.</p></div>
      <div class="step"><h3>Snap the 'after' photo</h3><p class="muted">One photo completes the job. Hit a problem? Record a voice note – AVA tells the tenant, owner or manager for you.</p></div>
      <div class="step"><h3>Get paid from trust</h3><p class="muted">Payment from the AVA trust account 2 days after the job is confirmed – it confirms itself after 72 h.</p></div>
      <div class="step"><h3>Build your rating</h3><p class="muted">Tenants and owners rate quality, punctuality, price and communication. Better ratings win more work.</p></div></div></div></section>
    <section class="section" style="background:var(--surface);border-block:1px solid var(--line)" id="signup"><div class="wrap grid2" style="align-items:start;gap:40px">
      <div class="stack"><h2>${R(s.fee)} / month. That's it.</h2><div class="pricecard"><b>${R(s.fee)}</b><span>per month, cancel any time</span><ul>
        <li>${icon('check')}Repair requests within ${s.radius} km for your trades</li><li>${icon('check')}Unlimited quotes – no lead or commission fees</li><li>${icon('check')}Public profile with ratings and reviews</li>
        <li>${icon('check')}Photo-proof job completion and voice-note issue reports</li><li>${icon('check')}Payment from the AVA trust account</li><li>${icon('check')}First ${s.trial_days} days free</li></ul></div>
        <p class="small muted">${s.companies} companies listed${s.avg_rating ? ` · average rating ${s.avg_rating}★` : ''} · ${s.requests_month} quote requests sent in the last 30 days.</p></div>
      <form class="card form" id="jf"><h3>List your company</h3>
        <div class="cols"><label class="field"><span>Company name</span><input class="input" name="company" required></label><label class="field"><span>Your name</span><input class="input" name="name" required></label></div>
        <div class="cols"><label class="field"><span>Email</span><input class="input" type="email" name="email" required></label><label class="field"><span>Mobile</span><input class="input" name="phone" required></label></div>
        <label class="field"><span>Password</span><input class="input" type="password" name="password" minlength="6" required></label>
        <div class="field"><span>Trades</span><div class="feat">${['Plumber', 'Electrician', 'Handyman', 'Painter / builder', 'Roofer / waterproofer', 'Tiler', 'Carpentry', 'Locksmith / security', 'Appliance repair', 'Pest control', 'Garden / pool service', 'Solar / inverter installer', 'HVAC technician', 'Glazier'].map(t => `<label class="check"><input type="checkbox" data-trade="${t}">${t}</label>`).join('')}</div></div>
        <label class="field"><span>Base address</span><input class="input" name="base_address" id="ba" placeholder="Where your team works from"></label>
        <div id="jmap" style="height:220px;border-radius:10px;overflow:hidden"></div><input type="hidden" name="lat"><input type="hidden" name="lng">
        <p class="tiny muted">Tap the map at your base. The circle shows the ${s.radius} km request area.</p>
        <div class="cols"><label class="field"><span>Call-out fee (R)</span><input class="input" type="number" name="callout_fee"></label><label class="field"><span>Years in business</span><input class="input" type="number" name="years"></label><label class="field"><span>CIPC reg. no.</span><input class="input" name="registration"></label></div>
        <label class="check"><input type="checkbox" name="insured">We have public liability insurance</label>
        <label class="check small"><input type="checkbox" required>I agree to AVA's terms and to a CIPC, ID and reference check.</label>
        <button class="btn cta lg">Start free trial</button></form></div></section>`);
  const L = window.L, map = L.map('jmap').setView([-26.0, 28.1], 7);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(map);
  let mk, ring;
  const set = ll => { $('[name=lat]').value = ll.lat.toFixed(5); $('[name=lng]').value = ll.lng.toFixed(5); mk ? mk.setLatLng(ll) : (mk = L.marker(ll).addTo(map)); ring ? ring.setLatLng(ll) : (ring = L.circle(ll, { radius: s.radius * 1000, color: '#1ba3a0', fillOpacity: .1 }).addTo(map)); };
  map.on('click', e => set(e.latlng));
  let tm; $('#ba').oninput = () => { clearTimeout(tm); tm = setTimeout(async () => { try { const r = await (await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=za&q=' + encodeURIComponent($('#ba').value))).json(); if (r[0]) { const ll = { lat: +r[0].lat, lng: +r[0].lon }; set(ll); map.setView(ll, 12); } } catch (_) { } }, 700); };
  $('#jf').onsubmit = async e => {
    e.preventDefault(); const f = e.target; const o = Object.fromEntries(new FormData(f));
    o.trades = $$('[data-trade]', f).filter(c => c.checked).map(c => c.dataset.trade).join(', ');
    if (!o.trades) return toast('Choose at least one trade', true);
    if (!o.lat) return toast('Tap the map at your base so we can send you nearby jobs', true);
    o.role = 'contractor'; o.insured = f.insured.checked ? 1 : 0;
    await act($('#jf .btn.cta'), async () => { await api.post('/api/auth/register', o); const { refreshMe } = await import('./core.js'); await refreshMe(); }, 'Welcome to AVA – your free trial has started');
    go('#/app');
  };
});

route('/pros', async (_, q) => {
  $('#app').innerHTML = pubShell(`<div class="wrap section stack"><div class="stack tight"><h1>Maintenance companies on AVA</h1><p class="muted">Vetted companies, rated by tenants and owners on real jobs.</p></div>
    <div class="row wrap"><select class="input" id="tr" style="max-width:240px"><option value="">All trades</option></select><input class="input" id="ar" placeholder="Area, e.g. Pretoria" style="max-width:240px" value="${esc(q.area || '')}"><span class="small muted" id="pc"></span><span class="spacer"></span><a class="btn primary sm" href="#/pros/join">${icon('tool')}List your company – R250/month</a></div>
    <div class="prosplit"><div class="cards" id="pl"></div><div id="dmap" class="dmap"></div></div></div>`);
  const L = window.L, dmap = L.map('dmap', { scrollWheelZoom: false }).setView([-28.5, 25.5], 5);
  L.tileLayer(TILE, { attribution: '© OpenStreetMap' }).addTo(dmap);
  const layer = L.layerGroup().addTo(dmap);
  const stats = await api.get('/api/pros/stats');
  $('#tr').innerHTML += stats.trades.map(t => `<option ${q.trade === t ? 'selected' : ''}>${esc(t)}</option>`).join('');
  const load = async () => {
    const rows = await api.get(`/api/pros?trade=${encodeURIComponent($('#tr').value)}&area=${encodeURIComponent($('#ar').value)}`);
    layer.clearLayers();
    const pts = rows.filter(c => c.lat != null).map(c => { L.marker([c.lat, c.lng], { icon: dotIcon('on') }).addTo(layer).bindPopup(`<b>${esc(c.company || c.name)}</b><br>${c.rating?.avg ? '★ ' + c.rating.avg + ' (' + c.rating.n + ')' : 'New'} · ${esc((c.trades || []).slice(0, 2).join(', '))}<br><a href="#/pro/${c.id}">View profile</a>`); L.circle([c.lat, c.lng], { radius: stats.radius * 1000, color: '#1ba3a0', weight: 1, fillOpacity: .03, interactive: false }).addTo(layer); return [c.lat, c.lng]; });
    if (pts.length) dmap.fitBounds(pts, { padding: [30, 30], maxZoom: 11 });
    $('#pc').textContent = rows.length + ' compan' + (rows.length === 1 ? 'y' : 'ies');
    $('#pl').innerHTML = rows.map(c => `<a class="card stack tight procard" href="#/pro/${c.id}"><div class="row"><span class="avatar" style="width:44px;height:44px">${esc((c.company || c.name).split(' ').map(x => x[0]).slice(0, 2).join(''))}</span><div class="grow"><b>${esc(c.company || c.name)}</b><div class="small muted">${esc(c.base_address || '')}</div></div></div>
      <div class="row small">${starsRow(c.rating?.avg)}<b>${c.rating?.avg ?? 'New'}</b><span class="muted">(${c.rating?.n || 0}) · ${c.jobs_done} jobs</span></div>
      <div class="feat">${(c.trades || []).map(t => `<span>${esc(t)}</span>`).join('')}</div><div class="row wrap" style="gap:4px">${badge(c.vetted, 'Vetted')}${badge(c.insured, 'Insured')}${c.years ? `<span class="pill">${c.years} yrs</span>` : ''}</div></a>`).join('') || '<p class="muted">No companies match.</p>';
  };
  $('#tr').onchange = load; $('#ar').oninput = () => { clearTimeout(window._pt); window._pt = setTimeout(load, 300); };
  load();
});

route('/pro/:id', async ({ id }) => {
  const p = await api.get('/api/pros/' + id);
  $('#app').innerHTML = pubShell(`<div class="wrap section stack"><a class="btn ghost sm" href="#/pros" style="width:max-content">${icon('back')}All companies</a>
    <div class="card row top wrap" style="gap:18px"><span class="avatar" style="width:72px;height:72px;font-size:24px">${esc((p.company || p.name).split(' ').map(x => x[0]).slice(0, 2).join(''))}</span>
      <div class="grow stack tight"><h1>${esc(p.company || p.name)}</h1><div class="small muted">${esc(p.base_address || '')} · on AVA since ${fdate(p.member_since)}</div>
        <div class="feat">${(p.trades || []).map(t => `<span>${esc(t)}</span>`).join('')}</div><div class="row wrap" style="gap:4px">${badge(p.vetted, 'Vetted by AVA')}${badge(p.insured, 'Insured')}${p.years ? `<span class="pill">${p.years} years in business</span>` : ''}${p.bee_level ? `<span class="pill">B-BBEE ${esc(p.bee_level)}</span>` : ''}${p.active ? '' : '<span class="pill warn">Not taking AVA requests</span>'}</div>
        ${p.bio ? `<p>${esc(p.bio)}</p>` : ''}</div>
      <div class="kpis" style="min-width:280px"><div class="kpi"><span>Jobs on AVA</span><b>${p.jobs_done}</b></div><div class="kpi"><span>Avg days to finish</span><b>${p.avg_days ?? '–'}</b></div><div class="kpi"><span>Responds to</span><b>${p.response_rate != null ? p.response_rate + '%' : '–'}</b><small>of requests</small></div></div></div>
    <div class="grid2" style="align-items:start">${reviewsBlock(p)}${p.lat != null ? `<div class="card stack tight"><h3>${icon('map')} Where they work</h3><div id="pmap2" style="height:300px;border-radius:10px;overflow:hidden"></div><p class="tiny muted">Receives AVA requests for rentals within ${p.radius || 10} km of its base.</p></div>` : ''}</div></div>`);
  if (p.lat != null) { const L = window.L, mm = L.map('pmap2', { scrollWheelZoom: false }).setView([p.lat, p.lng], 11); L.tileLayer(TILE, { attribution: '© OpenStreetMap' }).addTo(mm); L.marker([p.lat, p.lng], { icon: dotIcon('on') }).addTo(mm); const c = L.circle([p.lat, p.lng], { radius: (p.radius || 10) * 1000, color: '#1ba3a0', fillOpacity: .08 }).addTo(mm); mm.fitBounds(c.getBounds()); }
});


// ------------------------------------------------------------------ Browse jobs: open repair requests near the company, on a map
const PRIO = { Urgent: 'urgent', High: 'high', Medium: 'medium', Low: 'low' };
route('/app/jobs', async (_, q) => {
  const pg = page('Browse jobs', { sub: 'repairs near you that still need a company' });
  const d = await api.get('/api/contractor/issues');
  if (!d.base) {
    pg.innerHTML = `<div class="card stack"><h3>Set your base first</h3><p class="muted">Pin where your team works from, and AVA shows you every open repair in your area.</p><a class="btn primary" href="#/app/profile">Set my base</a></div>`;
    return;
  }
  const trades = [...new Set(d.issues.map(i => i.trade))].sort();
  pg.innerHTML = `<div class="row wrap" style="margin-bottom:12px"><div class="seg" id="ft"><button data-v="" aria-pressed="true">All (${d.issues.length})</button>${trades.map(t => `<button data-v="${esc(t)}">${esc(t)}</button>`).join('')}</div>
      <span class="spacer"></span><span class="small muted">${icon('pin')} Within ${d.base.radius} km of ${esc(d.base.address || 'your base')} · <a href="#/app/profile">change</a></span></div>
    <div class="jobsplit"><div class="stack" id="jl"></div><div id="jmap2" class="jobmap"></div></div>
    <div class="row wrap small legend" style="margin-top:8px"><span><span class="cpin urgent"></span>Urgent</span><span><span class="cpin high"></span>High</span><span><span class="cpin medium"></span>Medium</span><span><span class="cpin low"></span>Low</span><span><span class="cpin mine"></span>You're quoting</span><span><span class="cpin base"></span>Your base</span></div>`;
  const L = window.L, map = L.map('jmap2', { scrollWheelZoom: false }).setView([d.base.lat, d.base.lng], 11);
  L.tileLayer(TILE, { attribution: '© OpenStreetMap' }).addTo(map);
  const ring = L.circle([d.base.lat, d.base.lng], { radius: d.base.radius * 1000, color: '#1ba3a0', weight: 1.5, fillOpacity: .05 }).addTo(map);
  L.marker([d.base.lat, d.base.lng], { icon: dotIcon('base', '⌂') }).addTo(map).bindPopup('Your base');
  map.fitBounds(ring.getBounds());
  const layer = L.layerGroup().addTo(map);
  let filter = q.trade || '';
  const card = i => `<div class="jobcard2" id="j${i.id}">${i.photo ? `<img class="ph" src="${esc(i.photo)}" data-zoom="${esc(i.photo)}" alt="">` : `<span class="ph">${icon('tool')}</span>`}
    <div class="stack tight"><div class="row wrap" style="gap:6px"><b class="grow">${esc(i.title)}</b><span class="pill prio-${i.priority}">${i.priority}</span></div>
      <div class="meta"><span>${icon('pin')}${esc(i.suburb)}, ${esc(i.city)} · ${i.distance_km} km</span><span>${icon('tool')}${esc(i.trade)}</span><span>${icon('cal')}${ago(i.created_at)}</span>
        <span>${icon('users')}${i.n_quotes} of ${d.max_quotes} quotes</span>${i.quote_deadline && i.status === 'quoting' ? `<span>closes ${fdt(i.quote_deadline)}</span>` : ''}</div>
      ${i.status === 'new' ? `<span class="small" style="color:var(--warn)"><b>No company has quoted yet</b> – be the first.</span>` : ''}
      <div class="row">${i.mine ? `<a class="btn sm primary" href="#/app/ticket/${i.id}">${i.mine === 'requested' ? 'Send your quote' : 'View your quote'}</a><span class="small muted">You're quoting on this job</span>`
        : i.can_apply ? `<button class="btn sm primary" data-apply="${i.id}">Apply to quote</button><span class="tiny muted">Full address after the owner books you</span>`
        : `<span class="small muted">${esc(i.why_not || '')}</span>`}</div></div></div>`;
  const draw = () => {
    const rows = d.issues.filter(i => !filter || i.trade === filter);
    $('#jl').innerHTML = rows.map(card).join('') || `<div class="card muted">No open ${filter ? esc(filter.toLowerCase()) + ' ' : ''}jobs in your area right now. You'll get a notification as soon as one is reported.</div>`;
    layer.clearLayers();
    rows.forEach(i => L.marker([i.lat, i.lng], { icon: dotIcon(i.mine ? 'mine' : PRIO[i.priority] || 'medium') }).addTo(layer)
      .bindPopup(`<b>${esc(i.title)}</b><br>${esc(i.suburb)} · ${i.distance_km} km<br>${i.priority} · ${i.n_quotes} of ${d.max_quotes} quotes`)
      .on('click', () => { const el = $('#j' + i.id); $$('.jobcard2').forEach(x => x.classList.remove('hl')); el.classList.add('hl'); el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }));
    $$('[data-apply]').forEach(b => b.onclick = async () => {
      const i = d.issues.find(x => x.id == b.dataset.apply);
      if (!await confirmBox('Apply to quote', `<b>${esc(i.title)}</b> in ${esc(i.suburb)} (${i.distance_km} km). You'll see the photos and details and can send your price straight away. The owner compares up to ${d.max_quotes} quotes and chooses.`, 'Apply')) return;
      await act(b, () => api.post(`/api/tickets/${i.id}/apply`), "You're in – send your quote");
      go('#/app/ticket/' + i.id);
    });
  };
  $$('#ft button').forEach(b => { b.setAttribute('aria-pressed', b.dataset.v === filter); b.onclick = () => { filter = b.dataset.v; $$('#ft button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(); }; });
  draw();
}, { auth: true });
