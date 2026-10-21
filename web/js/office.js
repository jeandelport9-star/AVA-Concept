// Workspace pages: command centre, portfolio, leasing, leases, money, contractors, inbox, reports, admin.
import { $, $$, act, ago, api, cchip, confirmBox, esc, fdate, fdt, formData, formObj, fslot, go, icon, initials, INSP, LOGO, modal, period, pickFiles, pill, plural, qs, R, R2, route, signModal, ST, stars, state, toast, today, upload } from './core.js';
import { page, moreMenu } from './shell.js';
import { openTour } from './public.js';

const A = { auth: true };
const isStaff = () => ['pm', 'admin'].includes(state.user.role);
const isOffice = () => ['pm', 'admin', 'landlord'].includes(state.user.role);
const TASKIC = { arrears: 'money', renewal: 'doc', inspection: 'pano', maintenance: 'tool', approval: 'clip', application: 'users', snag: 'clip', escalation: 'alert', deposit: 'shield', payout: 'money' };

route('/app/more', () => moreMenu(), A);

// ================================================================== home (per role)
route('/app', async () => {
  const r = state.user.role;
  if (r === 'tenant') return tenantHome();
  if (r === 'contractor') return (await import('./work.js')).contractorHome();
  if (r === 'landlord') return landlordHome();
  return commandCentre();
}, A);

function kpiTiles(k) {
  return `<div class="kpis">
    <a class="kpi" href="#/app/properties"><span>Homes managed</span><b>${k.properties}</b><small>${k.occupancy}% occupied · ${k.vacant} vacant</small></a>
    <a class="kpi" href="#/app/money"><span>Rent roll</span><b>${R(k.rent_roll)}</b><small>${k.let} active leases</small></a>
    <a class="kpi ${k.collection_rate < 90 ? 'alert' : 'good'}" href="#/app/money"><span>Collected this month</span><b>${k.collection_rate}%</b><small>${R(k.collected)} of ${R(k.charged)}</small></a>
    <a class="kpi ${k.arrears ? 'alert' : ''}" href="#/app/money?tab=arrears"><span>Arrears</span><b>${R(k.arrears)}</b><small>${plural(k.in_arrears, 'tenant')}</small></a>
    <a class="kpi ${k.urgent_tickets ? 'alert' : ''}" href="#/app/maintenance"><span>Open repairs</span><b>${k.open_tickets}</b><small>${k.urgent_tickets} urgent</small></a>
    <a class="kpi" href="#/app/money?tab=deposits"><span>Deposits in trust</span><b>${R(k.deposits_held)}</b><small>interest-bearing</small></a>
  </div>`;
}

async function commandCentre() {
  const pg = page('Command centre', { actions: `<button class="btn sm" id="run">${icon('refresh')}<span class="hide-sm">Run autopilot</span></button><a class="btn primary sm" href="#/app/properties/new">${icon('plus')}<span class="hide-sm">Property</span></a>` });
  const d = await api.get('/api/dashboard');
  const k = d.kpis;
  const groups = {};
  d.tasks.forEach(t => (groups[t.kind] ||= []).push(t));
  pg.innerHTML = `
    <div class="autopilot"><div>${icon('bolt', 'ico')}</div><div style="flex:1;min-width:220px"><b>${d.automated_week}</b> things handled by AVA Autopilot this week</div>
      <div class="small" style="opacity:.85">Rent matched, reminders sent, quotes requested, inspections booked.<br>Last run ${ago(d.last_tick)}. You only see the exceptions below.</div></div>
    ${kpiTiles(k)}
    <div class="grid2" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);align-items:start">
      <div class="card flush inbox"><div class="card-head"><h3>Needs you <span class="pill cta">${d.tasks.length}</span></h3><div class="seg" id="tf"><button aria-pressed="true" data-k="">All</button>${Object.keys(groups).map(g => `<button data-k="${g}">${g} ${groups[g].length}</button>`).join('')}</div></div>
        <div id="tasks"></div></div>
      <div class="stack">
        ${d.anomalies.length ? `<div class="card stack tight"><h3>${icon('spark')} <span class="ai">AVA spotted</span></h3>${d.anomalies.map(a => `<div class="small">• ${esc(a.text)}</div>`).join('')}</div>` : ''}
        <div class="card flush"><div class="card-head"><h3>Coming up</h3></div><div class="list">
          ${d.today.viewings.map(v => `<a class="li" href="#/app/leasing"><span class="pill info">${icon('eye')}</span><span class="grow"><span class="title">${esc(v.name)}</span><span class="small muted">${esc(v.title)}</span></span><span class="small nowrap">${fslot(v.slot)}</span></a>`).join('')}
          ${d.today.inspections.map(i => `<a class="li" href="#/app/inspection/${i.id}"><span class="pill jac">${icon('pano')}</span><span class="grow"><span class="title">${INSP[i.type]}${['ingoing', 'interim', 'outgoing'].includes(i.type) ? ' inspection' : ''}</span><span class="small muted">${esc(i.title)}</span></span><span class="small nowrap">${fdate(i.date)}</span></a>`).join('') || ''}
        </div></div>
        <div class="card flush"><div class="card-head"><h3>Activity</h3></div><div class="feed">${d.activity.map(a => `<div><span>${a.actor === 'AVA Autopilot' ? icon('bolt') : icon('users')}</span><span>${a.link ? `<a href="${esc(a.link)}">${esc(a.text)}</a>` : esc(a.text)}</span><time>${ago(a.created_at)}</time></div>`).join('') || '<div class="muted">No activity yet.</div>'}</div></div>
        ${d.commission_pct != null ? `<a class="kpi" href="#/app/earnings"><span>Earned in ${period(d.pm_earnings_period)}</span><b>${R(d.pm_earnings)}</b><small>${d.commission_pct}% commission + finder's fees · paid on the ${d.payout_day}th</small></a>` : ''}
      </div></div>`;
  const draw = kind => {
    const list = d.tasks.filter(t => !kind || t.kind === kind);
    $('#tasks').innerHTML = list.length ? list.map(t => `<div class="task" data-id="${t.id}"><span class="ic ${t.kind}">${icon(TASKIC[t.kind] || 'bolt')}</span>
      <div style="flex:1;min-width:0"><a href="${esc(t.link || '#/app')}"><b>${esc(t.title)}</b></a><div class="small muted">${esc(t.detail || '')}</div>${t.due ? `<div class="tiny faint">Due ${fdate(t.due)}</div>` : ''}</div>
      <div class="row" style="gap:4px"><button class="iconbtn" data-snz title="Snooze 3 days">${icon('cal')}</button><button class="iconbtn" data-done title="Done">${icon('check')}</button></div></div>`).join('')
      : `<div class="empty">${icon('check')}<h3>All clear</h3><p>AVA will put anything that needs a human here.</p></div>`;
    $$('#tasks .task').forEach(el => {
      $('[data-done]', el).onclick = async () => { await api.post(`/api/tasks/${el.dataset.id}/done`); el.remove(); d.tasks = d.tasks.filter(t => t.id != el.dataset.id); };
      $('[data-snz]', el).onclick = async () => { await api.post(`/api/tasks/${el.dataset.id}/snooze`); el.remove(); toast('Snoozed for 3 days'); };
    });
  };
  $$('#tf button').forEach(b => b.onclick = () => { $$('#tf button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(b.dataset.k); });
  draw('');
  $('#run').onclick = async () => { const r = await act($('#run'), () => api.post('/api/autopilot/run')); const n = Object.values(r).reduce((a, b) => a + b, 0); toast(n ? `Autopilot did ${n} thing(s)` : 'Autopilot: nothing new'); commandCentre(); };
}

// what the owner saves with AVA compared with a traditional rental agent (10% + VAT for full management)
function savingsCard(v) {
  if (!v || !v.rows.length) return '';
  return `<div class="savings"><div class="sv-top"><div><span>You save with AVA</span><b>${R(v.month)}<small> / month</small></b></div><div><span>Per year</span><b>${R(v.year)}</b></div>
      <div><span>Already saved</span><b>${R(v.saved_12m)}</b><small>on your paid statements</small></div></div>
    <div class="tablewrap"><table class="t"><tr><th>Home</th><th class="num">Rent</th><th class="num">Traditional agent<br><span class="tiny">${v.agent_pct}% + VAT</span></th><th class="num">AVA<br><span class="tiny">platform + PM commission</span></th><th class="num">You save / month</th><th class="num">Per year</th></tr>
      ${v.rows.map(r => `<tr><td><a href="#/app/property/${r.id}">${esc(r.title)}</a></td><td class="num">${R(r.rent)}</td><td class="num">${R(r.agent)}</td><td class="num" title="${R(r.ava_fee)} AVA + ${R(r.commission)} commission (${r.pct}%)">${R(r.ava)}</td><td class="num"><b>${R(r.saving_month)}</b></td><td class="num">${R(r.saving_year)}</td></tr>`).join('')}
      ${v.rows.length > 1 ? `<tr><td><b>Total</b></td><td class="num"><b>${R(v.rows.reduce((a, r) => a + r.rent, 0))}</b></td><td class="num"><b>${R(v.agent_month)}</b></td><td class="num"><b>${R(v.ava_month)}</b></td><td class="num"><b>${R(v.month)}</b></td><td class="num"><b>${R(v.year)}</b></td></tr>` : ''}</table></div>
    <p class="tiny muted">Management cost only, like for like. Rental insurance is optional cover and is not included on either side.</p></div>`;
}

async function landlordHome() {
  const pg = page(`Hello, ${state.user.name.split(' ')[0]}`);
  const d = await api.get('/api/dashboard');
  const inc = d.income_12m.slice().reverse();
  pg.innerHTML = `${d.approvals.length ? `<div class="card stack tight" style="border-color:var(--warn)"><h3>${icon('alert')} Waiting for your approval</h3>${d.approvals.map(t => `<a class="li" href="#/app/ticket/${t.id}" style="padding:6px 0"><span class="grow"><b>${esc(t.title)}</b> <span class="muted small">${esc(t.ptitle)}</span></span><span class="btn sm primary">Review quotes</span></a>`).join('')}</div>` : ''}
    <div class="kpis"><div class="kpi"><span>Your homes</span><b>${d.kpis.properties}</b><small>${d.kpis.occupancy}% occupied</small></div><div class="kpi"><span>Monthly rent roll</span><b>${R(d.kpis.rent_roll)}</b></div>
      <div class="kpi"><span>Collected this month</span><b>${R(d.kpis.collected)}</b><small>${d.kpis.collection_rate}%</small></div><div class="kpi ${d.kpis.arrears ? 'alert' : ''}"><span>Arrears</span><b>${R(d.kpis.arrears)}</b></div>
      <div class="kpi"><span>Open repairs</span><b>${d.kpis.open_tickets}</b></div><div class="kpi"><span>Deposits in trust</span><b>${R(d.kpis.deposits_held)}</b></div></div>
    ${savingsCard(d.savings)}
    <div class="card"><h3>Income and costs</h3>${barChart(inc.map(x => ({ label: period(x.period), a: x.income, b: x.costs })), 'Rent received', 'Fees & repairs')}</div>
    <div class="card flush"><div class="card-head"><h3>Your properties</h3></div>${propTable(d.properties)}</div>
    <div class="card flush"><div class="card-head"><h3>Statements</h3></div><div class="list">${d.statements.map(s => `<a class="li" href="#/app/statement/${s.property_id}/${s.period}">${icon('doc')}<span class="grow">${period(s.period)} · ${esc(d.properties.find(p => p.id === s.property_id)?.title || '')}</span><b class="num">${R2(s.payout)}</b></a>`).join('') || '<div class="muted">No payouts yet.</div>'}</div></div>`;
  bindRows(pg);
}

export function barChart(rows, la, lb) {
  if (!rows.length) return '<p class="muted small">No data yet.</p>';
  const max = Math.max(...rows.map(r => Math.max(r.a || 0, r.b || 0)), 1), w = 100 / rows.length;
  return `<svg class="chart" viewBox="0 0 100 50" preserveAspectRatio="none" role="img" aria-label="${la} vs ${lb}">${rows.map((r, i) => `<rect x="${i * w + w * .12}" y="${45 - 42 * r.a / max}" width="${w * .36}" height="${42 * r.a / max}" fill="#1ba3a0" rx=".6"><title>${r.label}: ${R(r.a)}</title></rect><rect x="${i * w + w * .52}" y="${45 - 42 * (r.b || 0) / max}" width="${w * .36}" height="${42 * (r.b || 0) / max}" fill="#0b1f3a" rx=".6"><title>${r.label}: ${R(r.b)}</title></rect>`).join('')}</svg>
    <div class="row small muted" style="justify-content:space-between">${rows.map(r => `<span>${r.label}</span>`).join('')}</div><div class="row small"><span class="dot" style="background:#1ba3a0"></span>${la}<span class="dot" style="background:#0b1f3a;margin-left:10px"></span>${lb}</div>`;
}

// ================================================================== tenant
async function tenantHome() {
  const pg = page(`Hi ${state.user.name.split(' ')[0]}`);
  const d = await api.get('/api/dashboard');
  const l = d.lease;
  if (!l) {
    pg.innerHTML = `<div class="card stack"><h2>Find your next home</h2><p class="muted">Browse homes with 360° tours, book a viewing and apply from your phone.</p><a class="btn cta" href="#/search">Search homes</a></div>
      ${d.applications.length ? `<div class="card flush"><div class="card-head"><h3>Your applications</h3></div><div class="list">${d.applications.map(a => `<div class="li"><span class="grow"><b>${esc(a.title)}</b><span class="small muted"> · score ${a.score ?? '…'}</span></span>${pill(a.status)}</div>`).join('')}</div></div>` : ''}
      ${d.viewings.length ? `<div class="card flush"><div class="card-head"><h3>Upcoming viewings</h3></div><div class="list">${d.viewings.map(v => `<a class="li" href="#/p/${v.property_id}"><span class="grow"><b>${esc(v.title)}</b></span><span class="small">${fslot(v.slot)}</span></a>`).join('')}</div></div>` : ''}`;
    return;
  }
  const owe = d.balance > 0;
  pg.innerHTML = `${l.status === 'awaiting_signature' ? `<a class="card row" href="#/app/lease/${l.id}" style="border-color:var(--warn)">${icon('doc')}<b class="grow">Your lease is ready to sign</b><span class="btn primary sm">Sign now</span></a>` : ''}
    <div class="card stack" style="background:${owe ? 'var(--bad-tint)' : 'var(--brand)'};color:${owe ? 'var(--ink)' : '#fff'};border:0">
      <span class="small" style="opacity:.8">${owe ? 'Amount due' : 'You are up to date'}</span><b style="font:600 34px var(--f-head)">${R2(Math.max(d.balance, 0))}</b>
      <span class="small" style="opacity:.85">Next rent ${R(l.rent)} due ${fdate(d.next_due)} · reference <span class="mono">${d.ref}</span></span>
      <div class="row"><a class="btn ${owe ? 'cta' : ''}" href="#/app/pay">${icon('money')}Pay now</a><a class="btn ghost" style="color:inherit" href="#/app/pay?tab=statement">Statement</a></div></div>
    <div class="grid2"><a class="card row" href="#/app/maintenance/new" style="text-decoration:none">${icon('tool')}<div class="grow"><b>Report a problem</b><div class="small muted">Photos help. Emergencies are dispatched immediately.</div></div></a>
      <button class="card row" style="text-align:left;cursor:pointer" onclick="document.getElementById('fab').click()">${icon('spark')}<div class="grow"><b>Ask the virtual agent</b><div class="small muted">Balance, lease, repairs, your rights – 24/7.</div></div></button></div>
    <div class="card flush"><div class="card-head"><h3>Your repairs</h3><a class="btn sm" href="#/app/maintenance">All</a></div><div class="list">${d.tickets.map(t => `<a class="li" href="#/app/ticket/${t.id}"><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted">${t.ref} · ${ago(t.created_at)}</span></span>${pill(t.status)}</a>`).join('') || '<div class="muted">No repairs logged.</div>'}</div></div>
    <div class="grid2"><div class="card stack tight"><h3>${esc(l.title)}</h3><p class="small muted">${esc(l.address)}</p><div class="costs"><div><span>Lease</span><span>${fdate(l.start_date)} – ${fdate(l.end_date)}</span></div><div><span>Deposit held (with interest)</span><span class="num">${R2(d.deposit_held)}</span></div></div><a class="btn sm" href="#/app/lease/${l.id}">View lease</a></div>
      <div class="card stack tight"><h3>Your portfolio manager</h3>${d.pm ? `<div class="row"><span class="avatar">${initials(d.pm.name)}</span><div><b>${esc(d.pm.name)}</b><div class="small muted">${esc(d.pm.phone || '')}</div></div></div><a class="btn sm" href="#/app/inbox">Message</a>` : ''}</div></div>
    ${d.inspections.length ? `<div class="card flush"><div class="card-head"><h3>Inspections</h3></div><div class="list">${d.inspections.map(i => `<a class="li" href="#/app/inspection/${i.id}">${icon('pano')}<span class="grow">${INSP[i.type]} · ${fdate(i.date)}</span>${pill(i.status)}</a>`).join('')}</div></div>` : ''}`;
}

route('/app/pay', async (_, q) => {
  const pg = page('Pay rent');
  const d = await api.get('/api/dashboard');
  if (!d.lease) { pg.innerHTML = '<div class="empty">No lease yet.</div>'; return; }
  const l = await api.get('/api/leases/' + d.lease.id);
  pg.innerHTML = `<div class="grid2" style="align-items:start"><div class="card stack"><h3>Pay now</h3>
      <label class="field"><span>Amount (R)</span><input class="input" id="amt" type="number" step="1" value="${Math.round(Math.max(0, l.balance))}"></label>
      <button class="btn cta lg" id="pay">${icon('money')}Pay by card / Instant EFT</button>
      <p class="small muted">Secure payment through PayFast. Or pay by EFT to the AVA trust account with reference <b class="mono">${l.ref}</b> – it is matched automatically.</p></div>
    <div class="card stack tight"><h3>Deposit</h3><p class="small muted">Held in an interest-bearing trust account (Rental Housing Act s5(3)(c)).</p><div class="costs">${l.deposit_ledger.map(x => `<div><span>${fdate(x.date)} ${esc(x.description)}</span><span class="num">${R2(x.amount)}</span></div>`).join('')}<div class="tot"><span>Held</span><span class="num">${R2(l.deposit_held)}</span></div></div></div></div>
    <div class="card flush"><div class="card-head"><h3>Statement</h3><button class="btn sm" onclick="print()">${icon('print')}Print</button></div>${ledgerTable(l.ledger)}</div>`;
  $('#pay').onclick = async () => {
    const amt = +$('#amt').value; if (amt <= 0) return toast('Enter an amount', true);
    const r = await act($('#pay'), () => api.post('/api/pay/start', { lease_id: l.id, amount: amt }));
    if (r.mode === 'payfast') {
      const f = document.createElement('form'); f.method = 'post'; f.action = r.url;
      Object.entries(r.fields).forEach(([k, v]) => { const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.append(i); });
      document.body.append(f); f.submit(); return;
    }
    const m = modal({ title: 'Test payment', body: `<div class="ai-note">${icon('spark')}<span>PayFast isn't connected yet (Settings → Payments), so this is a simulated card payment of <b>${R2(amt)}</b>. It is allocated exactly like a real one.</span></div>
      <div class="cols form"><input class="input" value="4000 0000 0000 0002" readonly><input class="input" value="12/29" readonly></div>`, foot: '<button class="btn cta" id="ok">Pay ' + R2(amt) + '</button>' });
    $('#ok', m).onclick = async () => { await act($('#ok', m), () => api.post('/api/pay/simulate/' + r.payment_id), 'Payment received – thank you!'); m.close(); go('#/app/pay?x=' + Date.now()); };
  };
}, A);

export function ledgerTable(rows, running = true) {
  let bal = 0;
  return `<div class="tablewrap"><table class="t"><tr><th>Date</th><th>Description</th><th class="num">Charge</th><th class="num">Paid</th>${running ? '<th class="num">Balance</th>' : ''}</tr>
    ${rows.map(x => { bal += x.amount; return `<tr><td class="nowrap">${fdate(x.date)}</td><td>${esc(x.description)}</td><td class="num">${x.amount > 0 ? R2(x.amount) : ''}</td><td class="num">${x.amount < 0 ? R2(-x.amount) : ''}</td>${running ? `<td class="num">${R2(bal)}</td>` : ''}</tr>`; }).join('') || '<tr><td colspan="5" class="muted">No entries</td></tr>'}</table></div>`;
}

route('/app/saved', async () => {
  const pg = page('Saved homes & alerts');
  const [f, a] = await Promise.all([api.get('/api/favourites'), api.get('/api/alerts')]);
  const { lcard } = await import('./public.js');
  pg.innerHTML = `<h2>Saved homes</h2><div class="cards">${f.map(lcard).join('') || '<p class="muted">Tap ♡ on a listing to save it.</p>'}</div>
    <h2>Area alerts</h2><div class="card flush list">${a.map(x => { const q = JSON.parse(x.query); return `<div class="li"><span class="grow">${esc(q.city || 'Map area')} ${q.max_rent ? '· up to ' + R(q.max_rent) : ''} ${q.beds ? '· ' + q.beds + '+ beds' : ''}</span><button class="btn sm" data-del="${x.id}">Remove</button></div>`; }).join('') || '<div class="muted">On the map search, tap "Alert me for this area".</div>'}</div>`;
  $$('[data-del]').forEach(b => b.onclick = async () => { await api.del('/api/alerts/' + b.dataset.del); b.closest('.li').remove(); });
}, A);

route('/app/learn', async () => {
  const pg = page(state.user.role === 'tenant' ? 'Know your rights' : 'AVA Learn');
  const L = [
    ['Deposits', 'The deposit is held in an interest-bearing account and the interest belongs to the tenant. After the outgoing inspection it is refunded within 7 days if there is no damage, within 14 days of repairs if there is, and within 21 days if the tenant did not attend the outgoing inspection. Deductions must be supported by the ingoing/outgoing comparison and receipts.', 'Rental Housing Act s5(3)'],
    ['Inspections', 'The landlord and tenant must jointly inspect the property before the tenant moves in, and within 3 days before the tenant moves out. If the landlord fails to do the outgoing inspection, it is deemed that there is no damage.', 'Rental Housing Act s5(3)(e)–(f), s5(7)'],
    ['Cancelling a fixed-term lease', 'A tenant may cancel a fixed-term lease with 20 business days\' written notice. The landlord may charge a reasonable cancellation penalty, taking into account the time left and how quickly the home can be re-let.', 'Consumer Protection Act s14'],
    ['Breach and arrears', 'If a tenant is in breach, the landlord must give 20 business days\' written notice to remedy before cancelling. AVA sends reminders on day 1, a final reminder on day 5 and a letter of demand on day 10.', 'CPA s14(2)(b)'],
    ['Evictions', 'Only a court order can evict a tenant. Changing locks, removing doors or cutting electricity or water to force a tenant out is unlawful ("self-help").', 'PIE Act 19 of 1998'],
    ['Repairs', 'The landlord must keep the home in a habitable state and repair fair wear and tear; the tenant pays for damage they cause. AVA records who is responsible on every repair.', 'Rental Housing Act s4A–4B'],
    ['Personal information', 'Applications, IDs and payslips are used only to vet the application and are kept securely.', 'POPIA 4 of 2013'],
  ];
  pg.innerHTML = `<div class="ai-note">${icon('learn')}<span>Plain-language summaries for South African residential rentals. Not legal advice – for a dispute, the Rental Housing Tribunal in your province is free.</span></div>
    ${L.map(([t, b, s], i) => `<details class="card" ${i ? '' : 'open'}><summary style="cursor:pointer"><b>${t}</b> <span class="pill">${s}</span></summary><p style="margin-top:10px">${b}</p></details>`).join('')}`;
}, A);

// ================================================================== properties
function propTable(rows) {
  return `<div class="tablewrap"><table class="t"><tr><th>Property</th><th class="hide-sm">Tenant</th><th class="num">Rent</th><th class="num">Balance</th><th>Status</th><th class="hide-sm num">Repairs</th></tr>
    ${rows.map(p => `<tr class="click" data-href="#/app/property/${p.id}"><td><div class="row"><div style="width:52px;height:38px;border-radius:6px;background:#ddd url('${esc(p.cover || '')}') center/cover;flex:none"></div><div><b>${esc(p.title)}</b><div class="small muted">${esc(p.suburb || '')}${p.kind === 'project' ? ' · new build' : ''}</div></div></div></td>
      <td class="hide-sm">${p.lease ? esc(p.lease.tenant_name) + `<div class="tiny muted">to ${fdate(p.lease.end_date)}</div>` : '<span class="faint">–</span>'}</td>
      <td class="num">${R(p.lease?.rent || p.rent)}</td><td class="num ${p.balance > 0 ? 'prio-Urgent' : ''}">${p.lease ? R(p.balance) : ''}</td>
      <td>${p.kind === 'project' ? `<span class="pill jac">${p.open_snags} snags</span>` : p.lease?.status === 'awaiting_signature' ? pill('awaiting_signature') : pill(p.listing_status)}</td><td class="num hide-sm">${p.open_tickets || ''}</td></tr>`).join('')}</table></div>`;
}
function bindRows(el) { $$('[data-href]', el).forEach(r => r.onclick = e => { if (!e.target.closest('a,button')) go(r.dataset.href); }); }

route('/app/properties', async (_, q) => {
  const pg = page(state.user.role === 'landlord' ? 'My properties' : 'Properties', { actions: isOffice() ? `<a class="btn primary sm" href="#/app/properties/new">${icon('plus')}Add property</a>` : '' });
  const rows = await api.get('/api/properties');
  let f = q.f || '';
  const draw = () => {
    const s = ($('#ps')?.value || '').toLowerCase();
    const list = rows.filter(p => (!f || (f === 'vacant' ? !p.lease && p.kind === 'rental' : f === 'arrears' ? p.balance > 0 : f === 'live' ? p.listing_status === 'live' : f === 'project' ? p.kind === 'project' : true))
      && (!s || `${p.title} ${p.suburb} ${p.lease?.tenant_name || ''} ${p.landlord_name || ''}`.toLowerCase().includes(s)));
    $('#pt').innerHTML = propTable(list); bindRows($('#pt'));
  };
  pg.innerHTML = `<div class="row wrap"><input class="input" id="ps" placeholder="Search property, tenant or owner" style="max-width:320px"><div class="seg" id="pf">${[['', 'All'], ['live', 'Listed'], ['vacant', 'Vacant'], ['arrears', 'In arrears'], ['project', 'New builds']].map(([k, l]) => `<button data-k="${k}" aria-pressed="${f === k}">${l}</button>`).join('')}</div></div>
    <div class="card flush" id="pt"></div>`;
  $('#ps').oninput = draw;
  $$('#pf button').forEach(b => b.onclick = () => { f = b.dataset.k; $$('#pf button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(); });
  draw();
}, A);

const FEATURES = ['Garden', 'Pool', 'Complex pool', 'Flatlet', 'Study', 'Garage', 'Double garage', 'Pet friendly', 'Solar / inverter', 'Backup power', 'Generator', 'Borehole', 'Water tank', 'Fibre', 'Air conditioning', 'Fireplace', 'Wooden floors', 'Lapa / braai', 'Built-in braai', 'Staff quarters', 'Security estate', 'Complex security', 'Electric fence', '24h security', 'Gym', 'Wheelchair accessible', 'Sea view', 'Mountain view', 'Furnished option'];

function propForm(p = {}, landlords = []) {
  return `<form class="form" id="pform">
    <div class="cols"><label class="field"><span>Listing name</span><input class="input" name="title" value="${esc(p.title || '')}" required placeholder="e.g. 14 Lynnwood Mews"></label>
      <label class="field"><span>Kind</span><select class="input" name="kind"><option value="rental">Rental</option><option value="project" ${p.kind === 'project' ? 'selected' : ''}>New build / construction (snag lists)</option></select></label></div>
    <label class="field"><span>Street address</span><input class="input" name="address" value="${esc(p.address || '')}" id="addr" placeholder="Start typing – we'll find it on the map"></label>
    <div class="cols"><label class="field"><span>Suburb</span><input class="input" name="suburb" value="${esc(p.suburb || '')}"></label><label class="field"><span>City</span><input class="input" name="city" value="${esc(p.city || '')}"></label>
      <label class="field"><span>Province</span><select class="input" name="province">${['Gauteng', 'Western Cape', 'KwaZulu-Natal', 'Eastern Cape', 'Free State', 'Limpopo', 'Mpumalanga', 'North West', 'Northern Cape'].map(x => `<option ${p.province === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      <label class="field"><span>Erf / unit</span><input class="input" name="erf" value="${esc(p.erf || '')}"></label></div>
    <div id="pmap" style="height:220px;border-radius:10px;overflow:hidden"></div><input type="hidden" name="lat" value="${p.lat || ''}"><input type="hidden" name="lng" value="${p.lng || ''}">
    <p class="tiny muted">Click the map to drop the pin exactly on the building.</p>
    <div class="cols"><label class="field"><span>Type</span><select class="input" name="type">${['House', 'Townhouse', 'Apartment', 'Cottage', 'Room', 'Farm', 'Vacant land', 'Retirement', 'Commercial', 'Industrial'].map(x => `<option ${p.type === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
      <label class="field"><span>Bedrooms</span><input class="input" type="number" step="0.5" name="bedrooms" value="${p.bedrooms ?? 2}"></label><label class="field"><span>Bathrooms</span><input class="input" type="number" step="0.5" name="bathrooms" value="${p.bathrooms ?? 1}"></label>
      <label class="field"><span>Parking</span><input class="input" type="number" name="parking" value="${p.parking ?? 1}"></label><label class="field"><span>Floor m²</span><input class="input" type="number" name="size_m2" value="${p.size_m2 || ''}"></label><label class="field"><span>Erf m²</span><input class="input" type="number" name="erf_size" value="${p.erf_size || ''}"></label></div>
    <div class="cols"><label class="field"><span>Rent (R / month)</span><input class="input" type="number" name="rent" value="${p.rent || ''}" id="rentin"></label><label class="field"><span>Deposit (R)</span><input class="input" type="number" name="deposit" value="${p.deposit || ''}"></label>
      <label class="field"><span>Available from</span><input class="input" type="date" name="available_from" value="${p.available_from || ''}"></label></div>
    <div id="price"></div>
    <div class="field"><span>Features</span><div class="feat">${FEATURES.map(f => `<label class="check"><input type="checkbox" data-feat="${esc(f)}" ${(p.features || []).includes(f) ? 'checked' : ''}>${f}</label>`).join('')}</div></div>
    <div class="row wrap"><label class="check"><input type="checkbox" name="pets" ${p.pets ? 'checked' : ''}>Pets allowed</label><label class="check"><input type="checkbox" name="furnished" ${p.furnished ? 'checked' : ''}>Furnished</label><label class="check"><input type="checkbox" name="insured" ${p.insured ?? 1 ? 'checked' : ''}>Rental insurance (${R(250)}/m)</label></div>
    ${state.user.role !== 'landlord' && !p.id ? `<div class="cols"><label class="field"><span>Owner</span><select class="input" name="landlord_id"><option value="">New owner…</option>${landlords.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join('')}</select></label>
      <label class="field"><span>New owner's email</span><input class="input" name="landlord_email" type="email"></label><label class="field"><span>New owner's name</span><input class="input" name="landlord_name"></label></div>` : ''}
  </form>`;
}
function bindPropForm(p = {}) {
  const L = window.L;
  const m = L.map('pmap').setView([p.lat || -25.77, p.lng || 28.24], p.lat ? 16 : 11);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { attribution: 'Esri', maxZoom: 19 }).addTo(m);
  let mk = p.lat ? L.marker([p.lat, p.lng]).addTo(m) : null;
  const set = (lat, lng) => { $('[name=lat]').value = lat.toFixed(6); $('[name=lng]').value = lng.toFixed(6); mk ? mk.setLatLng([lat, lng]) : (mk = L.marker([lat, lng]).addTo(m)); };
  m.on('click', e => set(e.latlng.lat, e.latlng.lng));
  let t;
  $('#addr').oninput = () => { clearTimeout(t); t = setTimeout(async () => {
    const qv = [$('#addr').value, $('[name=suburb]').value, $('[name=city]').value, 'South Africa'].filter(Boolean).join(', ');
    try { const r = await (await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=za&q=' + encodeURIComponent(qv))).json();
      if (r[0]) { set(+r[0].lat, +r[0].lon); m.setView([+r[0].lat, +r[0].lon], 17); } } catch (_) { }
  }, 700); };
  setTimeout(() => m.invalidateSize(), 200);
  return m;
}
function propPayload(form) {
  const d = formObj(form);
  d.features = $$('[data-feat]', form).filter(c => c.checked).map(c => c.dataset.feat);
  return d;
}

route('/app/properties/new', async () => {
  const pg = page('Add property', { back: '#/app/properties' });
  const landlords = isStaff() ? await api.get('/api/people?role_=landlord') : [];
  pg.innerHTML = `<div class="card">${propForm({}, landlords)}<div class="row" style="margin-top:16px"><span class="spacer"></span><button class="btn primary" id="save">Save property</button></div></div>`;
  const m = bindPropForm();
  $('#save').onclick = async () => {
    const f = $('#pform'); if (!f.reportValidity()) return;
    const r = await act($('#save'), () => api.post('/api/properties', propPayload(f)), 'Property added');
    m.remove(); go('#/app/property/' + r.id + '?tab=listing');
  };
}, A);

route('/app/property/:id', async ({ id }, q) => {
  const p = await api.get('/api/properties/' + id);
  const pg = page(p.title, { back: '#/app/properties', sub: esc(p.suburb || ''), actions: p.listing_status === 'live' ? `<a class="btn sm" href="#/p/${p.id}" target="_blank">${icon('eye')}<span class="hide-sm">Public listing</span></a>` : '' });
  const active = p.leases.find(l => l.status === 'active'), pend = p.leases.find(l => l.status === 'awaiting_signature');
  const tabs = p.kind === 'project' ? [['overview', 'Overview'], ['snags', 'Snags'], ['inspections', 'Inspections'], ['listing', 'Details']]
    : [['overview', 'Overview'], ['listing', 'Listing & media'], ['tenancy', 'Tenancy'], ['money', 'Money'], ['maintenance', 'Repairs'], ['inspections', 'Inspections'], ['docs', 'Documents']];
  let tab = q.tab || 'overview';
  pg.innerHTML = `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-t="${k}" aria-selected="${k === tab}">${l}</button>`).join('')}</div><div id="tb" class="stack"></div>`;
  const T = {
    overview: () => `<div class="grid2" style="align-items:start"><div class="stack">
        <div class="card row" style="padding:0;overflow:hidden;align-items:stretch"><div style="width:42%;min-height:170px;background:#ddd url('${esc(p.media.find(m => m.kind === 'photo')?.url || '')}') center/cover"></div>
          <div style="padding:16px" class="stack tight"><b>${esc(p.address || '')}</b><span class="small muted">${p.bedrooms} bed · ${p.bathrooms} bath · ${p.parking} parking${p.size_m2 ? ' · ' + Math.round(p.size_m2) + ' m²' : ''}</span>
            <span>${pill(p.listing_status)} ${p.kind === 'project' ? '<span class="pill jac">New build</span>' : ''}</span><span class="small">Owner: <b>${esc(p.landlord?.name || '–')}</b></span><span class="small">PM: ${esc(p.pm?.name || '–')}</span></div></div>
        ${active ? `<div class="card stack tight"><div class="row"><h3 class="grow">Current tenant</h3>${pill(active.balance > 0 ? 'unpaid' : 'paid', active.balance > 0 ? 'Owes ' + R(active.balance) : 'Up to date')}</div>
          <div class="row"><span class="avatar">${initials(active.tenant_name)}</span><div class="grow"><b>${esc(active.tenant_name)}</b><div class="small muted">${esc(active.tenant_phone || '')} · ${esc(active.tenant_email)}</div></div><a class="btn sm" href="#/app/lease/${active.id}">Lease</a></div>
          <div class="costs"><div><span>Lease</span><span>${fdate(active.start_date)} – ${fdate(active.end_date)}</span></div><div><span>Rent</span><span class="num">${R(active.rent)}</span></div><div><span>Deposit held</span><span class="num">${R2(active.deposit_held)}</span></div></div>
          ${p.risk ? `<div class="ai-note">${icon('spark')}<span><b>Renewal risk ${p.risk.level}</b> (${p.risk.score}/100): ${esc(p.risk.reasons.join(', '))}. ${esc(p.risk.action)}.</span></div>` : ''}</div>` : p.kind === 'rental' ? `<div class="card stack tight"><h3>Vacant</h3><p class="muted small">${p.listing_status === 'live' ? 'Listed on AVA.' : 'Not listed yet.'} ${p.applications.length} application(s), ${p.viewings.length} upcoming viewing(s).</p><div class="row"><a class="btn sm" href="#/app/leasing">Leasing</a><button class="btn sm" id="letnow">Let to a tenant directly</button></div></div>` : ''}
        ${p.snag_metrics ? snagSummary(p.snag_metrics, p.id) : ''}
      </div><div class="stack">
        ${p.fees ? `<div class="card stack tight"><h3>Owner economics</h3><div class="costs">${p.fees.lines.map(l => `<div><span>${esc(l.label)}</span><span class="num">−${R(l.amount)}</span></div>`).join('')}<div class="tot"><span>Net to owner / month</span><span class="num">${R(p.fees.net)}</span></div></div><span class="small muted">AVA costs ${p.fees.pct_of_rent}% of rent vs ~11.5% with a traditional agent.</span></div>` : ''}
        ${p.price ? `<div class="card stack tight"><h3><span class="ai">${icon('spark')} Rent check</span></h3><p><b>${R(p.price.low)} – ${R(p.price.high)}</b> <span class="muted small">suggested</span></p><p class="small muted">${p.price.basis.map(esc).join('<br>')}</p>${p.rent ? `<span class="pill ${p.rent > p.price.high ? 'warn' : p.rent < p.price.low ? 'info' : 'ok'}">${p.rent > p.price.high ? 'Above market – may take longer to let' : p.rent < p.price.low ? 'Below market' : 'In line with the market'}</span>` : ''}</div>` : ''}
        <div class="card flush"><div class="card-head"><h3>Open repairs</h3><a class="btn sm" href="#/app/maintenance/new?property=${p.id}">${icon('plus')}</a></div><div class="list">${p.tickets.filter(t => !['closed', 'cancelled'].includes(t.status)).map(t => `<a class="li" href="#/app/ticket/${t.id}"><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted">${t.ref} · <span class="prio-${t.priority}">${t.priority}</span></span></span>${pill(t.status)}</a>`).join('') || '<div class="muted small">None</div>'}</div></div>
      </div></div>`,
    listing: () => `<div class="grid2" style="align-items:start"><div class="card stack">${propForm(p)}<div class="row"><button class="btn" id="aic">${icon('spark')}Write listing with AI</button><span class="spacer"></span><button class="btn primary" id="psave">Save</button></div>
        <label class="field"><span>Headline</span><input class="input" id="headline" value="${esc(p.headline || '')}"></label><label class="field"><span>Description</span><textarea class="input" id="desc" rows="7">${esc(p.description || '')}</textarea></label></div>
      <div class="stack"><div class="card stack"><div class="row"><h3 class="grow">Publish</h3>${pill(p.listing_status)}</div>
          <p class="small muted">Publishing puts it on the AVA portal, alerts renters whose saved area matches, and opens viewing slots.</p>
          <div class="row">${p.listing_status === 'live' ? `<button class="btn" id="unpub">Take off market</button>` : `<button class="btn cta" id="pub">${icon('upload')}Publish listing</button>`}</div></div>
        <div class="card stack"><div class="row"><h3 class="grow">Photos</h3><button class="btn sm" id="addph">${icon('camera')}Add photos</button></div>
          <div class="thumbs">${p.media.filter(m => m.kind === 'photo').map(m => `<div style="position:relative"><img src="${esc(m.url)}" data-zoom="${esc(m.url)}" alt=""><button class="iconbtn" data-delm="${m.id}" style="position:absolute;top:-8px;right:-8px;width:24px;height:24px;background:#fff;box-shadow:var(--sh)">${icon('x')}</button></div>`).join('') || '<span class="muted small">No photos yet</span>'}</div></div>
        <div class="card stack"><div class="row"><h3 class="grow">360° virtual tour</h3><button class="btn sm" id="addpano">${icon('pano')}Add 360° photo</button></div>
          <p class="small muted">Equirectangular JPGs from any 360° camera (Insta360, Ricoh Theta, BLK360 export). You can also reuse the panoramas from an inspection.</p>
          <div class="thumbs">${p.media.filter(m => m.kind === 'pano').map(m => `<div style="position:relative;width:120px"><img src="${esc(m.url)}" style="width:120px;height:60px" alt=""><span class="tiny">${esc(m.room || '')}</span><button class="iconbtn" data-delm="${m.id}" style="position:absolute;top:-8px;right:-8px;width:24px;height:24px;background:#fff;box-shadow:var(--sh)">${icon('x')}</button></div>`).join('')}</div>
          ${p.media.some(m => m.kind === 'pano') ? `<button class="btn sm" id="tour">${icon('eye')}Preview tour</button>` : ''}</div></div></div>`,
    tenancy: () => `<div class="stack">${[pend, active].filter(Boolean).map(l => `<div class="card stack tight"><div class="row"><h3 class="grow">${l.status === 'active' ? 'Active lease' : 'Lease awaiting signature'}</h3>${pill(l.status)}</div><div class="costs"><div><span>Tenant</span><b>${esc(l.tenant_name)}</b></div><div><span>Period</span><span>${fdate(l.start_date)} – ${fdate(l.end_date)}</span></div><div><span>Rent / escalation</span><span>${R(l.rent)} · ${l.escalation_pct}%</span></div></div><a class="btn sm" href="#/app/lease/${l.id}">Open lease</a></div>`).join('')}
      ${!active && !pend ? `<div class="card stack"><h3>No tenant</h3><button class="btn primary" id="letnow">Let to a tenant directly</button></div>` : ''}
      <div class="card flush"><div class="card-head"><h3>Previous leases</h3></div><div class="list">${p.leases.filter(l => !['active', 'awaiting_signature'].includes(l.status)).map(l => `<a class="li" href="#/app/lease/${l.id}"><span class="grow">${esc(l.tenant_name)} · ${fdate(l.start_date)} – ${fdate(l.end_date)}</span>${pill(l.status)}</a>`).join('') || '<div class="muted small">None</div>'}</div></div></div>`,
    money: () => `<div class="grid2" style="align-items:start"><div class="card flush"><div class="card-head"><h3>Tenant account</h3>${active ? `<button class="btn sm" id="recpay">${icon('plus')}Record payment</button>` : ''}</div>${ledgerTable(p.tenant_ledger.slice().reverse())}</div>
      <div class="card flush"><div class="card-head"><h3>Owner account</h3><span class="num small">${R2(p.owner_balance)} held</span></div>${ledgerTable(p.owner_ledger.slice().reverse(), false)}</div></div>`,
    maintenance: () => `<div class="card flush"><div class="card-head"><h3>Repairs</h3><a class="btn sm primary" href="#/app/maintenance/new?property=${p.id}">${icon('plus')}Log repair</a></div><div class="list">${p.tickets.map(t => `<a class="li" href="#/app/ticket/${t.id}"><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted">${t.ref} · ${fdate(t.created_at)} · ${esc(t.category)}${t.cost ? ' · ' + R(t.cost) : ''}</span></span>${pill(t.status)}</a>`).join('') || '<div class="muted">No repairs.</div>'}</div></div>`,
    inspections: () => `<div class="card flush"><div class="card-head"><h3>Inspections</h3><button class="btn sm primary" id="newinsp">${icon('plus')}New inspection</button></div><div class="list">${p.inspections.map(i => `<a class="li" href="#/app/inspection/${i.id}">${icon('pano')}<span class="grow"><span class="title">${INSP[i.type]}${i.round > 1 ? ' – round ' + i.round : ''}</span><span class="small muted">${fdate(i.date)}</span></span>${pill(i.status)}</a>`).join('') || '<div class="muted">None yet.</div>'}</div></div>`,
    snags: () => `<div id="snaghost"></div>`,
    docs: () => `<div class="card flush"><div class="card-head"><h3>Documents</h3><button class="btn sm" id="adddoc">${icon('upload')}Upload</button></div><div class="list">${p.documents.map(d => `<a class="li" href="${esc(d.url)}" target="_blank">${icon('doc')}<span class="grow">${esc(d.name)}</span><span class="small muted">${fdate(d.created_at)}</span></a>`).join('') || '<div class="muted small">Upload title deeds, CoCs (electrical, gas, electric fence, beetle), body corporate rules, plans.</div>'}</div></div>`,
  };
  const reload = () => go(`#/app/property/${id}?tab=${tab}&r=${Date.now()}`);
  const show = async k => {
    tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k));
    $('#tb').innerHTML = T[k]();
    $('#letnow') && ($('#letnow').onclick = () => letDirect(p));
    $('#newinsp') && ($('#newinsp').onclick = () => newInspection(p));
    $('#recpay') && ($('#recpay').onclick = () => recordPayment(active, reload));
    $('#adddoc') && ($('#adddoc').onclick = async () => { const f = await pickFiles({ accept: '*/*' }); if (f.length) { await upload(`/api/properties/${id}/documents`, f); reload(); } });
    if (k === 'snags') { const { snagBoard } = await import('./inspect.js'); snagBoard($('#snaghost'), p.id); }
    if (k === 'listing') {
      const m = bindPropForm(p);
      $('#aic').onclick = async () => { const c = await act($('#aic'), () => api.post(`/api/properties/${id}/ai-copy`)); $('#headline').value = c.headline; $('#desc').value = c.description; toast('Draft written – edit as you like'); };
      $('#psave').onclick = async () => { const d = propPayload($('#pform')); d.headline = $('#headline').value; d.description = $('#desc').value; await act($('#psave'), () => api.put('/api/properties/' + id, d), 'Saved'); };
      $('#pub') && ($('#pub').onclick = async () => { const d = propPayload($('#pform')); d.headline = $('#headline').value; d.description = $('#desc').value; await api.put('/api/properties/' + id, d); const r = await act($('#pub'), () => api.post(`/api/properties/${id}/publish`)); toast(`Published · ${r.alerts_sent} alert(s) sent`); m.remove(); reload(); });
      $('#unpub') && ($('#unpub').onclick = async () => { await api.post(`/api/properties/${id}/unpublish`); reload(); });
      $('#addph').onclick = async () => { const f = await pickFiles(); if (f.length) { await act($('#addph'), () => upload(`/api/properties/${id}/media`, f, 'files', { kind: 'photo' }), 'Uploaded'); m.remove(); reload(); } };
      $('#addpano').onclick = async () => { const f = await pickFiles({ multiple: false }); if (!f.length) return; const room = prompt('Which room is this?', 'Lounge') || ''; await act($('#addpano'), () => upload(`/api/properties/${id}/media`, f, 'files', { kind: 'pano', room }), 'Added to tour'); m.remove(); reload(); };
      $('#tour') && ($('#tour').onclick = () => openTour(p.media.filter(x => x.kind === 'pano'), p.title));
      $$('[data-delm]').forEach(b => b.onclick = async () => { await api.del('/api/media/' + b.dataset.delm); b.parentElement.remove(); });
    }
  };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
}, A);

export function snagSummary(m, pid) {
  return `<a class="card stack tight" href="#/app/snags/${pid}" style="text-decoration:none;color:inherit"><div class="row"><h3 class="grow">${icon('clip')} Snag list</h3><span class="pill ${m.overdue ? 'bad' : 'ok'}">${m.overdue} overdue</span></div>
    <div class="meter"><i style="width:${m.close_rate}%"></i></div><div class="row small muted"><span>${m.closed}/${m.total} closed (${m.close_rate}%)</span><span class="spacer"></span><span>${m.ready} ready to verify</span></div></a>`;
}

async function newInspection(p) {
  const types = p.kind === 'project' ? [['snag', 'Snag list (practical completion)'], ['reinspection', 'Re-inspection / close-out'], ['handover', 'Handover to owner']]
    : [['ingoing', 'Ingoing (move-in)'], ['interim', 'Interim / routine'], ['outgoing', 'Outgoing (move-out)'], ['snag', 'Snag list']];
  const m = modal({ title: 'New inspection', body: `<form class="form" id="nf"><div class="field"><span>Type</span>${types.map(([v, l], i) => `<label class="check"><input type="radio" name="type" value="${v}" ${i ? '' : 'checked'}>${l}</label>`).join('')}</div>
    <label class="field"><span>Date</span><input class="input" type="date" name="date" value="${today()}"></label></form>
    <p class="small muted">Rooms are set up from the bedrooms and bathrooms. Outgoing and re-inspections copy the previous inspection so you compare like for like.</p>`, foot: '<button class="btn primary" id="go">Start</button>' });
  $('#go', m).onclick = async () => { const d = formObj($('#nf', m)); d.property_id = p.id; const r = await act($('#go', m), () => api.post('/api/inspections', d)); m.close(); go('#/app/inspection/' + r.id); };
}

function letDirect(p) {
  const m = modal({ title: 'Let directly', body: `<p class="small muted">For a tenant you already know (or an existing tenancy you're moving onto AVA). AVA creates the tenant's account, the lease for e-signing and the move-in invoice.</p>
    <form class="form" id="lf"><div class="cols"><label class="field"><span>Tenant name</span><input class="input" name="tenant_name" required></label><label class="field"><span>Tenant email</span><input class="input" name="tenant_email" type="email" required></label></div>
    <div class="cols"><label class="field"><span>Start</span><input class="input" type="date" name="start_date" value="${p.available_from || today()}"></label><label class="field"><span>Months</span><input class="input" type="number" name="months" value="12"></label><label class="field"><span>Rent</span><input class="input" type="number" name="rent" value="${p.rent || ''}"></label><label class="field"><span>Escalation %</span><input class="input" type="number" step="0.5" name="escalation" value="8"></label></div></form>`,
    foot: '<button class="btn primary" id="ok">Create lease</button>' });
  $('#ok', m).onclick = async () => { const f = $('#lf', m); if (!f.reportValidity()) return; const d = formObj(f); d.property_id = p.id; const r = await act($('#ok', m), () => api.post('/api/leases', d), 'Lease created – sent for signature'); m.close(); go('#/app/lease/' + r.id); };
}

function recordPayment(l, done) {
  const m = modal({ title: 'Record payment', body: `<form class="form" id="rp"><div class="cols"><label class="field"><span>Amount</span><input class="input" type="number" step="1" name="amount" value="${Math.round(Math.max(0, l.balance))}" required></label><label class="field"><span>Date</span><input class="input" type="date" name="date" value="${today()}"></label></div>
    <div class="cols"><label class="field"><span>Method</span><select class="input" name="method"><option value="eft">EFT</option><option value="debit_order">Debit order</option><option value="cash">Cash deposit</option><option value="card">Card</option></select></label><label class="field"><span>Reference</span><input class="input" name="reference" value="AVA${String(l.id).padStart(5, '0')}"></label></div></form>
    <p class="small muted">AVA allocates it automatically: outstanding deposit → fees → tenant-liable repairs → rent to the owner.</p>`, foot: '<button class="btn primary" id="ok">Save</button>' });
  $('#ok', m).onclick = async () => { const d = formObj($('#rp', m)); d.lease_id = l.id; await act($('#ok', m), () => api.post('/api/payments', d), 'Payment allocated'); m.close(); done(); };
}

// ================================================================== leasing
route('/app/leasing', async (_, q) => {
  const pg = page('Leasing');
  const [apps, views, props] = await Promise.all([api.get('/api/applications'), api.get('/api/viewings'), api.get('/api/properties')]);
  let tab = q.tab || 'applications';
  const live = props.filter(p => p.listing_status === 'live'), vacant = props.filter(p => p.kind === 'rental' && !p.lease && p.listing_status !== 'live');
  pg.innerHTML = `<div class="kpis"><div class="kpi"><span>Live listings</span><b>${live.length}</b></div><div class="kpi ${vacant.length ? 'alert' : ''}"><span>Vacant, not listed</span><b>${vacant.length}</b></div>
    <div class="kpi"><span>Applications to review</span><b>${apps.filter(a => ['submitted', 'screening'].includes(a.status)).length}</b></div><div class="kpi"><span>Viewings this week</span><b>${views.filter(v => v.slot >= today() && v.status === 'confirmed').length}</b></div></div>
    <div class="tabs">${[['applications', 'Applications'], ['viewings', 'Viewings'], ['listings', 'Listings']].map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="lb"></div>`;
  const T = {
    applications: () => `<div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Applicant</th><th>Property</th><th class="num">Income</th><th class="num">Rent : income</th><th>AVA score</th><th>Status</th><th></th></tr>
      ${apps.map(a => { const r = a.rent / ((a.income || 0) + (a.other_income || 0) || 1); return `<tr><td><b>${esc(a.name)}</b><div class="tiny muted">${esc(a.employer || '')} · ${ago(a.created_at)}</div></td><td>${esc(a.title)}</td><td class="num">${R(a.income)}</td>
        <td class="num"><span class="pill ${r <= .3 ? 'ok' : r <= .35 ? 'warn' : 'bad'}">${Math.round(r * 100)}%</span></td><td><b>${a.score ?? '…'}</b>/100</td><td>${pill(a.status)}</td><td><button class="btn sm" data-app="${a.id}">Review</button></td></tr>`; }).join('') || '<tr><td colspan="7" class="muted">No applications.</td></tr>'}</table></div></div>`,
    viewings: () => `<div class="card flush list">${views.map(v => `<div class="li"><span class="pill ${v.slot < today() ? '' : 'info'}">${fslot(v.slot)}</span><span class="grow"><b>${esc(v.name || '')}</b> <span class="small muted">${esc(v.phone || '')} · ${esc(v.title)}</span></span>${pill(v.status)}
      ${v.status === 'confirmed' ? `<button class="btn sm" data-v="${v.id}" data-s="done">Done</button><button class="btn sm ghost" data-v="${v.id}" data-s="no_show">No-show</button>` : ''}</div>`).join('') || '<div class="muted">No viewings.</div>'}</div>`,
    listings: () => `<div class="card flush">${propTable([...live, ...vacant])}</div>`,
  };
  const show = k => { tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k)); $('#lb').innerHTML = T[k](); bindRows($('#lb'));
    $$('[data-app]').forEach(b => b.onclick = () => reviewApp(apps.find(a => a.id == b.dataset.app)));
    $$('[data-v]').forEach(b => b.onclick = async () => { await api.put('/api/viewings/' + b.dataset.v, { status: b.dataset.s }); b.closest('.li').querySelector('.pill:last-of-type')?.replaceWith(Object.assign(document.createElement('span'), { innerHTML: pill(b.dataset.s) })); toast('Updated'); }); };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
}, A);

function reviewApp(a) {
  const docs = a.docs || [];
  const m = modal({ title: `${a.name} – ${a.title}`, cls: 'wide', body: `<div class="grid2"><div class="stack tight">
      <div class="costs"><div><span>Employer</span><b>${esc(a.employer || '–')}</b></div><div><span>Gross income</span><span class="num">${R(a.income)}${a.other_income ? ' + ' + R(a.other_income) : ''}</span></div><div><span>Rent</span><span class="num">${R(a.rent)}</span></div>
        <div><span>Occupants / pets</span><span>${a.occupants} / ${a.pets ? 'yes' : 'no'}</span></div><div><span>Move-in</span><span>${fdate(a.move_in)}</span></div><div><span>Credit score</span><b>${a.credit_score ?? 'not checked'}</b></div><div><span>Rental history</span><span>${esc(a.rental_history || '–')}</span></div></div>
      ${a.message ? `<p class="card tint small">"${esc(a.message)}"</p>` : ''}
      <div class="row wrap">${docs.map(d => `<a class="btn sm" target="_blank" href="${esc(d.url)}">${icon('doc')}${esc(d.kind.replace('_', ' '))}</a>`).join('') || '<span class="muted small">No documents</span>'}</div></div>
    <div class="stack"><div class="card tint stack tight"><div class="row"><b class="grow">AVA score</b><b style="font:600 30px var(--f-head)">${a.score ?? '…'}</b></div><div class="meter"><i style="width:${a.score || 0}%;background:${a.score >= 70 ? 'var(--ok)' : a.score >= 45 ? 'var(--warn)' : 'var(--bad)'}"></i></div>
      <div class="small">${(a.score_notes || '').split('\n').map(n => `• ${esc(n)}`).join('<br>')}</div></div>
      <button class="btn" id="cc">${icon('shield')}Run credit + TPN check</button></div></div>
    <form class="form cols" id="lf"><label class="field"><span>Lease start</span><input class="input" type="date" name="start_date" value="${a.move_in || today()}"></label><label class="field"><span>Months</span><input class="input" type="number" name="months" value="12"></label><label class="field"><span>Escalation %</span><input class="input" type="number" name="escalation" value="8" step="0.5"></label></form>`,
    foot: ['approved', 'declined', 'withdrawn'].includes(a.status) ? '' : `<button class="btn danger" id="dec">Decline</button><span class="spacer"></span><button class="btn primary" id="appr">Approve & send lease</button>` });
  $('#cc', m).onclick = async () => { const r = await act($('#cc', m), () => api.post(`/api/applications/${a.id}/credit-check`), 'Checks complete'); m.close(); reviewApp({ ...a, ...r }); };
  $('#dec', m)?.addEventListener('click', async () => { await api.put('/api/applications/' + a.id, { status: 'declined', decision_note: 'Declined after review' }); m.close(); toast('Declined – applicant notified kindly'); go('#/app/leasing?r=' + Date.now()); });
  $('#appr', m)?.addEventListener('click', async () => { const r = await act($('#appr', m), () => api.post(`/api/applications/${a.id}/approve`, formObj($('#lf', m))), 'Approved – lease sent for e-signature'); m.close(); go('#/app/lease/' + r.lease_id); });
}

// ================================================================== leases
route('/app/leases', async () => {
  const pg = page('Leases');
  const rows = await api.get('/api/leases');
  const soon = new Date(Date.now() + 60 * 864e5).toISOString().slice(0, 10);
  pg.innerHTML = `<div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Property</th><th>Tenant</th><th>Start</th><th>End</th><th class="num">Rent</th><th class="num">Balance</th><th>Status</th></tr>
    ${rows.map(l => `<tr class="click" data-href="#/app/lease/${l.id}"><td><b>${esc(l.title)}</b></td><td>${esc(l.tenant_name)}</td><td>${fdate(l.start_date)}</td><td class="${l.status === 'active' && l.end_date <= soon ? 'prio-High' : ''}">${fdate(l.end_date)}</td><td class="num">${R(l.rent)}</td><td class="num ${l.balance > 0 ? 'prio-Urgent' : ''}">${R(l.balance)}</td><td>${pill(l.status)}</td></tr>`).join('')}</table></div></div>`;
  bindRows(pg);
}, A);

route('/app/lease/:id', async ({ id }) => leaseView(id), A);
route('/app/lease', async () => { const d = await api.get('/api/dashboard'); if (d.lease) return leaseView(d.lease.id); page('My lease').innerHTML = '<div class="empty">No lease yet.</div>'; }, A);

async function leaseView(id) {
  const l = await api.get('/api/leases/' + id);
  const u = state.user;
  const pg = page('Lease · ' + l.property.title, { back: u.role === 'tenant' ? '#/app' : '#/app/leases', actions: `<button class="btn sm" onclick="print()">${icon('print')}<span class="hide-sm">Print</span></button>` });
  const mine = u.id === l.tenant_id ? 'tenant' : (u.id === l.landlord?.id || ['pm', 'admin'].includes(u.role)) ? 'landlord' : null;
  const canSign = l.status === 'awaiting_signature' && ((mine === 'tenant' && !l.tenant_sig) || (mine === 'landlord' && !l.landlord_sig));
  pg.innerHTML = `<div class="grid2" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);align-items:start"><div class="stack">
      ${canSign ? `<div class="card row" style="border-color:var(--cta)"><b class="grow">Please read and sign the lease</b><button class="btn cta" id="sign">${icon('doc')}Sign now</button></div>` : ''}
      <div class="card stack"><div class="row"><h2 class="grow">Residential lease agreement</h2>${pill(l.status)}</div>
        <div class="costs"><div><span>Premises</span><b>${esc(l.property.address || l.property.title)}</b></div><div><span>Landlord</span><span>${esc(l.landlord?.company || l.landlord?.name || '')}</span></div><div><span>Tenant</span><span>${esc(l.tenant.name)}</span></div>
          <div><span>Period</span><span>${fdate(l.start_date)} – ${fdate(l.end_date)}</span></div><div><span>Rent</span><b>${R(l.rent)} / month, due day ${l.due_day}</b></div><div><span>Escalation</span><span>${l.escalation_pct}% per year</span></div><div><span>Deposit</span><span>${R(l.deposit)}</span></div><div><span>Payment reference</span><span class="mono">${l.ref}</span></div></div>
        <div class="lease-doc">${esc(l.terms || '')}</div>
        <div class="split"><div><span class="small muted">Tenant</span>${l.tenant_sig ? `<img class="sigimg" src="${l.tenant_sig}" alt="Tenant signature"><span class="tiny muted">${fdt(l.tenant_signed_at)}</span>` : '<p class="faint">Not signed</p>'}</div>
          <div><span class="small muted">Landlord / agent</span>${l.landlord_sig ? `<img class="sigimg" src="${l.landlord_sig}" alt="Landlord signature"><span class="tiny muted">${fdt(l.landlord_signed_at)}</span>` : '<p class="faint">Not signed</p>'}</div></div></div>
      <div class="card flush"><div class="card-head"><h3>Tenant account</h3><b class="num">${R2(l.balance)}</b></div>${ledgerTable(l.ledger)}</div></div>
    <div class="stack"><div class="card stack tight"><h3>${icon('shield')} No steps missed</h3><div class="checklist">${l.checklist.map(c => `<div><span class="tick ${c.done ? 'y' : 'n'}">${c.done ? '✓' : ''}</span>${esc(c.step)}</div>`).join('')}</div></div>
      ${l.risk ? `<div class="ai-note">${icon('spark')}<span><b>Renewal risk ${l.risk.level}</b> – ${esc(l.risk.reasons.join(', '))}. ${esc(l.risk.action)}.</span></div>` : ''}
      <div class="card stack tight"><h3>Deposit in trust</h3><div class="costs">${l.deposit_ledger.slice(-6).map(x => `<div><span class="small">${fdate(x.date)} ${esc(x.description)}</span><span class="num">${R2(x.amount)}</span></div>`).join('')}<div class="tot"><span>Held</span><span class="num">${R2(l.deposit_held)}</span></div></div></div>
      ${l.status === 'active' ? `<div class="card stack tight"><h3>Actions</h3>${['pm', 'admin', 'landlord'].includes(u.role) ? `<button class="btn" id="renew">${icon('refresh')}Offer renewal</button>` : ''}<button class="btn" id="notice">${icon('doc')}${u.role === 'tenant' ? 'Give notice' : 'Record notice'}</button></div>` : ''}
      <div class="card stack tight"><h3>People</h3><div class="small">PM: <b>${esc(l.pm?.name || '')}</b> ${esc(l.pm?.phone || '')}</div><div class="small">Tenant: <b>${esc(l.tenant.name)}</b> ${esc(l.tenant.phone || '')}</div></div></div></div>`;
  $('#sign')?.addEventListener('click', async () => { const sig = await signModal('Sign lease', mine === 'tenant' ? l.tenant.name : u.name); if (!sig) return; await act(null, () => api.post(`/api/leases/${id}/sign`, { sig }), 'Signed'); leaseView(id); });
  $('#renew')?.addEventListener('click', async () => {
    const nr = Math.round(l.rent * (1 + l.escalation_pct / 100) / 10) * 10;
    const m = modal({ title: 'Renewal offer', body: `<form class="form cols" id="rf"><label class="field"><span>New rent</span><input class="input" name="rent" type="number" value="${nr}"></label><label class="field"><span>Months</span><input class="input" name="months" type="number" value="12"></label></form><p class="small muted">A new lease starting ${fdate(new Date(new Date(l.end_date).getTime() + 864e5).toISOString())} is sent to both parties to sign. No admin fee on renewals.</p>`, foot: '<button class="btn primary" id="ok">Send renewal</button>' });
    $('#ok', m).onclick = async () => { const r = await act($('#ok', m), () => api.post(`/api/leases/${id}/renew`, formObj($('#rf', m))), 'Renewal sent'); m.close(); go('#/app/lease/' + r.id); };
  });
  $('#notice')?.addEventListener('click', async () => { if (!await confirmBox('Notice to vacate', 'This records written notice today. Under the CPA the lease ends no sooner than 20 business days from now. The outgoing inspection will be booked automatically.', 'Give notice')) return; const r = await api.post(`/api/leases/${id}/notice`, {}); toast('Notice recorded – lease ends ' + fdate(r.end_date)); leaseView(id); });
}

// ================================================================== money
route('/app/money', async (_, q) => {
  const u = state.user;
  const pg = page(u.role === 'landlord' ? 'Statements' : 'Money', { actions: isStaff() ? `<button class="btn sm" id="imp">${icon('upload')}<span class="hide-sm">Import bank CSV</span></button>` : '' });
  const [d, po] = await Promise.all([api.get('/api/money/summary'), api.get('/api/money/payouts' + (q.period ? '?period=' + q.period : ''))]);
  let tab = q.tab || 'roll';
  pg.innerHTML = `${kpiTiles(d.kpis)}<div class="tabs">${[['roll', 'Rent roll'], ['arrears', 'Arrears'], ['payments', 'Payments'], ['payouts', u.role === 'landlord' ? 'Payouts' : 'Owner payouts'], ['deposits', 'Deposits']].map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="mb"></div>`;
  const roll = list => `<div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Property</th><th>Tenant</th><th>Ref</th><th class="num">Rent</th><th class="num">Paid ${period(d.period)}</th><th class="num">Balance</th><th>Status</th>${isOffice() ? '<th></th>' : ''}</tr>
    ${list.map(l => `<tr><td><a href="#/app/property/${l.property_id}"><b>${esc(l.title)}</b></a></td><td>${esc(l.tenant_name)}<div class="tiny muted">${esc(l.tenant_phone || '')}</div></td><td class="mono small">${l.ref}</td><td class="num">${R(l.rent)}</td><td class="num">${R(l.paid_month)}</td><td class="num ${l.balance > 0 ? 'prio-Urgent' : ''}">${R2(l.balance)}</td><td>${pill(l.state)}</td>
      ${isOffice() ? `<td><button class="btn sm" data-pay="${l.id}">Record</button></td>` : ''}</tr>`).join('') || '<tr><td colspan="8" class="muted">Nothing here.</td></tr>'}</table></div></div>`;
  const T = {
    roll: () => roll(d.rent_roll),
    arrears: () => `<div class="ai-note">${icon('bolt')}<span>Autopilot sends a reminder the day after rent is due, a final reminder on day 5 and a letter of demand on day 10 (CPA s14 – 20 business days to remedy). You only need to step in after that.</span></div>` + roll(d.rent_roll.filter(l => l.balance > 0)),
    payments: () => `<div class="card flush list">${d.payments.map(p => `<div class="li"><span class="pill ok">${esc(p.method)}</span><span class="grow"><b>${esc(p.tenant_name)}</b> <span class="small muted">${esc(p.title)} · ${esc(p.reference || '')}</span></span><span class="small muted">${fdate(p.created_at)}</span><b class="num">${R2(p.amount)}</b></div>`).join('')}</div>`,
    payouts: () => `<div class="row"><label class="field" style="max-width:200px"><span>Period</span><input class="input" type="month" id="per" value="${po.period}"></label><span class="spacer"></span>${isStaff() && po.rows.some(r => !r.paid) ? `<button class="btn primary" id="runpo">${icon('money')}Release ${po.rows.filter(r => !r.paid).length} payouts</button>` : ''}</div>
      <div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Property</th><th>Owner</th><th class="num">Rent received</th><th class="num">Est. fees</th><th class="num">Paid out</th><th></th></tr>
      ${po.rows.map(r => `<tr><td><b>${esc(r.title)}</b></td><td>${esc(r.landlord || '')}</td><td class="num">${R2(r.rent_in)}</td><td class="num">${r.fees_est != null ? R2(r.fees_est) : ''}</td><td class="num">${r.paid ? R2(r.paid) : pill('open', 'Pending')}</td><td><a class="btn sm" href="#/app/statement/${r.property_id}/${po.period}">Statement</a></td></tr>`).join('') || '<tr><td colspan="6" class="muted">No rent received in this period.</td></tr>'}</table></div></div>`,
    deposits: () => `<div class="card flush"><table class="t"><tr><th>Property</th><th>Tenant</th><th class="num">Deposit</th><th class="num">Held incl. interest</th></tr>${d.rent_roll.map(l => `<tr><td>${esc(l.title)}</td><td>${esc(l.tenant_name)}</td><td class="num">${R(l.deposit)}</td><td class="num">${R2(l.deposit_held)}</td></tr>`).join('')}</table></div>`,
  };
  const show = k => { tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k)); $('#mb').innerHTML = T[k]();
    $$('[data-pay]').forEach(b => b.onclick = () => recordPayment(d.rent_roll.find(l => l.id == b.dataset.pay), () => go('#/app/money?tab=' + tab + '&r=' + Date.now())));
    $('#per') && ($('#per').onchange = e => go('#/app/money?tab=payouts&period=' + e.target.value));
    $('#runpo') && ($('#runpo').onclick = async () => { if (!await confirmBox('Release payouts', `Deduct fees, repairs and insurance and pay each owner their balance for ${period(po.period)}? Owners get their statement by notification.`, 'Release')) return; const r = await act($('#runpo'), () => api.post('/api/money/payouts/run', { period: po.period })); toast(`${r.results.length} payouts released`); go('#/app/money?tab=payouts&period=' + po.period + '&r=' + Date.now()); });
  };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
  $('#imp')?.addEventListener('click', async () => {
    const f = await pickFiles({ accept: '.csv,text/csv', multiple: false }); if (!f.length) return;
    const r = await act($('#imp'), () => upload('/api/payments/import', f, 'file'));
    modal({ title: 'Bank import', body: `<p><b>${r.matched.length}</b> payment(s) matched by reference and allocated. ${r.unmatched.length} not matched.</p>${r.unmatched.length ? `<div class="card tint small">${r.unmatched.map(x => `${R2(x.amount)} · ${esc(x.line)}`).join('<br>')}</div><p class="small muted">Record unmatched ones by hand from the rent roll.</p>` : ''}`, onClose: () => go('#/app/money?r=' + Date.now()) });
  });
}, A);

route('/app/statement/:pid/:per', async ({ pid, per }) => {
  const s = await api.get(`/api/statement/${pid}/${per}`);
  const pg = page('Owner statement', { back: '#/app/money?tab=payouts', actions: `<button class="btn sm" onclick="print()">${icon('print')}Print / PDF</button>` });
  let bal = s.opening;
  pg.innerHTML = `<div class="card stack" style="max-width:860px"><div class="row top"><div class="grow"><div class="logo">${LOGO}</div><span class="small muted">AVA Rentals · Trust account statement</span></div><div class="right"><h2>${period(per)}</h2><span class="small muted">${esc(s.property.title)}</span></div></div>
    <div class="costs"><div><span>Owner</span><b>${esc(s.landlord?.company || s.landlord?.name || '')}</b></div><div><span>Property</span><span>${esc(s.property.address || '')}</span></div></div>
    <table class="t"><tr><th>Date</th><th>Description</th><th class="num">Amount</th><th class="num">Balance</th></tr><tr><td></td><td class="muted">Opening balance</td><td></td><td class="num">${R2(bal)}</td></tr>
    ${s.rows.map(r => { bal += r.amount; return `<tr><td class="nowrap">${fdate(r.date)}</td><td>${esc(r.description)}</td><td class="num">${R2(r.amount)}</td><td class="num">${R2(bal)}</td></tr>`; }).join('')}</table>
    <div class="kpis"><div class="kpi"><span>Income</span><b>${R2(s.income)}</b></div><div class="kpi"><span>Fees & costs</span><b>${R2(s.expenses)}</b></div><div class="kpi good"><span>Paid to you</span><b>${R2(s.payout)}</b></div></div></div>`;
}, A);

route('/app/earnings', async () => {
  const pg = page(state.user.role === 'admin' ? 'Revenue' : 'My earnings');
  const e = await api.get('/api/money/earnings');
  const by = {};
  e.pm.forEach(r => { (by[r.period] ||= { label: period(r.period), a: 0, b: 0 }); if (r.kind === 'commission') by[r.period].a += r.amount; else by[r.period].b += r.amount; });
  const rows = Object.entries(by).sort().map(([, v]) => v);
  const me = e.book.length === 1 ? e.book[0] : null;
  const bookCard = b => `<div class="card flush"><div class="card-head"><h3>${me ? 'What you earn per home' : esc(b.name)}${b.region && !me ? ` <span class="small muted">${esc(b.region)}</span>` : ''}</h3><span class="pill">${b.pct}% commission</span></div>
    <div class="tablewrap"><table class="t"><tr><th>Home</th><th>Status</th><th class="num">Rent</th><th class="num">Commission ${b.pct}%</th><th class="num">Finder's fee</th><th class="num">Per month</th><th class="num">Per year</th></tr>
    ${b.rows.map(r => `<tr class="${r.let ? '' : 'muted'}"><td><a href="#/app/property/${r.id}"><b>${esc(r.title)}</b></a><div class="tiny muted">${esc(r.area)}</div></td><td>${r.let ? '<span class="pill ok">Let</span>' : '<span class="pill">Vacant – asking</span>'}</td>
      <td class="num">${R(r.rent)}</td><td class="num">${R(r.commission)}</td><td class="num">${R(r.finders_fee)}</td><td class="num"><b>${R(r.month)}</b></td><td class="num">${R(r.month * 12)}</td></tr>`).join('')}
    <tr><td colspan="2"><b>Let now (${b.let} homes)</b></td><td class="num"><b>${R(b.rent_roll)}</b></td><td class="num"><b>${R(b.commission_month)}</b></td><td class="num"><b>${R(b.finders_month)}</b></td><td class="num"><b>${R(b.month)}</b></td><td class="num"><b>${R(b.year)}</b></td></tr>
    <tr class="muted"><td colspan="5">If every vacant home is let at its asking rent</td><td class="num">${R(b.potential_month)}</td><td class="num">${R(b.potential_year)}</td></tr></table></div></div>`;
  pg.innerHTML = `${me ? `<div class="kpis"><div class="kpi"><span>You earn per month</span><b>${R(me.month)}</b><small>${R(me.commission_month)} commission + ${R(me.finders_month)} finder's fees</small></div>
      <div class="kpi"><span>Per year at this rate</span><b>${R(me.year)}</b><small>before escalations</small></div>
      <div class="kpi"><span>When all your homes are let</span><b>${R(me.potential_month)}</b><small>${R(me.potential_year)} a year</small></div>
      <div class="kpi"><span>Commission tier</span><b>${me.pct}%</b><small>${me.homes} homes · 3% up to 20 · 4% up to 50 · 5% above</small></div></div>
    ${me.next_tier ? `<div class="ai-note">${icon('spark')}<span>Manage <b>${me.next_tier.more} more home${me.next_tier.more === 1 ? '' : 's'}</b> (${me.next_tier.homes} in total) to move to <b>${me.next_tier.pct}%</b>. On today's let homes alone that's <b>${R(me.next_tier.extra_month)} more a month</b> (${R(me.next_tier.extra_month * 12)} a year).</span></div>` : ''}
    <p class="small muted">Commission is ${me.pct}% of the rent collected on each let home, plus a ${R(e.finders_fee)} finder's fee per let home per month. It is paid from the AVA trust account with the owner statements on the ${e.payout_day}th of every month.</p>
    ${bookCard(me)}` : `<div class="card flush"><div class="card-head"><h3>Portfolio managers – commission</h3></div><div class="tablewrap"><table class="t"><tr><th>Portfolio manager</th><th class="num">Homes</th><th class="num">Let</th><th class="num">Tier</th><th class="num">Rent roll</th><th class="num">Earns per month</th><th class="num">Per year</th><th class="num">When fully let</th></tr>
      ${e.book.map(b => `<tr><td><b>${esc(b.name)}</b><div class="tiny muted">${esc(b.region || '')}</div></td><td class="num">${b.homes}</td><td class="num">${b.let}</td><td class="num">${b.pct}%</td><td class="num">${R(b.rent_roll)}</td><td class="num"><b>${R(b.month)}</b></td><td class="num">${R(b.year)}</td><td class="num">${R(b.potential_month)}</td></tr>`).join('')}
      <tr><td><b>Total</b></td><td class="num">${e.book.reduce((a, b) => a + b.homes, 0)}</td><td class="num">${e.book.reduce((a, b) => a + b.let, 0)}</td><td></td><td class="num"><b>${R(e.book.reduce((a, b) => a + b.rent_roll, 0))}</b></td><td class="num"><b>${R(e.book.reduce((a, b) => a + b.month, 0))}</b></td><td class="num"><b>${R(e.book.reduce((a, b) => a + b.year, 0))}</b></td><td class="num">${R(e.book.reduce((a, b) => a + b.potential_month, 0))}</td></tr></table></div></div>`}
    ${e.managed != null ? `<div class="kpis"><div class="kpi"><span>Homes under management</span><b>${e.managed}</b></div><div class="kpi"><span>Rented now</span><b>${e.rented}</b></div></div>
    <div class="card stack tight"><h3>First-year targets</h3>${e.targets.map(t => `<div class="bars"><div class="b"><span>Month ${t.month}: ${t.rented}</span><div class="track"><i style="width:${Math.min(100, e.rented / t.rented * 100)}%;background:var(--brand-2)"></i></div><span class="small">${Math.min(100, Math.round(e.rented / t.rented * 100))}%</span></div></div>`).join('')}<p class="small muted">Reach 150 homes with a 4.5★ rating and 95% of tenants in good standing to earn R100 000 in AVA shares.</p></div>` : ''}
    <div class="card"><h3>${state.user.role === 'admin' ? 'Portfolio manager payouts' : 'Earnings by month'}</h3>${barChart(rows, 'Commission', "Finder's fees")}</div>
    ${e.ava.length ? `<div class="card"><h3>AVA revenue</h3><table class="t">${e.ava.map(r => `<tr><td>${period(r.period)}</td><td class="num">${R2(r.amount)}</td></tr>`).join('')}</table></div>` : ''}`;
}, A);

// ================================================================== contractors
route('/app/contractors', async () => {
  const pg = page('Contractors', { actions: `<button class="btn primary sm" id="addc">${icon('plus')}Add contractor</button>` });
  const rows = await api.get('/api/contractors');
  pg.innerHTML = `<div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Contractor</th><th>Trades</th><th>Areas</th><th>Rating</th><th class="num">Jobs</th><th class="num">Avg days</th><th class="num">Open snags</th><th>Status</th></tr>
    ${rows.map(c => `<tr><td><b>${esc(c.company || c.name)}</b><div class="tiny muted">${esc(c.name)} · ${esc(c.phone || '')}${c.bee_level ? ' · B-BBEE ' + esc(c.bee_level) : ''}</div></td><td class="small">${(c.trades || []).map(esc).join(', ')}</td><td class="small">${(c.areas || []).map(esc).join(', ')}</td>
      <td>${stars(c.rating)} <span class="tiny muted">(${c.reviews})</span></td><td class="num">${c.jobs_done}${c.jobs_open ? ` <span class="tiny muted">+${c.jobs_open}</span>` : ''}</td><td class="num">${c.avg_days ?? '–'}</td><td class="num">${c.snags_open || ''}</td>
      <td>${c.approved ? `<span class="pill ok">Approved</span>` : `<button class="btn sm primary" data-ap="${c.user_id}">Approve</button>`} ${c.vetted ? '<span class="pill" title="ID, CIPC and criminal check done">Vetted</span>' : ''}</td></tr>`).join('')}</table></div></div>`;
  $$('[data-ap]').forEach(b => b.onclick = async () => { await api.put('/api/contractors/' + b.dataset.ap, { approved: 1, vetted: 1 }); toast('Approved'); go('#/app/contractors?r=' + Date.now()); });
  $('#addc').onclick = () => {
    const m = modal({ title: 'Add contractor', body: `<form class="form" id="cf"><div class="cols"><label class="field"><span>Company</span><input class="input" name="company" required></label><label class="field"><span>Contact name</span><input class="input" name="name" required></label></div>
      <div class="cols"><label class="field"><span>Email</span><input class="input" type="email" name="email" required></label><label class="field"><span>Phone</span><input class="input" name="phone"></label></div>
      <label class="field"><span>Trades</span><input class="input" name="trades" placeholder="Plumber, Electrician, Handyman"></label><div class="cols"><label class="field"><span>Areas</span><input class="input" name="areas" placeholder="Pretoria, Centurion"></label><label class="field"><span>Call-out fee</span><input class="input" type="number" name="callout_fee"></label></div></form>`, foot: '<button class="btn primary" id="ok">Add</button>' });
    $('#ok', m).onclick = async () => { const f = $('#cf', m); if (!f.reportValidity()) return; const r = await act($('#ok', m), () => api.post('/api/contractors', formObj(f))); m.close(); toast(`Added – temporary password ${r.temp_password}`); go('#/app/contractors?r=' + Date.now()); };
  };
}, A);

// ================================================================== inbox
route('/app/inbox', async (_, q) => {
  const pg = page(isStaff() ? 'Inbox' : 'Messages');
  const threads = await api.get('/api/threads');
  pg.innerHTML = `<div class="card flush inboxgrid"><div class="threads list" id="th">${threads.map(t => `<button class="li" data-k="${t.key}"><span class="avatar" style="${t.flag ? 'background:var(--bad)' : ''}">${initials(t.title)}</span><span class="grow"><span class="title">${esc(t.title)}</span><span class="small muted" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.last?.body || 'No messages yet')}</span></span>${t.unread ? `<span class="pill cta">${t.unread}</span>` : ''}</button>`).join('') || '<div class="empty">No conversations yet.</div>'}</div>
    <div class="chat" id="cv"><div class="empty">Choose a conversation.</div></div></div>`;
  const open = async k => {
    $$('#th [data-k]').forEach(b => b.style.background = b.dataset.k === k ? 'var(--brand-tint)' : '');
    const t = await api.get('/api/threads/' + encodeURIComponent(k));
    $('#cv').innerHTML = `<div class="card-head"><h3>${esc(t.title)}</h3></div><div class="msgs">${t.messages.map(m => `<div class="msg ${m.mine ? 'mine' : ''}">${esc(m.body)}<small>${m.mine ? '' : esc(m.from_name) + ' · '}${ago(m.created_at)}${m.sentiment === 'negative' ? ' · ⚠ upset' : ''}</small></div>`).join('') || '<p class="muted center">Say hello 👋</p>'}</div>
      ${t.suggested ? `<div class="suggest" id="sug">${icon('spark')} Suggested reply: “${esc(t.suggested)}” – tap to use</div>` : ''}<form id="mf"><input class="input" id="mi" placeholder="Write a message…" autocomplete="off"><button class="btn primary">Send</button></form>`;
    $('#cv .msgs').scrollTop = 1e6;
    $('#sug') && ($('#sug').onclick = () => { $('#mi').value = t.suggested; $('#mi').focus(); });
    $('#mf').onsubmit = async e => { e.preventDefault(); const body = $('#mi').value.trim(); if (!body) return; await api.post('/api/threads/' + encodeURIComponent(k), { body }); open(k); };
  };
  $$('#th [data-k]').forEach(b => b.onclick = () => open(b.dataset.k));
  const first = q.t || (threads.length && innerWidth > 1060 ? threads[0].key : null);
  if (first) open(first);
  else if (state.user.role === 'tenant' && !threads.length) {
    const d = await api.get('/api/dashboard'); if (d.lease) { pg.querySelector('#th').innerHTML = `<button class="li" data-k="lease:${d.lease.id}"><span class="avatar">PM</span><span class="grow">Your portfolio manager</span></button>`; $('#th [data-k]').onclick = () => open('lease:' + d.lease.id); open('lease:' + d.lease.id); }
  }
}, A);

// ================================================================== reports, settings, admin
route('/app/reports', async () => {
  const pg = page('Reports');
  const R_ = [['rent-roll', 'Rent roll', 'Every active lease with rent, escalation, balance and deposit.'], ['arrears', 'Arrears', 'Tenants owing money, with phone numbers for follow-up.'],
    ['maintenance', 'Maintenance', 'All repairs with category, priority, contractor, cost and days open.'], ['snags', 'Snag list', 'All snags with trade, contractor, quantity × rate, due date and rework count.'], ['owner-ledger', 'Owner ledger', 'Every trust movement per property – for audits and tax returns.']];
  pg.innerHTML = `<div class="grid3">${R_.map(([k, t, d]) => `<a class="card stack tight" href="/api/reports/${k}.xlsx" style="color:inherit;text-decoration:none">${icon('excel')}<h3>${t}</h3><p class="small muted">${d}</p><span class="btn sm">Download Excel</span></a>`).join('')}</div>`;
}, A);

route('/app/settings', async () => {
  const pg = page(state.user.role === 'admin' ? 'Settings & fees' : 'Settings');
  const s = await api.get('/api/settings');
  const admin = state.user.role === 'admin';
  const f = (k, l, t = 'number', h = '') => `<label class="field"><span>${l}</span><input class="input" name="${k}" type="${t}" value="${esc(Array.isArray(s[k]) ? JSON.stringify(s[k]) : s[k] ?? '')}" ${admin ? '' : 'disabled'} step="any">${h ? `<small>${h}</small>` : ''}</label>`;
  pg.innerHTML = `<form class="stack" id="sf">
    ${state.user.role === 'pm' ? `<div class="card stack"><h3>My commission</h3><p class="small muted">Option 2 in the pricing model: pick between 3% and 5% (used when AVA runs in 'chosen' mode).</p><div class="row"><input class="input" id="cp" type="number" min="3" max="5" step="0.5" value="${state.user.commission_pct || 4}" style="max-width:120px"><button class="btn" type="button" id="cps">Save</button></div></div>` : ''}
    <div class="card stack"><h3>Tenant fees</h3><div class="form cols">${f('vetting_fee', 'Vetting fee (R)')}${f('deposit_months', 'Deposit (× rent)')}${f('key_deposit', 'Key deposit (R)')}${f('inspection_base', 'Inspection base (≤2 bed, 1 bath)')}${f('inspection_extra_room', 'Per extra room')}</div></div>
    <div class="card stack"><h3>Landlord fees</h3><div class="form cols">${f('admin_fee', 'Admin fee per new contract')}${f('insurance_monthly', 'Insurance / month')}${f('own_admin_monthly', 'Own administrator / month')}${f('ava_tiers', 'Platform fee per home by homes managed [[up to, R]]', 'text', 'e.g. [[5,399],[20,349],[50,299],[999999,249]]')}</div></div>
    <div class="card stack"><h3>Portfolio managers</h3><div class="form cols"><label class="field"><span>Commission mode</span><select class="input" name="pm_commission_mode" ${admin ? '' : 'disabled'}><option value="tiered">Tiered by homes managed</option><option value="chosen" ${s.pm_commission_mode === 'chosen' ? 'selected' : ''}>PM picks 3–5%</option></select></label>${f('pm_tiers', 'Tiers [[up to, %]]', 'text')}${f('finders_fee', "Finder's fee / month")}</div></div>
    <div class="card stack"><h3>Automation</h3><div class="form cols">${f('quote_window_hours', 'Quote window (hours)')}${f('quotes_to_request', 'Quotes to request')}${f('shortlist_size', 'Shortlist size')}${f('auto_approve_limit', 'Emergency auto-approve limit (R)')}${f('payout_day', 'Owner payout day')}${f('deposit_interest_pct', 'Deposit interest % p.a.')}</div></div>
    ${admin ? `<div class="card stack"><h3>Payments – PayFast</h3><div class="form cols">${f('payfast_merchant_id', 'Merchant ID', 'text')}${f('payfast_merchant_key', 'Merchant key', 'text')}${f('payfast_passphrase', 'Passphrase', 'text')}${f('public_url', 'Public URL of this server', 'text', 'Needed for PayFast to call back (ITN)')}</div><label class="check"><input type="checkbox" name="payfast_sandbox" ${s.payfast_sandbox ? 'checked' : ''}>Sandbox mode</label>${f('trust_bank', 'Trust bank details shown to tenants', 'text')}</div>
    <div class="card stack"><h3>AI</h3><p class="small muted">AVA's triage, scoring, pricing and assistant work offline with rules. Add an Anthropic API key to let Claude write replies and listing copy.</p><div class="form cols"><label class="field"><span>Provider</span><select class="input" name="ai_provider"><option value="rules">Rules (offline)</option><option value="anthropic" ${s.ai_provider === 'anthropic' ? 'selected' : ''}>Anthropic Claude</option></select></label>${f('anthropic_api_key', 'API key', 'password')}${f('anthropic_model', 'Model', 'text')}</div></div>
    <div class="row"><span class="spacer"></span><button class="btn primary" id="ss">Save settings</button></div>` : ''}</form>`;
  $('#cps')?.addEventListener('click', async () => { await act($('#cps'), () => api.put('/api/me', { commission_pct: +$('#cp').value }), 'Saved'); });
  $('#ss')?.addEventListener('click', async e => {
    e.preventDefault(); const o = {};
    $$('#sf [name]').forEach(i => { let v = i.type === 'checkbox' ? i.checked : i.value; if (i.type === 'number') v = +v; if (typeof v === 'string' && v.trim().startsWith('[')) { try { v = JSON.parse(v); } catch (_) { } } o[i.name] = v; });
    await act($('#ss'), () => api.put('/api/settings', o), 'Settings saved');
  });
}, A);

route('/app/users', async () => {
  const pg = page('Users', { actions: `<button class="btn primary sm" id="addpm">${icon('plus')}Add portfolio manager</button>` });
  const rows = await api.get('/api/users');
  pg.innerHTML = `<div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th><th>Active</th></tr>${rows.map(u => `<tr><td><b>${esc(u.name)}</b><div class="tiny muted">${esc(u.company || '')}</div></td><td>${esc(u.email)}</td><td>${esc(u.role)}</td><td class="small">${fdate(u.created_at)}</td><td><label class="check"><input type="checkbox" data-u="${u.id}" ${u.active ? 'checked' : ''}></label></td></tr>`).join('')}</table></div></div>`;
  $$('[data-u]').forEach(c => c.onchange = () => api.put('/api/users/' + c.dataset.u, { active: c.checked ? 1 : 0 }).then(() => toast('Updated')));
  $('#addpm').onclick = () => { const m = modal({ title: 'Add portfolio manager', body: `<form class="form" id="uf"><label class="field"><span>Name</span><input class="input" name="name" required></label><label class="field"><span>Email</span><input class="input" type="email" name="email" required></label><input type="hidden" name="role" value="pm"></form>`, foot: '<button class="btn primary" id="ok">Add</button>' });
    $('#ok', m).onclick = async () => { const r = await act($('#ok', m), () => api.post('/api/users', formObj($('#uf', m)))); m.close(); toast('Added – temporary password ' + r.temp_password); go('#/app/users?r=' + Date.now()); }; };
}, A);

route('/app/reviews', async () => {
  const pg = page('Reviews to moderate');
  const rows = await api.get('/api/reviews');
  pg.innerHTML = `<p class="muted small">Ratings below 3 are held for review before they affect a contractor's score.</p><div class="card flush list">${rows.map(r => `<div class="li"><span class="stars">${'★'.repeat(r.rating)}${'☆'.repeat(5 - r.rating)}</span><span class="grow"><b>${esc(r.company || r.cname)}</b> <span class="small muted">by ${esc(r.author)}</span><div class="small">${esc(r.text || '')}</div></span><button class="btn sm" data-r="${r.id}" data-s="published">Publish</button><button class="btn sm ghost" data-r="${r.id}" data-s="rejected">Reject</button></div>`).join('') || '<div class="empty">Nothing to moderate.</div>'}</div>`;
  $$('[data-r]').forEach(b => b.onclick = async () => { await api.put('/api/reviews/' + b.dataset.r, { status: b.dataset.s }); b.closest('.li').remove(); toast('Done'); });
}, A);

// ================================================================== AI & virtual agent
route('/app/ai', async () => {
  const pg = page('AI & virtual agent', { actions: `<button class="btn sm" onclick="document.getElementById('fab').click()">${icon('spark')}Try the agent</button>` });
  const s = await api.get('/api/agent/stats');
  const CAPS = [
    ['chat', 'Virtual leasing agent', 'Answers prospects 24/7 from the listing data: costs, pets, backup power, area. Pre-qualifies on income, offers open slots and books viewings, starts applications, finds similar homes, and hands over hot leads to you.', `${s.viewings_booked} viewings booked this week`],
    ['users', 'Tenant & owner agent', 'Balance and payment reference, repair status, lease dates, notice, renewal, inspections, deposit refund, statements, approvals – answered from live data, in plain language, any hour.', `${s.messages} messages this week`],
    ['tool', 'Maintenance triage', 'Reads every request, sets category, trade, urgency and who is liable, gives safety steps for emergencies, dispatches emergencies within your auto-approve limit, and requests quotes from the best-rated contractors.', `${s.tickets_triaged} requests triaged · ${s.emergencies} emergencies dispatched`],
    ['clip', 'Quote ranking', 'Ranks quotes 60% on price and 40% on contractor rating, penalises slow ETAs, and sends the shortlist to the landlord when the window closes.', `${s.quotes_ranked} quotes ranked`],
    ['shield', 'Tenant scoring', 'Affordability (rent : income), credit score, documents and TPN rental history combined into one score with reasons.', `${s.apps_scored} applications scored`],
    ['chart', 'Rent pricing & listing copy', 'Suggests a rent range from comparable homes (median and R/m²) and writes the listing description from the property data.', 'On every property page'],
    ['alert', 'Sentiment & escalation', 'Spots frustrated tenants in messages and repair requests, raises the priority and puts it in your inbox before it becomes a complaint.', `${s.escalations} escalations raised`],
    ['refresh', 'Renewal risk & anomalies', 'Scores each tenancy for renewal risk from payment history and repair experience; flags duplicate payments and repair costs far above normal.', 'Command centre'],
    ['bolt', 'Autopilot', 'Rent charging, escalations, arrears ladder, deposit interest, renewal offers, inspection bookings, quote shortlists, stalled-job nudges, snag deadlines, payout runs.', `${s.autopilot_actions} actions logged`],
  ];
  pg.innerHTML = `<div class="kpis"><div class="kpi"><span>Conversations (7 days)</span><b>${s.conversations}</b></div><div class="kpi good"><span>Handled without you</span><b>${s.messages ? Math.round(100 * (s.messages - s.handoffs) / s.messages) : 100}%</b></div>
      <div class="kpi"><span>Handed to you</span><b>${s.handoffs}</b></div><div class="kpi"><span>Viewings booked by the agent</span><b>${s.viewings_booked}</b></div></div>
    <div class="grid3">${CAPS.map(([ic, t, d, m]) => `<div class="card stack tight"><div class="row">${icon(ic)}<h3 class="grow">${t}</h3></div><p class="small muted">${d}</p><span class="pill jac" style="width:max-content;max-width:100%;white-space:normal">${esc(m)}</span></div>`).join('')}</div>
    <div class="ai-note">${icon('spark')}<span>Runs offline on transparent rules. Add an Anthropic API key under Settings → AI and the agent writes its replies with Claude, from the same facts – it never invents prices or promises.</span></div>
    <div class="card flush"><div class="card-head"><h3>Recent virtual-agent conversations</h3><div class="seg" id="fl"><button data-f="" aria-pressed="true">All</button><button data-f="h">Handed over</button></div></div><div class="list" id="cl"></div></div>`;
  const draw = f => {
    $('#cl').innerHTML = s.recent.filter(r => !f || r.handoff).map(r => `<div class="stack tight"><div class="row small"><span class="pill ${r.handoff ? 'warn' : 'jac'}">${esc(r.intent)}</span><b>${esc(r.name || 'Visitor')}</b><span class="muted">${esc(r.role)}${r.title ? ' · ' + esc(r.title) : ''}</span><span class="spacer"></span><span class="tiny faint">${ago(r.created_at)}</span></div>
      <div class="small">“${esc(r.text)}”</div><div class="small muted">→ ${esc(r.reply)}</div></div>`).join('') || '<div class="muted">No conversations yet – open the agent bottom right and try it.</div>';
  };
  $$('#fl button').forEach(b => b.onclick = () => { $$('#fl button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(b.dataset.f); });
  draw('');
}, A);
