// Signed-in workspace: side navigation (desktop), bottom tabs (phone), top bar, notifications, AVA Assist.
import { $, $$, api, esc, go, icon, initials, LOGO, modal, state, ago, toast, refreshMe } from './core.js';

const NAV = {
  pm: [['Today', [['', 'Command centre', 'bolt'], ['inbox', 'Inbox', 'chat'], ['ai', 'AI & virtual agent', 'spark']]],
       ['Portfolio', [['properties', 'Properties', 'building'], ['leasing', 'Leasing', 'key'], ['leases', 'Leases', 'doc'], ['money', 'Money', 'money']]],
       ['Operations', [['maintenance', 'Maintenance', 'tool'], ['inspections', 'Inspections', 'pano'], ['snags', 'Snag lists', 'clip'], ['contractors', 'Contractors', 'users']]],
       ['Business', [['reports', 'Reports', 'chart'], ['earnings', 'My earnings', 'star'], ['settings', 'Settings', 'cog']]]],
  landlord: [['', [['', 'Overview', 'home'], ['properties', 'My properties', 'building'], ['maintenance', 'Repairs & approvals', 'tool'], ['money', 'Statements', 'money'],
       ['inspections', 'Inspections', 'pano'], ['inbox', 'Messages', 'chat'], ['learn', 'AVA Learn', 'learn']]]],
  tenant: [['', [['', 'Home', 'home'], ['pay', 'Pay rent', 'money'], ['maintenance', 'Repairs', 'tool'], ['lease', 'My lease', 'doc'], ['inspections', 'Inspections', 'pano'],
       ['inbox', 'Messages', 'chat'], ['saved', 'Saved & alerts', 'heart'], ['learn', 'Know your rights', 'learn']]]],
  contractor: [['', [['', 'My jobs', 'tool'], ['jobs', 'Browse jobs', 'map'], ['snags', 'Snags', 'clip'], ['profile', 'Profile', 'users']]]],
  admin: [['AVA', [['', 'Command centre', 'bolt'], ['ai', 'AI & virtual agent', 'spark'], ['users', 'Users', 'users'], ['reviews', 'Reviews', 'star'], ['settings', 'Settings & fees', 'cog']]],
       ['Portfolio', [['properties', 'Properties', 'building'], ['leasing', 'Leasing', 'key'], ['leases', 'Leases', 'doc'], ['money', 'Money', 'money'], ['earnings', 'Revenue', 'chart']]],
       ['Operations', [['maintenance', 'Maintenance', 'tool'], ['inspections', 'Inspections', 'pano'], ['snags', 'Snag lists', 'clip'], ['contractors', 'Contractors', 'users'], ['inbox', 'Inbox', 'chat'], ['reports', 'Reports', 'excel']]]],
};
const BOTTOM = {
  pm: [['', 'Today', 'bolt'], ['maintenance', 'Repairs', 'tool'], ['inspections', 'Inspect', 'pano'], ['money', 'Money', 'money'], ['more', 'More', 'grid']],
  admin: [['', 'Today', 'bolt'], ['maintenance', 'Repairs', 'tool'], ['inspections', 'Inspect', 'pano'], ['money', 'Money', 'money'], ['more', 'More', 'grid']],
  landlord: [['', 'Home', 'home'], ['properties', 'Homes', 'building'], ['maintenance', 'Repairs', 'tool'], ['money', 'Money', 'money'], ['more', 'More', 'grid']],
  tenant: [['', 'Home', 'home'], ['pay', 'Pay', 'money'], ['maintenance', 'Repairs', 'tool'], ['inbox', 'Chat', 'chat'], ['more', 'More', 'grid']],
  contractor: [['', 'My jobs', 'tool'], ['jobs', 'Browse jobs', 'map'], ['snags', 'Snags', 'clip'], ['profile', 'Profile', 'users']],
};

export function page(title, { back, actions = '', sub = '' } = {}) {
  const u = state.user;
  const cur = (location.hash.match(/^#\/app\/?([^/?]*)/) || [])[1] || '';
  if (!$('.shell')) {
    $('#app').innerHTML = `<div class="shell"><aside class="side" id="side"></aside><div class="main"><div class="topbar" id="topbar"></div><main class="page" id="page"></main></div></div>
      <nav class="bottomnav" id="bottom"></nav>`;
  }
  document.body.classList.toggle('pro', u.role === 'contractor');   // maintenance companies: no rental portal, no rental assistant
  $('#side').innerHTML = `<a class="logo" href="${u.role === 'contractor' ? '#/app' : '#/'}">${LOGO}</a>` + NAV[u.role].map(([g, items]) => (g ? `<div class="grp">${g}</div>` : '') +
    items.map(([k, l, ic]) => `<a href="#/app${k ? '/' + k : ''}" class="${cur === k ? 'on' : ''}">${icon(ic)}${l}</a>`).join('')).join('') +
    (u.role === 'contractor' ? '' : `<a href="#/search">${icon('search')}Browse listings</a>`) + `
    <div class="me"><span class="avatar">${initials(u.name)}</span><div style="min-width:0;flex:1"><b style="color:#fff;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(u.name)}</b><span>${{ pm: 'Portfolio manager', admin: 'AVA admin', landlord: 'Landlord', tenant: 'Tenant', contractor: 'Maintenance company' }[u.role]}</span></div>
    <button class="iconbtn" id="logout" title="Sign out" style="color:#c9d6d2">${icon('logout')}</button></div>`;
  $('#bottom').innerHTML = BOTTOM[u.role].map(([k, l, ic]) => `<a href="#/app${k ? '/' + k : ''}" class="${cur === k ? 'on' : ''}">${icon(ic)}${l}</a>`).join('');
  $('#topbar').innerHTML = `${back ? `<a class="iconbtn back" href="${back}" aria-label="Back">${icon('back')}</a>` : ''}<h1>${esc(title)}${sub ? ` <span class="muted small" style="font-family:var(--f-ui);font-weight:500">${sub}</span>` : ''}</h1>
    <div class="row noprint">${actions}</div><button class="iconbtn noprint" id="bell" aria-label="Notifications">${icon('bell')}${state.unread ? `<span class="badge">${state.unread}</span>` : ''}</button>`;
  $('#logout').onclick = async () => { await api.post('/api/auth/logout'); state.user = null; location.hash = '#/'; location.reload(); };
  $('#bell').onclick = notifications;
  const pg = $('#page'); pg.innerHTML = '<p class="muted">Loading…</p>';
  return pg;
}

export function moreMenu() {
  const u = state.user;
  const pg = page('More');
  pg.innerHTML = `<div class="card flush list">${NAV[u.role].flatMap(([, items]) => items).map(([k, l, ic]) => `<a class="li" href="#/app${k ? '/' + k : ''}">${icon(ic)}<span class="grow">${l}</span></a>`).join('')}
    ${state.user.role === 'contractor' ? `<a class="li" href="#/app/jobs">${icon('map')}<span class="grow">Browse jobs</span></a>` : `<a class="li" href="#/search">${icon('search')}<span class="grow">Browse listings</span></a>`}<button class="li" id="lo">${icon('logout')}<span class="grow">Sign out</span></button></div>`;
  $('#lo').onclick = async () => { await api.post('/api/auth/logout'); location.hash = '#/'; location.reload(); };
}

async function notifications() {
  const rows = await api.get('/api/notifications');
  const m = modal({ title: 'Notifications', body: rows.length ? `<div class="list" style="margin:-20px">${rows.map(n => `<a class="li" href="${esc(n.link || '#/app')}" ${n.read ? '' : 'style="background:var(--brand-tint)"'}>
      <span class="grow"><b class="title">${esc(n.title)}</b><span class="small muted">${esc(n.body || '')}</span></span><span class="tiny faint nowrap">${ago(n.created_at)}</span></a>`).join('')}</div>`
    : '<div class="empty">Nothing new.</div>' });
  $$('a', m).forEach(a => a.addEventListener('click', () => m.close()));
  await api.post('/api/notifications/read'); state.unread = 0; $('#bell .badge')?.remove();
}

