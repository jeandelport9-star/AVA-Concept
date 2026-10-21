// Inspections & snag lists, built on Site Inspect's 360 viewer.
// Rental: ingoing / interim / outgoing, room by room, C1–C5, photos, 360 per room, pins, compare, deposit reconciliation, e-signatures.
// Construction: snag list → contractor fixes with 'after' photo → re-inspection closes or rejects (rework) → metrics.
import { $, $$, act, ago, api, cchip, CONDW, confirmBox, esc, fdate, fdt, go, icon, INSP, modal, pickFiles, pill, plural, R, R2, route, signModal, state, toast, today, upload } from './core.js';
import { page } from './shell.js';
import { PanoViewer } from './pano.js';

const A = { auth: true };
const RENTAL = ['ingoing', 'interim', 'outgoing'];
const TRADES = ['Painter / builder', 'Carpentry', 'Tiler', 'Plumber', 'Electrician', 'Roofer / waterproofer', 'Handyman', 'Glazier', 'Landscaper', 'Locksmith / security'];
const UNITS = ['no.', 'm', 'm²', 'm³', 'item', 'lot'];
const CATS = ['Workmanship', 'Non-conformance', 'Health & safety', 'Incomplete work', 'Damage', 'Cleaning'];
const PRI = ['Urgent', 'High', 'Medium', 'Low'];
const PCOL = { Urgent: '#c03b28', High: '#e0702a', Medium: '#d5a20d', Low: '#6a736f' };

// ------------------------------------------------------------------ list
route('/app/inspections', async (_, q) => {
  const u = state.user;
  const pg = page('Inspections', { actions: ['pm', 'admin', 'landlord'].includes(u.role) ? `<button class="btn primary sm" id="ni">${icon('plus')}New inspection</button>` : '' });
  const rows = await api.get('/api/inspections');
  let tab = q.tab || 'open';
  pg.innerHTML = `<div class="ai-note">${icon('pano')}<span>Capture each room with a <b>360° camera</b> (Insta360, Ricoh Theta – photo or video) or just your <b>phone camera</b>. Outgoing inspections open next to the ingoing one so damage vs fair wear and tear is obvious, and deposit deductions are calculated for you.</span></div>
    <div class="tabs">${[['open', 'To do'], ['rental', 'Rental'], ['construction', 'Snag lists'], ['final', 'Signed off']].map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="il"></div>`;
  const draw = () => {
    const list = rows.filter(i => tab === 'open' ? i.status !== 'final' : tab === 'final' ? i.status === 'final' : tab === 'rental' ? RENTAL.includes(i.type) : !RENTAL.includes(i.type));
    $('#il').innerHTML = `<div class="card flush list">${list.map(i => `<a class="li" href="#/app/inspection/${i.id}"><span class="pill ${RENTAL.includes(i.type) ? 'brand' : 'jac'}">${INSP[i.type]}${i.round > 1 ? ' ' + i.round : ''}</span>
      <span class="grow"><span class="title">${esc(i.title)}</span><span class="small muted">${fdate(i.date)} · ${esc(i.inspector || '')} · ${RENTAL.includes(i.type) ? `${i.rated}/${i.items} items` : plural(i.snags, 'snag')} · ${i.panos} × 360°</span></span>${pill(i.status)}</a>`).join('') || '<div class="empty">Nothing here.</div>'}</div>`;
  };
  $$('.tabs [data-t]').forEach(b => b.onclick = () => { tab = b.dataset.t; $$('.tabs [data-t]').forEach(x => x.setAttribute('aria-selected', x === b)); draw(); });
  draw();
  $('#ni')?.addEventListener('click', async () => {
    const props = await api.get('/api/properties');
    const m = modal({ title: 'New inspection', body: `<form class="form" id="nf"><label class="field"><span>Property</span><select class="input" name="property_id">${props.map(p => `<option value="${p.id}" data-k="${p.kind}">${esc(p.title)}</option>`).join('')}</select></label>
      <label class="field"><span>Type</span><select class="input" name="type">${Object.entries(INSP).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label><label class="field"><span>Date</span><input class="input" type="date" name="date" value="${today()}"></label></form>`, foot: '<button class="btn primary" id="go">Start</button>' });
    $('#go', m).onclick = async () => { const d = Object.fromEntries(new FormData($('#nf', m))); const r = await act($('#go', m), () => api.post('/api/inspections', d)); m.close(); go('#/app/inspection/' + r.id); };
  });
}, A);

// ------------------------------------------------------------------ inspection
route('/app/inspection/:id', async ({ id }, q) => {
  let I = await api.get('/api/inspections/' + id);
  const u = state.user;
  const rental = RENTAL.includes(I.type), snagMode = !rental;
  const edit = I.can_edit;
  const pg = page(`${INSP[I.type]}${I.round > 1 ? ' · round ' + I.round : ''} · ${I.property.title}`, { back: I.property ? `#/app/property/${I.property_id}?tab=inspections` : '#/app/inspections',
    actions: `<button class="btn sm" id="rep">${icon('print')}<span class="hide-sm">Report</span></button>` });
  let tab = q.tab || (I.status === 'final' || !edit ? 'report' : 'capture');
  let roomId = +q.room || I.rooms[0]?.id;
  const viewers = [];
  const kill = () => { while (viewers.length) viewers.pop().destroy(); };
  const tabs = [['capture', rental ? 'Rooms' : 'Snags by room'], ...(I.compare_to_id ? [['compare', rental ? 'Compare & charges' : 'Previous round']] : []), ['sign', 'Sign-off'], ['report', 'Report']];
  pg.innerHTML = `<div class="card row wrap" style="padding:12px 16px">${pill(I.status)}<span class="small">${fdate(I.date)}</span>${I.lease ? `<span class="small muted">Tenant: <b>${esc(I.lease.tenant_name)}</b></span>` : ''}
      ${I.compare_to ? `<span class="small muted">Compared with ${INSP[I.compare_to.type]} of ${fdate(I.compare_to.date)}</span>` : ''}<span class="spacer"></span>
      ${rental ? `<span class="small muted" id="progress"></span>` : `<span class="small muted" id="snagcount">${plural(I.snags.length, 'snag')}</span>`}</div>
    <div class="tabs">${tabs.map(([k, l]) => `<button data-t="${k}" aria-selected="${tab === k}">${l}</button>`).join('')}</div><div id="ib"></div>`;
  $('#rep').onclick = () => show('report');
  const refresh = async () => { I = await api.get('/api/inspections/' + id); };
  const prog = () => { if (!rental) { $('#snagcount') && ($('#snagcount').textContent = plural(I.snags.length, 'snag')); return; } const all = I.rooms.flatMap(r => r.items), done = all.filter(i => i.condition).length; $('#progress').textContent = `${done}/${all.length} items rated · ${I.rooms.filter(r => r.pano_url).length}/${I.rooms.length} rooms in 360°`; };

  function show(k) {
    tab = k; kill(); $$('.tabs [data-t]').forEach(b => b.setAttribute('aria-selected', b.dataset.t === k));
    ({ capture, compare, sign, report })[k]();
    prog();
  }
  $$('.tabs [data-t]').forEach(b => b.onclick = () => show(b.dataset.t));

  // ---------------- capture
  function capture() {
    $('#ib').innerHTML = `<div class="insp"><nav class="roomnav" id="rn"></nav><div class="stack" id="room"></div></div>`;
    drawNav(); drawRoom();
  }
  function drawNav() {
    $('#rn').innerHTML = I.rooms.map(r => {
      const p = rental ? `${r.items.filter(i => i.condition).length}/${r.items.length}` : `${I.snags.filter(s => s.room_id === r.id || s.room === r.name).length}`;
      return `<button data-r="${r.id}" aria-current="${r.id === roomId}">${r.pano_url ? icon('pano') : `<span style="width:18px"></span>`}<span>${esc(r.name)}</span><span class="prog">${p}</span></button>`;
    }).join('') + (edit ? `<button id="addroom" style="color:var(--brand)">${icon('plus')}Add room</button>` : '');
    $$('#rn [data-r]').forEach(b => b.onclick = () => { roomId = +b.dataset.r; kill(); drawNav(); drawRoom(); history.replaceState(null, '', `#/app/inspection/${id}?tab=capture&room=${roomId}`); });
    $('#addroom')?.addEventListener('click', async () => { const n = prompt('Room name', 'Study'); if (!n) return; const r = await api.post(`/api/inspections/${id}/rooms`, { name: n }); await refresh(); roomId = r.id; capture(); });
  }
  function roomSnags(r) { return I.snags.filter(s => s.room_id === r.id || (!s.room_id && s.room === r.name) || (I.type === 'reinspection' && s.room === r.name)); }

  function drawRoom() {
    const r = I.rooms.find(x => x.id === roomId); if (!r) return;
    const prevRoom = I.prev_rooms?.[r.name];
    const idx = I.rooms.indexOf(r);
    $('#room').innerHTML = `<div class="card stack"><div class="row wrap"><h2 class="grow">${esc(r.name)}</h2>
        ${edit ? `<button class="btn sm" id="p360">${icon('pano')}360° photo</button><button class="btn sm" id="pvid">${icon('video')}From 360° video</button><button class="btn sm" id="pcam">${icon('camera')}Phone photos</button>` : ''}</div>
      ${r.pano_url ? `<div class="${prevRoom?.pano_url ? 'split' : ''}">${prevRoom?.pano_url ? `<div class="pano" id="pv0" style="height:360px"></div>` : ''}<div class="pano" id="pv1" style="height:360px"></div></div>
        <p class="tiny muted">Drag to look around, scroll or pinch to zoom.${edit ? (snagMode ? ' Tap “Add snag here”, then tap the defect.' : ' Use 📍 on an item, then tap the spot in the 360 to pin it.') : ''}</p>`
      : `<div class="dropzone" id="dz">${icon('pano')}<b>Add a 360° view of the ${esc(r.name.toLowerCase())}</b><span class="small">Upload a 360° photo (equirectangular JPG) or pick a frame from a 360° video. Stand in the middle of the room, camera at about 1.5 m.</span>${prevRoom?.pano_url ? '<span class="small">The previous inspection has a 360° here – capture the same spot for a fair comparison.</span>' : ''}</div>`}
      ${(r.photos || []).length ? `<div class="thumbs">${r.photos.map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}">`).join('')}</div>` : ''}</div>
      <div class="stack tight" id="items"></div>
      <div class="row">${idx > 0 ? `<button class="btn" data-go="${I.rooms[idx - 1].id}">‹ ${esc(I.rooms[idx - 1].name)}</button>` : ''}<span class="spacer"></span>${idx < I.rooms.length - 1 ? `<button class="btn primary" data-go="${I.rooms[idx + 1].id}">${esc(I.rooms[idx + 1].name)} ›</button>` : `<button class="btn primary" id="tosign">Go to sign-off ›</button>`}</div>`;
    $$('[data-go]').forEach(b => b.onclick = () => { roomId = +b.dataset.go; kill(); drawNav(); drawRoom(); scrollTo(0, 0); });
    $('#tosign')?.addEventListener('click', () => show('sign'));
    $('#dz')?.addEventListener('click', () => edit && pickPano(r));
    $('#p360')?.addEventListener('click', () => pickPano(r));
    $('#pvid')?.addEventListener('click', () => videoFrame(r));
    $('#pcam')?.addEventListener('click', async () => { const f = await pickFiles({ capture: 'environment' }); if (!f.length) return; await act($('#pcam'), () => upload(`/api/rooms/${r.id}/photos`, f), 'Photos added'); await refresh(); drawRoom(); });
    let main = null, prev = null;
    if (r.pano_url) {
      let tagging = null;
      main = new PanoViewer($('#pv1'), {
        onTag: async ({ yaw, pitch }) => {
          main.setTagMode(false);
          if (tagging === 'snag') return snagForm(r, { yaw: +yaw.toFixed(1), pitch: +pitch.toFixed(1) }, main);
          if (tagging) { await api.put('/api/items/' + tagging, { pin: { yaw: +yaw.toFixed(1), pitch: +pitch.toFixed(1) } }); const it = r.items.find(i => i.id === tagging); it.pin = { yaw, pitch }; setPins(); toast('Pinned'); }
          tagging = null;
        },
        onPin: pid => { const el = $(`[data-item="${pid}"]`) || $(`[data-snag="${pid}"]`); el?.scrollIntoView({ behavior: 'smooth', block: 'center' }); el?.animate([{ background: 'var(--cta-tint)' }, { background: 'transparent' }], 1600); },
        onView: cam => { if (prev && $('#sync')?.checked && !prev._syncing) { prev.cam.yaw = cam.yaw; prev.cam.pitch = cam.pitch; prev.cam.fov = cam.fov; prev.dirty = true; } },
      });
      viewers.push(main); main.load(r.pano_url);
      $('#pv1').insertAdjacentHTML('beforeend', `<span class="label">${prevRoom?.pano_url ? 'Now' : esc(r.name)}</span><div class="hud">${edit && snagMode ? `<button class="btn sm" id="snaghere">${icon('pin')}Add snag here</button>` : ''}${prevRoom?.pano_url ? `<label class="btn sm"><input type="checkbox" id="sync" checked style="margin:0">Sync views</label>` : ''}</div>`);
      if (r.pano_yaw) main.lookAt({ yaw: r.pano_yaw, pitch: 0 }, true);
      if (prevRoom?.pano_url) { prev = new PanoViewer($('#pv0')); viewers.push(prev); prev.load(prevRoom.pano_url); $('#pv0').insertAdjacentHTML('beforeend', `<span class="label">${INSP[I.compare_to.type]} · ${fdate(I.compare_to.date)}</span>`); }
      $('#snaghere')?.addEventListener('click', () => { tagging = 'snag'; main.setTagMode(true); toast('Tap the defect in the 360° view'); });
      r._tag = itemId => { tagging = itemId; main.setTagMode(true); main.el.scrollIntoView({ behavior: 'smooth', block: 'center' }); toast('Tap the spot in the 360° view'); };
    }
    const setPins = () => {
      if (!main) return;
      const pins = rental ? r.items.filter(i => i.pin).map(i => ({ id: i.id, yaw: i.pin.yaw, pitch: i.pin.pitch, label: i.name, color: i.charge_to === 'tenant' ? '#c03b28' : i.worse ? '#e0702a' : '#0e5e52' }))
        : roomSnags(r).filter(s => s.pin).map(s => ({ id: s.id, yaw: s.pin.yaw, pitch: s.pin.pitch, label: s.ref.split('-').pop() + ' ' + s.title.slice(0, 22), color: s.status === 'closed' ? '#1d8a57' : s.status === 'ready' ? '#1ba3a0' : PCOL[s.priority] }));
      main.setPins(pins);
    };
    r._setPins = setPins;
    setPins();
    rental ? drawItems(r) : drawSnags(r, main);
  }

  function drawItems(r) {
    const charges = I.type !== 'ingoing';
    $('#items').innerHTML = `${edit ? `<div class="row wrap"><button class="btn sm" id="allgood">${icon('check')}${I.compare_to ? 'Rest same as before' : 'Rest in good condition'}</button><button class="btn sm ghost" id="additem">${icon('plus')}Item</button><span class="spacer"></span><span class="tiny muted">C1 excellent · C2 good · C3 fair · C4 poor · C5 very poor</span></div>` : ''}
      ${r.items.map(it => `<div class="item ${it.worse ? 'worse' : ''}" data-item="${it.id}"><div class="head"><b>${esc(it.name)}</b>
        ${edit ? `<div class="cond" role="group" aria-label="Condition">${[1, 2, 3, 4, 5].map(c => `<button class="c${c}" data-c="${c}" aria-pressed="${it.condition === c}" title="${CONDW[c]}">C${c}</button>`).join('')}</div>` : cchip(it.condition)}
        ${edit ? `<button class="iconbtn" data-cam title="Photo">${icon('camera')}</button>${r.pano_url ? `<button class="iconbtn" data-pin title="Pin on 360" style="${it.pin ? 'color:var(--brand)' : ''}">${icon('pin')}</button>` : ''}` : ''}</div>
        ${it.prev ? `<div class="prev">Before: ${cchip(it.prev.condition)} ${esc(it.prev.notes || '')} ${(it.prev.photos || []).map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" style="width:34px;height:34px;object-fit:cover;border-radius:5px">`).join('')}${it.worse ? `<span class="pill bad">Worse by ${it.worse}</span>` : ''}</div>` : ''}
        ${edit ? `<div class="row wrap"><label class="check small"><input type="checkbox" data-f="clean" ${it.clean !== 0 ? 'checked' : ''}>Clean</label><label class="check small"><input type="checkbox" data-f="working" ${it.working !== 0 ? 'checked' : ''}>Working</label>
            <input class="input" data-f="notes" value="${esc(it.notes || '')}" placeholder="Notes – e.g. scuff left of door, 2 nail holes" style="flex:1;min-width:200px"></div>
          ${charges ? `<div class="row wrap small"><span class="muted">Repair cost</span><input class="input" type="number" data-f="charge" value="${it.charge || ''}" placeholder="R" style="width:110px"><select class="input" data-f="charge_to" style="width:auto"><option value="">No charge</option><option value="tenant" ${it.charge_to === 'tenant' ? 'selected' : ''}>Tenant (damage)</option><option value="landlord" ${it.charge_to === 'landlord' ? 'selected' : ''}>Landlord (wear & tear / defect)</option></select></div>` : ''}`
          : `${it.notes ? `<span class="small">${esc(it.notes)}</span>` : ''}${it.charge ? `<span class="small"><b>${R(it.charge)}</b> → ${esc(it.charge_to)}</span>` : ''}`}
        ${(it.photos || []).length ? `<div class="thumbs">${it.photos.map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}">`).join('')}</div>` : ''}</div>`).join('')}`;
    const save = async (it, patch) => { Object.assign(it, patch); await api.put('/api/items/' + it.id, patch); drawNav(); prog(); };
    $$('[data-item]').forEach(el => {
      const it = r.items.find(i => i.id == el.dataset.item);
      $$('[data-c]', el).forEach(b => b.onclick = () => { const c = +b.dataset.c; $$('[data-c]', el).forEach(x => x.setAttribute('aria-pressed', x === b)); it.worse = it.prev?.condition && c > it.prev.condition ? c - it.prev.condition : 0; el.classList.toggle('worse', !!it.worse); save(it, { condition: c }); });
      $$('[data-f]', el).forEach(i => i.onchange = () => save(it, { [i.dataset.f]: i.type === 'checkbox' ? (i.checked ? 1 : 0) : i.type === 'number' ? +i.value || null : i.value }));
      $('[data-cam]', el)?.addEventListener('click', async () => { const f = await pickFiles({ capture: 'environment' }); if (!f.length) return; const res = await upload(`/api/items/${it.id}/photos`, f); it.photos = res.photos; drawItems(r); });
      $('[data-pin]', el)?.addEventListener('click', () => r._tag?.(it.id));
    });
    $('#allgood')?.addEventListener('click', async () => {
      const todo = r.items.filter(i => !i.condition);
      for (const it of todo) await save(it, { condition: it.prev?.condition || 2, clean: 1, working: 1 });
      drawItems(r); toast(`${todo.length} item(s) rated`);
    });
    $('#additem')?.addEventListener('click', async () => { const n = prompt('Item name', 'Built-in braai'); if (!n) return; await api.post(`/api/rooms/${r.id}/items`, { name: n }); await refresh(); drawRoom(); });
  }

  function drawSnags(r, viewer) {
    const list = roomSnags(r);
    const reinsp = I.type === 'reinspection';
    $('#items').innerHTML = `${edit && !reinsp ? `<div class="row"><button class="btn primary sm" id="addsnag">${icon('plus')}Add snag</button><span class="spacer"></span><span class="tiny muted">Each snag gets a reference, trade, contractor, measured quantity and due date.</span></div>` : ''}
      <div class="card flush">${list.map(s => snagRow(s, { verify: reinsp && edit && s.status !== 'closed' })).join('') || '<div class="empty">No snags in this room.</div>'}</div>`;
    $('#addsnag')?.addEventListener('click', () => snagForm(r, null, viewer));
    bindSnagRows($('#items'), list, async () => { await refresh(); drawNav(); drawRoom(); }, I.id);
  }

  function snagForm(r, pin, viewer) {
    const files = [];
    const m = modal({ title: 'New snag – ' + r.name, body: `<form class="form" id="sf"><label class="field"><span>Defect</span><input class="input" name="title" required placeholder="e.g. Paint drips on east wall"></label>
      <div class="cols"><label class="field"><span>Category</span><select class="input" name="category">${CATS.map(c => `<option>${c}</option>`).join('')}</select></label><label class="field"><span>Priority</span><select class="input" name="priority">${PRI.map(p => `<option ${p === 'Medium' ? 'selected' : ''}>${p}</option>`).join('')}</select></label></div>
      <div class="cols"><label class="field"><span>Trade</span><select class="input" name="trade" id="trade">${TRADES.map(t => `<option>${t}</option>`).join('')}</select></label><label class="field"><span>Responsible contractor</span><select class="input" name="contractor_id" id="con"><option value="">–</option>${I.contractors.map(c => `<option value="${c.id}" data-t="${esc((c.trades || []).join('|'))}">${esc(c.company || c.name)}</option>`).join('')}</select></label></div>
      <div class="cols"><label class="field"><span>Quantity</span><input class="input" name="qty" type="number" step="1" value="1"></label><label class="field"><span>Unit</span><select class="input" name="unit">${UNITS.map(x => `<option>${x}</option>`).join('')}</select></label><label class="field"><span>Rate (R/unit)</span><input class="input" name="rate" type="number" step="1"></label><label class="field"><span>Due</span><input class="input" name="due_date" type="date"></label></div>
      <label class="field"><span>Description / location</span><textarea class="input" name="description" rows="2" placeholder="Exact location, standard breached (e.g. SANS 10400-XA), fix required"></textarea></label>
      <div class="field"><span>Photos ${pin ? '· pinned on 360 ✓' : ''}</span><div class="thumbs" id="sp"><button class="add" type="button" id="sa">${icon('camera')}</button></div></div></form>
      <p class="tiny muted">Leave the due date blank to use the priority default (Urgent 2 days · High 7 · Medium 14 · Low 21).</p>`, foot: '<button class="btn primary" id="ok">Add snag</button>' });
    const drawp = () => { $('#sp', m).innerHTML = files.map(f => `<img src="${URL.createObjectURL(f)}">`).join('') + `<button class="add" type="button" id="sa">${icon('camera')}</button>`; $('#sa', m).onclick = addp; };
    const addp = async () => { files.push(...await pickFiles({ capture: 'environment' })); drawp(); };
    $('#sa', m).onclick = addp;
    $('#trade', m).onchange = e => { const o = [...$('#con', m).options].find(o => (o.dataset.t || '').toLowerCase().includes(e.target.value.split(' ')[0].toLowerCase())); if (o) $('#con', m).value = o.value; };
    $('#trade', m).onchange({ target: $('#trade', m) });
    $('#ok', m).onclick = async () => {
      const f = $('#sf', m); if (!f.reportValidity()) return;
      const fd = new FormData(f); fd.set('property_id', I.property_id); fd.set('inspection_id', I.id); fd.set('room', r.name); fd.set('room_id', r.id);
      if (pin) fd.set('pin', JSON.stringify(pin));
      if (!files.length && pin && viewer) { const shot = await viewShot(viewer, pin); if (shot) files.push(shot); }
      files.forEach(x => fd.append('photos', x));
      await act($('#ok', m), () => api.post('/api/snags', fd), 'Snag added'); m.close(); await refresh(); drawNav(); drawRoom();
    };
  }

  async function pickPano(r) {
    const f = await pickFiles({ multiple: false });
    if (!f.length) return;
    const img = await new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = URL.createObjectURL(f[0]); });
    if (img && Math.abs(img.width / img.height - 2) > 0.15 && !await confirmBox('Not a 360° photo?', `This image is ${img.width}×${img.height}. 360° photos are twice as wide as they are high (equirectangular). Use it anyway?`, 'Use it')) return;
    await act(null, () => upload(`/api/rooms/${r.id}/pano`, f, 'file'), '360° view added');
    await refresh(); kill(); drawNav(); drawRoom();
  }

  function videoFrame(r) {
    pickFiles({ accept: 'video/*', multiple: false }).then(f => {
      if (!f.length) return;
      const url = URL.createObjectURL(f[0]);
      const m = modal({ title: 'Pick a frame from the 360° video', cls: 'wide', body: `<video id="vv" src="${url}" muted playsinline style="width:100%;border-radius:8px;background:#000;max-height:50vh"></video>
        <input type="range" id="vs" min="0" max="1000" value="0" style="width:100%"><div class="row small muted"><span id="vt">0:00</span><span class="spacer"></span><span>Export from the camera app as an equirectangular MP4 (Insta360 Studio: “360° video”, FlowState on). Pick a moment where you stand still in the middle of the room.</span></div>`,
        foot: '<button class="btn primary" id="use">Use this frame</button>', onClose: () => URL.revokeObjectURL(url) });
      const v = $('#vv', m);
      v.onloadedmetadata = () => { $('#vs', m).oninput = e => { v.currentTime = v.duration * e.target.value / 1000; $('#vt', m).textContent = `${Math.floor(v.currentTime / 60)}:${String(Math.floor(v.currentTime % 60)).padStart(2, '0')}`; }; };
      v.onerror = () => toast('This browser can\'t decode that video (H.265 / 5.7K is often the problem). Export as H.264 or upload a 360° photo instead.', true);
      $('#use', m).onclick = async () => {
        if (!v.videoWidth) return toast('Video not loaded', true);
        const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext('2d').drawImage(v, 0, 0);
        const blob = await new Promise(res => c.toBlob(res, 'image/jpeg', .9));
        await act($('#use', m), () => upload(`/api/rooms/${r.id}/pano`, [new File([blob], 'frame.jpg', { type: 'image/jpeg' })], 'file'), '360° frame added');
        m.close(); await refresh(); kill(); drawNav(); drawRoom();
      };
    });
  }

  // ---------------- compare
  function compare() {
    if (!rental) {
      $('#ib').innerHTML = `<div class="ai-note">${icon('clip')}<span>Re-inspection round ${I.round}: verify each snag the contractor marked as ready, close it with an 'after' photo, or reject it for rework (counts against first-time-right).</span></div><div class="card flush">${I.snags.map(s => snagRow(s, { verify: I.can_edit && s.status !== 'closed' })).join('')}</div>`;
      bindSnagRows($('#ib'), I.snags, async () => { await refresh(); compare(); }, I.id);
      return;
    }
    const rows = I.rooms.flatMap(r => r.items.filter(i => i.prev && (i.worse || i.charge || (i.notes && i.notes !== i.prev.notes))).map(i => ({ ...i, room: r.name })));
    const dep = I.deposit;
    $('#ib').innerHTML = `<div class="grid2" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);align-items:start"><div class="card flush"><div class="card-head"><h3>Changes since ${INSP[I.compare_to.type].toLowerCase()}</h3><span class="pill ${rows.length ? 'warn' : 'ok'}">${rows.length}</span></div>
        <div class="tablewrap"><table class="t"><tr><th>Room / item</th><th>Before</th><th>Now</th><th>Notes</th><th class="num">Cost</th><th>Charged to</th></tr>
        ${rows.map(i => `<tr><td><b>${esc(i.room)}</b><div class="small">${esc(i.name)}</div></td><td>${cchip(i.prev.condition)}${(i.prev.photos || []).slice(0, 1).map(p => ` <img src="${esc(p)}" data-zoom="${esc(p)}" style="width:44px;height:44px;object-fit:cover;border-radius:6px;display:inline-block;vertical-align:middle">`).join('')}</td>
          <td>${cchip(i.condition)}${(i.photos || []).slice(0, 1).map(p => ` <img src="${esc(p)}" data-zoom="${esc(p)}" style="width:44px;height:44px;object-fit:cover;border-radius:6px;display:inline-block;vertical-align:middle">`).join('')}</td><td class="small">${esc(i.notes || '')}</td><td class="num">${i.charge ? R(i.charge) : ''}</td><td>${i.charge_to ? `<span class="pill ${i.charge_to === 'tenant' ? 'bad' : 'info'}">${i.charge_to}</span>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">No changes recorded yet. Rate the rooms first.</td></tr>'}</table></div></div>
      ${dep ? `<div class="card stack"><h3>${icon('shield')} Deposit reconciliation</h3><div class="costs"><div><span>Deposit + interest held</span><span class="num">${R2(dep.held)}</span></div>
          ${dep.charges.map(c => `<div><span class="small">${esc(c.room)}: ${esc(c.name)}</span><span class="num">−${R2(c.charge)}</span></div>`).join('')}${dep.arrears ? `<div><span>Arrears</span><span class="num">−${R2(dep.arrears)}</span></div>` : ''}
          <div class="tot"><span>Refund to tenant</span><span class="num">${R2(dep.refund)}</span></div></div>
        <p class="small muted">Refund due by <b>${fdate(dep.refund_by)}</b> – ${esc(dep.rule)}. Only damage beyond fair wear and tear may be deducted; landlord items become repair requests on sign-off.</p>
        ${dep.refunded ? '<span class="pill ok">Refunded</span>' : I.status === 'final' && ['pm', 'admin'].includes(u.role) ? `<button class="btn primary" id="refund">${icon('money')}Refund ${R2(dep.refund)} now</button>` : ''}</div>` : ''}</div>`;
    $('#refund')?.addEventListener('click', async () => { if (!await confirmBox('Refund deposit', `Pay ${R2(dep.refund)} to the tenant, ${R2(dep.deductions)} to the owner for damage, and end the lease?`, 'Refund')) return; await act($('#refund'), () => api.post(`/api/inspections/${id}/refund-deposit`), 'Deposit refunded'); await refresh(); compare(); });
  }

  // ---------------- sign-off
  function sign() {
    const tenantRole = u.role === 'tenant';
    const unrated = rental ? I.rooms.flatMap(r => r.items).filter(i => !i.condition).length : 0;
    $('#ib').innerHTML = `<div class="grid2" style="align-items:start"><div class="card stack"><h3>Summary</h3>
        <textarea class="input" id="sum" rows="5" ${edit ? '' : 'disabled'} placeholder="Overall condition, keys and remotes handed over, meter readings, anything agreed on the day">${esc(I.summary || '')}</textarea>
        ${rental ? `<label class="check"><input type="checkbox" id="tp" ${I.tenant_present ? 'checked' : ''} ${edit ? '' : 'disabled'}>Tenant present (joint inspection)</label>` : ''}
        ${unrated ? `<div class="pill warn">${unrated} items still need a condition</div>` : ''}
        ${edit ? `<button class="btn" id="savesum">Save summary</button>` : ''}</div>
      <div class="card stack"><h3>Signatures</h3>
        ${sigBox('Inspector / agent', I.agent_sig, I.agent_signed_at, edit && !I.agent_sig ? 'agent' : null)}
        ${rental ? sigBox('Tenant', I.tenant_sig, I.tenant_signed_at, I.status !== 'final' && !I.tenant_sig && (edit || tenantRole) ? 'tenant' : null) : sigBox('Contractor / site agent', I.contractor_sig, I.contractor_signed_at, edit && !I.contractor_sig ? 'contractor' : null)}
        ${edit ? `<button class="btn cta lg" id="fin">${icon('check')}Sign off & lock</button><p class="tiny muted">Locks the report, sends it to the tenant and owner${rental ? ', raises repair requests for charged items' : ''}${I.type === 'outgoing' ? ' and starts the deposit refund clock' : ''}.</p>` : ''}
        ${tenantRole && !I.tenant_sig && I.status !== 'final' ? '<p class="small muted">Check every room before signing. You can add comments in Messages.</p>' : ''}</div></div>`;
    $('#savesum')?.addEventListener('click', async () => { await act($('#savesum'), () => api.put('/api/inspections/' + id, { summary: $('#sum').value, tenant_present: $('#tp')?.checked ? 1 : 0 }), 'Saved'); await refresh(); });
    $$('[data-sign]').forEach(b => b.onclick = async () => {
      const who = b.dataset.sign; const sig = await signModal('Sign inspection', who === 'tenant' ? (I.lease?.tenant_name || 'Tenant') : u.name); if (!sig) return;
      await api.put('/api/inspections/' + id, { summary: $('#sum').value, ...(rental ? { tenant_present: $('#tp')?.checked ? 1 : 0 } : {}) }).catch(() => { });
      await act(b, () => api.post(`/api/inspections/${id}/sign`, { who, sig }), 'Signed'); await refresh(); sign();
    });
    $('#fin')?.addEventListener('click', async () => {
      await api.put('/api/inspections/' + id, { summary: $('#sum').value, ...(rental ? { tenant_present: $('#tp')?.checked ? 1 : 0 } : {}) });
      const r = await act($('#fin'), () => api.post(`/api/inspections/${id}/finalise`));
      toast(r.tickets_created ? `Signed off – ${r.tickets_created} repair request(s) raised` : 'Signed off'); go(`#/app/inspection/${id}?tab=${I.type === 'outgoing' ? 'compare' : 'report'}&r=${Date.now()}`);
    });
  }
  const sigBox = (label, sig, at, who) => `<div class="stack tight"><span class="small muted">${label}</span>${sig ? `<img class="sigimg" src="${sig}" alt="${label} signature"><span class="tiny muted">${fdt(at)}</span>` : who ? `<button class="btn" data-sign="${who}">${icon('doc')}Sign as ${label.toLowerCase()}</button>` : '<span class="faint small">Not signed</span>'}</div>`;

  // ---------------- report
  function report() {
    const P = I.property;
    const metrics = !rental ? snagStats(I.snags) : null;
    $('#ib').innerHTML = `<div class="row noprint"><span class="spacer"></span><button class="btn" onclick="print()">${icon('print')}Print / save as PDF</button></div>
      <div class="card stack" id="report"><div class="row top"><div class="grow"><div class="logo">AVA</div><span class="small muted">${rental ? 'Rental Housing Act 50 of 1999 s5 – joint inspection' : 'Construction snag list / NCR register'}</span></div>
        <div class="right"><h2>${INSP[I.type]} inspection${I.round > 1 ? ' – round ' + I.round : ''}</h2><span class="small">${fdate(I.date)} · ${pill(I.status)}</span></div></div>
        <div class="costs"><div><span>Property</span><b>${esc(P.title)}</b></div><div><span>Address</span><span>${esc(P.address || '')}</span></div>${I.lease ? `<div><span>Tenant</span><span>${esc(I.lease.tenant_name)}</span></div>` : ''}${I.compare_to ? `<div><span>Compared with</span><span>${INSP[I.compare_to.type]} of ${fdate(I.compare_to.date)}</span></div>` : ''}</div>
        ${I.summary ? `<p style="white-space:pre-wrap">${esc(I.summary)}</p>` : ''}
        ${metrics ? `<div class="kpis"><div class="kpi"><span>Snags</span><b>${metrics.total}</b></div><div class="kpi"><span>Closed</span><b>${metrics.closed}</b></div><div class="kpi ${metrics.overdue ? 'alert' : ''}"><span>Overdue</span><b>${metrics.overdue}</b></div><div class="kpi"><span>Cost to rectify</span><b>${R(metrics.cost)}</b></div></div>
          <table class="t"><tr><th>Ref</th><th>Room</th><th>Defect</th><th>Trade / contractor</th><th class="num">Qty</th><th class="num">Amount</th><th>Due</th><th>Status</th></tr>${I.snags.map(s => `<tr><td class="mono small">${s.ref}</td><td>${esc(s.room || '')}</td><td><b>${esc(s.title)}</b><div class="tiny muted">${esc(s.category)} · <span class="prio-${s.priority}">${s.priority}</span></div>${(s.photos_before || []).slice(0, 1).map(p => `<img src="${esc(p)}" style="width:90px;border-radius:6px;margin-top:4px">`).join('')}</td><td class="small">${esc(s.trade || '')}</td><td class="num">${s.qty} ${esc(s.unit)}</td><td class="num">${s.rate ? R(s.qty * s.rate) : ''}</td><td class="small">${fdate(s.due_date)}</td><td>${pill(s.status)}</td></tr>`).join('')}</table>` : ''}
        ${rental ? I.rooms.map(r => `<div class="stack tight" style="break-inside:avoid"><h3>${esc(r.name)}</h3>${r.pano_url ? `<img src="${esc(r.pano_url)}" alt="360 of ${esc(r.name)}" style="width:100%;max-height:180px;object-fit:cover;border-radius:8px">` : ''}
          <table class="t"><tr><th>Item</th><th>Condition</th><th>Clean</th><th>Working</th><th>Notes</th>${I.type !== 'ingoing' ? '<th class="num">Charge</th>' : ''}</tr>${r.items.map(i => `<tr><td>${esc(i.name)}</td><td>${cchip(i.condition)}${i.prev ? ` <span class="tiny muted">was C${i.prev.condition || '–'}</span>` : ''}</td><td>${i.clean === 0 ? 'No' : 'Yes'}</td><td>${i.working === 0 ? 'No' : 'Yes'}</td><td class="small">${esc(i.notes || '')}${(i.photos || []).map(p => ` <img src="${esc(p)}" data-zoom="${esc(p)}" style="width:48px;height:48px;object-fit:cover;border-radius:5px;display:inline-block">`).join('')}</td>${I.type !== 'ingoing' ? `<td class="num">${i.charge ? R(i.charge) + ' ' + esc(i.charge_to || '') : ''}</td>` : ''}</tr>`).join('')}</table></div>`).join('') : ''}
        ${I.deposit ? `<div class="card tint stack tight"><h3>Deposit</h3><div class="costs"><div><span>Held incl. interest</span><span class="num">${R2(I.deposit.held)}</span></div><div><span>Deductions</span><span class="num">−${R2(I.deposit.deductions)}</span></div><div class="tot"><span>Refund</span><span class="num">${R2(I.deposit.refund)}</span></div></div><span class="small muted">Due by ${fdate(I.deposit.refund_by)} (${esc(I.deposit.rule)})</span></div>` : ''}
        <div class="split">${sigBox('Inspector / agent', I.agent_sig, I.agent_signed_at)}${rental ? sigBox('Tenant', I.tenant_sig, I.tenant_signed_at) : sigBox('Contractor / site agent', I.contractor_sig, I.contractor_signed_at)}</div></div>`;
  }

  show(tab);
  (await import('./core.js')).onLeave(kill);
}, A);

// A flat 'before' photo cut out of the 360 at the pin, so every snag has evidence even without a phone photo.
async function viewShot(viewer, pin) {
  try {
    const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = viewer.url; });
    const W = Math.min(img.width, 4096), H = W / 2;
    const c = document.createElement('canvas'); c.width = W; c.height = H; const g = c.getContext('2d'); g.drawImage(img, 0, 0, W, H);
    const src = g.getImageData(0, 0, W, H).data;
    const w = 800, h = 600, fov = 55 * Math.PI / 180, f = (w / 2) / Math.tan(fov / 2);
    const out = document.createElement('canvas'); out.width = w; out.height = h; const og = out.getContext('2d'); const od = og.createImageData(w, h);
    const y0 = pin.yaw * Math.PI / 180, p0 = pin.pitch * Math.PI / 180, cp = Math.cos(p0), sp = Math.sin(p0), cy = Math.cos(y0), sy = Math.sin(y0);
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
      let x = i - w / 2, y = h / 2 - j, z = f; const n = Math.hypot(x, y, z); x /= n; y /= n; z /= n;
      const y1 = cp * y + sp * z, z1 = -sp * y + cp * z, x2 = cy * x + sy * z1, z2 = -sy * x + cy * z1;
      const u = Math.floor(((Math.atan2(x2, z2) / (2 * Math.PI) + .5) * W) % W), v = Math.min(H - 1, Math.max(0, Math.floor((.5 - Math.asin(Math.max(-1, Math.min(1, y1))) / Math.PI) * H)));
      const si = (v * W + u) * 4, di = (j * w + i) * 4; od.data[di] = src[si]; od.data[di + 1] = src[si + 1]; od.data[di + 2] = src[si + 2]; od.data[di + 3] = 255;
    }
    og.putImageData(od, 0, 0);
    og.strokeStyle = '#e0702a'; og.lineWidth = 4; og.beginPath(); og.arc(w / 2, h / 2, 46, 0, Math.PI * 2); og.stroke();
    return await new Promise(res => out.toBlob(b => res(b ? new File([b], 'snag.jpg', { type: 'image/jpeg' }) : null), 'image/jpeg', .85));
  } catch (_) { return null; }
}

// ------------------------------------------------------------------ snag rows (shared)
function snagRow(s, { verify = false, contractor = false } = {}) {
  const ph = (s.photos_after || [])[0] || (s.photos_before || [])[0];
  const overdue = s.status !== 'closed' && s.due_date < today();
  return `<div class="snagrow" data-snag="${s.id}">${ph ? `<img src="${esc(ph)}" data-zoom="${esc(ph)}" alt="">` : '<div class="noimg"></div>'}
    <div style="min-width:0"><div class="row wrap" style="gap:6px"><span class="mono tiny muted">${esc(s.ref)}</span>${pill(s.status)}<span class="tiny prio-${s.priority}">${s.priority}</span>${overdue ? '<span class="pill bad">Overdue</span>' : ''}${s.rework_count ? `<span class="pill warn">Rework ×${s.rework_count}</span>` : ''}</div>
      <b>${esc(s.title)}</b><div class="small muted">${esc(s.room || '')} · ${esc(s.category || '')} · ${esc(s.trade || '')}${s.contractor_company || s.contractor_name ? ' · ' + esc(s.contractor_company || s.contractor_name) : ''} · ${s.qty} ${esc(s.unit)}${s.rate ? ' · ' + R(s.qty * s.rate) : ''} · due ${fdate(s.due_date)}</div>
      ${s.contractor_note ? `<div class="small" style="color:var(--jac)">“${esc(s.contractor_note)}”</div>` : ''}
      ${(s.photos_before || []).length + (s.photos_after || []).length > 1 ? `<div class="thumbs" style="margin-top:4px">${(s.photos_before || []).map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" style="width:44px;height:44px" title="Before">`).join('')}${(s.photos_after || []).map(p => `<img src="${esc(p)}" data-zoom="${esc(p)}" style="width:44px;height:44px;outline:2px solid var(--ok)" title="After">`).join('')}</div>` : ''}</div>
    <div class="row" style="gap:6px;justify-content:flex-end">${verify ? `<button class="btn sm" data-rej>Reject</button><button class="btn sm primary" data-close>Close</button>` : ''}${contractor && ['open', 'in_progress'].includes(s.status) ? `<button class="btn sm primary" data-ready>${icon('camera')}Fixed</button>` : ''}</div></div>`;
}
function bindSnagRows(root, list, done, inspectionId) {
  $$('[data-snag]', root).forEach(el => {
    const s = list.find(x => x.id == el.dataset.snag);
    $('[data-close]', el)?.addEventListener('click', async () => {
      const f = s.photos_after?.length ? [] : await pickFiles({ capture: 'environment' });
      const fd = new FormData(); fd.set('result', 'close'); if (inspectionId) fd.set('inspection_id', inspectionId); f.forEach(x => fd.append('photos', x));
      await act(null, () => api.post(`/api/snags/${s.id}/verify`, fd), `${s.ref} closed`); done();
    });
    $('[data-rej]', el)?.addEventListener('click', async () => {
      const note = prompt('Why is it not accepted?', 'Still visible / not to standard'); if (note === null) return;
      const fd = new FormData(); fd.set('result', 'reject'); fd.set('note', note);
      await act(null, () => api.post(`/api/snags/${s.id}/verify`, fd), `${s.ref} sent back for rework`); done();
    });
    $('[data-ready]', el)?.addEventListener('click', async () => {
      const f = await pickFiles({ capture: 'environment' }); if (!f.length) return toast("Add an 'after' photo of the fix", true);
      const note = prompt('Note for the inspector (optional)', 'Fixed, please check') || '';
      const fd = new FormData(); fd.set('note', note); f.forEach(x => fd.append('photos', x));
      await act(null, () => api.post(`/api/snags/${s.id}/ready`, fd), 'Marked ready for re-inspection'); done();
    });
  });
}
function snagStats(list) {
  const t = today();
  return { total: list.length, closed: list.filter(s => s.status === 'closed').length, overdue: list.filter(s => s.status !== 'closed' && s.due_date < t).length,
    cost: list.filter(s => s.status !== 'closed').reduce((a, s) => a + (s.qty || 1) * (s.rate || 0), 0) };
}

// ------------------------------------------------------------------ snag dashboards
function metricsBlock(m) {
  const mx = Math.max(1, ...m.by_trade.map(t => t.total));
  return `<div class="kpis"><div class="kpi"><span>Snags raised</span><b>${m.total}</b><small>${m.density_per_100m2 != null ? m.density_per_100m2 + ' per 100 m²' : ''}</small></div>
    <div class="kpi"><span>Closed</span><b>${m.close_rate}%</b><small>${m.closed} of ${m.total}</small></div>
    <div class="kpi ${m.ready ? '' : ''}"><span>Ready to verify</span><b>${m.ready}</b><small>contractor says fixed</small></div>
    <div class="kpi ${m.overdue ? 'alert' : 'good'}"><span>Overdue</span><b>${m.overdue}</b></div>
    <div class="kpi"><span>Avg days to close</span><b>${m.avg_days_to_close ?? '–'}</b></div>
    <div class="kpi"><span>First-time right</span><b>${m.first_time_right ?? '–'}%</b><small>closed without rework</small></div>
    <div class="kpi"><span>Open cost to rectify</span><b>${R(m.cost_to_rectify)}</b><small>qty × rate</small></div>
    <div class="kpi"><span>Severity index</span><b>${m.severity_index}</b><small>Urgent 4 · High 3 · Med 2 · Low 1</small></div></div>
  <div class="grid2" style="align-items:start"><div class="card stack tight"><h3>By trade</h3><div class="bars">${m.by_trade.map(t => `<div class="b"><span class="small">${esc(t.trade)}</span><div class="track"><i style="width:${t.closed / mx * 100}%;background:var(--ok)"></i><i style="width:${(t.open - t.overdue) / mx * 100}%;background:var(--warn)"></i><i style="width:${t.overdue / mx * 100}%;background:var(--bad)"></i></div><span class="small num">${t.open}/${t.total}</span></div>`).join('')}</div>
      <div class="row tiny muted"><span class="dot ok"></span>closed <span class="dot warn"></span>open <span class="dot bad"></span>overdue</div></div>
    <div class="card flush"><div class="card-head"><h3>Contractor scorecard</h3></div><div class="tablewrap"><table class="t"><tr><th>Contractor</th><th class="num">Snags</th><th class="num">Closed</th><th class="num">Overdue</th><th class="num">Avg days</th><th class="num">First-time right</th></tr>
      ${m.by_contractor.map(c => `<tr><td>${esc(c.contractor)}</td><td class="num">${c.total}</td><td class="num">${c.closed}</td><td class="num ${c.overdue ? 'prio-Urgent' : ''}">${c.overdue}</td><td class="num">${c.avg_days ?? '–'}</td><td class="num">${c.ftr != null ? c.ftr + '%' : '–'}</td></tr>`).join('')}</table></div></div></div>`;
}

export async function snagBoard(host, pid) {
  const u = state.user;
  const [m, list] = await Promise.all([api.get('/api/snags/metrics?property_id=' + pid), api.get('/api/snags?property_id=' + pid)]);
  const contractor = u.role === 'contractor';
  let f = 'open';
  host.innerHTML = `${contractor ? '' : metricsBlock(m)}<div class="row wrap"><div class="seg" id="sf">${[['open', 'Open'], ['ready', 'Ready to verify'], ['overdue', 'Overdue'], ['closed', 'Closed'], ['', 'All']].map(([k, l]) => `<button data-k="${k}" aria-pressed="${f === k}">${l}</button>`).join('')}</div><span class="spacer"></span>
    ${!contractor ? `<a class="btn sm" href="/api/reports/snags.xlsx">${icon('excel')}Excel</a><button class="btn sm primary" id="reinsp">${icon('clip')}Start re-inspection</button>` : ''}</div><div class="card flush" id="sl"></div>`;
  const draw = () => {
    const t = today();
    const rows = list.filter(s => f === '' ? true : f === 'open' ? s.status !== 'closed' : f === 'overdue' ? s.status !== 'closed' && s.due_date < t : s.status === f);
    $('#sl', host).innerHTML = rows.map(s => snagRow(s, { verify: !contractor && s.status === 'ready', contractor })).join('') || '<div class="empty">Nothing here.</div>';
    bindSnagRows($('#sl', host), rows, () => snagBoard(host, pid));
  };
  $$('#sf button', host).forEach(b => b.onclick = () => { f = b.dataset.k; $$('#sf button', host).forEach(x => x.setAttribute('aria-pressed', x === b)); draw(); });
  $('#reinsp', host)?.addEventListener('click', async () => {
    const existing = (await api.get('/api/inspections?property_id=' + pid)).find(i => i.type === 'reinspection' && i.status !== 'final');
    const id = existing ? existing.id : (await api.post('/api/inspections', { property_id: pid, type: 'reinspection' })).id;
    go(`#/app/inspection/${id}?tab=compare`);
  });
  draw();
}

route('/app/snags', async () => {
  const u = state.user;
  const pg = page(u.role === 'contractor' ? 'My snags' : 'Snag lists');
  if (u.role === 'contractor') {
    const list = await api.get('/api/snags?status=open');
    pg.innerHTML = `<div class="ai-note">${icon('camera')}<span>Fix the snag, tap <b>Fixed</b> and take an 'after' photo from the same angle. The inspector verifies it at the next re-inspection – rejected work counts against your first-time-right score.</span></div><div class="card flush" id="sl"></div>`;
    $('#sl').innerHTML = list.map(s => snagRow({ ...s }, { contractor: true }).replace('<b>', `<span class="tiny muted">${esc(s.ptitle)}</span><br><b>`)).join('') || '<div class="empty">No open snags. 🎉</div>';
    bindSnagRows($('#sl'), list, () => go('#/app/snags?r=' + Date.now()));
    return;
  }
  const [m, props] = await Promise.all([api.get('/api/snags/metrics'), api.get('/api/properties')]);
  const withSnags = props.filter(p => p.kind === 'project' || p.open_snags);
  pg.innerHTML = `<div class="ai-note">${icon('clip')}<span><b>Better measures than a spreadsheet snag list:</b> every snag is pinned on a 360° view with a before photo, measured (qty × unit × rate), assigned to a trade and contractor with a due date by priority, and only closes with an 'after' photo at re-inspection. You see close-out rate, overdue items, days to close, first-time-right and cost to rectify per contractor.</span></div>
    ${metricsBlock(m)}<div class="card flush"><div class="card-head"><h3>Projects & properties</h3><a class="btn sm" href="#/app/properties/new">${icon('plus')}New build project</a></div><div class="list">${withSnags.map(p => `<a class="li" href="#/app/snags/${p.id}">${icon('building')}<span class="grow"><span class="title">${esc(p.title)}</span><span class="small muted">${esc(p.suburb || '')}</span></span><span class="pill ${p.open_snags ? 'warn' : 'ok'}">${p.open_snags} open</span></a>`).join('') || '<div class="muted">Add a property of kind “New build” to start a snag list.</div>'}</div></div>`;
}, A);

route('/app/snags/:pid', async ({ pid }) => {
  const u = state.user;
  const p = u.role === 'contractor' ? { title: 'Snags' } : await api.get('/api/properties/' + pid);
  const pg = page(p.title, { back: '#/app/snags', actions: u.role !== 'contractor' ? `<a class="btn sm" href="#/app/property/${pid}?tab=inspections">${icon('pano')}<span class="hide-sm">Inspections</span></a>` : '' });
  pg.innerHTML = '<div id="sb" class="stack"></div>';
  await snagBoard($('#sb'), +pid);
}, A);
