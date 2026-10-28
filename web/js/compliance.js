// FICA identity checks and POPIA: the person's own Identity & privacy page, the staff FICA register and review,
// the admin's data-subject request queue and consent register, and the public privacy notice.
import { $, $$, act, api, esc, fdate, fdt, go, icon, modal, route, state, toast, today } from './core.js';
import { page } from './shell.js';
import { nav, footer } from './public.js';

const A = { auth: true };
const KST = { verified: ['Verified', 'ok'], review: ['Needs a look', 'warn'], failed: ['Failed', 'bad'], none: ['Not done', ''], draft: ['Started', ''] };
export const kpill = s => { const [w, c] = KST[s || 'none'] || [s, '']; return `<span class="pill ${c}">${w}</span>`; };
const RES = { pass: ['ok', 'check'], warn: ['warn', 'alert'], fail: ['bad', 'x'] };
const checks = list => `<div class="list">${list.map(c => `<div class="li"><span class="pill ${RES[c.result][0]}" style="min-width:28px;justify-content:center">${icon(RES[c.result][1])}</span>
  <span class="grow"><b>${esc(c.name)}</b><span class="small muted" style="display:block">${esc(c.detail)}</span></span></div>`).join('')}</div>`;

// ================================================================== my identity & privacy (every user)
route('/app/privacy', async (_, q) => {
  const pg = page('Identity & privacy');
  const [k, p] = await Promise.all([api.get('/api/me/kyc'), api.get('/api/me/privacy')]);
  const c = k.check;
  const showForm = !c || c.status === 'failed' || q.redo;
  pg.innerHTML = `<div class="grid2" style="align-items:start"><div class="stack">
    <div class="card stack" id="kyc"><div class="row"><h3 class="grow">${icon('idcard')} Identity check (FICA)</h3>${kpill(c?.status)}</div>
      <p class="small muted">The law (FICA) requires rental agents to confirm who their clients are. We check your ID number with Home Affairs, match a selfie to your ID photo and screen against sanctions lists. ${k.required ? 'It must be done before a lease can be approved.' : ''}${k.provider === 'simulated' ? ' <i>(Demo: the outside checks are simulated.)</i>' : ''}</p>
      ${c && !showForm ? `${checks(c.checks)}<div class="costs"><div><span>Name</span><b>${esc(c.first_names)} ${esc(c.surname)}</b></div><div><span>ID</span><span>${esc(c.id_masked)}</span></div><div><span>Checked</span><span>${fdt(c.submitted_at)}</span></div></div>
        ${c.status === 'review' ? `<div class="ai-note">${icon('alert')}<span>Your manager will look at the points marked in yellow. You can also add a missing document now.</span></div>` : ''}
        ${c.review_note ? `<p class="small"><b>Note from AVA:</b> ${esc(c.review_note)}</p>` : ''}
        ${c.status !== 'verified' ? '<a class="btn" href="#/app/privacy?redo=1">Update my details</a>' : ''}` : kycForm(c)}
    </div></div>
    <div class="stack">
      <div class="card stack"><h3>${icon('shield')} How we may use your information</h3><p class="small muted">You decide. Changes take effect straight away and are recorded (POPIA).</p>
        <div class="list">${p.consents.filter(x => !(x.purpose === 'prospecting' && state.user.role !== 'landlord') && !(x.purpose === 'credit_check' && state.user.role === 'landlord')).map(x => `<label class="li" style="cursor:${x.required ? 'default' : 'pointer'}"><input type="checkbox" data-c="${x.purpose}" ${x.granted ? 'checked' : ''} ${x.required ? 'disabled' : ''}>
          <span class="grow"><span style="display:block">${esc(x.label)}</span>${x.since ? `<span class="tiny muted" style="display:block">${x.granted ? 'Agreed' : 'Withdrawn'} ${fdate(x.since)}</span>` : ''}${x.required ? '<span class="tiny muted" style="display:block">Needed while you have a lease or property with AVA</span>' : ''}</span></label>`).join('')}</div></div>
      <div class="card stack"><h3>Your data</h3><p class="small muted">See everything AVA holds about you, ask us to correct it, or to delete it. We answer within 30 days.</p>
        <div class="row wrap"><a class="btn" href="/api/me/export">${icon('doc')}Download my data</a><button class="btn" id="req">${icon('send')}Make a request</button></div>
        ${p.requests.length ? `<div class="list">${p.requests.map(r => `<div class="li"><span class="grow"><b>${esc(p.kinds[r.kind] || r.kind)}</b><span class="small muted">${fdate(r.created_at)} · ${r.status === 'open' ? 'due ' + fdate(r.due_date) : esc(r.response || '')}</span></span><span class="pill ${r.status === 'open' ? 'warn' : r.status === 'declined' ? 'bad' : 'ok'}">${r.status}</span></div>`).join('')}</div>` : ''}
        <p class="tiny muted">Information Officer: ${esc(p.officer.name)} · <a href="mailto:${esc(p.officer.email)}">${esc(p.officer.email)}</a>. You may also complain to the Information Regulator (inforegulator.org.za).</p></div>
    </div></div>`;
  $$('[data-c]').forEach(i => i.onchange = async () => { await act(null, () => api.put('/api/me/consents', { [i.dataset.c]: i.checked }), i.checked ? 'Thanks – saved' : 'Withdrawn – saved'); });
  $('#req').onclick = () => {
    const m = modal({ title: 'Privacy request', body: `<form class="form" id="rf"><div class="field"><span>What would you like?</span>${Object.entries(p.kinds).map(([k, l], i) => `<label class="check"><input type="radio" name="kind" value="${k}" ${i ? '' : 'checked'}>${esc(l)}</label>`).join('')}</div>
      <label class="field"><span>Details (optional)</span><textarea class="input" name="detail" rows="3" placeholder="e.g. my phone number is wrong"></textarea></label></form>
      <p class="small muted">Stopping marketing works immediately. Deleting your data can only happen once you no longer have a lease or property with AVA, and records the law makes us keep (FICA, tax) are kept for 5 years.</p>`,
      foot: '<button class="btn primary" id="ok">Send request</button>' });
    $('#ok', m).onclick = async () => { const f = Object.fromEntries(new FormData($('#rf', m))); await act($('#ok', m), () => api.post('/api/me/requests', f), 'Request sent'); m.close(); go('#/app/privacy?r=' + Date.now()); };
  };
  bindKyc();
}, A);

function kycForm(c) {
  const u = state.user;
  const [first, ...rest] = (u.name || '').split(' ');
  return `<form class="form" id="kf">
    <div class="seg" id="idt"><button type="button" data-v="sa_id" aria-pressed="true">SA ID</button><button type="button" data-v="passport" aria-pressed="false">Passport</button></div>
    <input type="hidden" name="id_type" value="sa_id">
    <div class="cols"><label class="field"><span>First names (as on ID)</span><input class="input" name="first_names" value="${esc(c?.first_names || first || '')}" required></label>
      <label class="field"><span>Surname</span><input class="input" name="surname" value="${esc(c?.surname || rest.join(' '))}" required></label></div>
    <div class="cols"><label class="field"><span id="idl">ID number</span><input class="input" name="id_number" inputmode="numeric" autocomplete="off" required></label>
      <label class="field pp" hidden><span>Date of birth</span><input class="input" type="date" name="dob"></label><label class="field pp" hidden><span>Nationality</span><input class="input" name="nationality"></label></div>
    <label class="field"><span>Home address</span><input class="input" name="address" value="${esc(c?.address || '')}"></label>
    <div class="cols"><label class="field"><span>Copy of ID / passport</span><input class="input" type="file" name="id_doc" accept="image/*,.pdf"></label>
      <label class="field"><span>Selfie</span><input class="input" type="file" name="selfie" accept="image/*" capture="user"></label></div>
    <div class="cols"><label class="field"><span>Proof of address (under 3 months)</span><input class="input" type="file" name="poa_doc" accept="image/*,.pdf"></label>
      <label class="field"><span>Date on the proof of address</span><input class="input" type="date" name="poa_date" max="${today()}"></label></div>
    ${c ? `<p class="tiny muted">Documents you sent before are kept unless you replace them.</p>` : ''}
    <button class="btn primary" id="ks">${icon('shield')}Verify me</button></form>`;
}

function bindKyc() {
  const f = $('#kf');
  if (!f) return;
  $$('#idt button').forEach(b => b.onclick = () => {
    $$('#idt button').forEach(x => x.setAttribute('aria-pressed', x === b)); f.id_type.value = b.dataset.v;
    $$('.pp', f).forEach(x => x.hidden = b.dataset.v === 'sa_id'); $('#idl').textContent = b.dataset.v === 'sa_id' ? 'ID number' : 'Passport number';
  });
  f.onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(f); [...fd.keys()].forEach(k => { const v = fd.get(k); if (v instanceof File && !v.size) fd.delete(k); });
    const r = await act($('#ks'), () => api.post('/api/me/kyc', fd));
    toast(r.status === 'verified' ? 'You are verified ✓' : r.status === 'review' ? 'Sent – a few points need a person to look' : 'We could not verify you', r.status === 'failed');
    go('#/app/privacy?r=' + Date.now());
  };
}

// a nudge on the home pages until the person is verified
export function kycNudge() {
  const s = state.user?.fica;
  if (!state.features?.fica_required || !['tenant', 'landlord'].includes(state.user?.role) || s === 'verified') return '';
  return `<a class="card row" href="#/app/privacy" style="text-decoration:none;color:inherit;border-color:var(--warn)">${icon('idcard')}<span class="grow"><b>${s === 'review' ? 'Your identity check needs a look' : 'Verify your identity'}</b>
    <span class="small muted" style="display:block">${s === 'review' ? 'Add the missing document so we can finish.' : 'A 2-minute FICA check (ID, selfie, proof of address) – needed before a lease can be approved.'}</span></span>${kpill(s)}</a>`;
}

// ================================================================== staff: FICA register, POPIA queue, consent register
route('/app/compliance', async (_, q) => {
  if (!['pm', 'admin'].includes(state.user.role)) return go('#/app');
  const admin = state.user.role === 'admin';
  const pg = page('FICA & POPIA', { sub: 'Identity checks, consent and privacy requests' });
  const o = await api.get('/api/compliance');
  const TABS = [['fica', 'FICA register'], ...(admin ? [['popia', `Privacy requests${o.dsr_open ? ` (${o.dsr_open})` : ''}`], ['consents', 'Consent register']] : [])];
  let tab = q.tab || 'fica';
  pg.innerHTML = `<div class="kpis"><a class="kpi" href="#/app/compliance?tab=fica"><span>Verified</span><b>${o.kyc.verified || 0}</b><small>tenants & owners</small></a>
    <a class="kpi ${o.kyc.review ? 'alert' : ''}" href="#/app/compliance?tab=fica&st=review"><span>Need a look</span><b>${o.kyc.review || 0}</b><small>checks a person must review</small></a>
    <a class="kpi" href="#/app/compliance?tab=fica&st=none"><span>Not done</span><b>${o.kyc.none || 0}</b><small>${o.fica_required ? 'required before approval' : 'optional'}</small></a>
    ${admin ? `<a class="kpi ${o.dsr_overdue ? 'alert' : ''}" href="#/app/compliance?tab=popia"><span>Privacy requests</span><b>${o.dsr_open}</b><small>${o.dsr_overdue ? o.dsr_overdue + ' overdue' : 'answer within 30 days'}</small></a>
    <a class="kpi" href="#/app/compliance?tab=consents"><span>Marketing opt-ins</span><b>${o.marketing_optins}</b><small>people who said yes</small></a>` : ''}</div>
    <p class="small muted">Verification: ${o.provider === 'simulated' ? 'simulated (add the provider key under Settings)' : esc(o.provider)} · Information Officer: ${esc(o.officer.name)} · Owner payouts ${o.hold_payouts ? 'held until owner is verified' : 'not held for FICA'}</p>
    <div class="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="tb" class="stack"></div>`;
  const show = async k => { tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k)); history.replaceState(null, '', `#/app/compliance?tab=${k}`); await C[k]($('#tb'), q); };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
}, A);
route('/app/compliance/popia', () => go('#/app/compliance?tab=popia'), A);

const C = {
  async fica(el, q) {
    let st = q.st || '';
    const draw = async () => {
      const r = await api.get('/api/compliance/kyc' + (st ? '?status=' + st : ''));
      el.innerHTML = `<div class="seg" id="fs">${[['', 'All'], ['review', 'Need a look'], ['none', 'Not done'], ['failed', 'Failed'], ['verified', 'Verified']].map(([v, l]) => `<button data-v="${v}" aria-pressed="${v === st}">${l}</button>`).join('')}</div>
        <div class="card flush"><table class="t"><tr><th>Person</th><th>Role</th><th>Status</th><th>Risk</th><th>Checked</th><th>Note</th></tr>
        ${r.rows.map(x => `<tr ${x.id ? `data-k="${x.id}" style="cursor:pointer"` : ''}><td><b>${esc(x.name)}</b><div class="tiny muted">${esc(x.email)}</div></td><td>${x.role === 'tenant' ? 'Tenant' : 'Owner'}</td><td>${kpill(x.status)}</td>
          <td>${x.risk ? `<span class="pill ${x.risk === 'low' ? 'ok' : x.risk === 'medium' ? 'warn' : 'bad'}">${x.risk}</span>` : ''}</td><td class="small">${x.submitted_at ? fdate(x.submitted_at) : '–'}</td><td class="small muted">${esc(x.review_note || '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Nobody here.</td></tr>'}</table></div>`;
      $$('#fs button').forEach(b => b.onclick = () => { st = b.dataset.v; draw(); });
      $$('[data-k]').forEach(t => t.onclick = () => go('#/app/compliance/kyc/' + t.dataset.k));
    };
    draw();
  },
  async popia(el) {
    const rows = await api.get('/api/compliance/requests');
    el.innerHTML = `<div class="card flush"><table class="t"><tr><th>Person</th><th>Request</th><th>Received</th><th>Due</th><th>Status</th><th></th></tr>
      ${rows.map(r => `<tr><td><b>${esc(r.name || r.email)}</b><div class="tiny muted">${esc(r.role || '')}</div></td><td>${esc(r.kind_label)}${r.detail ? `<div class="small muted">${esc(r.detail)}</div>` : ''}${r.response ? `<div class="small"><b>Reply:</b> ${esc(r.response)}</div>` : ''}</td>
        <td class="small">${fdate(r.created_at)}</td><td class="small" style="${r.overdue ? 'color:var(--bad);font-weight:700' : ''}">${fdate(r.due_date)}</td>
        <td><span class="pill ${r.status === 'open' ? (r.overdue ? 'bad' : 'warn') : r.status === 'declined' ? '' : 'ok'}">${r.status}</span></td>
        <td>${r.status === 'open' ? `<button class="btn sm" data-r="${r.id}" data-kind="${r.kind}">Respond</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No requests.</td></tr>'}</table></div>
      <p class="small muted">POPIA s23–25: people may see, correct and ask to delete their information. Reply within 30 days. Records FICA and tax law require are kept for 5 years after the relationship ends.</p>`;
    $$('[data-r]').forEach(b => b.onclick = () => {
      const r = rows.find(x => x.id === +b.dataset.r);
      const tpl = { access: `Your data export is ready – sign in and use Identity & privacy → Download my data. It shows everything we hold about you.`, correction: 'We have corrected your details as asked.', objection: 'Marketing is switched off.' }[r.kind] || '';
      const m = modal({ title: esc(r.kind_label), body: `<p><b>${esc(r.name || r.email)}</b> · due ${fdate(r.due_date)}</p>${r.detail ? `<p class="small">${esc(r.detail)}</p>` : ''}
        <label class="field"><span>Reply to the person</span><textarea class="input" id="resp" rows="4">${esc(tpl)}</textarea></label>
        ${r.kind === 'deletion' ? '<p class="small muted"><b>Delete now</b> removes the profile, contact details, application documents and selfie, and keeps lease, payment and FICA records for 5 years as the law requires. It is refused while the person still has an active lease or property.</p>' : ''}`,
        foot: `${r.kind === 'deletion' ? '<button class="btn danger" id="del">Delete now</button>' : ''}<button class="btn" id="dec">Decline</button><span class="spacer"></span><button class="btn primary" id="done">Done – send reply</button>` });
      const go2 = async (btn, action) => { await act($('#' + btn, m), () => api.post(`/api/compliance/requests/${r.id}`, { action, response: $('#resp', m).value }), 'Done'); m.close(); C.popia(el); };
      $('#done', m).onclick = () => go2('done', 'done'); $('#dec', m).onclick = () => go2('dec', 'declined'); $('#del', m) && ($('#del', m).onclick = () => go2('del', 'delete'));
    });
  },
  async consents(el) {
    const c = await api.get('/api/compliance/consents');
    el.innerHTML = `<div class="kpis">${c.summary.map(s => `<div class="kpi"><span>${esc(c.purposes[s.purpose]?.split('(')[0] || s.purpose)}</span><b>${s.granted}</b><small>${s.withdrawn} withdrawn / said no</small></div>`).join('')}</div>
      <div class="card flush"><table class="t"><tr><th>When</th><th>Who</th><th>Purpose</th><th>Choice</th><th>How</th><th>Notice</th></tr>
      ${c.rows.map(r => `<tr><td class="small nowrap">${fdt(r.created_at)}</td><td>${esc(r.name || r.email || '')}</td><td class="small">${esc(r.purpose)}</td><td><span class="pill ${r.granted ? 'ok' : 'bad'}">${r.granted ? 'Yes' : 'No'}</span></td><td class="small muted">${esc(r.source || '')}</td><td class="tiny muted">${esc(r.version || '')}</td></tr>`).join('')}</table></div>`;
  },
};

route('/app/compliance/kyc/:id', async ({ id }) => {
  const k = await api.get('/api/compliance/kyc/' + id);
  const pg = page(`FICA – ${k.user.name}`, { back: '#/app/compliance' });
  const doc = (u, l) => u ? (/\.pdf$/i.test(u) ? `<a class="btn sm" href="${esc(u)}" target="_blank">${icon('doc')}${l}</a>` : `<figure style="margin:0"><img src="${esc(u)}" data-zoom="${esc(u)}" style="width:150px;height:110px;object-fit:cover;border-radius:8px"><figcaption class="tiny muted">${l}</figcaption></figure>`) : `<span class="pill">${l} missing</span>`;
  pg.innerHTML = `<div class="grid2" style="align-items:start"><div class="stack">
    <div class="card stack"><div class="row"><h3 class="grow">Checks</h3>${kpill(k.status)}</div>${checks(k.checks)}
      <p class="tiny muted">Run ${fdt(k.submitted_at)} · ${esc(k.provider)}${k.verified_at ? ' · verified ' + fdate(k.verified_at) : ''}</p></div>
    ${k.status !== 'verified' ? `<div class="card stack"><h3>Decision</h3><p class="small muted">Look at the documents and the points in yellow or red. The reason is kept in the FICA register.</p>
      <textarea class="input" id="note" rows="3" placeholder="e.g. Proof of address is a municipal account dated last month – checked against the original"></textarea>
      <div class="row"><button class="btn danger" id="rej">Reject</button><span class="spacer"></span><button class="btn primary" id="ok">${icon('check')}Approve</button></div></div>` : `<div class="card"><p class="small"><b>Note:</b> ${esc(k.review_note || 'Verified automatically – every check passed.')}</p></div>`}
  </div><div class="stack">
    <div class="card stack"><h3>Person</h3><div class="costs"><div><span>Name</span><b>${esc(k.first_names)} ${esc(k.surname)}</b></div><div><span>${k.id_type === 'sa_id' ? 'ID number' : 'Passport'}</span><span>${esc(k.id_number)}</span></div>
      <div><span>Born</span><span>${fdate(k.dob)}${k.gender ? ' · ' + esc(k.gender) : ''}</span></div><div><span>Citizenship</span><span>${esc(k.citizenship || '')}</span></div><div><span>Address</span><span>${esc(k.address || '–')}</span></div>
      <div><span>Account</span><span>${esc(k.user.email)} · ${esc(k.user.phone || '')}</span></div></div></div>
    <div class="card stack"><h3>Documents</h3><div class="row wrap">${doc(k.files.id, 'ID copy')}${doc(k.files.selfie, 'Selfie')}${doc(k.files.poa, 'Proof of address' + (k.poa_date ? ' · ' + fdate(k.poa_date) : ''))}</div></div>
    ${k.history.length ? `<div class="card stack tight"><h3>Earlier checks</h3>${k.history.map(h => `<div class="row small"><span class="grow">${fdate(h.submitted_at)}</span>${kpill(h.status)}</div>`).join('')}</div>` : ''}
  </div></div>`;
  const dec = async (btn, d) => { await act($(btn), () => api.post(`/api/compliance/kyc/${id}/review`, { decision: d, note: $('#note').value }), d === 'verified' ? 'Approved' : 'Rejected'); go(`#/app/compliance/kyc/${id}?r=${Date.now()}`); };
  $('#ok') && ($('#ok').onclick = () => dec('#ok', 'verified')); $('#rej') && ($('#rej').onclick = () => dec('#rej', 'failed'));
}, A);

// ================================================================== public privacy notice
route('/privacy-notice', async () => {
  const o = await api.get('/api/compliance-public').catch(() => ({}));
  $('#app').innerHTML = nav() + `<div class="wrap section stack" style="max-width:820px">
    <h1>Privacy notice</h1><p class="muted">How AVA uses your personal information, under the Protection of Personal Information Act (POPIA).</p>
    <div class="card stack"><h3>What we collect and why</h3><ul class="small">
      <li><b>To run your rental</b> – name, contact details, lease, payments and inspection records. Needed to provide the service.</li>
      <li><b>Identity checks (FICA)</b> – ID number, ID copy, selfie and proof of address. Rental agents must verify their clients; we screen against sanctions and politically-exposed-person lists.</li>
      <li><b>Credit and rental-history checks</b> – only when you apply for a home, and only with your consent.</li>
      <li><b>News and offers</b> – only if you say yes. Every message has an unsubscribe link or "reply STOP".</li>
      <li><b>Property owners we contact</b> – owner details from property-data providers (deeds office records). We may call once to introduce AVA; we only email or SMS once you agree, and we stop when you ask.</li></ul></div>
    <div class="card stack"><h3>Your rights</h3><p class="small">You may see the information we hold, have it corrected, object to marketing, and ask us to delete it. Signed-in users do this under <b>Identity & privacy</b>; anyone else can email the Information Officer. We answer within 30 days. Records that FICA and tax law require us to keep are kept for 5 years after the relationship ends, then destroyed.</p>
      <p class="small">Information Officer: ${esc(o.name || 'AVA')} · <a href="mailto:${esc(o.email || 'privacy@ava.co.za')}">${esc(o.email || 'privacy@ava.co.za')}</a> · Complaints: Information Regulator, inforegulator.org.za.</p></div>
    <div class="card stack"><h3>Who we share with</h3><p class="small">Your portfolio manager and the property owner (only what they need for the lease), the identity-verification and credit bureaus, our bank and debit-order provider, and the rental insurer. All in South Africa or bound to the same protection. We never sell personal information.</p></div>
  </div>` + footer();
});
