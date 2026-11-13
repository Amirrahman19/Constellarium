/* Zoomable treemap: every idea is a tile, grouped by category (nested blocks).
   Overview first, detail on demand: labels appear only where a tile is big enough to read, and zooming
   into a block (click / scroll) re-lays it out to fill the screen, so its sub-blocks and idea titles become readable.
   Uses the app's global state and helpers (S, F, filteredIdeas, childrenOf, catById, showDetail, openIdea). No libraries. */

let tmFocus = null;      // category id we are zoomed into (null = everything)
let tmSel = null;        // selected idea id
let tmHL = '';           // project id to highlight ('' = none)
const TM_ST = { new: '#8a93a6', exploring: '#e2b93b', 'in-progress': '#4f8cff', done: '#27ae60', shelved: '#4a5265' };
const TM_HDR = 17, TM_PAD = 2;

function tmTree(ideas) {
  const cats = catById(), byCat = new Map(), none = [];
  for (const i of ideas) {
    if (i.category && cats.has(i.category)) (byCat.get(i.category) || byCat.set(i.category, []).get(i.category)).push(i);
    else none.push(i);
  }
  const leaf = i => ({ type: 'idea', idea: i, value: 1 });
  const build = c => {
    const all = childrenOf(c.id).map(build).filter(Boolean).concat((byCat.get(c.id) || []).map(leaf));
    return all.length ? { type: 'cat', id: c.id, name: c.name, color: c.color, kids: all, value: all.reduce((s, k) => s + k.value, 0) } : null;
  };
  const kids = childrenOf(null).map(build).filter(Boolean);
  if (none.length) kids.push({ type: 'cat', id: '__none', name: 'Uncategorised', color: '#8a93a6', kids: none.map(leaf), value: none.length });
  return { type: 'cat', id: null, name: 'All ideas', color: '#8a93a6', kids, value: kids.reduce((s, k) => s + k.value, 0) };
}
function tmFind(node, id, path = []) {
  const p = path.concat(node);
  if (node.id === id) return p;
  for (const k of node.kids || []) if (k.type === 'cat') { const r = tmFind(k, id, p); if (r) return r; }
  return null;
}

// Squarified treemap (Bruls et al.): keeps tiles close to square so they stay readable.
function tmSquarify(items, rect) {
  const out = []; let { x, y, w, h } = rect;
  const total = items.reduce((s, i) => s + i.value, 0);
  if (!total || w <= 0 || h <= 0) return out;
  const scale = (w * h) / total;
  const queue = [...items].sort((a, b) => b.value - a.value).map(it => ({ it, a: it.value * scale }));
  const worst = (row, side) => {
    const s = row.reduce((t, r) => t + r.a, 0), mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  const flush = row => {
    const s = row.reduce((t, r) => t + r.a, 0);
    if (w >= h) { const rw = s / h; let cy = y; for (const r of row) { const rh = r.a / rw; out.push({ it: r.it, x, y: cy, w: rw, h: rh }); cy += rh; } x += rw; w -= rw; }
    else { const rh = s / w; let cx = x; for (const r of row) { const rw = r.a / rh; out.push({ it: r.it, x: cx, y, w: rw, h: rh }); cx += rw; } y += rh; h -= rh; }
  };
  let row = [];
  while (queue.length) {
    const side = Math.min(w, h), next = queue[0];
    if (!row.length || worst(row.concat(next), side) <= worst(row, side)) row.push(queue.shift());
    else { flush(row); row = []; }
  }
  if (row.length) flush(row);
  return out;
}

function tmPlace(node, rect, top, out, hl) {
  for (const p of tmSquarify(node.kids, rect)) {
    const k = p.it, tp = top === undefined ? (k.type === 'cat' ? String(k.id) : '') : top;   // tp = the direct child of the focus this tile lives in
    const pos = `left:${p.x.toFixed(1)}px;top:${p.y.toFixed(1)}px;width:${p.w.toFixed(1)}px;height:${p.h.toFixed(1)}px`;
    if (k.type === 'idea') {
      if (p.w < 1.5 || p.h < 1.5) continue;
      const i = k.idea, legible = p.w >= 64 && p.h >= 24, dim = hl && !(i.projects || []).includes(hl);
      out.push(`<div class="tm-leaf${tmSel === i.id ? ' sel' : ''}${dim ? ' dim' : ''}" data-tm-idea="${esc(i.id)}" data-tm-top="${esc(tp)}" data-lg="${legible ? 1 : 0}" style="${pos};background:${TM_ST[i.status] || TM_ST.new}" title="${esc(i.title)} · ${esc(i.status)}">${legible ? `<span style="-webkit-line-clamp:${Math.max(1, Math.floor((p.h - 6) / 13))}">${esc(i.title)}</span>` : ''}</div>`);
      continue;
    }
    if (p.w < 12 || p.h < 12) {      // too small to open up: draw it as one solid block
      out.push(`<div class="tm-grp tiny" data-tm-cat="${esc(k.id)}" data-tm-top="${esc(tp)}" style="${pos};background:${esc(k.color)}" title="${esc(k.name)} · ${k.value} ideas"></div>`);
      continue;
    }
    const hdr = p.w >= 70 && p.h >= 34;
    out.push(`<div class="tm-grp" data-tm-cat="${esc(k.id)}" data-tm-top="${esc(tp)}" style="${pos};border-color:${esc(k.color)};background:color-mix(in srgb, ${esc(k.color)} 10%, var(--panel))" title="${esc(k.name)} · ${k.value} ideas (click to zoom in)">${hdr ? `<div class="tm-gh"><i style="background:${esc(k.color)}"></i><span>${esc(k.name)}</span><em>${k.value}</em></div>` : ''}</div>`);
    const top2 = hdr ? TM_HDR : TM_PAD;
    tmPlace(k, { x: p.x + TM_PAD, y: p.y + top2, w: p.w - 2 * TM_PAD, h: p.h - top2 - TM_PAD }, tp, out, hl);
  }
}

function renderTreemap() {
  const root = document.getElementById('board');
  root.classList.add('tm');
  const ideas = filteredIdeas();
  if (!ideas.length) { root.innerHTML = '<div class="muted" style="padding:30px">No ideas match the current filters.</div>'; return; }
  const tree = tmTree(ideas);
  let path = tmFind(tree, tmFocus);
  if (!path) { tmFocus = null; path = [tree]; }
  const focus = path[path.length - 1];
  const crumbs = path.map((n, k) => k === path.length - 1 ? `<b>${esc(n.name)}</b>` : `<a data-tm-go="${n.id === null ? '' : esc(n.id)}">${esc(n.name)}</a>`).join('<span class="tm-sep">›</span>');
  root.innerHTML = `<div class="tm-bar"><div class="tm-crumbs">${crumbs}<span class="muted small"> · ${focus.value} ideas</span></div>
    <div class="tm-tools"><label class="muted small">Highlight project <select id="tmHL"><option value="">none</option>${S.projects.map(p => `<option value="${esc(p.id)}" ${tmHL === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
    <span class="tm-legend">${Object.entries(TM_ST).map(([s, c]) => `<span><i style="background:${c}"></i>${s}</span>`).join('')}</span></div></div>
    <div class="tm-map" id="tmMap"></div>`;
  const map = document.getElementById('tmMap');
  // keep the whole map inside what is actually visible (never let the bottom run past the viewport)
  const visibleH = Math.floor(window.innerHeight - map.getBoundingClientRect().top - 10);
  if (visibleH > 80 && visibleH < map.clientHeight) { map.style.flex = 'none'; map.style.height = visibleH + 'px'; }
  const out = [];
  tmPlace(focus, { x: 0, y: 0, w: map.clientWidth, h: map.clientHeight }, undefined, out, tmHL);
  map.innerHTML = out.join('');
}

function tmZoomTo(id) { tmFocus = id === '' || id === undefined ? null : id; renderTreemap(); }
function tmUp() {
  const path = tmFind(tmTree(filteredIdeas()), tmFocus);
  if (path && path.length > 1) tmZoomTo(path[path.length - 2].id);
}
const tmActive = () => document.getElementById('board').classList.contains('tm') && !document.getElementById('board').hidden;

(function tmWire() {
  const board = document.getElementById('board');
  board.addEventListener('click', e => {
    if (!tmActive()) return;
    const go = e.target.closest('[data-tm-go]');
    if (go) { tmZoomTo(go.dataset.tmGo); return; }
    const el = e.target.closest('[data-tm-idea],[data-tm-cat]');
    if (!el) return;
    if (el.dataset.tmIdea) {
      const i = S.ideas.find(x => x.id === el.dataset.tmIdea);
      // readable tile (or already at its level) -> select it; too small to read -> zoom into its block first
      if (i && (el.dataset.lg === '1' || !el.dataset.tmTop)) { tmSel = i.id; document.getElementById('detail').classList.remove('dock-left'); showDetail({ type: 'idea', data: i }); renderTreemap(); }
      else if (el.dataset.tmTop) tmZoomTo(el.dataset.tmTop);
      return;
    }
    if (el.dataset.tmTop) tmZoomTo(el.dataset.tmTop);
  });
  board.addEventListener('dblclick', e => { if (!tmActive()) return; const el = e.target.closest('[data-tm-idea]'); if (el) openIdea(el.dataset.tmIdea); });
  board.addEventListener('change', e => { if (tmActive() && e.target.id === 'tmHL') { tmHL = e.target.value; renderTreemap(); } });
  let last = 0;
  board.addEventListener('wheel', e => {            // scroll up = zoom into what is under the pointer, scroll down = zoom out a level
    if (!tmActive() || !e.target.closest('#tmMap')) return;
    e.preventDefault();
    const now = Date.now(); if (now - last < 280) return; last = now;
    if (e.deltaY < 0) { const el = e.target.closest('[data-tm-top]'); if (el && el.dataset.tmTop) tmZoomTo(el.dataset.tmTop); }
    else tmUp();
  }, { passive: false });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && tmActive() && !document.querySelector('dialog[open]')) tmUp(); });
  let rt = 0;
  window.addEventListener('resize', () => { if (tmActive()) { clearTimeout(rt); rt = setTimeout(renderTreemap, 120); } });
})();
