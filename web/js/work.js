// Maintenance: tenant reports → AI triage → quotes → landlord approval → contractor → completion → rating → deducted from rent.
import { $, $$, act, ago, api, confirmBox, esc, fdate, fdt, formData, go, icon, initials, modal, pickFiles, pill, R, R2, route, stars, state, toast, upload } from './core.js';
import { page } from './shell.js';
import { marketBlocks, bindMarket, mapCard, bindMap } from './market.js';

const A = { auth: true };
const COLS = [['new', 'New'], ['quoting', 'Getting quotes'], ['awaiting_approval', 'Needs approval'], ['approved', 'Approved'], ['scheduled', 'Booked'], ['in_progress', 'In progress'], ['completed', 'Done – confirm']];

route('/app/maintenance', async (_, q) => {
  const u = state.user;
  const pg = page(u.role === 'landlord' ? 'Repairs & approvals' : u.role === 'tenant' ? 'Repairs' : 'Maintenance',
    { actions: `<a class="btn primary sm" href="#/app/maintenance/new">${icon('plus')}${u.role === 'tenant' ? 'Report a problem' : 'Log repair'}</a>` });
  const rows = await api.get('/api/tickets');
  let view = q.view || (u.role === 'pm' || u.role === 'admin' ? (innerWidth > 860 ? 'board' : 'list') : 'list');
  const open = rows.filter(t => !['closed', 'cancelled'].includes(t.status));
  pg.innerHTML = `${['pm', 'admin', 'landlord'].includes(u.role) ? `<div class="kpis"><div class="kpi ${rows.some(t => t.priority === 'Urgent' && !['closed', 'completed', 'cancelled'].includes(t.status)) ? 'alert' : ''}"><span>Urgent open</span><b>${open.filter(t => t.priority === 'Urgent').length}</b></div>
    <div class="kpi"><span>Open</span><b>${open.length}</b></div><div class="kpi"><span>Waiting on approval</span><b>${rows.filter(t => t.status === 'awaiting_approval').length}</b></div>
    <div class="kpi"><span>Spend (closed)</span><b>${R(rows.filter(t => ['completed', 'closed'].includes(t.status)).reduce((a, t) => a + (t.cost || 0), 0))}</b></div></div>` : ''}
    <div class="row wrap"><input class="input" id="ms" placeholder="Search" style="max-width:260px">${['pm', 'admin'].includes(u.role) ? `<div class="seg" id="mv"><button data-v="board" aria-pressed="${view === 'board'}">Board</button><button data-v="list" aria-pressed="${view === 'list'}">List</button></div>` : ''}
      <label class="check small"><input type="checkbox" id="closed">Show closed</label></div><div id="mb"></div>`;
  const draw = () => {
    const s = $('#ms').value.toLowerCase(), showClosed = $('#closed').checked;
    const list = rows.filter(t => (showClosed || !['closed', 'cancelled'].includes(t.status)) && (!s || `${t.title} ${t.ref} ${t.ptitle} ${t.category}`.toLowerCase().includes(s)));
    if (view === 'board') {
      $('#mb').innerHTML = `<div class="board">${COLS.map(([k, l]) => { const c = list.filter(t => t.status === k || (k === 'new' && t.status === 'info_needed')); return `<div class="col"><h4>${l}<span>${c.length}</span></h4>${c.map(card).join('')}</div>`; }).join('')}</div>`;
    } else {
      $('#mb').innerHTML = `<div class="card flush list">${list.map(t => `<a class="li" href="#/app/ticket/${t.id}"><span class="dot ${t.priority === 'Urgent' ? 'bad' : t.priority === 'High' ? 'warn' : ''}"></span><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted">${t.ref} · ${esc(t.ptitle)} · ${esc(t.category || '')} · ${ago(t.created_at)}</span></span>${t.cost ? `<span class="num small hide-sm">${R(t.cost)}</span>` : ''}${pill(t.status)}</a>`).join('') || '<div class="empty"><h3>No repairs</h3><p>Nice.</p></div>'}</div>`;
    }
  };
  const card = t => `<a class="tcard" href="#/app/ticket/${t.id}"><div class="row"><span class="tiny mono muted">${t.ref}</span><span class="spacer"></span><span class="tiny prio-${t.priority}">${t.priority}</span></div><b>${esc(t.title)}</b>
    <span class="tiny muted">${esc(t.ptitle)} · ${esc(t.category || '')}</span><div class="row tiny muted">${t.contractor_company ? icon('tool') + esc(t.contractor_company) : t.quotes_in ? `${t.quotes_in} quote(s) in` : ''}<span class="spacer"></span>${ago(t.updated_at)}</div>
    ${t.sentiment === 'negative' ? '<span class="pill bad">Upset tenant</span>' : ''}${t.responsible === 'tenant' ? '<span class="pill warn">Tenant liable</span>' : ''}</a>`;
  $('#ms').oninput = draw; $('#closed').onchange = draw;
  $$('#mv button').forEach(b => b.onclick = () => { view = b.dataset.v; $$('#mv button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(); });
  draw();
}, A);

route('/app/maintenance/new', async (_, q) => {
  const u = state.user;
  const pg = page(u.role === 'tenant' ? 'Report a problem' : 'Log repair', { back: '#/app/maintenance' });
  const props = u.role === 'tenant' ? [] : await api.get('/api/properties');
  const files = [];
  pg.innerHTML = `<div class="grid2" style="align-items:start"><form class="card form" id="tf">
    ${props.length ? `<label class="field"><span>Property</span><select class="input" name="property_id" required>${props.map(p => `<option value="${p.id}" ${q.property == p.id ? 'selected' : ''}>${esc(p.title)}</option>`).join('')}</select></label>` : ''}
    <label class="field"><span>What's wrong?</span><input class="input" name="title" id="tt" required placeholder="e.g. Geyser leaking in the roof"></label>
    <label class="field"><span>Details</span><textarea class="input" name="description" id="td" rows="4" placeholder="When did it start? Is it getting worse? Best times for access?"></textarea></label>
    <label class="field"><span>Room</span><input class="input" name="room" list="rooms" placeholder="Kitchen"><datalist id="rooms">${['Kitchen', 'Lounge', 'Bathroom', 'Main bedroom', 'Bedroom 2', 'Garage', 'Garden', 'Roof'].map(r => `<option>${r}</option>`).join('')}</datalist></label>
    <div class="field"><span>Photos or a short video</span><div class="thumbs" id="ph"><button type="button" class="add" id="addph">${icon('camera')}</button></div></div>
    <button class="btn cta lg" id="send">Send to AVA</button></form>
    <div class="stack"><div class="card stack tight" id="tri"><h3><span class="ai">${icon('spark')} AVA triage</span></h3><p class="small muted">Start typing – AVA works out the trade, urgency and who's responsible, and sends it to the best-rated contractors near you.</p></div>
      <div class="card stack tight"><h3>${icon('alert')} Emergency?</h3><p class="small">Burst pipes, gas smells, sparks or no power, break-ins and lock-outs are dispatched immediately to the nearest approved contractor – you don't have to wait for quotes.</p></div></div></div>`;
  const drawPh = () => { $('#ph').innerHTML = files.map(f => `<img src="${URL.createObjectURL(f)}" alt="">`).join('') + `<button type="button" class="add" id="addph">${icon('camera')}</button>`; $('#addph').onclick = add; };
  const add = async () => { files.push(...await pickFiles({ accept: 'image/*,video/*', capture: undefined })); drawPh(); };
  $('#addph').onclick = add;
  let t;
  const tri = () => { clearTimeout(t); t = setTimeout(async () => {
    const r = await api.post('/api/triage', { title: $('#tt').value, description: $('#td').value });
    $('#tri').innerHTML = `<h3><span class="ai">${icon('spark')} AVA triage</span></h3><div class="row wrap"><span class="pill">${esc(r.category)}</span><span class="pill prio-${r.priority}">${r.priority}</span><span class="pill">${esc(r.trade)}</span>${r.responsible === 'tenant' ? '<span class="pill warn">Tenant may be liable</span>' : ''}</div>
      ${r.advice ? `<div class="ai-note" style="background:var(--bad-tint);color:var(--bad)">${icon('alert')}<span><b>Do this now:</b> ${esc(r.advice)}</span></div>` : ''}<p class="tiny muted">${esc(r.why.join(' · ') || 'No specific keywords yet')}</p>`;
  }, 350); };
  $('#tt').oninput = tri; $('#td').oninput = tri;
  $('#tf').onsubmit = async e => {
    e.preventDefault();
    const fd = formData(e.target); files.forEach(f => fd.append('photos', f));
    const r = await act($('#send'), () => api.post('/api/tickets', fd));
    toast(r.status === 'approved' ? `${r.ref}: emergency – contractor dispatched` : `${r.ref} logged – quotes requested`);
    go('#/app/ticket/' + r.id);
  };
}, A);

route('/app/ticket/:id', async ({ id }) => ticketView(id), A);

async function ticketView(id) {
  const t = await api.get('/api/tickets/' + id);
  const u = state.user, c = t.can;
  const pg = page(`${t.ref} · ${t.title}`, { back: '#/app/maintenance' });
  const steps = ['new', 'quoting', 'awaiting_approval', 'approved', 'scheduled', 'in_progress', 'completed', 'closed'];
  const si = Math.max(0, steps.indexOf(t.status));
  const best = t.quotes.find(q => q.status === 'shortlisted') || t.quotes.find(q => q.status === 'submitted');
  pg.innerHTML = `<div class="card stack tight"><div class="row wrap">${pill(t.status)}<span class="pill prio-${t.priority}">${t.priority}</span><span class="pill">${esc(t.category || '')}</span>${t.responsible === 'tenant' ? '<span class="pill warn">Tenant liable</span>' : ''}${t.sentiment === 'negative' ? '<span class="pill bad">Upset</span>' : ''}<span class="spacer"></span><span class="small muted">${esc(t.property.title)}${t.room ? ' · ' + esc(t.room) : ''}</span></div>
      <div class="meter" title="Progress"><i style="width:${(si + 1) / steps.length * 100}%"></i></div></div>
    <div class="grid2" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);align-items:start"><div class="stack">
      ${marketBlocks(t, u)}${mapCard(t)}


      ${c.quote ? `<div class="card stack"><h3>Your quote</h3><form class="form" id="qf"><div class="cols"><label class="field"><span>Amount incl. VAT (R)</span><input class="input" type="number" step="1" name="amount" required value="${t.quotes[0]?.amount || ''}"></label><label class="field"><span>Days to complete</span><input class="input" type="number" name="eta_days" value="${t.quotes[0]?.eta_days || 2}"></label></div>
        <label class="field"><span>Notes / scope</span><textarea class="input" name="notes" rows="2">${esc(t.quotes[0]?.notes || '')}</textarea></label><label class="field"><span>Quote document (optional)</span><input class="input" type="file" name="file" accept=".pdf,image/*"></label><button class="btn primary">Submit quote</button></form>
        ${t.quote_deadline ? `<p class="tiny muted">Quotes close ${fdt(t.quote_deadline)}</p>` : ''}</div>` : ''}


      <div class="card stack"><h3>Timeline</h3><div class="timeline">${t.events.map(e => `<div class="ev ${e.internal ? 'internal' : ''}"><span class="av ${!e.user_id ? 'ai' : ''}">${e.user_id ? initials(e.user_name) : '✦'}</span><div class="bubble"><div class="small"><b>${e.user_id ? esc(e.user_name) : 'AVA'}</b> <span class="muted">· ${fdt(e.created_at)}${e.internal ? ' · internal' : ''}</span></div>${esc(e.text || '')}${e.photo ? `<img src="${esc(e.photo)}" data-zoom="${esc(e.photo)}" alt="">` : ''}${e.audio ? `<audio controls preload="none" src="${esc(e.audio)}" style="width:100%;margin-top:6px"></audio>` : ''}</div></div>`).join('')}</div>
        ${c.reply ? `<form class="row" id="cf" style="align-items:flex-end"><textarea class="input" id="ct" rows="1" placeholder="Add a message or photo…"></textarea><button type="button" class="iconbtn" id="cph" title="Photo">${icon('camera')}</button>${['pm', 'admin'].includes(u.role) ? `<label class="check tiny" title="Only staff see it"><input type="checkbox" id="cint">Internal</label>` : ''}<button class="btn primary">Send</button></form>` : ''}</div></div>
    <div class="stack">
      ${(t.photos || []).length || (t.after_photos || []).length ? `<div class="card stack tight"><h3>Photos</h3>${(t.photos || []).length ? `<span class="tiny muted">Reported</span><div class="thumbs">${t.photos.map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" alt="">`).join('')}</div>` : ''}${(t.after_photos || []).length ? `<span class="tiny muted">After</span><div class="thumbs">${t.after_photos.map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" alt="">`).join('')}</div>` : ''}</div>` : ''}
      <div class="card stack tight"><h3>Details</h3><p style="white-space:pre-wrap">${esc(t.description || '–')}</p><div class="costs">
        <div><span>Reported</span><span>${fdt(t.created_at)}</span></div>${t.tenant ? `<div><span>Tenant</span><span>${esc(t.tenant.name)} ${esc(t.tenant.phone || '')}</span></div>` : ''}
        <div><span>Contractor</span><span>${t.contractor ? esc(t.contractor.company || t.contractor.name) + ' ' + esc(t.contractor.phone || '') : '–'}</span></div>${t.scheduled_for ? `<div><span>Booked</span><span>${fdt(t.scheduled_for)}</span></div>` : ''}
        <div><span>Cost</span><b>${t.cost ? R2(t.cost) : '–'}</b></div><div><span>Paid from</span><span>${t.responsible === 'tenant' ? 'Charged to tenant' : t.deduct_from_rent ? 'Deducted from rent' : 'Owner pays directly'}</span></div></div>
        ${t.property.address && u.role !== 'tenant' && t.booked ? `<a class="btn sm" target="_blank" href="https://www.google.com/maps/dir/?api=1&destination=${t.property.lat},${t.property.lng}">${icon('map')}Directions</a>` : ''}</div>
      ${t.ai_notes && ['pm', 'admin'].includes(u.role) ? `<div class="ai-note">${icon('spark')}<span>${esc(t.ai_notes)}</span></div>` : ''}
      ${c.manage ? `<div class="card stack tight"><h3>Manage</h3><div class="form cols"><label class="field"><span>Priority</span><select class="input" id="mp">${['Urgent', 'High', 'Medium', 'Low'].map(p => `<option ${t.priority === p ? 'selected' : ''}>${p}</option>`).join('')}</select></label>
          <label class="field"><span>Responsible</span><select class="input" id="mr"><option value="landlord">Landlord</option><option value="tenant" ${t.responsible === 'tenant' ? 'selected' : ''}>Tenant</option></select></label></div>
        <label class="check small"><input type="checkbox" id="md" ${t.deduct_from_rent ? 'checked' : ''}>Deduct cost from next rent payout</label>
        <div class="row wrap"><button class="btn sm" id="msave">Save</button>${t.status === 'quoting' && t.quotes.some(q => q.status === 'submitted') ? `<button class="btn sm" id="sl">Close quotes now</button>` : ''}<button class="btn sm" id="assign">Assign directly</button><button class="btn sm" id="info">Ask for info</button><button class="btn sm danger" id="cancel">Cancel</button></div></div>
        ${t.quotes.length && !c.approve ? `<div class="card stack tight"><h3>Quotes</h3>${t.quotes.map(q => `<div class="row small"><span class="grow">${esc(q.company || q.contractor_name)}</span>${q.amount ? R2(q.amount) : ''} ${pill(q.status)}</div>`).join('')}</div>` : ''}` : ''}
    </div></div>`;
  const reload = () => ticketView(id);
  bindMarket(t, u, reload); bindMap(t, reload);
  $('#qf')?.addEventListener('submit', async e => { e.preventDefault(); await act($('#qf button'), () => api.post(`/api/tickets/${id}/quotes`, formData(e.target)), 'Quote submitted'); reload(); });
  let cfiles = [];
  $('#cph')?.addEventListener('click', async () => { cfiles = await pickFiles(); if (cfiles.length) toast(`${cfiles.length} photo(s) attached`); });
  $('#cf')?.addEventListener('submit', async e => { e.preventDefault(); const fd = new FormData(); fd.set('text', $('#ct').value); if ($('#cint')?.checked) fd.set('internal', '1'); cfiles.forEach(f => fd.append('photos', f)); await act(null, () => api.post(`/api/tickets/${id}/event`, fd)); reload(); });
  $('#msave')?.addEventListener('click', async () => { await act($('#msave'), () => api.put('/api/tickets/' + id, { priority: $('#mp').value, responsible: $('#mr').value, deduct_from_rent: $('#md').checked ? 1 : 0 }), 'Saved'); reload(); });
  $('#sl')?.addEventListener('click', async () => { await act($('#sl'), () => api.post(`/api/tickets/${id}/shortlist`), 'Shortlist sent to landlord'); reload(); });
  $('#cancel')?.addEventListener('click', async () => { if (await confirmBox('Cancel request', 'Cancel this request? The tenant is told.', 'Cancel request')) { await api.post(`/api/tickets/${id}/status`, { status: 'cancelled' }); reload(); } });
  $('#info')?.addEventListener('click', () => { const m = modal({ title: 'Ask for more information', body: `<div class="seg" id="to"><button aria-pressed="true" data-v="tenant">Tenant</button><button data-v="landlord">Landlord</button></div><textarea class="input" id="it" rows="3" placeholder="e.g. Please send a photo of the geyser nameplate"></textarea>`, foot: '<button class="btn primary" id="ok">Send</button>' });
    let to = 'tenant'; $$('#to button', m).forEach(b => b.onclick = () => { to = b.dataset.v; $$('#to button', m).forEach(x => x.setAttribute('aria-pressed', x === b)); });
    $('#ok', m).onclick = async () => { await api.post(`/api/tickets/${id}/request-info`, { to, text: $('#it', m).value }); m.close(); reload(); }; });
  $('#assign')?.addEventListener('click', () => { const m = modal({ title: 'Assign directly', body: `<p class="small muted">Skip quoting – e.g. a regular handyman or a small job. AVA's suggestion for <b>${esc(t.trade)}</b>:</p><div class="list">${t.suggested.map(s => `<label class="li check"><input type="radio" name="c" value="${s.id}"><span class="grow"><b>${esc(s.company || s.name)}</b> <span class="small muted">rating ${s.rating ? (+s.rating).toFixed(1) : 'new'} · ${s.load} open jobs · call-out ${R(s.callout_fee)}</span></span></label>`).join('') || '<p class="muted">No matching contractors.</p>'}</div><label class="field"><span>Agreed price (optional)</span><input class="input" type="number" id="ap"></label>`, foot: '<button class="btn primary" id="ok">Assign</button>' });
    $('#ok', m).onclick = async () => { const c = $('input[name=c]:checked', m); if (!c) return toast('Choose a contractor', true); await api.post(`/api/tickets/${id}/assign`, { contractor_id: +c.value, cost: $('#ap', m).value }); m.close(); reload(); }; });
}

export { contractorHome } from './market.js';


