/* Constellarium front-end. State lives in the local store (%APPDATA%/Constellarium/store.json); UI re-renders from /api/data. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STATUSES = ['new', 'exploring', 'in-progress', 'done', 'shelved'];

let S = { categories: [], projects: [], ideas: [] };
let F = { q: '', cat: null, project: null, status: '', tag: '' };
let view = 'graph';
let graph = null;
let editing = null; // idea id being edited

async function api(method, url, body) {
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let j = {};
  try { j = text ? JSON.parse(text) : {}; } catch (e) { throw new Error(`bad response (${r.status}): ${text.slice(0, 120)}`); }
  if (r.status === 401 && j.login) openLogin();   // session missing/expired
  if (!r.ok) { const err = new Error(j.error || r.statusText); err.status = r.status; throw err; }
  return j;
}
function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
async function reload() { S = await api('GET', '/api/data'); renderAll(); }

/* ---------- derived data ---------- */
const catById = () => new Map(S.categories.map(c => [c.id, c]));
const projById = () => new Map(S.projects.map(p => [p.id, p]));
function childrenOf(pid) { return S.categories.filter(c => (c.parent || null) === pid).sort((a, b) => a.name.localeCompare(b.name)); }
function subtreeIds(id) {
  const out = new Set([id]); const stack = [id];
  while (stack.length) { const x = stack.pop(); for (const c of S.categories) if (c.parent === x && !out.has(c.id)) { out.add(c.id); stack.push(c.id); } }
  return out;
}
function catPath(id) {
  const m = catById(); const parts = []; let c = m.get(id), guard = 0;
  while (c && guard++ < 20) { parts.unshift(c.name); c = m.get(c.parent); }
  return parts.join(' › ');
}
function filteredIdeas(ignore = {}) {
  const f = { ...F, ...ignore };
  const none = f.cat === '__none';
  const sub = f.cat && !none ? subtreeIds(f.cat) : null;
  const q = f.q.trim().toLowerCase();
  return S.ideas.filter(i => {
    if (none && i.category) return false;
    if (sub && !sub.has(i.category)) return false;
    if (f.project && !(i.projects || []).includes(f.project)) return false;
    if (f.status && i.status !== f.status) return false;
    if (f.tag && !(i.tags || []).includes(f.tag)) return false;
    if (q) {
      const hay = [i.title, i.description, i.author, i.primaryContact, i.secondaryContact, i.source, (i.tags || []).join(' '), catPath(i.category)].join(' ').toLowerCase();
      if (!q.split(/\s+/).every(w => hay.includes(w))) return false;
    }
    return true;
  });
}
const anyFilter = () => F.q || F.cat || F.project || F.status || F.tag;

/* ---------- sidebar ---------- */
function renderSidebar() {
  const ideas = S.ideas;
  const orphans = ideas.filter(i => !(i.projects || []).length).length;
  $('#stats').innerHTML = [[ideas.length, 'ideas'], [S.categories.length, 'categories'], [S.projects.length, 'projects'], [orphans, 'not linked to a project']]
    .map(([n, l]) => `<div class="stat"><b>${n}</b><span>${l}</span></div>`).join('');

  const counts = new Map();
  for (const i of ideas) if (i.category) counts.set(i.category, (counts.get(i.category) || 0) + 1);
  const total = id => { let n = 0; for (const x of subtreeIds(id)) n += counts.get(x) || 0; return n; };
  const row = (c, depth) => {
    const kids = childrenOf(c.id);
    return `<div class="node ${F.cat === c.id ? 'sel' : ''}" data-cat="${c.id}" style="padding-left:${6 + depth * 14}px">
      <span class="dot" style="background:${esc(c.color)}"></span><span>${esc(c.name)}</span><span class="cnt">${total(c.id)}</span></div>` + kids.map(k => row(k, depth + 1)).join('');
  };
  const uncat = ideas.filter(i => !i.category).length;
  $('#catTree').innerHTML = (childrenOf(null).map(c => row(c, 0)).join('') || '<span class="muted small">No categories yet</span>')
    + (uncat ? `<div class="node ${F.cat === '__none' ? 'sel' : ''}" data-cat="__none"><span class="dot" style="background:#999"></span><span>Uncategorised</span><span class="cnt">${uncat}</span></div>` : '');

  const pc = new Map(); for (const i of ideas) for (const p of i.projects || []) pc.set(p, (pc.get(p) || 0) + 1);
  $('#projList').innerHTML = S.projects.slice().sort((a, b) => (pc.get(b.id) || 0) - (pc.get(a.id) || 0)).map(p =>
    `<span class="chip ${F.project === p.id ? 'sel' : ''}" data-proj="${p.id}"><span class="dot" style="background:${esc(p.color)}"></span>${esc(p.name)}<span class="cnt">${pc.get(p.id) || 0}</span></span>`).join('') || '<span class="muted small">No projects yet</span>';

  const sc = new Map(); for (const i of ideas) sc.set(i.status, (sc.get(i.status) || 0) + 1);
  $('#statusList').innerHTML = STATUSES.filter(s => sc.get(s)).map(s => `<span class="chip ${F.status === s ? 'sel' : ''}" data-status="${s}">${s} <span class="cnt">${sc.get(s)}</span></span>`).join('') || '<span class="muted small">—</span>';

  const tc = new Map(); for (const i of ideas) for (const t of i.tags || []) tc.set(t, (tc.get(t) || 0) + 1);
  const tags = [...tc.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40);
  $('#tagList').innerHTML = tags.map(([t, n]) => `<span class="chip ${F.tag === t ? 'sel' : ''}" data-tag="${esc(t)}">#${esc(t)} <span class="cnt">${n}</span></span>`).join('') || '<span class="muted small">—</span>';
}
function toggleFilter(key, val) { F[key] = F[key] === val ? (key === 'status' || key === 'tag' ? '' : null) : val; renderAll(); }

/* ---------- graph ---------- */
const NODE_CAT_COLOR = '#8a93a6';
function buildGraph() {
  const mode = $('#gMode').value, showIdeas = $('#gIdeas').checked, showTags = $('#gTags').checked, showRel = $('#gRelated').checked;
  const cats = catById(), projs = projById();
  const ideas = filteredIdeas();
  const ideaSet = new Set(ideas.map(i => i.id));
  const nodes = [], links = [];
  const catCount = new Map(), projCount = new Map();
  for (const i of ideas) { if (i.category) catCount.set(i.category, (catCount.get(i.category) || 0) + 1); for (const p of i.projects || []) projCount.set(p, (projCount.get(p) || 0) + 1); }

  // which categories to show: ones with ideas + their ancestors (keeps the tree connected)
  const keepCat = new Set();
  const addAnc = id => { let c = cats.get(id), g = 0; while (c && g++ < 20) { keepCat.add(c.id); c = cats.get(c.parent); } };
  if (!anyFilter()) S.categories.forEach(c => keepCat.add(c.id)); else for (const id of catCount.keys()) addAnc(id);
  if (F.cat && cats.has(F.cat)) addAnc(F.cat);

  for (const c of S.categories) if (keepCat.has(c.id)) {
    const n = catCount.get(c.id) || 0;
    if (mode === 'map' && !n) continue; // map view = only categories that actually hold ideas
    nodes.push({ id: 'c:' + c.id, type: 'category', label: c.name, color: c.color, r: 12 + Math.sqrt(n) * 3, data: c, count: n });
    if (c.parent && keepCat.has(c.parent)) links.push({ source: 'c:' + c.parent, target: 'c:' + c.id, kind: 'tree' });
  }
  for (const p of S.projects) {
    if (anyFilter() && !projCount.has(p.id) && F.project !== p.id) continue;
    const n = projCount.get(p.id) || 0;
    nodes.push({ id: 'p:' + p.id, type: 'project', label: p.name, color: p.color, r: 11 + Math.sqrt(n) * 3, data: p, count: n });
  }

  if (mode === 'map') {
    const w = new Map();
    for (const i of ideas) for (const p of i.projects || []) if (i.category) { const k = i.category + '|' + p; w.set(k, (w.get(k) || 0) + 1); }
    for (const [k, n] of w) { const [c, p] = k.split('|'); links.push({ source: 'c:' + c, target: 'p:' + p, kind: 'map', w: n }); }
  } else if (showIdeas) {
    const tagNodes = new Set();
    for (const i of ideas) {
      const c = cats.get(i.category);
      nodes.push({ id: 'i:' + i.id, type: 'idea', label: i.title, color: c ? c.color : NODE_CAT_COLOR, r: 6, ring: !(i.projects || []).length, data: i });
      if (c) links.push({ source: 'i:' + i.id, target: 'c:' + c.id, kind: 'cat' });
      for (const p of i.projects || []) if (projs.has(p)) links.push({ source: 'i:' + i.id, target: 'p:' + p, kind: 'proj' });
      if (showRel) for (const r of i.related || []) if (ideaSet.has(r) && i.id < r) links.push({ source: 'i:' + i.id, target: 'i:' + r, kind: 'related' });
      if (showTags) for (const t of i.tags || []) {
        if (!tagNodes.has(t)) { tagNodes.add(t); nodes.push({ id: 't:' + t, type: 'tag', label: '#' + t, color: '#9aa3b5', r: 4, data: { tag: t } }); }
        links.push({ source: 'i:' + i.id, target: 't:' + t, kind: 'tag' });
      }
    }
  }
  return { nodes, links, ideas };
}
const isGraphMode = () => !['board', 'treemap'].includes($('#gMode').value);   // board + treemap are HTML layouts, not the canvas graph

function renderGraph() {
  const mode = $('#gMode').value;
  const isBoard = mode === 'board' || mode === 'treemap';
  $('#zoomCtl').hidden = mode === 'treemap';           // the treemap zooms by clicking / scrolling into blocks
  $('#board').classList.toggle('tm', mode === 'treemap');
  $('.graph-wrap').classList.toggle('boardmode', isBoard);
  if (!isBoard) $('#detail').classList.remove('dock-left');
  $('#board').hidden = !isBoard; $('#graph').hidden = isBoard; $('#legend').hidden = isBoard;
  $$('.gx').forEach(el => (el.hidden = isBoard));
  const { nodes, links } = isBoard ? { nodes: [], links: [] } : buildGraph();
  const empty = $('#graphEmpty');
  if (!S.ideas.length) {
    empty.hidden = false;
    empty.innerHTML = `<h3 style="margin:0;color:var(--text)">Your Constellarium is empty</h3><div>Import your team's ideas (CSV / JSON) or add the first one.</div>
      <div class="row-btns"><button class="primary" id="emptyImport">Import ideas</button><button class="ghost" id="emptyNew">+ New idea</button><button class="ghost" id="emptySample">Load sample data</button></div>`;
    $('#emptyImport').onclick = openImport; $('#emptyNew').onclick = () => openIdea(); $('#emptySample').onclick = loadSample;
  } else if (isBoard) empty.hidden = true;
  else if (!nodes.length) { empty.hidden = false; empty.innerHTML = '<div>No ideas match the current filters.</div>'; }
  else empty.hidden = true;
  if (isBoard) {
    if (S.ideas.length) { if (mode === 'treemap') renderTreemap(); else renderBoard(); }
    $('#graphHint').textContent = mode === 'treemap'
      ? 'click a block (or scroll up) to zoom in · scroll down, Esc or the path on top to zoom out · click a readable tile for details · double-click to edit'
      : 'hover a table or idea to trace its links · click for details · double-click an idea to edit · click a project row to filter';
    return;
  }
  if (!graph) graph = new Graph($('#graph'), { onSelect: showDetail, onHover: showTip, onDouble: n => { if (n.type === 'idea') openIdea(n.data.id); } });
  graph.setData(nodes, links);
  renderLegend();
  $('#graphHint').textContent = 'scroll to zoom · drag to pan/move · click a node for details · double-click an idea to edit';
  if (graph.selected) { const n = graph.byId.get(graph.selected); if (n) showDetail(n); else $('#detail').hidden = true; } else $('#detail').hidden = true;
}
function renderLegend() {
  const mode = $('#gMode').value;
  $('#legend').innerHTML = `<div><i style="background:#8a93a6;border-radius:4px"></i>Category</div><div><i style="background:#8a93a6;transform:rotate(45deg) scale(.85)"></i>Project</div>`
    + (mode === 'map' ? '<div class="muted">Line thickness = number of shared ideas</div>' :
      `<div><i style="background:#8a93a6;border-radius:50%"></i>Idea (colour = category)</div><div><i style="border:2px dashed #8a93a6;border-radius:50%"></i>Idea not linked to a project</div>`);
}
function showTip(n, px, py) {
  const t = $('#tooltip');
  if (!n) { t.hidden = true; return; }
  const kind = { category: 'Category', project: 'Project', idea: 'Idea', tag: 'Tag' }[n.type];
  t.innerHTML = `<b>${esc(n.label)}</b><br><span class="muted">${kind}${n.count !== undefined ? ' · ' + n.count + ' idea' + (n.count === 1 ? '' : 's') : ''}${n.type === 'idea' ? ' · ' + esc(n.data.status) : ''}</span>`;
  t.hidden = false; t.style.left = Math.min(px + 14, $('.graph-wrap').clientWidth - 290) + 'px'; t.style.top = (py + 14) + 'px';
}
function showDetail(n) {
  const d = $('#detail');
  if (!n) { d.hidden = true; return; }
  const cats = catById(), projs = projById();
  const ideaLi = i => `<li data-idea="${i.id}"><span class="dot" style="background:${esc((cats.get(i.category) || {}).color || '#999')}"></span>${esc(i.title)}</li>`;
  let h = `<button class="close" id="dClose">×</button>`;
  if (n.type === 'idea') {
    const i = n.data, c = cats.get(i.category);
    h += `<div class="kind">Idea · ${esc(i.status)}</div><h3>${esc(i.title)}</h3><p>${esc(i.description || '—').replace(/\n/g, '<br>')}</p>
      <div class="sec"><b>Category</b>${c ? `<span class="chip" data-gocat="${c.id}"><span class="dot" style="background:${esc(c.color)}"></span>${esc(catPath(c.id))}</span>` : '<span class="muted">none</span>'}</div>
      <div class="sec"><b>Projects</b>${(i.projects || []).map(p => projs.get(p)).filter(Boolean).map(p => `<span class="chip" data-goproj="${p.id}"><span class="dot" style="background:${esc(p.color)}"></span>${esc(p.name)}</span>`).join(' ') || '<span class="muted">not linked to any project</span>'}</div>
      ${(i.tags || []).length ? `<div class="sec"><b>Tags</b>${i.tags.map(t => `<span class="chip" data-gotag="${esc(t)}">#${esc(t)}</span>`).join(' ')}</div>` : ''}
      ${(i.related || []).length ? `<div class="sec"><b>Related ideas</b><ul>${i.related.map(r => S.ideas.find(x => x.id === r)).filter(Boolean).map(ideaLi).join('')}</ul></div>` : ''}
      ${(i.primaryContact || i.secondaryContact) ? `<div class="sec"><b>Contacts</b>${i.primaryContact ? `<div><span class="muted small">Primary</span> ${esc(i.primaryContact)}</div>` : ''}${i.secondaryContact ? `<div><span class="muted small">Secondary</span> ${esc(i.secondaryContact)}</div>` : ''}</div>` : ''}
      <div class="sec muted small">${i.author ? 'By ' + esc(i.author) + ' · ' : ''}${esc((i.createdAt || '').slice(0, 10))}${i.source ? '<br>Source: ' + esc(i.source) : ''}</div>
      <div class="actions"><button class="primary small" data-edit="${i.id}">Edit</button></div>`;
  } else if (n.type === 'category') {
    const c = n.data, ids = subtreeIds(c.id), list = S.ideas.filter(i => ids.has(i.category));
    const pc = new Map(); for (const i of list) for (const p of i.projects || []) pc.set(p, (pc.get(p) || 0) + 1);
    h += `<div class="kind">Category</div><h3>${esc(catPath(c.id))}</h3><p class="muted">${esc(c.description || '')}</p>
      <div class="sec"><b>Feeds projects</b>${[...pc.entries()].sort((a, b) => b[1] - a[1]).map(([p, k]) => { const pr = projs.get(p); return pr ? `<span class="chip" data-goproj="${p}"><span class="dot" style="background:${esc(pr.color)}"></span>${esc(pr.name)} <span class="cnt">${k}</span></span>` : ''; }).join(' ') || '<span class="muted">none yet</span>'}</div>
      <div class="sec"><b>${list.length} idea${list.length === 1 ? '' : 's'}</b><ul>${list.slice(0, 40).map(ideaLi).join('')}${list.length > 40 ? '<li class="muted">…</li>' : ''}</ul></div>
      <div class="actions"><button class="small" data-gocat="${c.id}">Filter to this</button><button class="small" data-editcat="${c.id}">Edit</button></div>`;
  } else if (n.type === 'project') {
    const p = n.data, list = S.ideas.filter(i => (i.projects || []).includes(p.id));
    const cc = new Map(); for (const i of list) if (i.category) cc.set(i.category, (cc.get(i.category) || 0) + 1);
    h += `<div class="kind">Project</div><h3>${esc(p.name)}</h3><p class="muted">${esc(p.description || '')}</p>
      <div class="sec"><b>Ideas come from categories</b>${[...cc.entries()].sort((a, b) => b[1] - a[1]).map(([c, k]) => { const ct = cats.get(c); return ct ? `<span class="chip" data-gocat="${c}"><span class="dot" style="background:${esc(ct.color)}"></span>${esc(ct.name)} <span class="cnt">${k}</span></span>` : ''; }).join(' ') || '<span class="muted">none yet</span>'}</div>
      <div class="sec"><b>${list.length} idea${list.length === 1 ? '' : 's'}</b><ul>${list.slice(0, 40).map(ideaLi).join('')}${list.length > 40 ? '<li class="muted">…</li>' : ''}</ul></div>
      <div class="actions"><button class="small" data-goproj="${p.id}">Filter to this</button><button class="small" data-editproj="${p.id}">Edit</button></div>`;
  } else {
    const t = n.data.tag, list = S.ideas.filter(i => (i.tags || []).includes(t));
    h += `<div class="kind">Tag</div><h3>#${esc(t)}</h3><div class="sec"><ul>${list.map(ideaLi).join('')}</ul></div><div class="actions"><button class="small" data-gotag="${esc(t)}">Filter to this</button></div>`;
  }
  d.innerHTML = h; d.hidden = false;
}

/* ---------- ideas list ---------- */
function renderList() {
  const cats = catById(), projs = projById();
  let ideas = filteredIdeas();
  const sort = $('#sortBy').value;
  ideas.sort((a, b) => sort === 'title' ? a.title.localeCompare(b.title)
    : sort === 'category' ? catPath(a.category).localeCompare(catPath(b.category)) || a.title.localeCompare(b.title)
      : sort === 'created' ? (b.createdAt || '').localeCompare(a.createdAt || '') : (b.updatedAt || '').localeCompare(a.updatedAt || ''));
  $('#listCount').textContent = `${ideas.length} of ${S.ideas.length} ideas`;
  const card = i => {
    const c = cats.get(i.category);
    return `<div class="card" data-idea="${i.id}" style="--c:${esc(c ? c.color : 'var(--border)')}">
      <h5>${esc(i.title)}</h5>${i.description ? `<p>${esc(i.description)}</p>` : ''}
      <div class="meta">${c ? `<span class="badge">${esc(catPath(c.id))}</span>` : '<span class="badge">uncategorised</span>'}
      <span class="badge status-${esc(i.status)}">${esc(i.status)}</span>
      ${(i.projects || []).map(p => projs.get(p)).filter(Boolean).map(p => `<span class="badge" style="border:1px solid ${esc(p.color)}">${esc(p.name)}</span>`).join('')}</div>
      <div class="meta">${(i.tags || []).map(t => '#' + esc(t)).join(' ')}${i.author ? ` · ${esc(i.author)}` : ''}</div>
      ${i.primaryContact ? `<div class="meta">&#9742; ${esc(i.primaryContact)}${i.secondaryContact ? ` &nbsp;/&nbsp; ${esc(i.secondaryContact)}` : ''}</div>` : ''}</div>`;
  };
  const gb = $('#groupBy').value;
  let html = '';
  if (!gb) html = ideas.map(card).join('');
  else {
    const keyOf = i => gb === 'category' ? (i.category ? catPath(i.category) : 'Uncategorised')
      : gb === 'status' ? i.status : gb === 'author' ? (i.author || 'Unknown')
        : null;
    const groups = new Map();
    for (const i of ideas) {
      const keys = gb === 'project' ? ((i.projects || []).map(p => (projs.get(p) || {}).name).filter(Boolean)) : [keyOf(i)];
      for (const k of (keys.length ? keys : ['No project'])) (groups.get(k) || groups.set(k, []).get(k)).push(i);
    }
    html = [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([k, arr]) => `<h4 class="group-h">${esc(k)} <span class="badge">${arr.length}</span></h4>` + arr.map(card).join('')).join('');
  }
  $('#ideaList').innerHTML = html || `<div class="list-empty">${S.ideas.length ? 'No ideas match the current filters.' : 'No ideas yet — use “Import” or “+ New idea”.'}</div>`;
}

/* ---------- manage ---------- */
function renderManage() {
  const counts = new Map(); for (const i of S.ideas) if (i.category) counts.set(i.category, (counts.get(i.category) || 0) + 1);
  const row = (c, d) => `<div class="row" style="margin-left:${d * 18}px"><span class="dot" style="background:${esc(c.color)}"></span><span class="name">${esc(c.name)}</span><span class="muted small">${counts.get(c.id) || 0}</span><button class="small" data-editcat="${c.id}">Edit</button></div>` + childrenOf(c.id).map(k => row(k, d + 1)).join('');
  $('#manageCats').innerHTML = childrenOf(null).map(c => row(c, 0)).join('') || '<span class="muted">No categories yet.</span>';
  const pc = new Map(); for (const i of S.ideas) for (const p of i.projects || []) pc.set(p, (pc.get(p) || 0) + 1);
  $('#manageProjs').innerHTML = S.projects.map(p => `<div class="row"><span class="dot" style="background:${esc(p.color)}"></span><span class="name" title="${esc(p.description)}">${esc(p.name)}</span><span class="muted small">${pc.get(p.id) || 0}</span><button class="small" data-editproj="${p.id}">Edit</button></div>`).join('') || '<span class="muted">No projects yet.</span>';
}

function renderAll() {
  renderSidebar();
  $$('.view').forEach(v => (v.hidden = v.id !== 'view-' + view));
  $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  if (view === 'graph') { renderGraph(); if (isGraphMode()) requestAnimationFrame(() => { graph.resize(); graph.draw(); }); else if ($('#gMode').value === 'board') requestAnimationFrame(boardLayout); }
  if (view === 'ideas') renderList();
  if (view === 'manage') renderManage();
  $('#authorList').innerHTML = [...new Set(S.ideas.map(i => i.author).filter(Boolean))].map(a => `<option value="${esc(a)}">`).join('');
  $('#contactList').innerHTML = [...new Set(S.ideas.flatMap(i => [i.primaryContact, i.secondaryContact]).filter(Boolean))].map(a => `<option value="${esc(a)}">`).join('');
}

/* ---------- idea dialog ---------- */
function catOptions(sel, excludeSubtreeOf) {
  const ex = excludeSubtreeOf ? subtreeIds(excludeSubtreeOf) : new Set();
  const out = []; const walk = (pid, d) => childrenOf(pid).forEach(c => { if (!ex.has(c.id)) { out.push(`<option value="${c.id}" ${sel === c.id ? 'selected' : ''}>${'  '.repeat(d)}${esc(c.name)}</option>`); walk(c.id, d + 1); } });
  walk(null, 0); return out.join('');
}
function openIdea(id) {
  editing = id || null;
  const i = id ? S.ideas.find(x => x.id === id) : { title: '', description: '', category: F.cat && F.cat !== '__none' ? F.cat : null, projects: F.project ? [F.project] : [], tags: F.tag ? [F.tag] : [], related: [], author: '', status: 'new', source: '', primaryContact: '', secondaryContact: '' };
  const f = $('#ideaForm');
  $('#ideaDlgTitle').textContent = id ? 'Edit idea' : 'New idea';
  f.primaryContact.value = i.primaryContact || ''; f.secondaryContact.value = i.secondaryContact || '';
  f.title.value = i.title; f.description.value = i.description || ''; f.author.value = i.author || ''; f.status.value = i.status; f.tags.value = (i.tags || []).join(', ');
  f.source.value = i.source || ''; f.newCategory.value = ''; f.newProject.value = ''; $('#fRelatedSearch').value = '';
  $('#fCategory').innerHTML = '<option value="">— none —</option>' + catOptions(i.category);
  $('#fProjects').innerHTML = S.projects.map(p => `<label><input type="checkbox" value="${p.id}" ${(i.projects || []).includes(p.id) ? 'checked' : ''}> <span class="dot" style="background:${esc(p.color)}"></span>${esc(p.name)}</label>`).join('') || '<span class="muted small">No projects yet — add one below.</span>';
  renderRelated(i.related || []);
  $('#ideaDelete').hidden = !id;
  $('#ideaDlg').showModal(); f.title.focus();
}
function renderRelated(checked) {
  const q = $('#fRelatedSearch').value.toLowerCase();
  const keep = new Set(checked);
  $('#fRelated').innerHTML = S.ideas.filter(x => x.id !== editing && (keep.has(x.id) || !q || x.title.toLowerCase().includes(q))).slice(0, 200)
    .map(x => `<label><input type="checkbox" value="${x.id}" ${keep.has(x.id) ? 'checked' : ''}> ${esc(x.title)}</label>`).join('') || '<span class="muted small">No other ideas yet.</span>';
}
async function saveIdea(e) {
  e.preventDefault();
  const f = $('#ideaForm');
  try {
    let category = f.category.value || null;
    if (f.newCategory.value.trim()) category = (await api('POST', '/api/categories', { name: f.newCategory.value.trim() })).id;
    let projects = $$('#fProjects input:checked').map(x => x.value);
    for (const name of f.newProject.value.split(',').map(s => s.trim()).filter(Boolean)) projects.push((await api('POST', '/api/projects', { name })).id);
    const body = { title: f.title.value, description: f.description.value, category, projects, tags: f.tags.value, author: f.author.value, primaryContact: f.primaryContact.value, secondaryContact: f.secondaryContact.value, status: f.status.value, source: f.source.value, related: $$('#fRelated input:checked').map(x => x.value) };
    if (editing) await api('PUT', '/api/ideas/' + editing, body); else await api('POST', '/api/ideas', body);
    $('#ideaDlg').close(); toast('Saved'); await reload();
  } catch (err) { toast('Error: ' + err.message, 4000); }
}

/* ---------- category / project dialog ---------- */
let ent = null;
function openEntity(kind, id) {
  const item = id ? (kind === 'cat' ? S.categories : S.projects).find(x => x.id === id) : null;
  ent = { kind, id };
  const f = $('#entForm');
  $('#entTitle').textContent = (id ? 'Edit ' : 'New ') + (kind === 'cat' ? 'category' : 'project');
  f.name.value = item ? item.name : ''; f.description.value = item ? item.description || '' : ''; f.color.value = item ? item.color : '#4f8cff';
  $('#entParentWrap').hidden = kind !== 'cat';
  if (kind === 'cat') $('#entParent').innerHTML = '<option value="">— top level —</option>' + catOptions(item ? item.parent : null, id);
  $('#entDelete').hidden = !id; $('#entDlg').showModal(); f.name.focus();
}
async function saveEntity(e) {
  e.preventDefault(); const f = $('#entForm');
  const body = { name: f.name.value, description: f.description.value, color: f.color.value };
  const base = ent.kind === 'cat' ? '/api/categories' : '/api/projects';
  try {
    if (ent.kind === 'cat') body.parent = f.parent.value || null;
    if (ent.id) await api('PUT', base + '/' + ent.id, body); else await api('POST', base, body);
    $('#entDlg').close(); await reload();
  } catch (err) { toast('Error: ' + err.message, 4000); }
}

/* ---------- import / export ---------- */
function parseCSV(text) {
  const sep = text.split('\n', 1)[0].includes('\t') ? '\t' : ',';
  const rows = []; let row = [], cur = '', q = false;
  for (let k = 0; k < text.length; k++) {
    const ch = text[k];
    if (q) { if (ch === '"') { if (text[k + 1] === '"') { cur += '"'; k++; } else q = false; } else cur += ch; }
    else if (ch === '"') q = true;
    else if (ch === sep) { row.push(cur); cur = ''; }
    else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[k + 1] === '\n') k++; row.push(cur); cur = ''; if (row.some(c => c.trim())) rows.push(row); row = []; }
    else cur += ch;
  }
  row.push(cur); if (row.some(c => c.trim())) rows.push(row);
  if (!rows.length) return [];
  const head = rows[0].map(h => h.trim().toLowerCase());
  return rows.slice(1).map(r => Object.fromEntries(head.map((h, i) => [h, (r[i] || '').trim()])));
}
let impPayload = null;
// an Export-JSON file (ids everywhere) as opposed to a name-based import
const isBackup = p => !!(p && Array.isArray(p.categories) && p.categories.length && p.categories[0].id && Array.isArray(p.ideas) && p.ideas.length && p.ideas[0].id);
function parseImport(text) {
  text = text.trim().replace(/^﻿/, '');
  if (!text) return null;
  if (text[0] === '{' || text[0] === '[') {
    const j = JSON.parse(text);
    return Array.isArray(j) ? { ideas: j } : j;
  }
  return { ideas: parseCSV(text) };
}
function previewImport() {
  const el = $('#impPreview'); impPayload = null; $('#impGo').disabled = true;
  try {
    const p = parseImport($('#impText').value);
    if (!p) { el.textContent = ''; return; }
    if (isBackup(p)) {
      el.innerHTML = `<b>Full Constellarium backup detected</b>: ${p.ideas.length} ideas, ${p.categories.length} categories, ${(p.projects || []).length} projects. Importing will <b>replace all current data</b> (the previous version is kept as a backup).`;
      impPayload = p; $('#impGo').disabled = false; return;
    }
    const n = (p.ideas || []).filter(i => i && String(i.title || '').trim()).length;
    const cats = new Set((p.ideas || []).map(i => (i.category || '').trim()).filter(Boolean));
    el.innerHTML = n ? `Ready: <b>${n}</b> ideas, <b>${cats.size}</b> distinct categories detected.` : '<span style="color:var(--danger)">No ideas found — check the “title” column/key.</span>';
    if (n) { impPayload = p; $('#impGo').disabled = false; }
  } catch (err) { el.innerHTML = `<span style="color:var(--danger)">Could not parse: ${esc(err.message)}</span>`; }
}
function openImport() { $('#impText').value = ''; $('#impPreview').textContent = ''; $('#impGo').disabled = true; $('#impFile').value = ''; $('#impDlg').showModal(); }
async function doImport(e) {
  e.preventDefault(); if (!impPayload) return;
  try {
    if (isBackup(impPayload)) {
      if (!confirm('Replace ALL current data with this backup?')) return;
      await api('POST', '/api/replace', { categories: impPayload.categories, projects: impPayload.projects || [], ideas: impPayload.ideas });
      $('#impDlg').close(); toast(`Restored backup: ${impPayload.ideas.length} ideas`, 5000); await reload(); return;
    }
    const r = await api('POST', '/api/import', impPayload);
    $('#impDlg').close(); toast(`Imported: ${r.ideasAdded} new, ${r.ideasUpdated} updated · +${r.categoriesAdded} categories, +${r.projectsAdded} projects`, 5000); await reload();
  } catch (err) { toast('Import failed: ' + err.message, 5000); }
}
function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
/* ---------- export: all or filtered (category incl. sub-categories, tag, plus the sidebar filters) ---------- */
function describeFilters(f) {
  const bits = [];
  if (f.q && f.q.trim()) bits.push(`search “${f.q.trim()}”`);
  if (f.cat) bits.push('category: ' + (f.cat === '__none' ? 'uncategorised' : catPath(f.cat)));
  if (f.project) bits.push('project: ' + ((projById().get(f.project) || {}).name || '?'));
  if (f.status) bits.push('status: ' + f.status);
  if (f.tag) bits.push('tag: #' + f.tag);
  return bits.length ? bits.join(' · ') : 'no filters';
}
function exportSet() {
  const f = $('#exportForm');
  if (f.scope.value === 'all') return { ideas: S.ideas, all: true, label: 'everything' };
  const ov = { cat: f.cat.value ? f.cat.value : F.cat, tag: f.tag.value ? f.tag.value : F.tag };
  return { ideas: filteredIdeas(ov), all: false, label: describeFilters({ ...F, ...ov }) };
}
function refreshExportInfo() {
  const r = exportSet();
  $('#expInfo').innerHTML = `<b>${r.ideas.length}</b> of ${S.ideas.length} ideas will be exported (${esc(r.label)}).`;
  $('#expGo').disabled = !r.ideas.length;
  $('#exportForm').cat.disabled = $('#exportForm').tag.disabled = $('#exportForm').scope.value === 'all';
}
function openExport() {
  const f = $('#exportForm');
  f.scope.value = anyFilter() ? 'view' : 'all';
  $('#expCat').innerHTML = '<option value="">' + (F.cat ? 'Current sidebar category' : 'Any category') + '</option><option value="__none">Uncategorised only</option>' + catOptions(null);
  const tags = [...new Set(S.ideas.flatMap(i => i.tags || []))].sort();
  $('#expTag').innerHTML = '<option value="">' + (F.tag ? 'Current sidebar tag' : 'Any tag') + '</option>' + tags.map(t => `<option value="${esc(t)}">#${esc(t)}</option>`).join('');
  refreshExportInfo();
  $('#exportDlg').showModal();
}
function csvQ(v) { return '"' + String(v ?? '').replace(/"/g, '""') + '"'; }
function exportCsv(ideas) {
  const projs = projById(), byId = new Map(S.ideas.map(x => [x.id, x]));
  const rows = ideas.map(i => [i.title, i.description, catPath(i.category).replace(/ › /g, ' > '), (i.projects || []).map(p => (projs.get(p) || {}).name).join(';'), (i.tags || []).join(';'), i.author, i.primaryContact, i.secondaryContact, i.status, i.source, (i.related || []).map(r => (byId.get(r) || {}).title).filter(Boolean).join(';'), i.createdAt].map(csvQ).join(','));
  return ['title,description,category,projects,tags,author,primaryContact,secondaryContact,status,source,related,createdAt'].concat(rows).join('\n');
}
function exportMarkdown(ideas, label) {
  const projs = projById(), groups = new Map();
  for (const i of ideas) { const k = i.category ? catPath(i.category) : 'Uncategorised'; (groups.get(k) || groups.set(k, []).get(k)).push(i); }
  let md = `# Constellarium export\n\n_${new Date().toISOString().slice(0, 10)} · ${ideas.length} ideas · ${label}_\n`;
  for (const k of [...groups.keys()].sort()) {
    md += `\n## ${k}\n`;
    for (const i of groups.get(k).sort((a, b) => a.title.localeCompare(b.title))) {
      md += `\n### ${i.title}\n`;
      md += `**Status:** ${i.status}` + ((i.projects || []).length ? ` · **Projects:** ${i.projects.map(p => (projs.get(p) || {}).name).filter(Boolean).join(', ')}` : '') + ((i.tags || []).length ? ` · **Tags:** ${i.tags.map(t => '#' + t).join(' ')}` : '') + '\n\n';
      if (i.description) md += i.description + '\n\n';
      if (i.primaryContact) md += `- **Primary contact:** ${i.primaryContact}\n`;
      if (i.secondaryContact) md += `- **Secondary contact:** ${i.secondaryContact}\n`;
      if (i.author) md += `- **Author:** ${i.author}\n`;
      if (i.source) md += `- **Source:** ${i.source}\n`;
    }
  }
  return md + '\n';
}
function doExport(e) {
  e.preventDefault();
  const f = $('#exportForm'), r = exportSet(), fmt = f.format.value, stamp = new Date().toISOString().slice(0, 10);
  const tag = r.all ? 'all' : 'filtered';
  if (fmt === 'csv') download(`constellarium-${tag}-${stamp}.csv`, exportCsv(r.ideas), 'text/csv');
  else if (fmt === 'md') download(`constellarium-${tag}-${stamp}.md`, exportMarkdown(r.ideas, r.label), 'text/markdown');
  else if (r.all) download(`constellarium-backup-${stamp}.json`, JSON.stringify(S, null, 2), 'application/json');
  else {   // filtered JSON is NAME-based (no ids) so importing it merges instead of replacing everything
    const cats = catById(), projs = projById(), byId = new Map(S.ideas.map(x => [x.id, x]));
    const out = r.ideas.map(i => ({ title: i.title, description: i.description, category: catPath(i.category).replace(/ › /g, ' > '), projects: (i.projects || []).map(p => (projs.get(p) || {}).name).filter(Boolean), tags: i.tags || [], author: i.author, primaryContact: i.primaryContact || '', secondaryContact: i.secondaryContact || '', status: i.status, source: i.source, related: (i.related || []).map(x => (byId.get(x) || {}).title).filter(Boolean), createdAt: i.createdAt }));
    download(`constellarium-filtered-${stamp}.json`, JSON.stringify({ ideas: out }, null, 2), 'application/json');
  }
  $('#exportDlg').close(); toast(`Exported ${r.ideas.length} ideas`);
}
async function loadSample() {
  try { const p = await (await fetch('/sample.json')).json(); const r = await api('POST', '/api/import', p); toast(`Loaded sample: ${r.ideasAdded} ideas`); await reload(); } catch (e) { toast('Could not load sample: ' + e.message); }
}

/* ---------- wiring ---------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-cat],[data-proj],[data-status],[data-tag],[data-idea],[data-edit],[data-editcat],[data-editproj],[data-gocat],[data-goproj],[data-gotag]');
  if (e.target.id === 'dClose') { $('#detail').hidden = true; if (graph) { graph.selected = null; graph.draw(); } return; }
  if (!t) return;
  const d = t.dataset;
  if (d.cat) toggleFilter('cat', d.cat);
  else if (d.proj) toggleFilter('project', d.proj);
  else if (d.status) toggleFilter('status', d.status);
  else if (d.tag) toggleFilter('tag', d.tag);
  else if (d.gocat) { F.cat = d.gocat; renderAll(); }
  else if (d.goproj) { F.project = d.goproj; renderAll(); }
  else if (d.gotag) { F.tag = d.gotag; renderAll(); }
  else if (d.edit) openIdea(d.edit);
  else if (d.editcat) openEntity('cat', d.editcat);
  else if (d.editproj) openEntity('proj', d.editproj);
  else if (d.idea) { if (t.closest('#detail')) { const n = graph && graph.byId.get('i:' + d.idea); if (n) { graph.select(n.id); showDetail(n); } else if ($('#gMode').value === 'board') showDetail({ type: 'idea', data: S.ideas.find(x => x.id === d.idea) }); else openIdea(d.idea); } else openIdea(d.idea); }
});
$('#tabs').onclick = e => { const b = e.target.closest('button'); if (b) { view = b.dataset.view; renderAll(); } };
$('#search').oninput = e => { F.q = e.target.value; clearTimeout(renderAll._t); renderAll._t = setTimeout(renderAll, 150); };
$('#clearFilters').onclick = () => { F = { q: '', cat: null, project: null, status: '', tag: '' }; $('#search').value = ''; renderAll(); };
['gMode', 'gIdeas', 'gTags', 'gRelated'].forEach(id => ($('#' + id).onchange = () => { $('#detail').hidden = true; if (graph) graph.selected = null; renderGraph(); if (isGraphMode() && graph) { graph._pendingFit = true; graph._earlyFit = false; graph.heat(0.6); } }));
$('#gFit').onclick = () => graph.fit();
const isBoardMode = () => $('#gMode').value === 'board';
$('#zIn').onclick = () => (isBoardMode() ? boardZoom(1.2) : graph.zoomBy(1.25));
$('#zOut').onclick = () => (isBoardMode() ? boardZoom(1 / 1.2) : graph.zoomBy(0.8));
$('#zFit').onclick = () => (isBoardMode() ? boardZoom(0) : graph.fit());
const layoutEl = $('.layout');
const setSide = collapsed => {
  layoutEl.classList.toggle('side-collapsed', collapsed);
  localStorage.setItem('constellariumSide', collapsed ? '1' : '0');
  setTimeout(() => { if (graph && isGraphMode()) { graph.resize(); graph.draw(); } }, 50);
};
$('#btnSide').onclick = () => setSide(!layoutEl.classList.contains('side-collapsed'));
if (localStorage.getItem('constellariumSide') === '1') layoutEl.classList.add('side-collapsed');
$('#gReheat').onclick = () => { graph.nodes.forEach(n => { n.x += (Math.random() - .5) * 120; n.y += (Math.random() - .5) * 120; }); graph.heat(1); graph._pendingFit = true; };
$('#gPng').onclick = () => graph.png();
['sortBy', 'groupBy'].forEach(id => ($('#' + id).onchange = renderList));
$('#btnNew').onclick = () => openIdea();
$('#btnImport').onclick = openImport;
$('#btnExport').onclick = openExport;
$('#exportForm').addEventListener('change', refreshExportInfo);
$('#exportForm').onsubmit = doExport;
$('#expCancel').onclick = () => $('#exportDlg').close();
$('#ideaForm').onsubmit = saveIdea;
$('#ideaCancel').onclick = () => $('#ideaDlg').close();
$('#ideaDelete').onclick = async () => { if (confirm('Delete this idea?')) { await api('DELETE', '/api/ideas/' + editing); $('#ideaDlg').close(); toast('Deleted'); reload(); } };
$('#fRelatedSearch').oninput = () => renderRelated($$('#fRelated input:checked').map(x => x.value));
$('#entForm').onsubmit = saveEntity;
$('#entCancel').onclick = () => $('#entDlg').close();
$('#entDelete').onclick = async () => {
  if (!confirm('Delete this ' + (ent.kind === 'cat' ? 'category? Its ideas move up one level.' : 'project? Ideas stay, but lose this link.'))) return;
  await api('DELETE', (ent.kind === 'cat' ? '/api/categories/' : '/api/projects/') + ent.id); $('#entDlg').close(); if (F.cat === ent.id) F.cat = null; if (F.project === ent.id) F.project = null; reload();
};
$('#addCat').onclick = () => openEntity('cat'); $('#addProj').onclick = () => openEntity('proj');
$('#impText').oninput = previewImport;
$('#impFile').onchange = async e => { const f = e.target.files[0]; if (f) { $('#impText').value = await f.text(); previewImport(); } };
$('#impCancel').onclick = () => $('#impDlg').close();
$('#impForm').onsubmit = doImport;
$('#impTemplate').onclick = e => { e.preventDefault(); download('constellarium-template.csv', 'title,description,category,projects,tags,author,status,source,related\n"Solar bus stops","Roof panels power the displays","Sustainability > Energy","Smart City;Campus Pilot","solar;iot","Aisha","exploring","Team brainstorm 2026-11-01",""\n', 'text/csv'); };
$('#loadSample').onclick = loadSample;
$('#clearAll').onclick = async () => { if (prompt('This deletes ALL ideas, categories and projects (a backup is kept in data/backups). Type DELETE to confirm.') === 'DELETE') { await api('POST', '/api/clear'); F = { q: '', cat: null, project: null, status: '', tag: '' }; toast('Cleared'); reload(); } };
$$('dialog').forEach(d => d.addEventListener('click', e => { if (e.target === d && !d.classList.contains('nodismiss')) d.close(); }));

function openLogin() {
  const dlg = $('#loginDlg');
  if (!dlg.open) dlg.showModal();
  $('#loginForm').password.focus();
}
$('#loginDlg').addEventListener('cancel', e => e.preventDefault());   // can't Esc past the login
$('#loginForm').onsubmit = async e => {
  e.preventDefault();
  try {
    await api('POST', '/api/login', { password: $('#loginForm').password.value });
    $('#loginDlg').close(); $('#loginForm').reset(); $('#loginErr').textContent = ''; $('#btnLogout').hidden = false;
    await reload();
  } catch (err) { $('#loginErr').textContent = err.message; }
};
$('#btnLogout').onclick = async () => { await api('POST', '/api/logout', {}); location.reload(); };

(async function boot() {
  try {
    const auth = await api('GET', '/api/auth');
    $('#btnLogout').hidden = !auth.required;
    if (auth.required && !auth.ok) { openLogin(); return; }
  } catch (e) { /* fall through to normal load, which reports errors */ }
  for (let attempt = 1; attempt <= 4; attempt++) {
    try { await reload(); return; }
    catch (e) {
      if (e.status === 401) return;               // login dialog already open
      if (attempt === 4) { toast('Could not reach server: ' + e.message + ' - reload the page', 10000); return; }
      await new Promise(r => setTimeout(r, 400 * attempt));
    }
  }
})();
