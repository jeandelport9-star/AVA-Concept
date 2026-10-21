// AVA Virtual Agent – one chat for visitors, renters, tenants, owners and contractors. It answers from live data and acts:
// books viewings, starts applications, logs repairs, opens the tour, hands over to the portfolio manager.
import { $, $$, api, esc, go, icon, state, toast, fslot } from './core.js';

const log = [];
let session = '';
try { session = sessionStorage.getItem('ava_s') || Math.random().toString(36).slice(2); sessionStorage.setItem('ava_s', session); } catch (_) { session = Math.random().toString(36).slice(2); }

const ctxProperty = () => { const m = location.hash.match(/^#\/p\/(\d+)/); return m ? +m[1] : null; };

function greeting() {
  const u = state.user, pid = ctxProperty();
  if (pid) return "Hi! I'm AVA's virtual agent for this home. Ask me anything – costs, pets, backup power, the area – or I can book you a viewing right now.";
  if (!u) return "Hi! I'm AVA's virtual agent. Tell me what you're looking for (e.g. “2 bed in Brooklyn under R12k with solar”) and I'll find it, book viewings and help you apply.";
  return {
    tenant: "Hi! I'm your AVA virtual agent. Ask about your balance, a repair, your lease, notice, the deposit or your rights – or just describe what's broken.",
    landlord: 'Hi! Ask me how your homes are doing, what you earned, or what is waiting for your approval.',
    contractor: 'Hi! Ask me about your quote requests, jobs and snags.',
  }[u.role] || "Hi! I'm the virtual agent. Paste any tenant question to see how I'd answer it, or ask about deposit rules, notice periods and evictions.";
}
function chips() {
  const u = state.user;
  if (ctxProperty()) return ['What does it cost to move in?', 'Are pets allowed?', 'Is there backup power?', 'Can I afford it on R45k?', 'When can I view it?', 'Speak to a person'];
  if (!u) return ['2 bed in Pretoria under R12k', 'Pet friendly house with a garden', 'Something with solar in Centurion'];
  return { tenant: ['What do I owe?', 'Status of my repair', 'When is my inspection?', 'I want to give notice', 'Will I get my deposit back?'],
    landlord: ['Anything to approve?', 'How much did I earn?', 'Are my tenants paying?'], contractor: ['What jobs do I have?'] }[u.role] || ['How does the deposit refund work?', 'Notice period for a fixed-term lease?', 'Can I evict for arrears?'];
}

export function toggleAgent() {
  if ($('#assist')) return $('#assist').remove();
  if (!log.length || log._ctx !== location.hash.split('?')[0]) { log.length = 0; log._ctx = location.hash.split('?')[0]; log.push({ bot: 1, text: greeting() }); }
  document.body.insertAdjacentHTML('beforeend', `<div class="assist" id="assist" role="dialog" aria-label="AVA virtual agent"><header>${icon('spark')}<b>AVA virtual agent</b><span class="small" style="opacity:.85">replies instantly · 24/7</span><button class="iconbtn" id="ax" style="color:#fff" aria-label="Close">${icon('x')}</button></header>
    <div class="chat"><div class="msgs" id="amsgs" aria-live="polite"></div><div class="row wrap" style="padding:8px 10px 0;gap:6px" id="achips"></div><form id="af"><input class="input" placeholder="Type your question…" id="ain" autocomplete="off" aria-label="Message"><button class="btn primary">Send</button></form></div></div>`);
  $('#ax').onclick = () => $('#assist').remove();
  $('#achips').innerHTML = chips().map(c => `<button class="btn sm" type="button">${esc(c)}</button>`).join('');
  $$('#achips button').forEach(b => b.onclick = () => send(b.textContent));
  $('#af').onsubmit = e => { e.preventDefault(); send($('#ain').value); };
  draw(); $('#ain').focus();
}

function draw() {
  const box = $('#amsgs'); if (!box) return;
  box.innerHTML = log.map((m, mi) => `<div class="msg ${m.bot ? 'bot' : 'mine'}">${esc(m.text)}${m.form ? m.form : ''}${(m.actions || []).length ? `<div class="row wrap" style="gap:6px;margin-top:8px">${m.actions.map((a, ai) => `<button class="btn sm" data-a="${mi}:${ai}">${esc(a.action === 'book' ? fslot(a.slot) : a.label)}</button>`).join('')}</div>` : ''}</div>`).join('');
  box.scrollTop = 1e6;
  $$('[data-a]', box).forEach(b => b.onclick = () => { const [mi, ai] = b.dataset.a.split(':').map(Number); doAction(log[mi].actions[ai]); });
  $$('form[data-lead]', box).forEach(f => f.onsubmit = e => { e.preventDefault(); lead(f); });
}

async function send(text) {
  text = (text || '').trim(); if (!text) return;
  log.push({ text }); draw(); if ($('#ain')) $('#ain').value = '';
  log.push({ bot: 1, text: '…' }); draw();
  try {
    const r = await api.post('/api/agent', { text, property_id: ctxProperty(), session });
    log.pop(); log.push({ bot: 1, text: r.reply, actions: r.actions });
  } catch (e) { log.pop(); log.push({ bot: 1, text: e.message }); }
  draw();
}

async function doAction(a) {
  const pid = ctxProperty();
  if (a.href) { go(a.href); return; }
  if (a.action === 'ask') return send(a.text);
  if (a.action === 'similar') return send('Show me similar homes');
  if (a.action === 'tour') { go(`#/p/${pid}?tour=1`); $('#assist')?.remove(); return; }
  if (a.action === 'apply') { if (!state.user) { go('#/login?next=' + encodeURIComponent(`#/p/${pid}?apply=1`)); $('#assist')?.remove(); return; } go(`#/p/${pid}?apply=1`); $('#assist')?.remove(); return; }
  if (a.action === 'book') {
    if (state.user) {
      try { await api.post('/api/viewings', { property_id: pid, slot: a.slot, via_agent: 1, session, phone: state.user.phone || '' }); log.push({ bot: 1, text: `Done – your viewing is confirmed for ${fslot(a.slot)}. I'll remind you the day before with the address.` }); }
      catch (e) { log.push({ bot: 1, text: e.message }); }
      return draw();
    }
    log.push({ bot: 1, text: `Lovely – ${fslot(a.slot)}. Who should I book it for?`, form: leadForm('book', a.slot) }); return draw();
  }
  if (a.action === 'handoff') { log.push({ bot: 1, text: 'What number should they call?', form: leadForm('handoff') }); return draw(); }
  if (a.action === 'ticket') {
    const fd = new FormData(); fd.set('title', a.title);
    try { const t = await api.post('/api/tickets', fd); log.push({ bot: 1, text: `Logged as ${t.ref} (${t.category}, ${t.priority}). ${t.status === 'approved' ? 'A contractor has been dispatched.' : 'Quotes have been requested – follow it under Repairs.'}`, actions: [{ label: 'Open ' + t.ref, href: '#/app/ticket/' + t.id }] }); }
    catch (e) { log.push({ bot: 1, text: e.message }); }
    draw();
  }
}
const leadForm = (kind, slot = '') => `<form data-lead="${kind}" data-slot="${slot}" class="stack tight" style="margin-top:8px"><input class="input" name="name" placeholder="Name" required><input class="input" name="phone" placeholder="Mobile" required>${kind === 'book' ? '<input class="input" name="email" type="email" placeholder="Email" required>' : ''}<button class="btn primary sm">${kind === 'book' ? 'Confirm viewing' : 'Call me back'}</button></form>`;
async function lead(f) {
  const d = Object.fromEntries(new FormData(f)); const pid = ctxProperty();
  try {
    if (f.dataset.lead === 'book') { await api.post('/api/viewings', { ...d, property_id: pid, slot: f.dataset.slot, via_agent: 1, session }); log.push({ bot: 1, text: `Booked, ${d.name.split(' ')[0]}! See you on ${fslot(f.dataset.slot)}. Directions and a reminder are on their way.` }); }
    else { await api.post('/api/agent/handoff', { ...d, property_id: pid, session }); log.push({ bot: 1, text: `Thanks ${d.name.split(' ')[0]} – the portfolio manager will call you on ${d.phone} shortly.` }); }
    log.forEach(m => delete m.form);
  } catch (e) { toast(e.message, true); return; }
  draw();
}
