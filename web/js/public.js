// Public portal: search like Property24 / Private Property, plus AVA's 360 tours, online viewings and applications.
import { $, $$, api, act, esc, feat, fdate, fslot, go, icon, LOGO, modal, onLeave, R, refreshMe, route, state, toast, formData, plural } from './core.js';
import { PanoViewer } from './pano.js';

const app = () => $('#app');

export function nav(active = '') {
  const u = state.user;
  return `<header class="topnav"><div class="in">
    <a class="logo" href="#/">${LOGO}</a>
    <nav><a href="#/search" class="${active === 'rent' ? 'on' : ''}">To rent</a><a href="#/search?view=map" class="${active === 'map' ? 'on' : ''}">Map</a>
      <a href="#/landlords" class="${active === 'landlords' ? 'on' : ''}">For landlords</a><a href="#/agents" class="${active === 'agents' ? 'on' : ''}">For agents</a>
      ${feat('maintenance') ? `<a href="#/pros" class="${active === 'pros' ? 'on' : ''}">Maintenance</a>` : ''}<a href="#/explore" class="${active === 'explore' ? 'on' : ''}">Investor tools</a></nav>
    <span class="spacer"></span>
    ${u ? `<a class="btn sm" href="#/app">${icon('grid')}My AVA</a>` : `<a class="btn ghost sm" href="#/login">Sign in</a><a class="btn primary sm" href="#/register">Join free</a>`}
  </div></header>`;
}
export const footer = () => `<footer class="footer"><div class="wrap grid3" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
  <div class="stack tight"><a class="logo" href="#/" style="color:#fff">${LOGO}</a><p>Rent with peace of mind. One portfolio manager, hundreds of homes, nothing missed.</p></div>
  <div class="stack tight"><b style="color:#fff">Renters</b><a href="#/search">Search homes</a><a href="#/search?view=map">Search the map</a><a href="#/register">Create an account</a></div>
  <div class="stack tight"><b style="color:#fff">Owners & agents</b><a href="#/landlords">List with AVA</a><a href="#/earn">What could my home earn?</a><a href="#/agents">Start your digital agency</a><a href="#/explore">Yield & bond calculator</a></div>
  ${feat('maintenance') ? `<div class="stack tight"><b style="color:#fff">Maintenance companies</b><a href="#/pros">Find a rated company</a><a href="#/pros/join">List your company – R250/month</a></div>` : ''}
  <div class="stack tight small"><b style="color:#fff">Compliance</b><span>Rental Housing Act 50 of 1999 · CPA · POPIA · FICA · PPRA registered portfolio managers · deposits held in interest-bearing trust.</span><a href="#/privacy-notice">Privacy notice</a></div>
</div></footer>`;

const facts = p => `<div class="facts"><span>${icon('bed')}${p.bedrooms || 0}</span><span>${icon('bath')}${p.bathrooms || 0}</span>${p.parking ? `<span>${icon('car')}${p.parking}</span>` : ''}${p.size_m2 ? `<span>${icon('area')}${Math.round(p.size_m2)} m²</span>` : ''}${p.erf_size ? `<span class="hide-sm" title="Erf size">Erf ${Math.round(p.erf_size).toLocaleString('en-ZA')} m²</span>` : ''}</div>`;
export const FB = '/uploads/media/demo/p003_0.jpg';
const isNew = p => p.published_at && (Date.now() - new Date(p.published_at)) < 3 * 864e5;
export function lcard(p) {
  return `<a class="lcard" href="#/p/${p.id}" data-id="${p.id}">
    <div class="ph"><img src="${esc(p.cover || FB)}" data-fb="${FB}" alt="${esc(p.title)}" loading="lazy">
      <div class="tags">${p.featured ? '<span class="pill cta">Featured</span>' : ''}${isNew(p) ? '<span class="pill ok">New</span>' : ''}${p.has_tour ? `<span class="pill jac">${icon('pano')}360°</span>` : ''}</div>
      ${p.photos ? `<span class="cnt">${icon('camera')}${p.photos}</span>` : ''}</div>
    <div class="bd"><div class="price">${R(p.rent)} <small>per month</small></div><b class="ttl">${esc(p.headline || p.title)}</b>
      <span class="small muted">${icon('pin')}${esc(p.suburb)}, ${esc(p.city)}</span>${facts(p)}
      <div class="foot"><span class="tiny">${esc(p.type)}</span><span class="tiny muted">${p.available_from && p.available_from > new Date().toISOString().slice(0, 10) ? 'Available ' + fdate(p.available_from) : 'Available now'}</span></div></div></a>`;
}
document.addEventListener('error', e => { const t = e.target; if (t.tagName === 'IMG' && t.dataset.fb && t.src.indexOf(t.dataset.fb) < 0) t.src = t.dataset.fb; }, true);

// ------------------------------------------------------------------ home
route('/', async () => {
  if (state.user?.role === 'contractor') return go('#/app/jobs');   // maintenance companies see jobs, not homes to rent
  const [stats, feat] = await Promise.all([api.get('/api/stats/public'), api.get('/api/listings?limit=12&sort=new')]);
  const hero = 'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=2000&q=70';
  app().innerHTML = nav() + `
  <section class="hero"><div class="bgimg" style="background-image:url('${hero}'),url('${FB}')"></div><div class="shade"></div><div class="in">
    <span class="pill jac" style="width:max-content;background:rgba(27,163,160,.18);color:#7fe0dc">${icon('spark')} Advanced Virtual Agent</span>
    <h1>Find your next home.<br><em>Skip the agent fees.</em></h1>
    <p class="lead">${stats.live} homes to rent across South Africa – every one vetted, many in 360°. Book a viewing in seconds, apply on your phone, and get answers 24/7 from AVA's virtual agent.</p>
    <form class="searchbar" id="hs"><input class="input" name="city" list="hcities" placeholder="Search a suburb, city or province" aria-label="Where"><datalist id="hcities">${stats.cities.map(c => `<option value="${esc(c)}">`).join('')}${stats.provinces.map(p => `<option value="${esc(p.province)}">`).join('')}</datalist>
      <select class="input" name="types" aria-label="Property type"><option value="">Any type</option>${['House', 'Apartment', 'Townhouse', 'Cottage', 'Room', 'Farm', 'Retirement'].map(v => `<option>${v}</option>`).join('')}</select>
      <select class="input" name="max_rent" aria-label="Max rent"><option value="">Max price</option>${[17500, 20000, 22500, 25000, 27500, 30000].map(v => `<option value="${v}">${R(v)}</option>`).join('')}</select>
      <select class="input" name="beds" aria-label="Bedrooms"><option value="">Bedrooms</option>${[1, 2, 3, 4, 5].map(v => `<option value="${v}">${v}+ beds</option>`).join('')}</select>
      <button class="btn cta lg">${icon('search')}Search</button></form>
    <div class="chips"><a href="#/search?features=backup_power">${icon('bolt')}Backup power</a><a href="#/search?pets=1">Pet friendly</a><a href="#/search?features=security">Security estates</a><a href="#/search?tour=1">${icon('pano')}360° tours</a><a href="#/search?listed_within=7">New this week (${stats.new_week})</a><a href="#/search?view=map">${icon('map')}Search on the map</a></div>
  </div></section>
  <section class="trust"><div class="wrap"><div><b>${stats.live}</b><span>homes to rent</span></div><div><b>${stats.managed}</b><span>homes managed</span></div><div><b>${stats.provinces.length}</b><span>provinces</span></div><div><b>24/7</b><span>virtual agent</span></div><div><b>0%</b><span>agent commission to tenants</span></div></div></section>
  <section class="section"><div class="wrap"><div class="row wrap"><div><h2>Just listed</h2><p class="sub">Fresh on AVA – verified landlords, real photos, 360° walk-throughs.</p></div><span class="spacer"></span><a class="btn" href="#/search?sort=recent">View all ${stats.live}</a></div>
    <div class="cards">${feat.map(lcard).join('')}</div></div></section>
  <section class="section" style="padding-top:0"><div class="wrap"><h2>Rent across South Africa</h2><p class="sub">From Sandton apartments to Garden Route cottages.</p>
    <div class="provs">${stats.provinces.map(p => `<a class="prov" href="#/search?areas=${encodeURIComponent(p.province)}"><img src="${esc(p.cover || FB)}" data-fb="${FB}" alt="" loading="lazy"><div><b>${esc(p.province)}</b><span>${p.n} homes · from ${R(p.lo)}</span></div></a>`).join('')}</div></div></section>
  <section class="section agentsec"><div class="wrap grid2" style="align-items:center;gap:40px">
    <div class="stack"><span class="pill jac" style="width:max-content">${icon('spark')} AVA virtual agent</span><h2 style="font-size:32px">The agent that never sleeps</h2>
      <p class="muted">Ask anything about a home – costs, pets, backup power, the area – and AVA answers instantly from the listing. It checks what you can afford, offers open viewing times and books them, starts your application, and hands you to a real portfolio manager when you need a person.</p>
      <div class="row wrap"><button class="btn primary" onclick="document.getElementById('fab').click()">${icon('spark')}Try it now</button><a class="btn" href="#/landlords">How it works for owners</a></div></div>
    <div class="chatdemo"><div class="msg mine">Is there backup power for load shedding?</div><div class="msg bot">Yes – solar and an inverter. The home also has fibre and a borehole.</div>
      <div class="msg mine">I earn R72 000. Can I afford it?</div><div class="msg bot">At R72 000 gross the rent is 30% of your income – comfortably within the guideline. Want to view it?</div>
      <div class="msg mine">Saturday morning?</div><div class="msg bot">Booked for Sat 10:00 ✓ I'll send directions and a reminder the day before.</div></div></div></section>
  <section class="section" style="background:var(--surface);border-block:1px solid var(--line)"><div class="wrap">
    <h2>How AVA replaces the traditional agent</h2><p class="sub">Every step a good agent does – done by the app, checked by a person, nothing forgotten.</p>
    <div class="steps">
      <div class="step"><h3>List & market</h3><p class="muted">AI writes the listing and checks the rent against comparable homes. Rooms go up in 360°. Saved-search alerts go out instantly.</p></div>
      <div class="step"><h3>Viewings on autopilot</h3><p class="muted">Renters pick an open slot or ask the virtual agent; AVA confirms, sends directions and reminders.</p></div>
      <div class="step"><h3>Vet & sign</h3><p class="muted">Affordability, credit and TPN rental history scored in seconds. Lease generated and signed on the phone.</p></div>
      <div class="step"><h3>Collect & pay out</h3><p class="muted">Rent matched to the reference automatically, arrears reminders escalate on their own, owners paid with a statement.</p></div>
      <div class="step"><h3>Fix things fast</h3><p class="muted">Issues triaged by AI, emergencies dispatched in minutes, quotes compared on price and rating, landlord approves in one tap.</p></div>
      <div class="step"><h3>Inspect fairly</h3><p class="muted">Ingoing and outgoing inspections with a 360° camera or phone, compared side by side. Deposits refunded on time with interest.</p></div>
    </div></div></section>
  <section class="section"><div class="wrap grid2" style="align-items:center">
    <div class="stack"><h2>Landlords keep more of the rent</h2><p class="muted">A typical agency charges 8–12% plus VAT every month. On AVA you pay a flat platform fee, a 3–5% portfolio-manager commission and optional rental insurance.</p>
      <div class="row wrap"><a class="btn primary" href="#/landlords">Calculate your saving</a><a class="btn" href="#/register?role=landlord">List a property</a></div></div>
    <div id="cmp"></div></div></section>` + footer();
  $('#hs').onsubmit = e => { e.preventDefault(); const p = new URLSearchParams([...new FormData(e.target)].filter(([, v]) => v).map(([k, v]) => [k === 'city' ? 'areas' : k, v])); go('#/search?' + p); };
  const f = await api.get('/api/fees/public?rent=20000');
  $('#cmp').innerHTML = compareBox(f, 20000);
});

const compareBox = (f, rent) => `<div class="compare-box"><div class="old"><span class="small muted">Traditional agent (10% + VAT)</span><b>${R(f.compare.traditional_monthly)}</b><span class="small muted">per month on ${R(rent)} rent</span></div>
  <div class="new"><span class="small" style="opacity:.8">AVA (platform + portfolio manager)</span><b>${R(f.compare.ava_monthly)}</b><span class="small" style="opacity:.8">You save ${R(f.compare.saving_month)} a month · ${R(f.compare.saving_year)} a year</span></div></div>`;

// ------------------------------------------------------------------ search (Property24 filter set)
const PRICES = [15000, 16000, 17000, 18000, 19000, 20000, 21000, 22000, 23000, 24000, 25000, 26000, 27000, 28000, 29000, 30000];
const SIZES = [30, 50, 75, 100, 150, 200, 250, 300, 400, 500];
const ERFS = [250, 500, 750, 1000, 1500, 2000, 5000, 10000];
const WITHIN = [['', 'Any time'], ['1', 'Last 24 hours'], ['3', 'Last 3 days'], ['7', 'Last 7 days'], ['14', 'Last 14 days'], ['30', 'Last 30 days']];
const SORTS = [['new', 'Featured & newest'], ['recent', 'Most recent'], ['low', 'Price: low to high'], ['high', 'Price: high to low'], ['size', 'Floor size: largest'], ['available', 'Available soonest'], ['beds', 'Most bedrooms']];
const list = v => (v || '').split(',').map(x => x.trim()).filter(Boolean);

route('/search', async (_, q) => {
  if (state.user?.role === 'contractor') return go('#/app/jobs');   // maintenance companies see jobs, not homes to rent
  const F = { ...q }; delete F.view;
  if (F.city && !F.areas) { F.areas = F.city; delete F.city; }
  if (F.type && !F.types) { F.types = F.type; delete F.type; }
  if (F.backup) { F.features = [...new Set([...list(F.features), 'backup_power'])].join(','); delete F.backup; }
  const facets = await api.get('/api/search/facets');
  const showMap = q.view !== 'list';
  app().innerHTML = nav(q.view === 'map' ? 'map' : 'rent') + `
  <div class="sbar"><div class="in">
    <div class="loc" id="loc"><span id="chips"></span><input id="locin" list="areas" placeholder="Suburb, city or province" aria-label="Location"><datalist id="areas">
      ${facets.cities.map(c => `<option value="${esc(c.name)}">${esc(c.province || '')} · ${c.n} to rent</option>`).join('')}${facets.areas.map(a => `<option value="${esc(a.name)}">${esc(a.city)} · ${a.n}</option>`).join('')}</datalist></div>
    <details class="dd" id="ddtype"><summary class="btn" id="tsum">Property type</summary><div class="ddpanel stack tight">${facets.types.map(t => `<label class="check ${t.n ? '' : 'faint'}"><input type="checkbox" data-type="${t.type}">${t.type === 'Apartment' ? 'Apartment / flat' : t.type}<span class="spacer"></span><span class="tiny muted">${t.n}</span></label>`).join('')}</div></details>
    <details class="dd" id="ddprice"><summary class="btn" id="psum">Price</summary><div class="ddpanel stack tight"><div class="row"><select class="input" id="pmin"><option value="">No min</option>${PRICES.map(v => `<option value="${v}">${R(v)}</option>`).join('')}</select><span>–</span>
      <select class="input" id="pmax"><option value="">No max</option>${PRICES.map(v => `<option value="${v}">${R(v)}</option>`).join('')}</select></div><span class="tiny muted">Monthly rental</span></div></details>
    <details class="dd" id="ddbeds"><summary class="btn" id="bsum">Bedrooms</summary><div class="ddpanel stack tight"><div class="seg" id="beds">${['', '1', '2', '3', '4', '5'].map(v => `<button type="button" data-v="${v}">${v ? v + '+' : 'Any'}</button>`).join('')}</div></div></details>
    <button class="btn" id="more">${icon('list')}More filters<span class="pill cta hide" id="mcount"></span></button>
    <span class="spacer"></span>
    <button class="btn sm ghost hide-sm" id="mapt">${icon('map')}${showMap ? 'Hide map' : 'Show map'}</button>
  </div></div>
  <div class="searchpage ${showMap ? '' : 'nomap'}"><div class="results">
    <div class="row wrap" style="margin-bottom:10px"><div><h2 id="count" style="font-size:20px">Searching…</h2><div id="active" class="row wrap" style="gap:6px;margin-top:6px"></div></div><span class="spacer"></span>
      <select class="input" id="sort" style="width:auto">${SORTS.map(([v, l]) => `<option value="${v}" ${F.sort === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button class="btn sm" id="alert">${icon('bell')}Save search & alert me</button></div>
    <div class="cards" id="res"></div></div>${showMap ? '<div class="map" id="map"></div>' : ''}</div>`;

  // ---------- state <-> controls
  const LBL = Object.fromEntries(facets.features.map(f => [f.key, f.label]));
  const sync = () => {
    $('#chips').innerHTML = list(F.areas).map(a => `<span class="chip">${esc(a)}<button type="button" data-rm-area="${esc(a)}" aria-label="Remove ${esc(a)}">×</button></span>`).join('');
    $$('[data-rm-area]').forEach(b => b.onclick = () => { F.areas = list(F.areas).filter(x => x !== b.dataset.rmArea).join(','); apply(); });
    $('#locin').placeholder = list(F.areas).length ? 'Add another area' : 'Suburb, city or province';
    $$('[data-type]').forEach(c => c.checked = list(F.types).includes(c.dataset.type));
    const tn = list(F.types).length; $('#tsum').textContent = tn ? (tn === 1 ? list(F.types)[0] : `${tn} types`) : 'Property type';
    $('#pmin').value = F.min_rent || ''; $('#pmax').value = F.max_rent || '';
    $('#psum').textContent = F.min_rent || F.max_rent ? `${F.min_rent ? R(F.min_rent) : 'Any'} – ${F.max_rent ? R(F.max_rent) : 'Any'}` : 'Price';
    $$('#beds button').forEach(b => b.setAttribute('aria-pressed', (F.beds || '') === b.dataset.v));
    $('#bsum').textContent = F.beds ? `${F.beds}+ beds` : 'Bedrooms';
    const more = ['baths', 'parking', 'min_size', 'max_size', 'min_erf', 'max_erf', 'pets', 'furnished', 'tour', 'available_by', 'listed_within', 'q'].filter(k => F[k]).length + list(F.features).length;
    $('#mcount').textContent = more; $('#mcount').classList.toggle('hide', !more);
    $$('#tsum,#psum,#bsum').forEach(el => el.classList.toggle('on', !/^(Property type|Price|Bedrooms)$/.test(el.textContent)));
    const chips = [];
    list(F.types).forEach(t => chips.push(['types', t, t]));
    if (F.min_rent || F.max_rent) chips.push(['price', '', $('#psum').textContent]);
    if (F.beds) chips.push(['beds', '', F.beds + '+ beds']);
    if (F.baths) chips.push(['baths', '', F.baths + '+ baths']);
    if (F.parking) chips.push(['parking', '', F.parking + '+ parking']);
    if (F.min_size || F.max_size) chips.push(['size', '', `Floor ${F.min_size || 0}–${F.max_size || '∞'} m²`]);
    if (F.min_erf || F.max_erf) chips.push(['erf', '', `Erf ${F.min_erf || 0}–${F.max_erf || '∞'} m²`]);
    if (F.pets) chips.push(['pets', '', 'Pets allowed']);
    if (F.furnished) chips.push(['furnished', '', F.furnished === 'no' ? 'Unfurnished' : 'Furnished']);
    if (F.tour) chips.push(['tour', '', '360° tour']);
    if (F.available_by) chips.push(['available_by', '', 'Available by ' + fdate(F.available_by)]);
    if (F.listed_within) chips.push(['listed_within', '', WITHIN.find(w => w[0] === F.listed_within)?.[1] || '']);
    if (F.q) chips.push(['q', '', `“${F.q}”`]);
    list(F.features).forEach(k => chips.push(['features', k, LBL[k] || k]));
    $('#active').innerHTML = chips.map(([k, v, l]) => `<span class="chip">${esc(l)}<button type="button" data-rm="${k}" data-v="${esc(v)}">×</button></span>`).join('') + (chips.length || list(F.areas).length ? '<button class="btn sm ghost" id="clear">Clear all</button>' : '');
    $$('[data-rm]').forEach(b => b.onclick = () => {
      const k = b.dataset.rm, v = b.dataset.v;
      if (k === 'types' || k === 'features') F[k] = list(F[k]).filter(x => x !== v).join(',');
      else if (k === 'price') { delete F.min_rent; delete F.max_rent; } else if (k === 'size') { delete F.min_size; delete F.max_size; }
      else if (k === 'erf') { delete F.min_erf; delete F.max_erf; } else delete F[k];
      apply();
    });
    $('#clear') && ($('#clear').onclick = () => { Object.keys(F).forEach(k => k !== 'sort' && delete F[k]); apply(); });
  };

  // ---------- map
  const L = window.L; let map = null, markers = [], fitted = false, byBounds = false;
  if (showMap) {
    map = L.map('map').setView([-28.5, 25.5], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap', maxZoom: 19 }).addTo(map);
    let armed = false; setTimeout(() => armed = true, 1500);
    map.on('dragend', () => { byBounds = true; load(); });
    map.on('zoomend', () => { if (armed && fitted) { byBounds = true; load(); } });
    onLeave(() => map.remove());
  }
  const params = () => { const p = new URLSearchParams(); Object.entries(F).forEach(([k, v]) => { if (v !== '' && v != null) p.set(k, v); }); return p; };
  async function load() {
    const p = params();
    if (byBounds && map) { const b = map.getBounds(); p.set('bounds', [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].map(x => x.toFixed(4)).join(',')); }
    const { rows, total } = await api.get('/api/search?' + p);
    const where = list(F.areas).length ? ' in ' + list(F.areas).join(', ') : byBounds ? ' in this map area' : ' in South Africa';
    $('#count').textContent = `${total} ${total === 1 ? 'property' : 'properties'} to rent${where}`;
    $('#res').innerHTML = rows.length ? rows.map(lcard).join('') : `<div class="empty"><h3>No properties match</h3><p>Remove a filter or two, or save this search – we'll alert you the moment a match is listed.</p></div>`;
    if (map) {
      markers.forEach(m => m.remove());
      markers = rows.filter(r => r.lat).map(r => { const m = L.marker([r.lat, r.lng], { icon: L.divIcon({ className: '', html: `<span class="pricepin" data-id="${r.id}">R${Math.round(r.rent / 100) / 10}k</span>`, iconSize: [0, 0] }) }).addTo(map); m.on('click', () => go('#/p/' + r.id)); return m; });
      if (!byBounds && markers.length) { map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2), { maxZoom: 13 }); fitted = true; }
      $$('.lcard', $('#res')).forEach(c => { c.onmouseenter = () => $(`.pricepin[data-id="${c.dataset.id}"]`)?.classList.add('on'); c.onmouseleave = () => $(`.pricepin[data-id="${c.dataset.id}"]`)?.classList.remove('on'); });
    }
  }
  function apply() {
    Object.keys(F).forEach(k => { if (F[k] === '' || F[k] == null) delete F[k]; });
    byBounds = false; sync();
    history.replaceState(null, '', '#/search?' + params() + (q.view ? '&view=' + q.view : ''));
    load();
  }

  // ---------- controls
  const addArea = v => { v = v.trim(); if (!v) return; F.areas = [...new Set([...list(F.areas), v])].join(','); $('#locin').value = ''; apply(); };
  $('#locin').addEventListener('change', e => addArea(e.target.value));
  $('#locin').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addArea(e.target.value); } if (e.key === 'Backspace' && !e.target.value && list(F.areas).length) { F.areas = list(F.areas).slice(0, -1).join(','); apply(); } });
  $$('[data-type]').forEach(c => c.onchange = () => { F.types = $$('[data-type]').filter(x => x.checked).map(x => x.dataset.type).join(','); apply(); });
  $('#pmin').onchange = e => { F.min_rent = e.target.value; apply(); };
  $('#pmax').onchange = e => { F.max_rent = e.target.value; apply(); };
  $$('#beds button').forEach(b => b.onclick = () => { F.beds = b.dataset.v; apply(); $('#ddbeds').open = false; });
  $('#sort').onchange = e => { F.sort = e.target.value; apply(); };
  $('#mapt')?.addEventListener('click', () => go('#/search?' + params() + '&view=' + (showMap ? 'list' : 'map')));
  const closeDD = e => $$('details.dd[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
  document.addEventListener('click', closeDD); onLeave(() => document.removeEventListener('click', closeDD));
  $('#more').onclick = () => moreFilters(F, facets, apply);
  $('#alert').onclick = async () => {
    if (!state.user) return go('#/login?next=' + encodeURIComponent(location.hash));
    const body = Object.fromEntries(params());
    if (byBounds && map) { const b = map.getBounds(); body.bounds = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()]; }
    await act($('#alert'), () => api.post('/api/alerts', body), "Search saved – we'll alert you when a matching home is listed");
  };
  sync(); await load();
});

function moreFilters(F, facets, apply) {
  const seg = (name, opts) => `<div class="seg" data-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${(F[name] || '') === v}">${l}</button>`).join('')}</div>`;
  const sel = (name, vals, unit, ph) => `<select class="input" data-f="${name}"><option value="">${ph}</option>${vals.map(v => `<option value="${v}" ${+F[name] === v ? 'selected' : ''}>${v.toLocaleString('en-ZA')} ${unit}</option>`).join('')}</select>`;
  const feats = list(F.features);
  const m = modal({ title: 'More filters', cls: 'wide', body: `<div class="grid2" style="gap:22px">
      <div class="stack"><div class="field"><span>Bathrooms</span>${seg('baths', [['', 'Any'], ['1', '1+'], ['2', '2+'], ['3', '3+'], ['4', '4+']])}</div>
        <div class="field"><span>Parking / garages</span>${seg('parking', [['', 'Any'], ['1', '1+'], ['2', '2+'], ['3', '3+'], ['4', '4+']])}</div>
        <div class="field"><span>Floor size</span><div class="row">${sel('min_size', SIZES, 'm²', 'No min')}<span>–</span>${sel('max_size', SIZES, 'm²', 'No max')}</div></div>
        <div class="field"><span>Erf / land size</span><div class="row">${sel('min_erf', ERFS, 'm²', 'No min')}<span>–</span>${sel('max_erf', ERFS, 'm²', 'No max')}</div></div>
        <div class="field"><span>Furnished</span>${seg('furnished', [['', 'Any'], ['1', 'Furnished'], ['no', 'Unfurnished']])}</div>
        <div class="field"><span>Listed</span>${seg('listed_within', WITHIN)}</div>
        <div class="cols form"><label class="field"><span>Available by</span><input class="input" type="date" data-f="available_by" value="${esc(F.available_by || '')}"></label>
          <label class="field"><span>Keywords</span><input class="input" data-f="q" value="${esc(F.q || '')}" placeholder="e.g. mountain view, borehole"></label></div></div>
      <div class="stack"><div class="field"><span>Must have</span><div class="stack tight">
          <label class="check"><input type="checkbox" data-c="pets" ${F.pets ? 'checked' : ''}>Pets allowed</label>
          <label class="check"><input type="checkbox" data-c="tour" ${F.tour ? 'checked' : ''}>${icon('pano')}360° virtual tour <span class="tiny muted">${facets.tour}</span></label></div></div>
        <div class="field"><span>Features</span><div class="grid2" style="gap:6px 14px">${facets.features.map(f => `<label class="check ${f.n ? '' : 'faint'}"><input type="checkbox" data-feat="${f.key}" ${feats.includes(f.key) ? 'checked' : ''}>${esc(f.label)}<span class="tiny muted">${f.n}</span></label>`).join('')}</div></div></div></div>`,
    foot: `<button class="btn ghost" id="reset">Reset these</button><span class="spacer"></span><button class="btn primary" id="show">Show results</button>` });
  const T = { ...F };
  $$('[data-seg]', m).forEach(g => $$('button', g).forEach(b => b.onclick = () => { T[g.dataset.seg] = b.dataset.v; $$('button', g).forEach(x => x.setAttribute('aria-pressed', x === b)); }));
  $('#reset', m).onclick = () => { ['baths', 'parking', 'min_size', 'max_size', 'min_erf', 'max_erf', 'furnished', 'listed_within', 'available_by', 'q', 'pets', 'tour', 'features'].forEach(k => delete F[k]); m.close(); apply(); };
  $('#show', m).onclick = () => {
    $$('[data-f]', m).forEach(i => T[i.dataset.f] = i.value);
    $$('[data-c]', m).forEach(c => T[c.dataset.c] = c.checked ? '1' : '');
    T.features = $$('[data-feat]', m).filter(c => c.checked).map(c => c.dataset.feat).join(',');
    Object.assign(F, T); m.close(); apply();
  };
}

// ------------------------------------------------------------------ listing
route('/p/:id', async ({ id }, q) => {
  if (state.user?.role === 'contractor') return go('#/app/jobs');   // maintenance companies see jobs, not homes to rent
  const p = await api.get('/api/listings/' + id);
  const photos = p.media.filter(m => m.kind === 'photo'), panos = p.media.filter(m => m.kind === 'pano');
  const g = photos.slice(0, 5);
  app().innerHTML = nav('rent') + `<div class="wrap" style="padding-top:18px;padding-bottom:40px">
    <div class="row wrap" style="margin-bottom:12px"><a href="#/search?city=${encodeURIComponent(p.city)}" class="btn ghost sm">${icon('back')}${esc(p.city)}</a><span class="spacer"></span>
      <button class="btn sm" id="share">Share</button><button class="btn sm" id="save">${icon('heart')}${p.saved ? 'Saved' : 'Save'}</button></div>
    <div class="gallery">${g.map((m, i) => `<button data-ph="${i}" aria-label="Photo ${i + 1}"><img src="${esc(m.url)}" data-fb="${FB}" alt="${esc(m.caption || '')}">${i === 0 && panos.length ? `<span class="btn cta tourbtn" data-tour>${icon('pano')}360° tour · ${panos.length} rooms</span>` : ''}${i === g.length - 1 && photos.length > g.length ? `<span class="more">+${photos.length - g.length} photos</span>` : ''}</button>`).join('')}</div>
    <div class="detail"><div class="stack loose">
      <div class="stack tight"><div class="row wrap">${p.featured ? '<span class="pill cta">Featured</span>' : ''}<span class="pill">${esc(p.type)}</span>${p.available_from ? `<span class="pill ok">Available ${fdate(p.available_from)}</span>` : ''}</div>
        <h1>${esc(p.headline || p.title)}</h1><p class="muted">${icon('pin')} ${esc(p.suburb)}, ${esc(p.city)} · ${esc(p.province || '')}</p></div>
      <div class="facts-row"><div><b>${p.bedrooms}</b><span>Bedrooms</span></div><div><b>${p.bathrooms}</b><span>Bathrooms</span></div><div><b>${p.parking}</b><span>Parking</span></div>${p.size_m2 ? `<div><b>${Math.round(p.size_m2)} m²</b><span>Floor size</span></div>` : ''}<div><b>${p.pets ? 'Yes' : 'No'}</b><span>Pets</span></div><div><b>${p.views}</b><span>Views</span></div></div>
      <div class="stack tight"><h2>About this home</h2><p style="white-space:pre-wrap">${esc(p.description)}</p></div>
      <div class="stack tight"><h2>Property overview</h2><div class="overview">${[['Listing number', 'AVA-' + String(p.id).padStart(6, '0')], ['Type of property', p.type], ['Available', p.available_from && p.available_from > new Date().toISOString().slice(0, 10) ? fdate(p.available_from) : 'Immediately'], ['Lease period', '12 months'], ['Rental', R(p.rent) + ' / month'], ['Deposit', R(p.deposit || p.rent)], ['Bedrooms', p.bedrooms], ['Bathrooms', p.bathrooms], ['Parking', p.parking], ['Floor size', p.size_m2 ? Math.round(p.size_m2) + ' m²' : '–'], ['Erf size', p.erf_size ? Math.round(p.erf_size).toLocaleString('en-ZA') + ' m²' : '–'], ['Pets allowed', p.pets ? 'Yes' : 'No'], ['Furnished', p.furnished ? 'Yes' : 'No'], ['Listed', p.published_at ? fdate(p.published_at) : '–']].map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join('')}</div></div>
      ${(p.features || []).length ? `<div class="stack tight"><h2>Features</h2><div class="feat">${p.features.map(f => `<span>${esc(f)}</span>`).join('')}</div></div>` : ''}
      ${panos.length ? `<div class="stack tight"><h2>Walk through it in 360°</h2><p class="muted">Captured with a 360° camera. Drag to look around; tap a room to move.</p><div class="pano" id="inlinepano" style="height:420px"></div></div>` : ''}
      <div class="stack tight"><h2>Location</h2><div id="lmap" style="height:300px;border-radius:12px;overflow:hidden"></div><p class="small muted">Exact address is shared when your viewing is confirmed.</p></div>
      <div class="card stack tight"><h3>${icon('shield')} Renting through AVA</h3><p class="small muted">Your deposit is held in an interest-bearing trust account and refunded with interest after a fair, photo-and-360° comparison of the ingoing and outgoing inspections (Rental Housing Act s5). Report problems in the app 24/7 and track every repair.</p></div>
      ${p.similar.length ? `<div class="stack tight"><h2>Similar homes</h2><div class="cards">${p.similar.map(lcard).join('')}</div></div>` : ''}
    </div>
    <aside class="sidecard"><div><div class="price" style="font:700 28px var(--f-ui)">${R(p.rent)} <small class="muted" style="font-size:14px;font-weight:500">/ month</small></div><span class="small muted">Deposit ${R(p.deposit)}</span></div>
      <details><summary class="small" style="cursor:pointer;font-weight:600">Move-in costs: ${R(p.move_in.total)}</summary><div class="costs" style="margin-top:8px">${p.move_in.lines.map(l => `<div><span>${esc(l.label)}</span><span class="num">${R(l.amount)}</span></div>`).join('')}<div class="tot"><span>Total</span><span class="num">${R(p.move_in.total)}</span></div></div></details>
      <div class="stack tight"><b>Book a viewing</b><div class="slots" id="slots"></div><button class="btn primary block" id="book" disabled>Choose a time</button></div>
      ${p.applied ? '<span class="pill ok" style="justify-content:center">You have applied ✓</span>' : `<button class="btn cta block lg" id="apply">Apply online</button>`}
      ${p.pm ? `<div class="row" style="border-top:1px solid var(--line);padding-top:12px"><span class="avatar">${esc(p.pm.name.split(' ').map(x => x[0]).join(''))}</span><div class="grow"><b>${esc(p.pm.name)}</b><div class="small muted">AVA portfolio manager · ${p.pm.managed} homes${p.pm.rating ? ' · ★ ' + p.pm.rating : ''}</div></div></div>` : ''}
    </aside></div></div>` + footer();
  const L = window.L;
  if (p.lat) {
    const m = L.map('lmap', { scrollWheelZoom: false }).setView([p.lat, p.lng], 14);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap' }).addTo(m);
    L.circle([p.lat, p.lng], { radius: 260, color: '#0e5e52', fillOpacity: .15 }).addTo(m);
    onLeave(() => m.remove());
  }
  $$('[data-ph]').forEach(b => b.onclick = e => { if (e.target.closest('[data-tour]')) return openTour(panos, p.title); photoViewer(photos, +b.dataset.ph); });
  if (panos.length) {
    const v = new PanoViewer($('#inlinepano')); onLeave(() => v.destroy());
    let i = 0; const show = () => { v.load(panos[i].url); $('#inlinepano .label')?.remove(); $('#inlinepano').insertAdjacentHTML('beforeend', `<span class="label">${esc(panos[i].room || 'Room ' + (i + 1))}</span>`); };
    $('#inlinepano').insertAdjacentHTML('beforeend', `<div class="hud"><button class="btn sm" data-prev>‹ Prev</button><button class="btn sm" data-next>Next room ›</button><span class="spacer"></span><button class="btn sm" data-full>${icon('pano')}Full screen tour</button></div>`);
    $('[data-prev]').onclick = () => { i = (i + panos.length - 1) % panos.length; show(); };
    $('[data-next]').onclick = () => { i = (i + 1) % panos.length; show(); };
    $('[data-full]').onclick = () => openTour(panos, p.title, i);
    show();
  }
  $('#save').onclick = async () => { if (!state.user) return go('#/login?next=' + encodeURIComponent(location.hash)); const r = await api.post('/api/favourites/' + id); $('#save').innerHTML = icon('heart') + (r.saved ? 'Saved' : 'Save'); toast(r.saved ? 'Saved to your favourites' : 'Removed'); };
  $('#share').onclick = () => { navigator.clipboard?.writeText(location.href); toast('Link copied'); };
  const slots = await api.get(`/api/listings/${id}/slots`);
  let chosen = null;
  $('#slots').innerHTML = slots.map(s => `<button ${s.free ? '' : 'disabled'} data-s="${s.slot}">${fslot(s.slot).replace(' · ', '<br>')}</button>`).join('');
  $$('#slots button').forEach(b => b.onclick = () => { chosen = b.dataset.s; $$('#slots button').forEach(x => x.setAttribute('aria-pressed', x === b)); $('#book').disabled = false; $('#book').textContent = 'Book ' + fslot(chosen); });
  $('#book').onclick = () => bookViewing(p, chosen);
  $('#apply')?.addEventListener('click', () => state.user ? applyModal(p) : go('#/login?next=' + encodeURIComponent(location.hash)));
  if (q.tour && panos.length) openTour(panos, p.title);
  if (q.apply && state.user && !p.applied) applyModal(p);
});

function photoViewer(photos, i) {
  const m = modal({ title: 'Photos', cls: 'wide', body: `<img id="pv" style="width:100%;border-radius:10px;max-height:70vh;object-fit:contain;background:#111"><div class="row"><button class="btn" data-p>‹</button><span class="spacer center" id="pc"></span><button class="btn" data-n>›</button></div>` });
  const show = () => { $('#pv', m).src = photos[i].url; $('#pc', m).textContent = `${i + 1} / ${photos.length}`; };
  $('[data-p]', m).onclick = () => { i = (i + photos.length - 1) % photos.length; show(); };
  $('[data-n]', m).onclick = () => { i = (i + 1) % photos.length; show(); };
  show();
}

export function openTour(panos, title, start = 0) {
  const m = modal({ title: `${title} · 360° tour`, cls: 'full tourmodal', body: `<div class="pano" id="tp"></div><div class="roomstrip">${panos.map((p, i) => `<button data-i="${i}" aria-pressed="${i === start}"><div style="background-image:url('${esc(p.url)}')"></div><span>${esc(p.room || p.caption || 'Room ' + (i + 1))}</span></button>`).join('')}</div>`,
    onClose: () => v.destroy() });
  const v = new PanoViewer($('#tp', m));
  const show = i => { v.load(panos[i].url); $$('.roomstrip button', m).forEach(b => b.setAttribute('aria-pressed', +b.dataset.i === i)); };
  $$('.roomstrip button', m).forEach(b => b.onclick = () => show(+b.dataset.i));
  show(start);
}

async function bookViewing(p, slot) {
  const u = state.user;
  const m = modal({ title: 'Book viewing', body: `<p><b>${esc(p.title)}</b><br><span class="muted">${fslot(slot)}</span></p>
    <form class="form" id="vf">${u ? '' : `<label class="field"><span>Name</span><input class="input" name="name" required></label><label class="field"><span>Email</span><input class="input" type="email" name="email" required></label>`}
    <label class="field"><span>Mobile</span><input class="input" name="phone" value="${esc(u?.phone || '')}" required></label><label class="field"><span>Anything we should know?</span><textarea class="input" name="notes" rows="2"></textarea></label></form>`,
    foot: `<button class="btn primary" id="vb">Confirm viewing</button>` });
  $('#vb', m).onclick = async () => {
    const f = $('#vf', m); if (!f.reportValidity()) return;
    const d = Object.fromEntries(new FormData(f)); d.property_id = p.id; d.slot = slot;
    const r = await act($('#vb', m), () => api.post('/api/viewings', d));
    m.close();
    modal({ title: 'Viewing confirmed ✓', body: `<p>See you on <b>${fslot(slot)}</b>.</p><p class="muted">We'll send a reminder the day before with the exact address and gate instructions.</p>
      <div class="row wrap"><a class="btn" target="_blank" href="https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lng}">${icon('map')}Directions</a>
      <a class="btn" download="viewing.ics" href="data:text/calendar,${encodeURIComponent(ics(p, slot))}">${icon('cal')}Add to calendar</a></div>
      <div class="ai-note">${icon('spark')}<span>Tip: bring your ID and 3 months' payslips – you can apply on the spot from your phone.</span></div>` });
  };
}
const ics = (p, s) => { const d = s.replace(/[-:]/g, '') + '00'; return `BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nDTSTART:${d}\nDURATION:PT30M\nSUMMARY:Viewing – ${p.title}\nLOCATION:${p.suburb}, ${p.city}\nEND:VEVENT\nEND:VCALENDAR`; };

function applyModal(p) {
  const u = state.user;
  const m = modal({ title: 'Apply for ' + p.title, cls: 'wide', body: `<form class="form" id="af">
    <div class="ai-note">${icon('spark')}<span>AVA checks affordability, credit and rental history in seconds. Upload clear PDFs or photos. Your information is processed under POPIA only for this application.</span></div>
    <div class="cols"><label class="field"><span>Full name</span><input class="input" name="name" value="${esc(u.name)}" required></label><label class="field"><span>Mobile</span><input class="input" name="phone" value="${esc(u.phone || '')}" required></label></div>
    <div class="cols"><label class="field"><span>Employer</span><input class="input" name="employer" required></label><label class="field"><span>Gross monthly income (R)</span><input class="input" name="income" type="number" min="0" required id="inc"></label><label class="field"><span>Other income (R)</span><input class="input" name="other_income" type="number" min="0" value="0"></label></div>
    <div id="aff" class="small"></div>
    <div class="cols"><label class="field"><span>Occupants</span><input class="input" name="occupants" type="number" min="1" value="1"></label><label class="field"><span>Move-in date</span><input class="input" name="move_in" type="date" value="${esc(p.available_from || '')}"></label><label class="check" style="align-self:end"><input type="checkbox" name="pets">I have pets</label></div>
    <div class="cols"><label class="field"><span>ID / passport</span><input class="input" type="file" name="id" accept="image/*,.pdf"></label><label class="field"><span>3 months' payslips</span><input class="input" type="file" name="payslips" multiple accept="image/*,.pdf"></label><label class="field"><span>3 months' bank statements</span><input class="input" type="file" name="bank_statements" multiple accept="image/*,.pdf"></label></div>
    <label class="field"><span>Message to the landlord</span><textarea class="input" name="message" rows="2" placeholder="A little about you"></textarea></label>
    <label class="check"><input type="checkbox" required> I consent to a credit and TPN rental-history check.</label></form>`,
    foot: `<button class="btn cta" id="ab">Submit application</button>` });
  $('#inc', m).oninput = e => { const v = +e.target.value; const r = v ? p.rent / v : 0; $('#aff', m).innerHTML = v ? `Rent would be <b>${Math.round(r * 100)}%</b> of income – ${r <= .3 ? '<span class="pill ok">comfortable</span>' : r <= .35 ? '<span class="pill warn">OK</span>' : '<span class="pill bad">stretched (guide ≤ 33%)</span>'}` : ''; };
  $('#ab', m).onclick = async () => {
    const f = $('#af', m); if (!f.reportValidity()) return;
    const fd = formData(f); fd.set('property_id', p.id);
    const r = await act($('#ab', m), () => api.post('/api/applications', fd));
    m.close();
    modal({ title: 'Application submitted', body: `<p>Thanks! Your AVA score is <b>${r.score}/100</b>.</p><ul>${r.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul><p class="muted">The landlord's portfolio manager has been notified. Track it under My AVA.</p>`, foot: '<a class="btn primary" href="#/app">Go to My AVA</a>' });
  };
}

// ------------------------------------------------------------------ landlords / pricing
route('/landlords', async () => {
  app().innerHTML = nav('landlords') + `<div class="wrap section stack loose">
    <div class="stack tight"><span class="pill brand" style="width:max-content">For property investors</span><h1>Your rental, run like a business – for a fraction of agent fees</h1>
    <p class="muted" style="max-width:720px">AVA replaces the services of an estate agent with an automated system that makes sure no step is missed: vetting, the lease, the deposit in trust, 360° inspections, rent collection, arrears, repairs and your monthly statement. A registered portfolio manager oversees it all.</p></div>
    <div class="grid2"><div class="card stack"><h3>What will it cost?</h3>
      <div class="form"><div class="cols"><label class="field"><span>Monthly rent (R)</span><input class="input" id="rent" type="number" value="20000"></label><label class="field"><span>Homes you manage on AVA</span><input class="input" id="homes" type="number" min="1" value="1"></label><label class="field"><span>Bedrooms</span><input class="input" id="beds" type="number" value="2"></label><label class="field"><span>Bathrooms</span><input class="input" id="baths" type="number" value="1"></label></div></div>
      <div id="calc"></div></div>
      <div class="card stack"><h3>Pricing</h3><div id="tiers"></div></div></div>
    <div class="steps"><div class="step"><h3>No steps missed</h3><p class="muted">A compliance checklist on every lease: vetting, signatures, deposit in an interest-bearing account, joint inspections, refund deadlines.</p></div>
      <div class="step"><h3>Approve in one tap</h3><p class="muted">${feat('maintenance') ? 'Repairs come to you with quotes from three rated companies within 10 km – compare price, rating and distance, and choose.' : 'Applications, leases, renewals and payouts come to you ready to approve – one tap and AVA does the rest.'} Emergencies under your limit are handled immediately.</p></div>
      <div class="step"><h3>Know your rights</h3><p class="muted">AVA Learn explains the Rental Housing Act, CPA and PIE Act in plain language, right where decisions are made.</p></div>
      <div class="step"><h3>Real statements</h3><p class="muted">Monthly owner statements with every rand traced: rent in, fees, repairs, payout. Exports to Excel for your tax return.</p></div></div>
    <div class="row wrap"><a class="btn cta lg" href="#/register?role=landlord">List my property</a><a class="btn lg" href="#/earn">${icon('chart')}What could my home earn?</a><a class="btn lg" href="#/explore">Run the yield numbers</a></div></div>` + footer();
  const upd = async () => {
    const f = await api.get(`/api/fees/public?rent=${+$('#rent').value || 0}&homes=${Math.max(1, +$('#homes').value || 1)}&bedrooms=${+$('#beds').value || 1}&bathrooms=${+$('#baths').value || 1}`);
    $('#calc').innerHTML = compareBox(f, +$('#rent').value) + `<div class="costs" style="margin-top:12px">${f.landlord.lines.map(l => `<div><span>${esc(l.label)}</span><span class="num">${R(l.amount)}</span></div>`).join('')}<div class="tot"><span>Monthly management cost</span><span class="num">${R(f.landlord.total)} (${f.landlord.pct_of_rent}% of rent)</span></div>
      <div class="muted"><span>Optional rental insurance</span><span class="num">${R(f.insurance)} / month</span></div>
      <div><span>Once-off admin fee (new lease)</span><span class="num">${R(f.admin_fee)}</span></div><div><span>Inspections (your 50%)</span><span class="num">${R(f.inspection_fee / 2)}</span></div></div>`;
    $('#tiers').innerHTML = `<table class="t"><tr><th>Homes you manage on AVA</th><th class="num">Platform fee per home / month</th></tr>${f.tiers.map((t, i) => `<tr style="${f.homes <= t[0] && (i === 0 || f.homes > f.tiers[i - 1][0]) ? 'background:var(--brand-tint);font-weight:700' : ''}"><td>${i ? f.tiers[i - 1][0] + 1 : 1}${t[0] > 9999 ? '+' : '–' + t[0]}</td><td class="num">${R(t[1])}</td></tr>`).join('')}</table>
      <p class="small muted">The more homes you manage on AVA, the lower the fee on every one of them. Portfolio-manager commission is 3–5% of rent collected. No admin fee on renewals.</p>`;
  };
  $$('#rent,#homes,#beds,#baths').forEach(i => i.oninput = upd); upd();
});

route('/agents', async () => {
  app().innerHTML = nav('agents') + `<div class="wrap section stack loose">
    <div class="stack tight"><span class="pill jac" style="width:max-content">Start your own digital agency</span><h1>Manage 150 homes on your own</h1>
    <p class="muted" style="max-width:720px">AVA portfolio managers run their own book with almost no start-up cost. Autopilot does the admin – rent matching, arrears letters, quote requests, renewals, inspection bookings – and only shows you the exceptions.</p></div>
    <div class="grid3"><div class="kpi"><span>Commission</span><b>3–5%</b><small>of rent collected, rising with the size of your book</small></div><div class="kpi"><span>Finder's fee</span><b>R50</b><small>per rented listing, per month</small></div><div class="kpi"><span>Basic salary (first year)</span><b>R10 000</b><small>while you build your book to 70 rentals</small></div><div class="kpi"><span>Equity incentive</span><b>R100 000</b><small>in shares at 150 homes, 4.5★ and 95% tenants in good standing</small></div></div>
    <div class="card"><h3>Commission tiers</h3><table class="t" style="margin-top:8px"><tr><th>Homes under management</th><th class="num">Commission</th></tr><tr><td>First 20</td><td class="num">3%</td></tr><tr><td>21 – 50</td><td class="num">4%</td></tr><tr><td>More than 50</td><td class="num">5%</td></tr></table></div>
    <div class="grid2" style="align-items:start"><form class="card form" id="pmc"><h3>What will you earn?</h3>
      <label class="field"><span>Homes you manage: <b id="hv">40</b></span><input type="range" min="5" max="200" step="1" value="40" name="homes"></label>
      <label class="field"><span>Of which let: <b id="lv">95</b>%</span><input type="range" min="50" max="100" step="1" value="95" name="occ"></label>
      <label class="field"><span>Average rent (R/month)</span><input class="input" type="number" name="rent" value="20000" step="500" min="15000" max="30000"></label>
      <p class="tiny muted">AVA homes rent for R15 000 – R30 000 a month.</p></form>
      <div class="card stack" id="pmr"></div></div>
    <div class="row"><a class="btn cta lg" href="#/register?role=pm">Apply as a portfolio manager</a></div></div>` + footer();
  const fee = await api.get('/api/fees/public?rent=20000');
  const tiers = fee.pm_tiers || [[20, 3], [50, 4], [999999, 5]];
  const calc = () => {
    const f = Object.fromEntries([...new FormData($('#pmc'))].map(([k, v]) => [k, +v]));
    $('#hv').textContent = f.homes; $('#lv').textContent = f.occ;
    const rent = Math.min(30000, Math.max(15000, f.rent || 20000));
    const pct = (tiers.find(([upto]) => f.homes <= upto) || tiers[tiers.length - 1])[1];
    const let_ = Math.round(f.homes * f.occ / 100);
    const com = Math.round(let_ * rent * pct / 100), ff = let_ * 50, month = com + ff;
    $('#pmr').innerHTML = `<h3>Your monthly income</h3><div class="costs">
        <div><span>Homes let</span><span>${let_} of ${f.homes}</span></div>
        <div><span>Rent collected</span><span>${R(let_ * rent)}</span></div>
        <div><span>Commission (${pct}% tier)</span><span>${R(com)}</span></div>
        <div><span>Finder's fees (R50 × ${let_})</span><span>${R(ff)}</span></div>
        <div class="tot"><span>Per month</span><b>${R(month)}</b></div><div><span>Per year</span><b>${R(month * 12)}</b></div></div>
      <p class="small muted">Per home that's ${R(Math.round(rent * pct / 100) + 50)} a month. The ${pct}% rate applies to your whole book once you manage ${pct === tiers[0][1] ? 'up to ' + tiers[0][0] : pct === tiers[1][1] ? 'more than ' + tiers[0][0] : 'more than ' + tiers[1][0]} homes.</p>`;
  };
  $('#pmc').oninput = calc; calc();
});

// investor calculator (AVA Explore)
route('/explore', async () => {
  app().innerHTML = nav('explore') + `<div class="wrap section stack loose"><div class="stack tight"><span class="pill brand" style="width:max-content">AVA Explore</span><h1>Is it a good buy-to-let?</h1><p class="muted">Gross and net yield, bond repayment and monthly cash flow – using AVA's fees instead of an agent's.</p></div>
    <div class="grid2"><form class="card form" id="ex">
      <div class="cols"><label class="field"><span>Purchase price (R)</span><input class="input" name="price" type="number" value="2650000"></label><label class="field"><span>Deposit (R)</span><input class="input" name="dep" type="number" value="165000"></label></div>
      <div class="cols"><label class="field"><span>Interest rate (%)</span><input class="input" name="rate" type="number" step="0.05" value="10.75"></label><label class="field"><span>Term (years)</span><input class="input" name="years" type="number" value="20"></label></div>
      <div class="cols"><label class="field"><span>Expected rent (R/month)</span><input class="input" name="rent" type="number" value="20000"></label><label class="field"><span>Levies + rates (R/month)</span><input class="input" name="levies" type="number" value="2300"></label></div>
      <div class="cols"><label class="field"><span>Maintenance (% of rent)</span><input class="input" name="maint" type="number" value="5"></label><label class="field"><span>Vacancy (months / year)</span><input class="input" name="vac" type="number" step="0.5" value="0.5"></label></div></form>
      <div class="card stack" id="exr"></div></div></div>` + footer();
  const calc = async () => {
    const f = Object.fromEntries([...new FormData($('#ex'))].map(([k, v]) => [k, +v]));
    const fee = await api.get(`/api/fees/public?rent=${f.rent}`);
    const loan = f.price - f.dep, r = f.rate / 1200, n = f.years * 12;
    const bond = r ? loan * r / (1 - Math.pow(1 + r, -n)) : loan / n;
    const eff = f.rent * (12 - f.vac) / 12;
    const ava = fee.landlord.total, agent = fee.compare.traditional_monthly;
    const net = eff - f.levies - eff * f.maint / 100 - ava;
    const cf = net - bond;
    $('#exr').innerHTML = `<div class="kpis"><div class="kpi"><span>Gross yield</span><b>${(f.rent * 12 / f.price * 100).toFixed(1)}%</b></div><div class="kpi"><span>Net yield (before bond)</span><b>${(net * 12 / f.price * 100).toFixed(1)}%</b></div>
      <div class="kpi"><span>Bond repayment</span><b>${R(bond)}</b></div><div class="kpi ${cf < 0 ? 'alert' : 'good'}"><span>Monthly cash flow</span><b>${R(cf)}</b></div></div>
      <div class="costs"><div><span>Effective rent (after vacancy)</span><span class="num">${R(eff)}</span></div><div><span>Levies + rates</span><span class="num">−${R(f.levies)}</span></div><div><span>Maintenance allowance</span><span class="num">−${R(eff * f.maint / 100)}</span></div>
      <div><span>AVA fees</span><span class="num">−${R(ava)}</span></div><div><span>Bond</span><span class="num">−${R(bond)}</span></div><div class="tot"><span>Cash flow</span><span class="num">${R(cf)}</span></div></div>
      <div class="ai-note">${icon('spark')}<span>With a traditional agent at 10% + VAT you would pay ${R(agent)} a month instead of ${R(ava)} – ${R((agent - ava) * 12)} a year more. ${cf < 0 ? 'The property costs you money each month; a bigger deposit or higher rent would be needed for it to wash its face.' : 'The property pays for itself.'}</span></div>`;
  };
  $('#ex').oninput = calc; calc();
});

// ------------------------------------------------------------------ auth
route('/login', async (_, q) => {
  if (state.user) return go(q.next && q.next.startsWith('#/') ? q.next : '#/app');   // already signed in
  app().innerHTML = nav() + `<div class="wrap" style="max-width:440px;padding-top:40px;padding-bottom:60px"><div class="card stack"><h1>Welcome back</h1>
    <form class="form" id="lf"><label class="field"><span>Email</span><input class="input" type="email" name="email" autocomplete="username" required></label>
    <label class="field"><span>Password</span><input class="input" type="password" name="password" autocomplete="current-password" required></label><button class="btn primary lg">Sign in</button></form>
    <p class="small muted">New here? <a href="#/register">Create a free account</a></p>
    <details class="small"><summary style="cursor:pointer">Demo accounts (password <span class="mono">demo1234</span>)</summary><div class="stack tight" style="margin-top:8px">
      ${[['thandi@ava.co.za', 'Portfolio manager'], ['emgee@example.co.za', 'Landlord'], ['lerato@example.com', 'Tenant (moving out)'], ['johan@example.com', 'Tenant'], ['plumbfix@example.co.za', 'Contractor'], ['admin@ava.co.za', 'AVA admin']]
      .map(([e, r]) => `<button class="btn sm" data-demo="${e}" style="justify-content:space-between"><span>${r}</span><span class="mono muted">${e}</span></button>`).join('')}</div></details></div></div>`;
  const login = async (email, password) => {
    await api.post('/api/auth/login', { email, password }); await refreshMe();
    go(q.next ? decodeURIComponent(q.next) : '#/app');
  };
  $('#lf').onsubmit = e => { e.preventDefault(); const d = Object.fromEntries(new FormData(e.target)); act($('#lf button'), () => login(d.email, d.password)); };
  $$('[data-demo]').forEach(b => b.onclick = () => act(b, () => login(b.dataset.demo, 'demo1234')));
});

route('/register', async (_, q) => {
  const roles = [['tenant', 'I want to rent'], ['landlord', 'I own property'], ['pm', 'I want to be a portfolio manager'], ...(feat('maintenance') ? [['contractor', "I'm a contractor"]] : [])];
  app().innerHTML = nav() + `<div class="wrap" style="max-width:520px;padding-top:40px;padding-bottom:60px"><div class="card stack"><h1>Join AVA</h1>
    <form class="form" id="rf"><div class="seg" id="rs">${roles.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${(q.role || 'tenant') === v}">${l}</button>`).join('')}</div>
    <input type="hidden" name="role" value="${esc(q.role || 'tenant')}">
    <div class="cols"><label class="field"><span>Full name</span><input class="input" name="name" required></label><label class="field"><span>Mobile</span><input class="input" name="phone"></label></div>
    <label class="field"><span>Email</span><input class="input" type="email" name="email" required></label>
    <label class="field"><span>Password</span><input class="input" type="password" name="password" minlength="6" required></label>
    <div id="extra"></div>
    <label class="check small"><input type="checkbox" required>I accept the terms and the <a href="#/privacy-notice" target="_blank">privacy notice</a>.</label><label class="check small"><input type="checkbox" name="marketing" value="1">Send me news and offers by email or SMS (optional – you can stop any time).</label><button class="btn cta lg">Create account</button></form></div></div>`;
  const extra = () => {
    const r = $('[name=role]').value;
    $('#extra').innerHTML = r === 'contractor' ? `<label class="field"><span>Company</span><input class="input" name="company" required></label><label class="field"><span>Trades (comma separated)</span><input class="input" name="trades" placeholder="Plumber, Electrician"></label><label class="field"><span>Areas</span><input class="input" name="areas" placeholder="Pretoria, Centurion"></label><p class="small muted">Maintenance companies list for R250/month (first 30 days free) and get repair requests within 10 km. <a href="#/pros/join#signup">Use the full company sign-up to set your base on the map →</a></p>`
      : r === 'landlord' || r === 'pm' ? `<label class="field"><span>Company (optional)</span><input class="input" name="company"></label>` : '';
  };
  $$('#rs button').forEach(b => b.onclick = () => { $$('#rs button').forEach(x => x.setAttribute('aria-pressed', x === b)); $('[name=role]').value = b.dataset.v; extra(); });
  extra();
  $('#rf').onsubmit = e => { e.preventDefault(); act($('#rf .btn.cta'), async () => { await api.post('/api/auth/register', Object.fromEntries(new FormData(e.target))); await refreshMe(); go('#/app'); }, 'Welcome to AVA!'); };
});
