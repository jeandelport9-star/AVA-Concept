// Growth & marketing: landlord prospecting (LOOM data), 'what your property can earn' reports, listing syndication to
// Property24 / Private Property with the leads inbox, email/SMS campaigns, the PM brochure – plus the condition score
// and portal cards on a property, and the public report, brochure and owner self-service pages.
import { $, $$, act, ago, api, esc, fdate, fdt, go, icon, initials, modal, R, route, state, toast } from './core.js';
import { page } from './shell.js';
import { nav, footer, FB } from './public.js';

const A = { auth: true };
const PST = { new: ['New', 'info'], contacted: ['Contacted', 'brand'], report_sent: ['Report sent', 'jac'], interested: ['Interested', 'ok'], signed: ['Signed up', 'ok'], not_interested: ['Not interested', ''] };
const ppill = s => { const [w, c] = PST[s] || [s, '']; return `<span class="pill ${c}">${w}</span>`; };
const COND = { 1: 'New / renovated', 2: 'Excellent', 3: 'Well kept', 4: 'Dated', 5: 'Worn', 6: 'Needs major work' };
const link = h => location.origin + location.pathname + h;
const copy = async t => { try { await navigator.clipboard.writeText(t); toast('Link copied'); } catch (_) { prompt('Copy this link', t); } };

route('/app/growth', async (_, q) => {
  if (!['pm', 'admin'].includes(state.user.role)) return go('#/app');
  const pg = page('Growth & marketing', { actions: state.user.role === 'pm' ? `<a class="btn sm" href="#/pm/${state.user.id}" target="_blank">${icon('eye')}<span class="hide-sm">My brochure</span></a>` : '' });
  const s = await api.get('/api/growth/summary');
  const TABS = [['prospects', 'Owner prospects'], ['reports', 'Earnings reports'], ['portals', `Portals & leads${s.syndication.new_leads ? ` (${s.syndication.new_leads})` : ''}`], ['campaigns', 'Email & SMS'], ...(state.user.role === 'pm' ? [['brochure', 'My brochure']] : [])];
  let tab = q.tab || 'prospects';
  const sy = s.syndication.portals;
  pg.innerHTML = `<div class="kpis"><a class="kpi" href="#/app/growth?tab=prospects"><span>Owner prospects</span><b>${s.prospects}</b><small>${s.interested} interested</small></a>
    <a class="kpi" href="#/app/growth?tab=reports"><span>Earnings reports</span><b>${s.reports}</b><small>${s.report_views} views · ${s.report_leads} asked to talk</small></a>
    ${sy.map(p => `<a class="kpi" href="#/app/growth?tab=portals"><span>${esc(p.name)}</span><b>${p.live}</b><small>live · ${p.views} views · ${p.enquiries} enquiries</small></a>`).join('')}</div>
    <div class="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="tb" class="stack"></div>`;
  const show = async k => { tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k)); history.replaceState(null, '', `#/app/growth?tab=${k}`); $('#tb').innerHTML = '<p class="muted">Loading…</p>'; await G[k]($('#tb'), q); };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
}, A);
route('/app/growth/leads', () => go('#/app/growth?tab=portals'), A);

const G = {
  // ------------------------------------------------------------ prospecting
  async prospects(el, q) {
    let st = '', sub = q.suburb || '';
    const draw = async () => {
      const d = await api.get(`/api/growth/prospects?status=${st}&suburb=${encodeURIComponent(sub)}`);
      el.innerHTML = `<div class="card stack"><div class="row wrap"><h3 class="grow">Find owners in your area</h3><span class="pill ${d.provider === 'LOOM' ? 'ok' : ''}">${d.provider === 'LOOM' ? 'LOOM connected' : 'Demo data (connect LOOM in Settings)'}</span><span class="pill info">${d.credits} contact credits</span></div>
          <p class="small muted">Deeds-office data: who owns each home, when they bought, what it's worth. Owners who live elsewhere, trusts and companies are likely investors – the people who need a rental manager.</p>
          <form class="row wrap" id="sf"><input class="input" name="suburb" list="subs" placeholder="Suburb" required style="max-width:220px"><input class="input" name="city" list="cities" placeholder="City" style="max-width:180px">
            <datalist id="subs">${d.areas.map(a => `<option value="${esc(a.suburb)}">`).join('')}</datalist><datalist id="cities">${[...new Set(d.areas.map(a => a.city))].map(c => `<option value="${esc(c)}">`).join('')}</datalist>
            <button class="btn primary">${icon('search')}Search area</button></form>
          <div class="row wrap small">${d.areas.slice(0, 8).map(a => `<button class="btn sm ghost" data-area="${esc(a.suburb)}|${esc(a.city)}">${esc(a.suburb)} <span class="muted">(${a.n} of yours)</span></button>`).join('')}</div></div>
        <div class="row wrap"><div class="seg" id="ps">${[['', 'All'], ...Object.entries(PST).map(([k, [l]]) => [k, l])].map(([v, l]) => `<button data-v="${v}" aria-pressed="${v === st}">${l}${v && d.pipeline[v] ? ` ${d.pipeline[v]}` : ''}</button>`).join('')}</div>
          <select class="input" id="psub" style="max-width:200px"><option value="">All suburbs</option>${d.suburbs.map(x => `<option ${x === sub ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></div>
        <div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Home</th><th>Owner</th><th class="num">Value</th><th class="num">Likely rent</th><th>Status</th><th></th></tr>
          ${d.rows.map(p => `<tr><td><b>${esc(p.address)}</b><div class="tiny muted">${esc(p.suburb)} · erf ${esc(p.erf)} · ${esc(p.type)} ${p.bedrooms} bed · ${Math.round(p.size_m2 || 0)} m²</div></td>
            <td>${esc(p.owner_name)} ${p.investor ? `<span class="pill jac" title="${p.owner_lives_elsewhere ? 'Owner lives at another address' : esc(p.owner_type)}">Investor</span>` : ''}<div class="tiny muted">${esc(p.owner_type)} · bought ${fdate(p.last_sale_date)}</div>
              ${p.contact_revealed ? `<div class="small"><a href="tel:${esc(p.phone)}">${icon('phone')}${esc(p.phone)}</a> · <a href="mailto:${esc(p.email)}">${esc(p.email)}</a></div>` : ''}${p.do_not_contact ? '<span class="pill bad">Do not contact</span>' : ''}</td>
            <td class="num">${R(p.est_value)}</td><td class="num">${R(p.est_rent)}</td><td>${ppill(p.status)}${p.reports.length ? `<div class="tiny muted">report seen ${p.reports[0].views}×</div>` : ''}</td>
            <td class="nowrap">${!p.contact_revealed && !p.do_not_contact ? `<button class="btn sm" data-rev="${p.id}" title="Uses 1 credit">${icon('phone')}Contact</button>` : ''}
              <button class="btn sm" data-rep="${p.id}">${icon('chart')}Report</button><button class="iconbtn" data-ed="${p.id}" title="Status & notes">${icon('cog')}</button></td></tr>`).join('') || '<tr><td colspan="6" class="muted">No prospects yet – search an area above.</td></tr>'}</table></div></div>
        <p class="tiny muted">POPIA: you may phone an owner to introduce AVA; email or SMS them only once they agree (the report's contact form records it). Mark "do not contact" the moment someone objects.</p>`;
      $('#sf').onsubmit = async e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target)); const r = await act($('#sf .btn'), () => api.post('/api/growth/prospects/search', f)); toast(`${r.added} homes added`); sub = f.suburb.trim().replace(/\b\w/g, c => c.toUpperCase()); draw(); };
      $$('[data-area]').forEach(b => b.onclick = () => { const [a, c] = b.dataset.area.split('|'); $('#sf').suburb.value = a; $('#sf').city.value = c; $('#sf').requestSubmit(); });
      $$('#ps button').forEach(b => b.onclick = () => { st = b.dataset.v; draw(); });
      $('#psub').onchange = e => { sub = e.target.value; draw(); };
      $$('[data-rev]').forEach(b => b.onclick = async () => { await act(b, () => api.post(`/api/growth/prospects/${b.dataset.rev}/reveal`), 'Contact details unlocked'); draw(); });
      $$('[data-rep]').forEach(b => b.onclick = async () => { const r = await act(b, () => api.post('/api/growth/reports', { prospect_id: +b.dataset.rep })); reportReady(r); draw(); });
      $$('[data-ed]').forEach(b => b.onclick = () => {
        const p = d.rows.find(x => x.id === +b.dataset.ed);
        const m = modal({ title: p.address, body: `<form class="form" id="ef"><label class="field"><span>Status</span><select class="input" name="status">${d.statuses.map(s => `<option value="${s}" ${s === p.status ? 'selected' : ''}>${PST[s][0]}</option>`).join('')}</select></label>
          <label class="field"><span>Notes</span><textarea class="input" name="note" rows="3">${esc(p.note || '')}</textarea></label>
          <label class="check"><input type="checkbox" name="do_not_contact" ${p.do_not_contact ? 'checked disabled' : ''}>Owner asked not to be contacted (recorded as a POPIA objection)</label></form>`, foot: '<button class="btn primary" id="ok">Save</button>' });
        $('#ok', m).onclick = async () => { const f = $('#ef', m); await act($('#ok', m), () => api.put('/api/growth/prospects/' + p.id, { status: f.status.value, note: f.note.value, do_not_contact: f.do_not_contact.checked && !p.do_not_contact }), 'Saved'); m.close(); draw(); };
      });
    };
    await draw();
  },

  // ------------------------------------------------------------ earnings reports
  async reports(el) {
    const rows = await api.get('/api/growth/reports');
    el.innerHTML = `<div class="row"><p class="small muted grow">A branded report showing an owner what their home should rent for, what a traditional agent would charge and what's left with AVA. Send the link by WhatsApp or email; you see when it is opened.</p>
        <button class="btn primary" id="nr">${icon('plus')}New report</button></div>
      <div class="card flush"><table class="t"><tr><th>Home</th><th class="num">Est. rent</th><th>Made</th><th>Opened</th><th>Owner's reply</th><th></th></tr>
      ${rows.map(r => `<tr><td><b>${esc(r.address || r.suburb)}</b><div class="tiny muted">${esc(r.suburb)}${r.owner ? ' · ' + esc(r.owner) : ''}</div></td><td class="num">${R(r.rent)}</td><td class="small">${fdate(r.created_at)}</td>
        <td class="small">${r.views ? `${r.views}× · ${ago(r.last_viewed_at)}` : '<span class="muted">not yet</span>'}</td>
        <td class="small">${r.lead_at ? `<b>${esc(r.lead_name)}</b> ${esc(r.lead_phone || r.lead_email || '')}<div class="tiny muted">${ago(r.lead_at)}</div>` : ''}</td>
        <td class="nowrap"><a class="btn sm" href="#/r/${r.token}" target="_blank">${icon('eye')}</a><button class="btn sm" data-cp="${r.token}">Copy link</button></td></tr>`).join('') || '<tr><td colspan="6" class="muted">No reports yet.</td></tr>'}</table></div>`;
    $$('[data-cp]').forEach(b => b.onclick = () => copy(link('#/r/' + b.dataset.cp)));
    $('#nr').onclick = () => {
      const m = modal({ title: 'Earnings report', body: `<form class="form" id="rf"><label class="field"><span>Street address</span><input class="input" name="address"></label>
        <div class="cols"><label class="field"><span>Suburb</span><input class="input" name="suburb" required></label><label class="field"><span>City</span><input class="input" name="city"></label></div>
        <div class="cols"><label class="field"><span>Type</span><select class="input" name="type"><option>House</option><option>Townhouse</option><option>Apartment</option><option>Cottage</option></select></label><label class="field"><span>Bedrooms</span><input class="input" type="number" name="bedrooms" value="3" step="0.5"></label>
          <label class="field"><span>Bathrooms</span><input class="input" type="number" name="bathrooms" value="2" step="0.5"></label><label class="field"><span>Size m²</span><input class="input" type="number" name="size_m2"></label></div>
        <div class="cols"><label class="field"><span>Condition</span><select class="input" name="condition_score"><option value="">Not known</option>${Object.entries(COND).map(([k, l]) => `<option value="${k}">C${k} – ${l}</option>`).join('')}</select></label><label class="field"><span>Owner's name</span><input class="input" name="name"></label></div></form>`,
        foot: '<button class="btn primary" id="ok">Make report</button>' });
      $('#ok', m).onclick = async () => { const f = $('#rf', m); if (!f.reportValidity()) return; const r = await act($('#ok', m), () => api.post('/api/growth/reports', Object.fromEntries(new FormData(f)))); m.close(); reportReady(r); G.reports(el); };
    };
  },

  // ------------------------------------------------------------ syndication + leads
  async portals(el) {
    const [o, leads] = await Promise.all([api.get('/api/growth/syndication'), api.get('/api/growth/leads')]);
    el.innerHTML = `<div class="grid2" style="align-items:start"><div class="stack">
        <div class="card flush"><div class="card-head"><h3>Live listings on the portals</h3></div><div class="tablewrap"><table class="t"><tr><th>Listing</th>${o.portals.map(p => `<th>${esc(p.name)}</th>`).join('')}</tr>
        ${o.listings.map(l => `<tr><td><a href="#/app/property/${l.id}?tab=listing"><b>${esc(l.title)}</b></a><div class="tiny muted">${esc(l.suburb)} · ${R(l.rent)}</div>${l.problems.length ? `<div class="tiny" style="color:var(--warn)">Needs ${esc(l.problems.join(', '))}</div>` : ''}</td>
          ${o.portals.map(p => `<td><label class="check small"><input type="checkbox" data-pid="${l.id}" data-portal="${p.portal}" ${l.portals[p.portal] === 'live' || l.portals[p.portal] === 'queued' ? 'checked' : ''} ${l.problems.length ? 'disabled' : ''}>${l.portals[p.portal] === 'live' ? 'Live' : l.portals[p.portal] === 'queued' ? 'Sending' : 'Off'}</label></td>`).join('')}</tr>`).join('') || `<tr><td colspan="3" class="muted">No live listings.</td></tr>`}</table></div>
          <div class="row" style="padding:10px 16px"><button class="btn sm" id="all">${icon('upload')}Send every ready listing to both portals</button></div></div>
        <div class="card stack tight"><h3>Where enquiries come from</h3><div class="costs">${o.portals.map(p => `<div><span>${esc(p.name)} <span class="tiny muted">(${p.mode})</span></span><span>${p.views} views · <b>${p.enquiries}</b> enquiries</span></div>`).join('')}
          <div><span>AVA portal</span><span>${o.ava.views} views · <b>${o.ava.viewings_30d}</b> viewings booked (30 days)</span></div></div>
          <p class="tiny muted">${o.portals.some(p => p.mode === 'simulated') ? 'Simulated until the agency IDs and feed keys are added in Settings. ' : ''}A listing comes off every portal by itself when it is let or taken off the market.</p></div></div>
      <div class="card flush"><div class="card-head"><h3>Leads inbox</h3><span class="pill info">${leads.filter(l => l.status === 'new').length} new</span></div><div class="list">
        ${leads.map(l => `<div class="li" style="align-items:flex-start"><span class="pill ${l.portal === 'property24' ? 'jac' : 'brand'}" style="min-width:34px;justify-content:center">${l.portal === 'property24' ? 'P24' : 'PP'}</span>
          <span class="grow"><b>${esc(l.name)}</b> <span class="small muted">· ${esc(l.title)}</span><span class="small" style="display:block">${esc(l.message || '')}</span>
            <span class="tiny muted"><a href="tel:${esc(l.phone)}">${esc(l.phone)}</a> · <a href="mailto:${esc(l.email)}">${esc(l.email)}</a> · ${ago(l.created_at)}</span></span>
          <span class="stack tight" style="align-items:flex-end">${l.status === 'new' || l.status === 'contacted' ? `<button class="btn sm" data-vw="${l.id}">${icon('cal')}Book viewing</button><button class="btn sm ghost" data-ls="${l.id}" data-s="${l.status === 'new' ? 'contacted' : 'closed'}">${l.status === 'new' ? 'Contacted' : 'Close'}</button>` : `<span class="pill">${l.status}</span>`}</span></div>`).join('') || '<div class="li muted">No enquiries yet.</div>'}</div></div></div>`;
    $$('[data-portal]').forEach(c => c.onchange = async () => { try { await api.post(`/api/properties/${c.dataset.pid}/portals/${c.dataset.portal}`, { on: c.checked }); toast(c.checked ? 'Sent to the portal' : 'Withdrawn'); } catch (e) { c.checked = !c.checked; toast(e.message, true); } G.portals(el); });
    $('#all').onclick = async () => { let n = 0; for (const c of $$('[data-portal]:not(:checked):not(:disabled)')) { try { await api.post(`/api/properties/${c.dataset.pid}/portals/${c.dataset.portal}`, { on: true }); n++; } catch (_) { } } toast(`${n} listings sent`); G.portals(el); };
    $$('[data-ls]').forEach(b => b.onclick = async () => { await api.put('/api/growth/leads/' + b.dataset.ls, { status: b.dataset.s }); G.portals(el); });
    $$('[data-vw]').forEach(b => b.onclick = () => {
      const m = modal({ title: 'Book a viewing', body: `<label class="field"><span>When</span><input class="input" type="datetime-local" id="sl"></label><p class="small muted">The viewing goes into the diary and the lead is marked.</p>`, foot: '<button class="btn primary" id="ok">Book</button>' });
      $('#ok', m).onclick = async () => { if (!$('#sl', m).value) return; await act($('#ok', m), () => api.put('/api/growth/leads/' + b.dataset.vw, { slot: $('#sl', m).value.replace('T', ' ') + ':00' }), 'Viewing booked'); m.close(); G.portals(el); };
    });
  },

  // ------------------------------------------------------------ campaigns
  async campaigns(el) {
    const d = await api.get('/api/crm/campaigns');
    el.innerHTML = `<div class="row"><p class="small muted grow">Service messages (water outage, new debit date, rent increase notice) go to everyone in the group. Marketing goes only to people who opted in, always with an unsubscribe. ${d.simulated.email || d.simulated.sms ? `<b>${[d.simulated.email && 'Email', d.simulated.sms && 'SMS'].filter(Boolean).join(' and ')} simulated</b> until set up in Settings.` : ''}</p>
        <button class="btn primary" id="nc">${icon('send')}New message</button></div>
      <div class="card flush"><table class="t"><tr><th>Message</th><th>Type</th><th>To</th><th>Sent</th><th class="num">Delivered</th><th class="num">Left out</th></tr>
      ${d.campaigns.map(c => `<tr data-c="${c.id}" style="cursor:pointer"><td><b>${esc(c.name)}</b><div class="tiny muted">${c.channel.toUpperCase()} · ${esc(c.author || '')}</div></td><td><span class="pill ${c.kind === 'marketing' ? 'jac' : 'info'}">${c.kind}</span></td>
        <td class="small">${esc(d.groups[c.audience.group] || '')}${c.audience.suburb ? ' · ' + esc(c.audience.suburb) : c.audience.city ? ' · ' + esc(c.audience.city) : ''}</td><td class="small">${c.sent_at ? fdate(c.sent_at) : '<span class="pill warn">Draft</span>'}</td>
        <td class="num">${c.counts.sent ?? ''}</td><td class="num">${c.counts.excluded ?? ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Nothing sent yet.</td></tr>'}</table></div>
      <div class="card flush"><div class="card-head"><h3>Automatic messages</h3><span class="small muted">${d.greetings.birthday ? 'Birthdays ✓' : 'Birthdays off'} · ${d.greetings.anniversary ? 'Lease anniversaries ✓' : 'Anniversaries off'} · by ${esc(d.greetings.channel)}</span></div><div class="list">
        ${d.automatic.map(o => `<div class="li"><span class="pill ${o.subject === 'Happy birthday' ? 'jac' : 'brand'}">${esc(o.subject)}</span><span class="grow"><b>${esc(o.name || o.to_addr)}</b><span class="small muted" style="display:block">${esc(o.body)}</span></span><span class="tiny muted nowrap">${fdate(o.created_at)}</span></div>`).join('') || '<div class="li muted">None yet – they go out on the day.</div>'}</div></div>`;
    $$('[data-c]').forEach(t => t.onclick = () => campaignView(+t.dataset.c, el));
    $('#nc').onclick = () => composer(d, el);
  },

  // ------------------------------------------------------------ brochure
  async brochure(el) {
    const p = await api.get('/api/public/pm/' + state.user.id);
    el.innerHTML = `<div class="grid2" style="align-items:start"><div class="card stack"><h3>About you</h3><p class="small muted">Shown on your brochure and every earnings report. Write it the way you'd introduce yourself to an owner.</p>
        <textarea class="input" id="bio" rows="6">${esc(state.user.bio || '')}</textarea><div class="row"><span class="spacer"></span><button class="btn primary" id="sv">Save</button></div></div>
      <div class="card stack"><h3>Your brochure</h3><p class="small muted">A one-page profile for owners: your homes, occupancy, on-time rent, reviews, fees and live listings. Share the link or print it to PDF.</p>
        <div class="costs"><div><span>Homes managed</span><b>${p.homes}</b></div><div><span>Occupancy</span><b>${p.occupancy ?? '–'}%</b></div><div><span>Rent paid by the 7th</span><b>${p.on_time ?? '–'}%</b></div><div><span>Areas</span><span>${esc(p.areas.slice(0, 4).join(', '))}</span></div></div>
        <div class="row"><a class="btn" href="#/pm/${p.id}" target="_blank">${icon('eye')}Open</a><button class="btn" id="cp">Copy link</button></div></div></div>`;
    $('#sv').onclick = async () => { await act($('#sv'), () => api.put('/api/me', { bio: $('#bio').value }), 'Saved'); state.user.bio = $('#bio').value; };
    $('#cp').onclick = () => copy(link('#/pm/' + p.id));
  },
};

function reportReady(r) {
  const url = link('#/r/' + r.token);
  const m = modal({ title: 'Report ready', body: `<p><b>${esc(r.address || r.suburb)}</b> – likely rent <b>${R(r.rent.estimate)}</b> (${R(r.rent.low)}–${R(r.rent.high)}).</p>
    <p class="small muted">Saving vs a traditional agent: <b>${R(r.agent.saving_month)}</b> a month, ${R(r.agent.saving_year)} a year.</p>
    <input class="input" value="${esc(url)}" readonly onclick="this.select()">`,
    foot: `<a class="btn" href="https://wa.me/?text=${encodeURIComponent('What your property could earn with AVA: ' + url)}" target="_blank">WhatsApp</a><a class="btn" href="#/r/${r.token}" target="_blank">${icon('eye')}Open</a><span class="spacer"></span><button class="btn primary" id="cp">Copy link</button>` });
  $('#cp', m).onclick = () => copy(url);
}

function composer(d, el) {
  const m = modal({ title: 'New message', cls: 'wide', body: `<form class="form" id="cf">
    <div class="cols"><div class="field"><span>Type</span><div class="seg" id="kd"><button type="button" data-v="service" aria-pressed="true">Service</button><button type="button" data-v="marketing" aria-pressed="false">Marketing</button></div></div>
      <div class="field"><span>Send by</span><div class="seg" id="ch"><button type="button" data-v="email" aria-pressed="true">Email</button><button type="button" data-v="sms" aria-pressed="false">SMS</button></div></div></div>
    <div class="cols"><label class="field"><span>To</span><select class="input" name="group">${Object.entries(d.groups).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select></label>
      <label class="field"><span>City (optional)</span><input class="input" name="city"></label><label class="field"><span>Suburb (optional)</span><input class="input" name="suburb"></label></div>
    <label class="field" id="sj"><span>Subject</span><input class="input" name="subject"></label>
    <label class="field"><span>Message</span><textarea class="input" name="body" rows="6" placeholder="Hi {first_name}, …"></textarea></label>
    <div class="row wrap tiny">${d.fields.map(f => `<button type="button" class="btn sm ghost" data-f="${f}">${f}</button>`).join('')}</div></form>
    <div id="pv" class="card tint stack tight" style="margin-top:12px"><span class="small muted">Preview shows who gets it.</span></div>`,
    foot: `<button class="btn" id="prev">${icon('eye')}Preview</button><span class="spacer"></span><button class="btn" id="draft">Save draft</button><button class="btn primary" id="send">${icon('send')}Send now</button>` });
  const f = $('#cf', m);
  let kind = 'service', channel = 'email';
  const seg = (id, set) => $$(`#${id} button`, m).forEach(b => b.onclick = () => { $$(`#${id} button`, m).forEach(x => x.setAttribute('aria-pressed', x === b)); set(b.dataset.v); });
  seg('kd', v => kind = v); seg('ch', v => { channel = v; $('#sj', m).hidden = v === 'sms'; });
  $$('[data-f]', m).forEach(b => b.onclick = () => { const t = f.body; const p = t.selectionStart ?? t.value.length; t.value = t.value.slice(0, p) + b.dataset.f + t.value.slice(p); t.focus(); });
  const payload = () => ({ name: f.subject.value || f.body.value.slice(0, 40), kind, channel, subject: f.subject.value, body: f.body.value, audience: { group: f.group.value, city: f.city.value.trim(), suburb: f.suburb.value.trim() } });
  $('#prev', m).onclick = async () => {
    const r = await act($('#prev', m), () => api.post('/api/crm/preview', payload()));
    $('#pv', m).innerHTML = `<div class="row"><b class="grow">${r.sending} of ${r.total} will get it</b>${r.sms_parts ? `<span class="pill">${r.sms_parts} SMS part${r.sms_parts > 1 ? 's' : ''} each</span>` : ''}</div>
      ${Object.entries(r.excluded).map(([k, n]) => `<div class="small muted">${n} left out: ${esc(k)}</div>`).join('')}
      ${r.sample.to ? `<div class="small"><b>To:</b> ${esc(r.sample.to)}${r.sample.subject ? `<br><b>Subject:</b> ${esc(r.sample.subject)}` : ''}</div><div class="small" style="white-space:pre-wrap;background:var(--surface);padding:10px;border-radius:8px">${esc(r.sample.body)}</div>` : ''}`;
  };
  const save = async (btn, send) => { const r = await act($(btn, m), () => api.post('/api/crm/campaigns', { ...payload(), send }), send ? null : 'Draft saved'); if (send) toast(`Sent to ${r.counts.sent} · ${r.counts.excluded} left out`); m.close(); G.campaigns(el); };
  $('#draft', m).onclick = () => save('#draft', false); $('#send', m).onclick = () => save('#send', true);
}

async function campaignView(id, el) {
  const c = await api.get('/api/crm/campaigns/' + id);
  const m = modal({ title: c.name, cls: 'wide', body: `<p class="small muted">${c.kind} · ${c.channel} · ${c.sent_at ? 'sent ' + fdt(c.sent_at) : 'draft'}</p>
    <div class="small" style="white-space:pre-wrap;background:var(--surface-2);padding:10px;border-radius:8px">${esc(c.body)}</div>
    <table class="t" style="margin-top:10px"><tr><th>To</th><th>Status</th><th>Note</th></tr>${c.outbox.map(o => `<tr><td>${esc(o.name || '')} <span class="tiny muted">${esc(o.to_addr || '')}</span></td><td><span class="pill ${o.status === 'sent' ? 'ok' : o.status === 'failed' ? 'bad' : ''}">${o.status}</span></td><td class="small muted">${esc(o.reason || o.provider_ref || '')}</td></tr>`).join('')}</table>`,
    foot: c.status === 'draft' ? '<span class="spacer"></span><button class="btn primary" id="snd">Send now</button>' : '' });
  $('#snd', m)?.addEventListener('click', async () => { const r = await act($('#snd', m), () => api.post(`/api/crm/campaigns/${id}/send`)); toast(`Sent to ${r.sent}`); m.close(); G.campaigns(el); });
}

// ================================================================== cards on the property page
export function conditionCard(host, p, reload) {
  const s = p.condition_score;
  host.innerHTML = `<div class="card stack tight"><div class="row"><h3 class="grow">${icon('camera')} Condition & finishes</h3>${s ? `<span class="pill ${s <= 2 ? 'ok' : s <= 3 ? 'info' : s <= 4 ? 'warn' : 'bad'}">C${s}</span>` : ''}</div>
    ${s ? `<p class="small"><b>${COND[s]}</b> – ${s <= 2 ? 'adds to' : s >= 4 ? 'takes off' : 'no change to'} the rent check.</p><p class="tiny muted">${esc(p.condition_notes || '')}</p>`
      : '<p class="small muted">Score the home C1 (new) to C6 (needs major work) from its photos or the last inspection. The rent check adjusts for it, the way valuers do.</p>'}
    <div class="row wrap"><button class="btn sm" id="cs">${icon('spark')}${s ? 'Score again' : 'Score it'}</button><select class="input" id="cm" style="max-width:190px"><option value="">…or set by hand</option>${Object.entries(COND).map(([k, l]) => `<option value="${k}">C${k} – ${l}</option>`).join('')}</select></div></div>`;
  $('#cs', host).onclick = async () => { const r = await act($('#cs', host), () => api.post(`/api/properties/${p.id}/condition`), 'Scored'); toast(`C${r.score} – ${r.word}`); reload(); };
  $('#cm', host).onchange = async e => { if (!e.target.value) return; await act(null, () => api.post(`/api/properties/${p.id}/condition`, { score: +e.target.value }), 'Saved'); reload(); };
}

export function portalsCard(host, p) {
  const draw = list => {
    host.innerHTML = `<div class="stack tight" style="border-top:1px solid var(--line);padding-top:12px;margin-top:4px"><b class="small">Also advertise on</b>${list.map(x => `<label class="row small" style="gap:8px">
      <input type="checkbox" data-portal="${x.portal}" ${['live', 'queued'].includes(x.status) ? 'checked' : ''} ${p.listing_status !== 'live' ? 'disabled' : ''}><span class="grow"><b>${esc(x.name)}</b> ${x.mode === 'simulated' ? '<span class="tiny muted">(simulated)</span>' : ''}
      ${x.status === 'live' ? `<span class="tiny muted">· ${esc(x.portal_ref)} · ${x.views} views · ${x.enquiries} enquiries</span>` : x.status === 'queued' ? '<span class="tiny muted">· sending</span>' : ''}</span>
      ${x.url && x.mode !== 'simulated' ? `<a class="tiny" href="${esc(x.url)}" target="_blank">view</a>` : ''}</label>`).join('')}
      ${p.listing_status !== 'live' ? '<span class="tiny muted">Publish first – the portals get the same listing.</span>' : ''}</div>`;
    $$('[data-portal]', host).forEach(c => c.onchange = async () => { try { draw(await api.post(`/api/properties/${p.id}/portals/${c.dataset.portal}`, { on: c.checked })); toast(c.checked ? 'Sent' : 'Withdrawn'); } catch (e) { c.checked = !c.checked; toast(e.message, true); } });
  };
  draw(p.portals || []);
}

// ================================================================== public: earnings report, PM brochure, owner self-service
const app = () => $('#app');

route('/r/:token', async ({ token }) => {
  const r = await api.get('/api/public/report/' + token);
  const pm = r.pm;
  const a = r.agent;
  app().innerHTML = nav('landlords') + `<div class="wrap section stack loose" style="max-width:960px">
    <div class="stack tight"><span class="pill brand" style="width:max-content">Rental earnings report · ${fdate(r.made)}</span>
      <h1>What ${esc(r.address || 'your home')} could earn</h1><p class="muted">${esc(r.type || '')} · ${r.bedrooms} bedrooms${r.bathrooms ? ` · ${r.bathrooms} bathrooms` : ''}${r.size_m2 ? ` · ${Math.round(r.size_m2)} m²` : ''} · ${esc(r.suburb)}${r.city ? ', ' + esc(r.city) : ''}${r.owner ? ` · prepared for ${esc(r.owner)}` : ''}</p></div>
    <div class="grid2" style="align-items:start">
      <div class="card stack" style="background:var(--brand);color:#fff;border:0"><span class="small" style="opacity:.85">Likely monthly rent</span><b style="font:600 44px var(--f-head)">${R(r.rent.estimate)}</b>
        <span class="small" style="opacity:.85">Range ${R(r.rent.low)} – ${R(r.rent.high)}${r.gross_yield ? ` · gross yield ${r.gross_yield}% on ${R(r.est_value)}` : ''} · typically let in ~${r.days_to_let} days</span>
        <div class="tiny" style="opacity:.75">${r.rent.basis.map(esc).join(' · ')}</div></div>
      <div class="card stack"><h3>Management cost per month</h3><div class="costs">
        <div><span>Traditional agent (${a.agent_pct}% + VAT)</span><span class="num">${R(a.traditional_monthly)}</span></div>
        <div><span>AVA (platform fee + portfolio manager)</span><span class="num">${R(a.ava_monthly)}</span></div>
        <div class="tot"><span>You keep extra</span><span class="num" style="color:var(--ok)">${R(a.saving_month)} / month</span></div></div>
        <p class="small"><b>${R(a.saving_year)} more a year</b>, with the same service: vetting, lease, deposit in trust, 360° inspections, rent collection and a monthly statement.</p></div></div>
    <div class="card stack"><h3>What you'd receive each month</h3><div class="costs">${r.ava.lines.map(l => `<div><span>${esc(l.label)}</span><span class="num">−${R(l.amount)}</span></div>`).join('')}
      <div class="tot"><span>Paid to you on the 7th (from ${R(r.rent.estimate)} rent)</span><span class="num">${R(r.ava.net)}</span></div></div></div>
    ${r.comparables.length ? `<div class="card flush"><div class="card-head"><h3>Similar homes</h3></div><table class="t"><tr><th>Home</th><th>Suburb</th><th>Beds</th><th class="num">m²</th><th class="num">Rent</th></tr>${r.comparables.map(c => `<tr><td>${esc(c.title)}</td><td>${esc(c.suburb)}</td><td>${c.bedrooms}</td><td class="num">${c.size_m2 ? Math.round(c.size_m2) : ''}</td><td class="num">${R(c.rent)}</td></tr>`).join('')}</table></div>` : ''}
    <div class="grid2" style="align-items:start">
      ${pm ? `<div class="card stack"><div class="row"><span class="avatar" style="width:52px;height:52px;font-size:19px">${initials(pm.name)}</span><div class="grow"><b>${esc(pm.name)}</b><div class="small muted">${esc(pm.company || 'AVA portfolio manager')}</div></div></div>
        <p class="small">${esc(pm.bio)}</p><div class="costs"><div><span>Homes managed</span><b>${pm.homes}</b></div>${pm.occupancy != null ? `<div><span>Occupancy</span><b>${pm.occupancy}%</b></div>` : ''}${pm.on_time != null ? `<div><span>Rent paid on time</span><b>${pm.on_time}%</b></div>` : ''}</div>
        <a class="btn" href="#/pm/${pm.id}">${icon('eye')}See ${esc(pm.name.split(' ')[0])}'s profile</a></div>` : ''}
      <div class="card stack" id="lead">${r.lead_sent ? `<h3>${icon('check')} Thanks – we'll be in touch</h3>` : `<h3>Talk to us</h3><p class="small muted">Leave your details and ${pm ? esc(pm.name.split(' ')[0]) : 'a portfolio manager'} will call you. No obligation.</p>
        <form class="form" id="lf"><label class="field"><span>Name</span><input class="input" name="name" required value="${esc(r.owner || '')}"></label><div class="cols"><label class="field"><span>Mobile</span><input class="input" name="phone"></label><label class="field"><span>Email</span><input class="input" type="email" name="email"></label></div>
          <label class="check small"><input type="checkbox" name="consent" required>AVA may contact me about letting this property (see the <a href="#/privacy-notice">privacy notice</a>).</label>
          <label class="check small"><input type="checkbox" name="marketing">Also send me rental-market news (optional).</label><button class="btn cta">Call me</button></form>`}</div></div>
    <p class="tiny muted">Estimates are based on comparable rentals and the condition of the home, not a valuation. Fees as published on ava.co.za; VAT included where it applies.</p>
  </div>` + footer();
  $('#lf') && ($('#lf').onsubmit = async e => { e.preventDefault(); const f = e.target; await act($('#lf .btn'), () => api.post(`/api/public/report/${token}/lead`, { name: f.name.value, phone: f.phone.value, email: f.email.value, consent: f.consent.checked, marketing: f.marketing.checked }), 'Thank you!'); $('#lead').innerHTML = `<h3>${icon('check')} Thanks – we'll be in touch</h3>`; });
});

route('/pm/:id', async ({ id }) => {
  const p = await api.get('/api/public/pm/' + id);
  app().innerHTML = nav('landlords') + `<div class="wrap section stack loose" style="max-width:960px">
    <div class="row wrap" style="gap:20px"><span class="avatar" style="width:84px;height:84px;font-size:30px">${initials(p.name)}</span><div class="grow stack tight"><span class="pill brand" style="width:max-content">AVA portfolio manager</span><h1 style="margin:0">${esc(p.name)}</h1>
      <span class="muted">${esc(p.company || '')}${p.since ? ' · on AVA since ' + p.since : ''}${p.rating ? ` · ★ ${p.rating} (${p.reviews} reviews)` : ''}</span></div>
      <div class="stack tight noprint">${p.phone ? `<a class="btn cta" href="tel:${esc(p.phone)}">${icon('phone')}${esc(p.phone)}</a>` : ''}<a class="btn" href="mailto:${esc(p.email)}">Email</a><button class="btn ghost" onclick="print()">${icon('print')}Print / PDF</button></div></div>
    <p style="max-width:720px">${esc(p.bio)}</p>
    <div class="kpis"><div class="kpi"><span>Homes managed</span><b>${p.homes}</b></div>${p.occupancy != null ? `<div class="kpi"><span>Occupancy</span><b>${p.occupancy}%</b></div>` : ''}${p.on_time != null ? `<div class="kpi"><span>Rent paid by the 7th</span><b>${p.on_time}%</b></div>` : ''}<div class="kpi"><span>Areas</span><b style="font-size:16px">${esc(p.areas.slice(0, 3).join(', '))}</b></div></div>
    <div class="grid2" style="align-items:start"><div class="card stack"><h3>What owners pay</h3><div class="costs"><div><span>AVA platform</span><span>from ${R(p.ava_fee_from)} per home / month</span></div><div><span>Portfolio manager</span><span>${p.commission_pct}% of rent collected</span></div><div><span>Traditional agent, for comparison</span><span>${p.agent_pct}% + VAT</span></div></div>
        <a class="btn" href="#/earn?pm=${p.id}">${icon('chart')}What could my home earn?</a></div>
      <div class="card stack"><h3>Every home gets</h3><ul class="small" style="margin:0;padding-left:18px"><li>Tenants vetted: affordability, credit, TPN and FICA identity check</li><li>Digital lease, deposit in an interest-bearing trust account</li><li>Rent by DebiCheck debit order; arrears followed up the next day</li><li>Joint 360° ingoing and outgoing inspections</li><li>Payout on the 7th with a statement, every rand traced</li><li>Listed on AVA, Property24 and Private Property</li></ul></div></div>
    ${p.listings.length ? `<h2>Homes ${esc(p.name.split(' ')[0])} has to let</h2><div class="cards">${p.listings.map(l => `<a class="lcard" href="#/p/${l.id}"><div class="ph"><img src="${esc(l.photo || FB)}" data-fb="${FB}" alt="" loading="lazy"></div><div class="bd"><div class="price">${R(l.rent)} <small>per month</small></div><b class="ttl">${esc(l.title)}</b><span class="small muted">${esc(l.suburb)} · ${l.bedrooms} bed · ${l.bathrooms} bath</span></div></a>`).join('')}</div>` : ''}
  </div>` + footer();
});

route('/earn', async (_, q) => {
  app().innerHTML = nav('landlords') + `<div class="wrap section stack" style="max-width:720px">
    <span class="pill brand" style="width:max-content">For owners</span><h1>What could my home earn?</h1><p class="muted">A free estimate from comparable rentals near you, and what you'd keep with AVA versus a traditional agent.</p>
    <form class="card form" id="ef"><label class="field"><span>Street address (optional)</span><input class="input" name="address"></label>
      <div class="cols"><label class="field"><span>Suburb</span><input class="input" name="suburb" required></label><label class="field"><span>City</span><input class="input" name="city" required></label></div>
      <div class="cols"><label class="field"><span>Type</span><select class="input" name="type"><option>House</option><option>Townhouse</option><option>Apartment</option><option>Cottage</option></select></label><label class="field"><span>Bedrooms</span><input class="input" type="number" name="bedrooms" value="3" step="0.5" min="0.5"></label>
        <label class="field"><span>Bathrooms</span><input class="input" type="number" name="bathrooms" value="2" step="0.5"></label><label class="field"><span>Size m² (optional)</span><input class="input" type="number" name="size_m2"></label></div>
      <label class="field"><span>Condition</span><select class="input" name="condition_score"><option value="">Not sure</option>${Object.entries(COND).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
      <button class="btn cta lg">${icon('chart')}Show my estimate</button></form></div>` + footer();
  $('#ef').onsubmit = async e => { e.preventDefault(); const r = await act($('#ef .btn'), () => api.post('/api/public/earn', Object.fromEntries(new FormData(e.target)))); go('#/r/' + r.token); };
});
