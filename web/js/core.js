// AVA core: API client, state, router, UI helpers. Plain ES modules, no build step.
export const state = { user: null, unread: 0, features: { maintenance: false, fixit_url: '' } };
// optional modules (Admin → Settings & fees): maintenance runs in Fixit while it is switched off
export const feat = name => !!(state.features || {})[name];

// ------------------------------------------------------------------ api
async function call(method, url, data) {
  const opt = { method, credentials: 'same-origin', headers: {} };
  if (data instanceof FormData) opt.body = data;
  else if (data !== undefined) { opt.body = JSON.stringify(data); opt.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, opt);
  if (r.status === 401 && !url.includes('/auth/')) { state.user = null; go('#/login?next=' + encodeURIComponent(location.hash)); throw new Error('Please sign in'); }
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail ? (typeof body.detail === 'string' ? body.detail : body.detail.map(d => d.msg).join(', ')) : `Error ${r.status}`);
  return body;
}
export const api = { get: u => call('GET', u), post: (u, d) => call('POST', u, d ?? {}), put: (u, d) => call('PUT', u, d), del: u => call('DELETE', u) };

// ------------------------------------------------------------------ dom + format
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
// Money: whole rands, rounded off, thousands separated by a space (R 22 800). No cents anywhere in the app.
export const R = n => { if (n == null || n === '' || isNaN(n)) return '–'; const v = Math.round(Number(n)); return (v < 0 ? '-R ' : 'R ') + String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); };
export const R2 = R;   // kept for older call sites – also whole rands
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const fdate = s => { if (!s) return '–'; const d = new Date(s.length <= 10 ? s + 'T00:00' : s); return `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}`; };
export const fdt = s => { if (!s) return '–'; const d = new Date(s); return `${d.getDate()} ${MON[d.getMonth()]} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
export const fslot = s => { const d = new Date(s); return `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()]} ${d.getDate()} ${MON[d.getMonth()]} · ${s.slice(11, 16)}`; };
export const ago = s => { if (!s) return ''; const m = (Date.now() - new Date(s.replace(' ', 'T'))) / 60000; if (m < 1) return 'just now'; if (m < 60) return `${m | 0} min ago`; if (m < 1440) return `${(m / 60) | 0} h ago`; const d = (m / 1440) | 0; return d < 30 ? `${d} d ago` : fdate(s); };
export const period = p => { if (!p) return ''; const [y, m] = p.split('-'); return `${MON[+m - 1]} ${y}`; };
export const today = () => new Date().toISOString().slice(0, 10);
export const initials = n => (n || '?').split(' ').filter(Boolean).slice(0, 2).map(x => x[0]).join('').toUpperCase();
export const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

export function toast(msg, err) {
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  $('#toasts').append(t); setTimeout(() => t.remove(), err ? 5000 : 3000);
}
export async function act(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, true); throw e; }
  finally { if (btn) btn.disabled = false; }
}

// ------------------------------------------------------------------ icons (stroke, 24 grid)
const P = {
  home: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm9 16l-4.3-4.3',
  bed: 'M3 18V7m0 6h18v5M3 13V9h7a3 3 0 0 1 3 3v1m8 0v-1a3 3 0 0 0-3-3h-5', bath: 'M4 12h16v3a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4zm2 0V6a2 2 0 0 1 4 0M7 19l-1 2m11-2l1 2',
  car: 'M5 16h14v-4l-2-5H7l-2 5zm0 0v2m14-2v2M7 13h.01M17 13h.01', area: 'M4 4h16v16H4zM4 9h5V4', heart: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z',
  pano: 'M12 5c5 0 9 3.1 9 7s-4 7-9 7-9-3.1-9-7 4-7 9-7zm0 0v14M3.5 12h17', bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zm4 4h4',
  grid: 'M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z', building: 'M4 21V5l8-3v19m0 0h8V9l-8-3M8 8h.01M8 12h.01M8 16h.01M16 12h.01M16 16h.01',
  key: 'M15 7a4 4 0 1 1-3.9 4.9L4 19v2h3v-2h2v-2h2l1.1-1.1A4 4 0 0 1 15 7z', doc: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6m-6 4h6',
  money: 'M3 7h18v10H3zM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM6 10v4m12-4v4', tool: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z',
  clip: 'M9 4h6v3H9zM7 5H5v16h14V5h-2M8 12l2.5 2.5L16 9', camera: 'M4 7h3l2-3h6l2 3h3v12H4zM12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z',
  users: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-6 10v-1a6 6 0 0 1 12 0v1m2-10a3 3 0 0 0 0-6m4 16v-1a5 5 0 0 0-3-4.6', chat: 'M4 5h16v11H9l-5 4z',
  chart: 'M4 20V4m0 16h16M8 16v-5m4 5V8m4 8v-3', cog: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm8.5 3l2-1.6-2-3.4-2.4.8a7 7 0 0 0-1.7-1L16 3.5h-4l-.4 2.3a7 7 0 0 0-1.7 1l-2.4-.8-2 3.4L7.5 11a7 7 0 0 0 0 2l-2 1.6 2 3.4 2.4-.8c.5.4 1.1.8 1.7 1l.4 2.3h4l.4-2.3c.6-.2 1.2-.6 1.7-1l2.4.8 2-3.4-2-1.6a7 7 0 0 0 0-2z',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4m-4-4h11', back: 'M15 5l-7 7 7 7', plus: 'M12 5v14M5 12h14', x: 'M6 6l12 12M18 6L6 18', check: 'M5 12l5 5L20 7',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z', bolt: 'M13 2L4 14h7l-1 8 9-12h-7z',
  cal: 'M4 6h16v15H4zM4 10h16M8 3v5m8-5v5', pin: 'M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21zm0-14a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z',
  alert: 'M12 3L2 20h20zm0 6v5m0 3h.01', star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z', upload: 'M12 16V4m-5 5l5-5 5 5M4 16v4h16v-4',
  map: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zm0 0v14m6-12v14', phone: 'M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2z',
  video: 'M3 7h12v10H3zm12 3l6-3v10l-6-3', hard: 'M4 18h16M6 18v-4a6 6 0 0 1 12 0v4M12 8V5m-3 1l1 2m5-2l-1 2', list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  shield: 'M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6z', learn: 'M3 8l9-4 9 4-9 4zm4 2v5c3 2 7 2 10 0v-5', eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  print: 'M7 9V3h10v6M7 17H4v-7h16v7h-3M7 14h10v7H7z', excel: 'M4 4h16v16H4zM9 4v16M4 9h16M4 14h16', refresh: 'M20 11a8 8 0 0 0-14.9-3M4 4v4h4m-4 5a8 8 0 0 0 14.9 3M20 20v-4h-4',
};
export const icon = (n, cls = 'ico') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[n] || P.grid}"/></svg>`;
export const LOGO = `<img class="mark" src="img/mark.png" alt=""><span>AVA<small>Advanced Virtual Agent</small></span>`;

// ------------------------------------------------------------------ status words
export const ST = {
  new: ['New', 'info'], quoting: ['Getting quotes', 'jac'], awaiting_approval: ['Needs approval', 'warn'], approved: ['Approved', 'brand'],
  scheduled: ['Booked', 'brand'], in_progress: ['In progress', 'brand'], completed: ['Done – confirm', 'ok'], closed: ['Closed', ''], cancelled: ['Cancelled', ''],
  info_needed: ['Info needed', 'warn'], draft: ['Draft', ''], live: ['Live', 'ok'], let: ['Let', 'brand'], off: ['Off market', ''],
  active: ['Active', 'ok'], awaiting_signature: ['Awaiting signature', 'warn'], ended: ['Ended', ''], submitted: ['Submitted', 'info'], screening: ['Screening', 'jac'],
  shortlisted: ['Shortlisted', 'brand'], declined: ['Declined', 'bad'], withdrawn: ['Withdrawn', ''], requested: ['Requested', 'info'], confirmed: ['Confirmed', 'ok'],
  done: ['Done', ''], no_show: ['No-show', 'bad'], open: ['Open', 'warn'], ready: ['Ready to verify', 'jac'], rejected: ['Rejected', 'bad'], expired: ['Expired', ''],
  awaiting_signatures: ['Awaiting signatures', 'warn'], final: ['Signed off', 'ok'], paid: ['Paid', 'ok'], partial: ['Part paid', 'warn'], unpaid: ['Unpaid', 'bad'],
};
export const pill = (s, txt) => { const [w, c] = ST[s] || [s, '']; return `<span class="pill ${c}">${esc(txt || w)}</span>`; };
export const INSP = { ingoing: 'Ingoing', interim: 'Interim', outgoing: 'Outgoing', snag: 'Snag list', handover: 'Handover', reinspection: 'Re-inspection' };
export const cchip = c => `<span class="cchip c${c || 0}" title="${c ? 'Condition ' + c + ' – ' + CONDW[c] : 'Not rated'}">${c ? 'C' + c : '–'}</span>`;
export const CONDW = { 1: 'Excellent', 2: 'Good', 3: 'Fair', 4: 'Poor', 5: 'Very poor' };
export const stars = n => n ? `<span class="stars" title="${n}/5">${'★'.repeat(Math.round(n))}${'☆'.repeat(5 - Math.round(n))}</span> <span class="small muted">${n}</span>` : '<span class="small faint">No ratings</span>';

// ------------------------------------------------------------------ modal
export function modal({ title, body, foot = '', cls = '', onClose } = {}) {
  const ov = document.createElement('div'); ov.className = 'overlay';
  ov.innerHTML = `<div class="modal ${cls}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2><button class="iconbtn" data-x aria-label="Close">${icon('x')}</button></header>
    <div class="body">${body}</div>${foot ? `<footer>${foot}</footer>` : ''}</div>`;
  document.body.append(ov);
  const close = () => { ov.remove(); document.removeEventListener('keydown', key); onClose?.(); };
  const key = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', key);
  ov.addEventListener('mousedown', e => { if (e.target === ov) close(); });
  $('[data-x]', ov).onclick = close;
  const m = $('.modal', ov); m.close = close;
  setTimeout(() => $('input:not([type=hidden]),textarea,select', m)?.focus(), 30);
  return m;
}
export function confirmBox(title, text, okLabel = 'Confirm') {
  return new Promise(res => {
    const m = modal({ title, body: `<p>${text}</p>`, foot: `<button class="btn" data-n>Cancel</button><button class="btn primary" data-y>${esc(okLabel)}</button>`, onClose: () => res(false) });
    $('[data-n]', m).onclick = () => m.close(); $('[data-y]', m).onclick = () => { res(true); m.close(); };
  });
}
export function lightbox(url) { modal({ title: 'Photo', body: `<img src="${esc(url)}" alt="" style="width:100%;border-radius:8px">`, cls: 'wide' }); }
document.addEventListener('click', e => { const im = e.target.closest('[data-zoom]'); if (im) lightbox(im.dataset.zoom || im.src); });

// ------------------------------------------------------------------ forms
export function formData(form) {
  const fd = new FormData(form);
  $$('input[type=checkbox]', form).forEach(c => { if (c.name) fd.set(c.name, c.checked ? '1' : '0'); });
  return fd;
}
export function formObj(form) { const o = {}; formData(form).forEach((v, k) => { if (!(v instanceof File)) o[k] = v; }); return o; }
export function pickFiles({ accept = 'image/*', multiple = true, capture } = {}) {
  return new Promise(res => {
    const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.multiple = multiple; if (capture) i.capture = capture;
    i.onchange = () => res([...i.files]); i.click();
  });
}
export async function upload(url, files, field = 'files', extra = {}) {
  const fd = new FormData(); files.forEach(f => fd.append(field, f)); Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  return api.post(url, fd);
}

// signature pad
export function sigPad(canvas) {
  const ctx = canvas.getContext('2d'); let down = false, drawn = false;
  const fit = () => { const r = canvas.getBoundingClientRect(); canvas.width = r.width * 2; canvas.height = r.height * 2; ctx.scale(2, 2); ctx.lineWidth = 2.4; ctx.lineCap = 'round'; ctx.strokeStyle = '#14203c'; };
  fit();
  const pos = e => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  canvas.onpointerdown = e => { down = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); };
  canvas.onpointermove = e => { if (!down) return; ctx.lineTo(...pos(e)); ctx.stroke(); drawn = true; };
  canvas.onpointerup = () => down = false;
  return { clear: () => { ctx.clearRect(0, 0, canvas.width, canvas.height); drawn = false; }, data: () => drawn ? canvas.toDataURL('image/png') : null };
}
export function signModal(title, who) {
  return new Promise(res => {
    const m = modal({ title, body: `<p class="muted small">${esc(who)} – sign with your finger or mouse. Signing electronically is valid under the ECT Act 25 of 2002.</p><canvas class="sigpad"></canvas>`,
      foot: `<button class="btn ghost" data-c>Clear</button><span class="spacer"></span><button class="btn primary" data-s>Sign</button>`, onClose: () => res(null) });
    const pad = sigPad($('canvas', m));
    $('[data-c]', m).onclick = () => pad.clear();
    $('[data-s]', m).onclick = () => { const d = pad.data(); if (!d) return toast('Draw your signature first', true); res(d); m.close(); };
  });
}

// ------------------------------------------------------------------ router
const routes = [];
export function route(pattern, fn, opts = {}) { routes.push({ re: new RegExp('^' + pattern.replace(/:(\w+)/g, '(?<$1>[^/?]+)') + '(?:\\?(?<qs>.*))?$'), fn, ...opts }); }
export function go(h) { if (location.hash === h) render(); else location.hash = h; }
export const qs = () => Object.fromEntries(new URLSearchParams((location.hash.split('?')[1]) || ''));
let cleanup = [];
export const onLeave = fn => cleanup.push(fn);
export async function render() {
  cleanup.forEach(f => { try { f(); } catch (_) { } }); cleanup = [];
  const h = location.hash.slice(1) || '/';
  if (!feat('maintenance') && /^\/(app\/(maintenance|ticket|jobs)(\/|$|\?)|pros(\/|$|\?)|pro\/)/.test(h)) return go(state.user ? '#/app' : '#/');   // maintenance is in Fixit for now
  if (!feat('maintenance') && state.user?.role === 'contractor' && /^\/app(\/profile)?(\?|$)/.test(h)) return go('#/app/snags');
  for (const r of routes) {
    const m = h.match(r.re);
    if (!m) continue;
    if (r.auth && !state.user) return go('#/login?next=' + encodeURIComponent('#' + h));
    try { await r.fn({ ...m.groups }, qs()); }
    catch (e) { console.error(e); const el = $('#page') || $('#app'); if (el) el.innerHTML = `<div class="empty"><h3>Something went wrong</h3><p>${esc(e.message)}</p><a class="btn" href="#/app">Go home</a></div>`; }
    window.scrollTo(0, 0);
    return;
  }
  go('#/');
}
window.addEventListener('hashchange', render);

export async function refreshMe() {
  const r = await api.get('/api/me'); state.user = r.user; state.unread = r.unread || 0; if (r.features) state.features = r.features; return r.user;
}
