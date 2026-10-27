// Trust accounting (admin): cashbooks, bank feed & reconciliation, payment batches, debit orders, deposit investments,
// journals, month locking and year-end. Plus the tenant's debit order card and the owner's payout bank details.
import { $, $$, act, api, confirmBox, esc, fdate, fdt, go, icon, modal, period, R, route, state, toast } from './core.js';
import { page } from './shell.js';

const BOOK = { trust: 'Trust account', deposit: 'Deposit trust', business: 'Business account' };
const lastMonth = () => { const d = new Date(); d.setDate(0); return d.toISOString().slice(0, 7); };
const thisMonth = () => new Date().toISOString().slice(0, 7);
const ok = b => b ? `<span class="pill ok">${icon('check')}Balanced</span>` : '<span class="pill bad">Out of balance</span>';
const amt = v => `<span class="num ${v < 0 ? 'neg' : ''}">${R(v)}</span>`;

route('/app/trust', async (_, q) => {
  if (state.user.role !== 'admin') return go('#/app');
  const pg = page('Trust accounts', { sub: 'Property Practitioners Act s54 · Rental Housing Act s5(3)' });
  const TABS = [['overview', 'Overview'], ['cashbook', 'Cashbooks'], ['recon', 'Reconcile'], ['batches', 'Payments'], ['debit', 'Debit orders'],
    ['deposits', 'Deposit investments'], ['journals', 'Journals'], ['periods', 'Months & year-end']];
  let tab = q.tab || 'overview';
  pg.innerHTML = `<div class="tabs">${TABS.map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="tb" class="stack"></div>`;
  const show = async k => { tab = k; $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k)); history.replaceState(null, '', `#/app/trust?tab=${k}`); $('#tb').innerHTML = '<div class="muted">Loading…</div>'; await T[k]($('#tb'), q); };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));
  show(tab);
}, { auth: true });

const T = {
  // ------------------------------------------------------------ overview: the trust trial balance
  async overview(el) {
    const o = await api.get('/api/trust');
    const tb = o.tb;
    el.innerHTML = `<div class="kpis">${o.books.map(b => `<a class="kpi" href="#/app/trust?tab=cashbook&book=${b.code}"><span>${esc(b.name)}</span><b>${R(b.cash)}</b>
        <small>${esc(b.bank)} ${b.account_masked}</small>${b.unmatched ? `<small style="color:var(--warn);font-weight:700">${b.unmatched} bank line${b.unmatched === 1 ? '' : 's'} to explain</small>` : ''}</a>`).join('')}</div>
      <div class="grid2" style="align-items:start">
        <div class="card stack"><div class="row"><h3 class="grow">Trust trial balance</h3>${ok(tb.trust.balanced)}</div>
          <p class="small muted">Money in the trust bank account must equal what AVA owes to owners and the fees and payables not yet paid out – to the rand.</p>
          <div class="costs"><div><span><b>Trust bank (cashbook)</b></span><b>${R(tb.trust.cash)}</b></div>
            ${tb.trust.lines.map(l => `<div><span>${esc(l.label)}</span><span>${R(l.amount)}</span></div>`).join('')}
            <div class="tot"><span>Total owed from trust</span><span>${R(tb.trust.liabilities)}</span></div>
            <div><span>Difference</span><b style="color:${tb.trust.balanced ? 'var(--ok)' : 'var(--bad)'}">${R(tb.trust.difference)}</b></div></div>
          ${tb.trust.tenant_prepayments ? `<p class="tiny muted">Includes ${R(tb.trust.tenant_prepayments)} rent paid in advance by tenants.</p>` : ''}</div>
        <div class="stack">
          <div class="card stack tight"><div class="row"><h3 class="grow">Deposit trust</h3>${ok(tb.deposit.balanced)}</div>
            <div class="costs"><div><span>In ${tb.deposit.accounts} deposit investment accounts</span><b>${R(tb.deposit.cash)}</b></div><div><span>Owed to tenants (deposits + interest)</span><span>${R(tb.deposit.liabilities)}</span></div></div>
            <a class="btn sm" href="#/app/trust?tab=deposits">Deposit accounts</a></div>
          <div class="card stack tight"><h3>To do</h3><div class="list">
            ${o.batches_waiting.map(b => `<a class="li" href="#/app/trust?tab=batches&b=${b.id}">${icon('money')}<span class="grow"><b>${b.ref}</b> ${BATCH[b.kind]} ${b.period ? '· ' + period(b.period) : ''}</span>${R(b.total)} <span class="pill ${b.status === 'draft' ? 'warn' : 'info'}">${b.status === 'draft' ? 'Authorise' : 'Release'}</span></a>`).join('')}
            ${o.books.filter(b => b.unmatched).map(b => `<a class="li" href="#/app/trust?tab=recon&book=${b.code}">${icon('refresh')}<span class="grow">Explain ${b.unmatched} bank line${b.unmatched === 1 ? '' : 's'} – ${esc(b.name)}</span></a>`).join('')}
            ${o.last_reconciled.trust < o.last_period ? `<a class="li" href="#/app/trust?tab=recon&per=${o.last_period}">${icon('check')}<span class="grow">Reconcile and lock ${period(o.last_period)}</span></a>` : ''}
            ${o.mandates.pending ? `<a class="li" href="#/app/trust?tab=debit">${icon('clip')}<span class="grow">${o.mandates.pending} debit order${o.mandates.pending === 1 ? '' : 's'} waiting for the tenant's DebiCheck approval</span></a>` : ''}
            </div><p class="tiny muted">Last locked month: ${o.last_locked ? period(o.last_locked) : '–'} · ${o.mandates.active} tenants pay by debit order · bank feeds: ${o.feeds.mode === 'simulated' ? 'simulated (add the bank API keys in Settings)' : 'live'}</p></div>
        </div></div>`;
  },

  // ------------------------------------------------------------ cashbooks with the bank feed
  async cashbook(el, q) {
    let code = q.book || 'trust', per = q.per || thisMonth();
    const draw = async () => {
      const c = await api.get(`/api/trust/cashbook/${code}?period=${per}`);
      el.innerHTML = `<div class="row wrap"><div class="seg" id="bk">${Object.entries(BOOK).map(([k, l]) => `<button data-v="${k}" aria-pressed="${k === code}">${l}</button>`).join('')}</div>
          <input class="input" type="month" id="per" value="${per}" style="max-width:170px"><span class="spacer"></span>
          <button class="btn sm" id="feed">${icon('refresh')}Get bank feed</button><button class="btn sm" id="imp">${icon('upload')}Import statement (OFX/CSV)</button></div>
        <p class="small muted">${esc(c.book.bank)} · branch ${esc(c.book.branch_code)} · account ${esc(c.book.account_no)}${c.locked ? ' · <b>month locked</b>' : ''}</p>
        <div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Date</th><th>Description</th><th>Reference</th><th class="num">In</th><th class="num">Out</th><th>Bank</th></tr>
          <tr><td></td><td><b>Opening balance</b></td><td></td><td class="num" colspan="2"><b>${R(c.opening)}</b></td><td></td></tr>
          ${c.tx.map(t => `<tr><td>${fdate(t.date)}</td><td>${esc(t.description || '')}</td><td class="small mono">${esc(t.reference || '')}</td><td class="num">${t.amount > 0 ? R(t.amount) : ''}</td><td class="num">${t.amount < 0 ? R(-t.amount) : ''}</td>
            <td>${t.bank_line_id ? `<span class="pill ok" title="On the bank statement ${fdate(t.bank_date)}">${icon('check')}Cleared</span>` : '<span class="pill">In transit</span>'}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No movements this month.</td></tr>'}
          <tr><td></td><td><b>Closing balance</b></td><td></td><td class="num" colspan="2"><b>${R(c.closing)}</b></td><td></td></tr></table></div></div>`;
      $$('#bk button', el).forEach(b => b.onclick = () => { code = b.dataset.v; draw(); });
      $('#per', el).onchange = e => { per = e.target.value; draw(); };
      $('#feed', el).onclick = async () => { const r = await act($('#feed', el), () => api.post('/api/trust/feed/' + code)); toast(`${r.new_lines} new bank lines · ${r.matched} matched · ${r.allocated} rent allocated · ${r.unmatched} to explain`); draw(); };
      $('#imp', el).onclick = () => { const i = document.createElement('input'); i.type = 'file'; i.accept = '.ofx,.qfx,.csv,.txt'; i.onchange = async () => { const fd = new FormData(); fd.append('file', i.files[0]); const r = await act(null, () => api.post('/api/trust/import/' + code, fd)); toast(`${r.new_lines} lines imported · ${r.matched} matched · ${r.allocated} rent allocated · ${r.unmatched} to explain`); draw(); }; i.click(); };
    };
    draw();
  },

  // ------------------------------------------------------------ bank reconciliation
  async recon(el, q) {
    let code = q.book || 'trust', per = q.per || lastMonth();
    const draw = async () => {
      const r = await api.get(`/api/trust/recon/${code}/${per}`);
      el.innerHTML = `<div class="row wrap"><div class="seg" id="bk">${Object.entries(BOOK).map(([k, l]) => `<button data-v="${k}" aria-pressed="${k === code}">${l}</button>`).join('')}</div>
          <input class="input" type="month" id="per" value="${per}" style="max-width:170px"><span class="spacer"></span>
          ${r.reconciled ? `<span class="pill ok">${icon('check')}Reconciled ${fdate(r.reconciled.created_at)}</span>` : `<button class="btn primary" id="sign" ${r.can_sign ? '' : 'disabled'}>${icon('check')}Sign off reconciliation</button>`}
          ${r.reconciled && !r.locked ? `<button class="btn" id="lock">Lock ${period(per)}</button>` : ''}${r.locked ? '<span class="pill">Locked</span>' : ''}</div>
        <div class="grid2" style="align-items:start"><div class="card stack tight"><h3>${esc(r.name)} · ${period(per)}</h3><div class="costs">
            <div><span>Bank statement balance at ${fdate(r.end)}</span><b>${R(r.statement_balance)}</b></div>
            <div><span>+ cashbook items not yet on the statement</span><span>${R(r.unpresented.reduce((a, t) => a + t.amount, 0))}</span></div>
            <div><span>− bank lines not yet in the cashbook</span><span>${R(r.unexplained.reduce((a, l) => a + l.amount, 0))}</span></div>
            <div class="tot"><span>Adjusted statement</span><span>${R(r.adjusted_statement)}</span></div>
            <div><span>Cashbook balance</span><b>${R(r.cashbook_balance)}</b></div></div>
          <p class="small muted">${r.can_sign || r.reconciled ? 'Every bank line is explained.' : 'Explain every bank line below, then sign off. A signed-off month can be locked – after that nothing in it can change.'}</p></div>
          <div class="stack">
            <div class="card flush"><div class="card-head"><h3>Bank lines to explain</h3></div><div class="list">${r.unexplained.filter(l => !l.matched_tx).map(l => `<div class="stack tight">
              <div class="row"><span class="grow"><b>${esc(l.description)}</b><div class="small muted">${fdate(l.date)}</div></span><b>${R(l.amount)}</b></div>
              <div class="row wrap" style="gap:6px">${l.amount > 0 ? `<button class="btn sm" data-ten="${l.id}">Rent from a tenant…</button><button class="btn sm" data-sus="${l.id}">Unidentified – to suspense</button>` : `<button class="btn sm" data-chg="${l.id}">Bank charges (business pays)</button>`}</div></div>`).join('') || '<div class="muted">Nothing to explain.</div>'}</div></div>
            ${r.unpresented.length ? `<div class="card flush"><div class="card-head"><h3>In transit (in the cashbook, not yet on the statement)</h3></div><div class="list">${r.unpresented.map(t => `<div class="row small"><span class="grow">${fdate(t.date)} ${esc(t.description || '')}</span>${R(t.amount)}</div>`).join('')}</div></div>` : ''}
          </div></div>`;
      $$('#bk button', el).forEach(b => b.onclick = () => { code = b.dataset.v; draw(); });
      $('#per', el).onchange = e => { per = e.target.value; draw(); };
      $('#sign', el)?.addEventListener('click', async () => { await act($('#sign', el), () => api.post(`/api/trust/recon/${code}/${per}`), 'Reconciliation signed off'); draw(); });
      $('#lock', el)?.addEventListener('click', async () => { if (!await confirmBox(`Lock ${period(per)}`, 'Nothing dated in this month can be added or changed afterwards. Corrections go in as journals in an open month.', 'Lock month')) return; await act($('#lock', el), () => api.post(`/api/trust/periods/${per}/lock`), 'Month locked'); draw(); });
      $$('[data-chg]', el).forEach(b => b.onclick = async () => { await act(b, () => api.post(`/api/trust/lines/${b.dataset.chg}/resolve`, { action: 'bank_charges' }), 'Recorded – the business account refunds the trust account'); draw(); });
      $$('[data-sus]', el).forEach(b => b.onclick = async () => { await act(b, () => api.post(`/api/trust/lines/${b.dataset.sus}/resolve`, { action: 'suspense' }), 'In suspense – allocate it once you know who paid'); draw(); });
      $$('[data-ten]', el).forEach(b => b.onclick = async () => {
        const j = await api.get('/api/trust/journals');
        const m = modal({ title: 'Allocate to a tenant', body: `<label class="field"><span>Which lease?</span><select class="input" id="ls">${j.properties.filter(p => p.lease_id).map(p => `<option value="${p.lease_id}">${esc(p.title)} · AVA${String(p.lease_id).padStart(5, '0')}</option>`).join('')}</select></label>`, foot: '<button class="btn primary" id="ok">Allocate</button>' });
        $('#ok', m).onclick = async () => { await act($('#ok', m), () => api.post(`/api/trust/lines/${b.dataset.ten}/resolve`, { action: 'tenant', lease_id: +$('#ls', m).value }), 'Allocated as rent'); m.close(); draw(); };
      });
    };
    draw();
  },

  // ------------------------------------------------------------ payment batches
  async batches(el, q) {
    const list = await api.get('/api/trust/batches');
    el.innerHTML = `<div class="row"><p class="small muted grow">Money leaves the trust account only in a batch: prepared, authorised, then released with a bank file for your online banking.</p>
        <button class="btn sm primary" id="ft">${icon('plus')}Prepare fee transfer</button></div>
      <div class="grid2" style="align-items:start;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr)"><div class="card flush list">${list.map(b => `<a class="li" href="#/app/trust?tab=batches&b=${b.id}" data-b="${b.id}">
          <span class="grow"><b>${b.ref}</b> ${BATCH[b.kind] || b.kind}<div class="small muted">${b.period ? period(b.period) + ' · ' : ''}${b.released_at ? 'released ' + fdate(b.released_at) : fdate(b.created_at)}</div></span>
          ${R(b.total)} <span class="pill ${b.status === 'released' ? 'ok' : b.status === 'authorised' ? 'info' : 'warn'}">${b.status}</span></a>`).join('') || '<div class="muted">No batches yet.</div>'}</div>
        <div id="bd"></div></div>`;
    $('#ft', el).onclick = async () => { const b = await act($('#ft', el), () => api.post('/api/trust/batches/fee-transfer'), 'Fee transfer prepared'); go(`#/app/trust?tab=batches&b=${b.id}&r=${Date.now()}`); };
    const open = async id => {
      const b = await api.get('/api/trust/batches/' + id);
      $('#bd', el).innerHTML = `<div class="card stack"><div class="row"><h3 class="grow">${b.ref} · ${BATCH[b.kind]}</h3><b>${R(b.total)}</b></div>
        <p class="small muted">Prepared ${b.created_by_name ? 'by ' + esc(b.created_by_name) + ' ' : ''}${fdt(b.created_at)}${b.authorised_at ? ` · authorised by ${esc(b.authorised_by_name || '')} ${fdt(b.authorised_at)}` : ''}${b.released_at ? ` · released ${fdt(b.released_at)}` : ''}</p>
        ${b.missing_bank ? `<div class="ai-note">${icon('alert')}<span>${b.missing_bank} payee${b.missing_bank === 1 ? ' has' : 's have'} no bank details – ask them to add them under Statements → Where we pay you.</span></div>` : ''}
        <div class="tablewrap"><table class="t"><tr><th>Payee</th><th>Bank</th><th>Account</th><th>Reference</th><th class="num">Amount</th></tr>
          ${b.lines.map(l => `<tr><td><b>${esc(l.payee)}</b>${l.note ? `<div class="tiny muted">${esc(l.note)}</div>` : ''}</td><td>${esc(l.bank || '')}</td><td class="mono small">${l.missing_bank ? '<span class="pill bad">missing</span>' : l.account_masked}</td><td class="small">${esc(l.reference || '')}</td><td class="num">${R(l.amount)}</td></tr>`).join('')}</table></div>
        <div class="row">${b.status === 'draft' ? `<button class="btn primary" id="au">${icon('check')}Authorise</button>` : ''}${b.status === 'authorised' ? `<button class="btn cta" id="rl">Release payments</button>` : ''}
          <span class="spacer"></span>${b.status !== 'draft' ? `<a class="btn sm" href="/api/trust/batches/${b.id}/bank-file">${icon('excel')}Bank file (CSV)</a>` : ''}</div></div>`;
      $('#au', el)?.addEventListener('click', async () => { await act($('#au', el), () => api.post(`/api/trust/batches/${id}/authorise`), 'Authorised'); T.batches(el, { b: id }); });
      $('#rl', el)?.addEventListener('click', async () => { if (!await confirmBox('Release payments', `Pay ${b.lines.length} payee${b.lines.length === 1 ? '' : 's'} ${R(b.total)} from the trust account. Upload the bank file to your online banking (or it goes straight to the bank once connected).`, 'Release')) return; await act($('#rl', el), () => api.post(`/api/trust/batches/${id}/release`), 'Released – download the bank file'); T.batches(el, { b: id }); });
    };
    $$('[data-b]', el).forEach(a => a.onclick = e => { e.preventDefault(); open(a.dataset.b); });
    const first = q.b || list.find(b => b.status !== 'released')?.id || list[0]?.id;
    if (first) open(first);
  },

  // ------------------------------------------------------------ debit orders
  async debit(el) {
    const d = await api.get('/api/trust/debit-orders');
    el.innerHTML = `<div class="row"><p class="small muted grow">DebiCheck debit orders through Netcash${d.netcash ? '' : ' – <b>simulated</b> until the Netcash service key is added in Settings'}. AVA collects the amount due on each tenant's debit day; unpaids go straight into arrears.</p>
        <input class="input" type="date" id="dd" style="max-width:170px"><button class="btn sm" id="run">Run debit orders</button></div>
      <div class="grid2" style="align-items:start"><div class="card flush"><div class="card-head"><h3>Mandates</h3></div><div class="tablewrap"><table class="t"><tr><th>Tenant</th><th>Bank</th><th>Day</th><th class="num">Max</th><th>DebiCheck</th></tr>
          ${d.mandates.map(m => `<tr><td><b>${esc(m.tenant)}</b><div class="tiny muted">${esc(m.title)} · ${m.ref}</div></td><td class="small">${esc(m.bank)} ${m.account}</td><td>${m.debit_day}</td><td class="num">${R(m.max_amount)}</td>
            <td><span class="pill ${m.debicheck === 'approved' ? 'ok' : m.debicheck === 'pending' ? 'warn' : 'bad'}">${m.debicheck}</span></td></tr>`).join('') || '<tr><td colspan="5" class="muted">No tenants on debit order yet – they sign up under Pay rent.</td></tr>'}</table></div></div>
        <div class="card flush"><div class="card-head"><h3>Collection runs</h3></div><div class="list">${d.runs.map(r => {
          const un = r.items.filter(i => i.status === 'unpaid');
          return `<div class="stack tight"><div class="row"><span class="grow"><b>${r.ref}</b> · ${fdate(r.action_date)} <span class="small muted">${r.count} debit${r.count === 1 ? '' : 's'}</span></span>${R(r.total)}<a class="btn sm" href="/api/trust/debit-orders/runs/${r.id}/file" title="Netcash batch file">${icon('doc')}</a></div>
            ${un.map(i => `<div class="small" style="color:var(--bad)">${icon('alert')} Unpaid: ${esc(i.title)} ${R(i.amount)} – ${esc(i.reason || '')}</div>`).join('')}</div>`; }).join('') || '<div class="muted">No runs yet.</div>'}</div></div></div>`;
    $('#dd', el).value = new Date().toISOString().slice(0, 10);
    $('#run', el).onclick = async () => { await act($('#run', el), () => api.post('/api/trust/debit-orders/run', { date: $('#dd', el).value }), 'Debit orders collected'); T.debit(el); };
  },

  // ------------------------------------------------------------ deposit investment accounts
  async deposits(el) {
    const rows = await api.get('/api/trust/deposits');
    const open = rows.filter(a => a.status === 'open');
    el.innerHTML = `<p class="small muted">Every tenant's deposit sits in its own interest-bearing investment account (Rental Housing Act s5(3)(c)); the interest belongs to the tenant and is paid out with the deposit.</p>
      <div class="kpis"><div class="kpi"><span>Open accounts</span><b>${open.length}</b></div><div class="kpi"><span>Held</span><b>${R(open.reduce((a, x) => a + x.balance, 0))}</b></div><div class="kpi"><span>Interest earned for tenants</span><b>${R(open.reduce((a, x) => a + x.interest, 0))}</b></div></div>
      <div class="card flush"><div class="tablewrap"><table class="t"><tr><th>Tenant</th><th>Property</th><th>Account</th><th>Opened</th><th class="num">Rate</th><th class="num">Interest</th><th class="num">Balance</th><th></th></tr>
        ${rows.map(a => `<tr><td><b>${esc(a.tenant)}</b></td><td>${esc(a.title)}</td><td class="small mono">${esc(a.bank)} ${esc(a.account_no)}</td><td>${fdate(a.opened_at)}</td><td class="num">${a.rate}%</td><td class="num">${R(a.interest)}</td><td class="num"><b>${R(a.balance)}</b></td>
          <td>${a.status === 'open' ? '<span class="pill ok">Open</span>' : `<span class="pill">Closed ${fdate(a.closed_at)}</span>`}</td></tr>`).join('')}</table></div></div>`;
  },

  // ------------------------------------------------------------ journals
  async journals(el) {
    const j = await api.get('/api/trust/journals');
    const ACC = [['owner', 'Owner (property)'], ['tenant', 'Tenant (property)'], ['deposit', 'Deposit (property)'], ...Object.entries(j.controls).map(([k, l]) => ['control:' + k, l])];
    el.innerHTML = `<div class="row"><p class="small muted grow">Corrections never edit history: a journal moves money between owner, tenant, deposit and control accounts in an open month, with a reason – and it must balance.</p><button class="btn sm primary" id="nj">${icon('plus')}New journal</button></div>
      <div class="card flush list">${j.journals.map(x => `<div class="stack tight"><div class="row"><b class="grow">${x.ref} · ${esc(x.reason)}</b><span class="small muted">${fdate(x.date)} · ${esc(x.by_name || '')}</span></div>
        ${x.lines.map(l => `<div class="row small"><span class="grow">${esc(l.account === 'control' ? j.controls[l.kind] : l.account)}${l.ptitle ? ' · ' + esc(l.ptitle) : ''}</span>${R(l.amount)}</div>`).join('')}</div>`).join('') || '<div class="muted">No journals yet.</div>'}</div>`;
    $('#nj', el).onclick = () => {
      const line = () => `<div class="row jl" style="gap:6px"><select class="input" data-a>${ACC.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select>
        <select class="input" data-p><option value="">–</option>${j.properties.map(p => `<option value="${p.id}" data-l="${p.lease_id || ''}">${esc(p.title)}</option>`).join('')}</select><input class="input" type="number" step="1" data-v placeholder="+ / − R" style="max-width:120px"></div>`;
      const m = modal({ title: 'New journal', body: `<label class="field"><span>Reason (shown in the audit trail)</span><input class="input" id="jr" placeholder="e.g. Admin fee not charged on new lease"></label>
        <label class="field"><span>Date</span><input class="input" type="date" id="jd" value="${new Date().toISOString().slice(0, 10)}"></label><div id="jls" class="stack tight">${line()}${line()}</div>
        <button class="btn sm" type="button" id="al">${icon('plus')}Line</button><p class="small" id="js"></p>`, foot: '<button class="btn primary" id="ok">Post journal</button>' });
      const sum = () => { const t = $$('[data-v]', m).reduce((a, i) => a + (+i.value || 0), 0); $('#js', m).innerHTML = t ? `<span style="color:var(--bad)">Out by ${R(t)}</span>` : '<span style="color:var(--ok)">Balances</span>'; };
      m.addEventListener('input', sum); sum();
      $('#al', m).onclick = () => $('#jls', m).insertAdjacentHTML('beforeend', line());
      $('#ok', m).onclick = async () => {
        const lines = $$('.jl', m).map(r => { const a = $('[data-a]', r).value, p = $('[data-p]', r); return { account: a.startsWith('control:') ? 'control' : a, kind: a.startsWith('control:') ? a.slice(8) : undefined, property_id: +p.value || undefined, lease_id: +(p.selectedOptions[0]?.dataset.l) || undefined, amount: +$('[data-v]', r).value || 0 }; }).filter(l => l.amount);
        await act($('#ok', m), () => api.post('/api/trust/journals', { reason: $('#jr', m).value, date: $('#jd', m).value, lines }), 'Journal posted'); m.close(); T.journals(el);
      };
    };
  },

  // ------------------------------------------------------------ months and year-end
  async periods(el) {
    const p = await api.get('/api/trust/periods');
    el.innerHTML = `<div class="grid2" style="align-items:start"><div class="card flush"><div class="card-head"><h3>Months</h3></div><div class="tablewrap"><table class="t"><tr><th>Month</th>${Object.values(BOOK).map(b => `<th>${b}</th>`).join('')}<th></th></tr>
        ${p.periods.map(x => `<tr><td><b>${period(x.period)}</b></td>${Object.keys(BOOK).map(c => `<td>${x.reconciled[c] ? `<span class="pill ok">${icon('check')}Reconciled</span>` : x.activity[c] ? `<a class="pill warn" href="#/app/trust?tab=recon&book=${c}&per=${x.period}">To reconcile</a>` : '<span class="muted small">–</span>'}</td>`).join('')}
          <td>${x.locked ? '<span class="pill">Locked</span>' : x.period < new Date().toISOString().slice(0, 7) ? `<button class="btn sm" data-lock="${x.period}">Lock</button>` : '<span class="small muted">open</span>'}</td></tr>`).join('')}</table></div></div>
      <div class="stack"><div class="card stack tight"><h3>Financial year-end</h3><p class="small muted">The year ends in ${['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][p.fy_end_month]}. Closing locks every month in the year and keeps a snapshot of the trust trial balance for the auditor (Fidelity Fund certificate).</p>
        ${p.closable.map(y => `<button class="btn" data-fy="${y}">Close financial year ending ${['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][p.fy_end_month]} ${y}</button>`).join('')}
        <div class="list">${p.year_ends.map(y => `<a class="li" href="#" data-ye="${y.fy}">${icon('doc')}<span class="grow">FY ${y.fy - 1}/${String(y.fy).slice(2)} · ${period(y.start_period)} – ${period(y.end_period)}</span><span class="pill ok">Closed</span></a>`).join('') || '<div class="muted">No year closed yet.</div>'}</div></div></div></div>`;
    $$('[data-lock]', el).forEach(b => b.onclick = async () => { await act(b, () => api.post(`/api/trust/periods/${b.dataset.lock}/lock`), 'Locked'); T.periods(el); });
    $$('[data-fy]', el).forEach(b => b.onclick = async () => { if (!await confirmBox('Close the financial year', 'Every month in the year is locked for good and the trial balance is kept for the audit.', 'Close year')) return; await act(b, () => api.post('/api/trust/year-end/' + b.dataset.fy), 'Year closed'); T.periods(el); });
    $$('[data-ye]', el).forEach(a => a.onclick = async e => {
      e.preventDefault(); const y = await api.get('/api/trust/year-end/' + a.dataset.ye); const s = y.snapshot;
      modal({ title: `Trial balance at ${fdate(s.as_at)}`, body: `<div class="costs"><div><span><b>Trust bank</b></span><b>${R(s.trust.cash)}</b></div>${s.trust.lines.map(l => `<div><span>${esc(l.label)}</span><span>${R(l.amount)}</span></div>`).join('')}
        <div class="tot"><span>Owed from trust</span><span>${R(s.trust.liabilities)}</span></div><div><span>Deposit trust</span><span>${R(s.deposit.cash)} vs ${R(s.deposit.liabilities)} owed</span></div></div>
        <p class="small">${ok(s.trust.balanced && s.deposit.balanced)}</p>`, cls: 'wide' });
    });
  },
};
const BATCH = { owner_payout: 'Owner payouts', fee_transfer: 'Fees, insurance & contractors', contractor: 'Contractor payments' };

// ------------------------------------------------------------------ tenant: pay by debit order
export async function debitCard(host) {
  const d = await api.get('/api/me/debit-order');
  const m = d.mandate;
  host.innerHTML = `<div class="card stack"><h3>${icon('refresh')} Pay by debit order</h3>${m ? `
      <div class="row"><span class="grow"><b>${esc(m.bank)} ${m.account}</b><div class="small muted">Collected on the ${m.debit_day}${['th', 'st', 'nd', 'rd'][m.debit_day % 10 > 3 || [11, 12, 13].includes(m.debit_day) ? 0 : m.debit_day % 10]} · up to ${R(m.max_amount)} · reference ${m.ref}</div></span>
        <span class="pill ${m.debicheck === 'approved' ? 'ok' : 'warn'}">${m.debicheck === 'approved' ? 'Active' : 'Approve in your banking app'}</span></div>
      ${m.debicheck === 'pending' ? `<p class="small muted">Your bank sends a DebiCheck request to your banking app. Approve it there and you never have to remember rent again.</p>${d.simulated ? '<button class="btn primary" id="apv">I\'ve approved it in my banking app (demo)</button>' : ''}` : ''}
      <button class="btn sm ghost" id="cx">Cancel debit order</button>` : `
      <p class="small muted">Rent is collected automatically on the ${d.due_day || 1}${d.due_day === 2 ? 'nd' : d.due_day === 3 ? 'rd' : d.due_day === 1 ? 'st' : 'th'} – no late fees, no reminders. Secured by DebiCheck: you approve it once in your banking app.</p>
      <form class="form" id="mf"><label class="field"><span>Account holder</span><input class="input" name="holder" value="${esc(state.user.name)}" required></label>
        <div class="cols"><label class="field"><span>Bank</span><select class="input" name="bank">${d.banks.map(b => `<option>${b}</option>`).join('')}</select></label>
        <label class="field"><span>Account type</span><select class="input" name="account_type"><option value="cheque">Cheque / current</option><option value="savings">Savings</option><option value="transmission">Transmission</option></select></label></div>
        <label class="field"><span>Account number</span><input class="input" name="account_no" inputmode="numeric" required></label>
        <label class="check small"><input type="checkbox" name="consent" required>I authorise AVA Rentals (via Netcash) to debit my account each month with the rent due, up to ${R((d.rent || 0) * 1.5)}.</label>
        <button class="btn primary">Set up debit order</button></form>`}</div>`;
  $('#mf', host)?.addEventListener('submit', async e => { e.preventDefault(); const o = Object.fromEntries(new FormData(e.target)); o.consent = 1; await act($('#mf button', host), () => api.post('/api/me/debit-order', o), 'Approve it in your banking app'); debitCard(host); });
  $('#apv', host)?.addEventListener('click', async () => { await act($('#apv', host), () => api.post('/api/me/debit-order/approve'), 'Debit order active'); debitCard(host); });
  $('#cx', host)?.addEventListener('click', async () => { if (!await confirmBox('Cancel debit order', 'You will need to pay rent yourself from next month.', 'Cancel it')) return; await api.del('/api/me/debit-order'); debitCard(host); });
}

// ------------------------------------------------------------------ owners and contractors: where we pay you
export async function bankCard(host) {
  const d = await api.get('/api/me/bank-account');
  const a = d.account;
  host.innerHTML = `<div class="card stack tight"><h3>${icon('money')} Where we pay you</h3>${a ? `<div class="row"><span class="grow"><b>${esc(a.bank)} ${a.account}</b><div class="small muted">${esc(a.holder)} · ${esc(a.account_type)} · branch ${esc(a.branch_code)}</div></span>${a.verified ? '<span class="pill ok">Verified</span>' : '<span class="pill warn">Being verified</span>'}</div><button class="btn sm" id="chg">Change</button>` : '<p class="small muted">Add your bank account so payouts can be released to you.</p><button class="btn primary sm" id="chg">Add bank account</button>'}</div>`;
  $('#chg', host).onclick = () => {
    const m = modal({ title: 'Bank account for payouts', body: `<form class="form" id="bf"><label class="field"><span>Account holder</span><input class="input" name="holder" value="${esc(a?.holder || state.user.company || state.user.name)}"></label>
      <div class="cols"><label class="field"><span>Bank</span><select class="input" name="bank">${d.banks.map(b => `<option ${a?.bank === b ? 'selected' : ''}>${b}</option>`).join('')}</select></label>
      <label class="field"><span>Type</span><select class="input" name="account_type"><option value="cheque">Cheque / current</option><option value="savings">Savings</option></select></label></div>
      <label class="field"><span>Account number</span><input class="input" name="account_no" inputmode="numeric" required></label><p class="tiny muted">Changes are verified with the bank before the next payout (account verification).</p></form>`, foot: '<button class="btn primary" id="ok">Save</button>' });
    $('#ok', m).onclick = async () => { await act($('#ok', m), () => api.post('/api/me/bank-account', Object.fromEntries(new FormData($('#bf', m)))), 'Saved'); m.close(); bankCard(host); };
  };
}
