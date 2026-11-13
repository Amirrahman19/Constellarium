/* Board view: each category is a small table of idea titles; project cards sit on the right,
   positioned near the categories that feed them; SVG curves show the links. */
const BOARD_ROWS = 6;
const boardOpen = new Set();   // category ids showing all rows
let boardHL = null;            // {cat|proj|idea} currently highlighted
let boardLinks = [];           // [{cat, proj, n}] aggregated
let boardScale = 1;
let boardPin = null;           // {key, hl} - click-to-pin selection; stays until clicked again / Esc
function boardZoom(f) {
  boardScale = f === 0 ? 1 : Math.max(0.4, Math.min(1.6, +(boardScale * f).toFixed(3)));
  const inner = document.querySelector('#board .board-inner');
  if (inner) { inner.style.transform = `scale(${boardScale})`; boardLayout(); }
}

function renderBoard() {
  const root = $('#board');
  const ideas = filteredIdeas();
  const cats = catById(), projs = projById();
  const byCat = new Map();
  for (const i of ideas) { const k = i.category || '__none'; (byCat.get(k) || byCat.set(k, []).get(k)).push(i); }

  const statusCls = s => 'st st-' + s;
  const dotsFor = i => (i.projects || []).map(p => projs.get(p)).filter(Boolean).map(p => `<span class="dot" title="${esc(p.name)}" style="background:${esc(p.color)}"></span>`).join('');
  const card = (c, label) => {
    const list = byCat.get(c.id) || [];
    const open = boardOpen.has(c.id), shown = open ? list : list.slice(0, BOARD_ROWS);
    return `<div class="bcard" data-bcat="${c.id}" style="--c:${esc(c.color)}">
      <div class="bh" data-bhead="cat:${c.id}"><span class="dot" style="background:${esc(c.color)}"></span><b>${esc(label)}</b><span class="cnt">${list.length}</span></div>
      <table>${shown.map(i => `<tr class="brow" data-brow="${i.id}"><td class="${statusCls(i.status)}" title="${esc(i.status)}"></td><td class="bt" title="${esc(i.title)}">${esc(i.title)}</td><td class="pd">${dotsFor(i)}</td></tr>`).join('')}
      ${list.length > BOARD_ROWS ? `<tr class="bmore" data-bmore="${c.id}"><td></td><td colspan="2">${open ? 'show less' : `+ ${list.length - BOARD_ROWS} more`}</td></tr>` : ''}</table></div>`;
  };

  // ---- left: families (top-level category + descendants) ----
  let left = '';
  const members = (t) => { const out = []; const walk = (id, d) => { out.push([cats.get(id), d]); childrenOf(id).forEach(k => walk(k.id, d + 1)); }; walk(t.id, 0); return out; };
  for (const top of childrenOf(null)) {
    const mem = members(top).filter(([c]) => (byCat.get(c.id) || []).length);
    if (!mem.length) continue;
    const total = mem.reduce((n, [c]) => n + byCat.get(c.id).length, 0);
    left += `<div class="bfam"><h4 class="bfh" style="--c:${esc(top.color)}"><span class="dot" style="background:${esc(top.color)}"></span>${esc(top.name)} <span class="badge">${total}</span></h4>
      <div class="bcards">${mem.map(([c, d]) => card(c, d === 0 ? c.name : catPath(c.id).split(' › ').slice(1).join(' › '))).join('')}</div></div>`;
  }
  if (byCat.get('__none')) left += `<div class="bfam"><h4 class="bfh"><span class="dot" style="background:#999"></span>Uncategorised</h4><div class="bcards">${card({ id: '__none', name: 'Uncategorised', color: '#999' }, 'Uncategorised')}</div></div>`;

  // ---- aggregate category -> project ----
  const agg = new Map(); let noProj = new Map();
  for (const i of ideas) {
    const ck = i.category || '__none';
    const ps = (i.projects || []).filter(p => projs.has(p));
    if (!ps.length) noProj.set(ck, (noProj.get(ck) || 0) + 1);
    for (const p of ps) { const k = ck + '|' + p; agg.set(k, (agg.get(k) || 0) + 1); }
  }
  boardLinks = [...agg].map(([k, n]) => { const [cat, proj] = k.split('|'); return { cat, proj, n }; });

  // ---- right: project cards ----
  const pcount = new Map(); for (const l of boardLinks) pcount.set(l.proj, (pcount.get(l.proj) || 0) + l.n);
  const usedProj = S.projects.filter(p => pcount.get(p.id) || F.project === p.id);
  const catName = id => id === '__none' ? 'Uncategorised' : ((cats.get(id) || {}).name || '?');
  const pcard = p => {
    const rows = boardLinks.filter(l => l.proj === p.id).sort((a, b) => b.n - a.n);
    return `<div class="pcard" data-bproj="${p.id}" style="--c:${esc(p.color)}">
      <div class="bh" data-bhead="proj:${p.id}"><span class="dia" style="background:${esc(p.color)}"></span><b>${esc(p.name)}</b><span class="cnt">${pcount.get(p.id) || 0}</span></div>
      <table>${rows.slice(0, 8).map(l => `<tr data-gocat="${l.cat}"><td class="bt">${esc(catName(l.cat))}</td><td class="pn">${l.n}</td></tr>`).join('')}${rows.length > 8 ? `<tr><td class="muted">+ ${rows.length - 8} more</td><td></td></tr>` : ''}</table></div>`;
  };
  const noProjTotal = [...noProj.values()].reduce((a, b) => a + b, 0);
  const npCard = noProjTotal ? `<div class="pcard np" data-bproj="__np"><div class="bh"><span class="dia" style="background:#999"></span><b>Not linked to a project</b><span class="cnt">${noProjTotal}</span></div>
      <table>${[...noProj].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([c, n]) => `<tr data-gocat="${c}"><td class="bt">${esc(catName(c))}</td><td class="pn">${n}</td></tr>`).join('')}</table></div>` : '';

  root.innerHTML = `<div class="board-inner"><svg class="blinks"></svg><div class="bleft">${left || '<div class="muted" style="padding:30px">No ideas match the current filters.</div>'}</div><div class="bmid"></div>
    <div class="bright">${usedProj.map(pcard).join('')}${npCard}</div></div>`;
  root.querySelector('.board-inner').style.transform = `scale(${boardScale})`;
  boardLayout();
}

function boardLayout() {
  const root = $('#board'); const inner = root.querySelector('.board-inner'); if (!inner) return;
  const right = inner.querySelector('.bright');
  const base = inner.getBoundingClientRect();
  const y = el => { const r = el.getBoundingClientRect(); return (r.top - base.top + r.height / 2) / boardScale; };
  const catCards = new Map([...inner.querySelectorAll('.bcard')].map(el => [el.dataset.bcat, el]));
  // place project cards near the weighted centre of the categories that feed them, then de-overlap
  const items = [...right.querySelectorAll('.pcard')].map(el => {
    const id = el.dataset.bproj; const ls = boardLinks.filter(l => l.proj === id && catCards.has(l.cat));
    const w = ls.reduce((a, l) => a + l.n, 0);
    const want = w ? ls.reduce((a, l) => a + y(catCards.get(l.cat)) * l.n, 0) / w : 1e9;
    return { el, want, h: el.offsetHeight };
  }).sort((a, b) => a.want - b.want);
  let cursor = 0;
  for (const it of items) {
    const top = Math.max(cursor, it.want === 1e9 ? cursor : it.want - it.h / 2);
    it.el.style.top = top + 'px'; cursor = top + it.h + 12;
  }
  const leftH = inner.querySelector('.bleft').offsetHeight;
  right.style.height = Math.max(cursor, leftH) + 'px';
  drawBoardLinks();
}

function drawBoardLinks() {
  const root = $('#board'); const inner = root.querySelector('.board-inner'); if (!inner) return;
  const svg = inner.querySelector('.blinks'); const base = inner.getBoundingClientRect();
  svg.setAttribute('width', inner.scrollWidth); svg.setAttribute('height', inner.scrollHeight);
  const pt = (el, side, rowEl) => { const r = el.getBoundingClientRect(); const h = (rowEl || el.querySelector('.bh')).getBoundingClientRect(); return [((side === 'r' ? r.right : r.left) - base.left) / boardScale, (h.top - base.top + h.height / 2) / boardScale]; };
  const projs = projById();
  let out = '';
  const hl = boardHL;
  for (const l of boardLinks) {
    const ce = inner.querySelector(`.bcard[data-bcat="${l.cat}"]`), pe = inner.querySelector(`.pcard[data-bproj="${l.proj}"]`);
    if (!ce || !pe) continue;
    const [x1, y1] = pt(ce, 'r'), [x2, y2] = pt(pe, 'l'); const dx = Math.max(40, (x2 - x1) * 0.5);
    const on = !hl || (hl.cat === l.cat) || (hl.proj === l.proj) || (hl.ideaCat === l.cat && hl.ideaProjs && hl.ideaProjs.includes(l.proj));
    const col = (projs.get(l.proj) || {}).color || '#999';
    out += `<path d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}" fill="none" stroke="${esc(col)}" stroke-width="${(1.2 + Math.min(6, l.n * 0.8)).toFixed(1)}" stroke-opacity="${on ? (hl ? 0.9 : 0.5) : 0.07}"/>`;
  }
  // row-level links while hovering an idea
  if (hl && hl.idea) {
    const row = inner.querySelector(`.brow[data-brow="${hl.idea}"]`);
    if (row) for (const p of hl.ideaProjs || []) {
      const pe = inner.querySelector(`.pcard[data-bproj="${p}"]`); if (!pe) continue;
      const rr = row.getBoundingClientRect(); const x1 = (rr.right - base.left) / boardScale, y1 = (rr.top - base.top + rr.height / 2) / boardScale;
      const [x2, y2] = pt(pe, 'l'); const dx = Math.max(40, (x2 - x1) * 0.5);
      out += `<path d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}" fill="none" stroke="${esc((projs.get(p) || {}).color || '#999')}" stroke-width="2.5" stroke-dasharray="5 3"/>`;
    }
  }
  svg.innerHTML = out;
  // dim non-related cards
  inner.querySelectorAll('.bcard,.pcard').forEach(el => {
    let dim = false;
    if (hl) {
      const cid = el.dataset.bcat, pid = el.dataset.bproj;
      if (cid !== undefined) dim = !(hl.cat === cid || hl.ideaCat === cid || (hl.proj && boardLinks.some(l => l.proj === hl.proj && l.cat === cid)));
      else dim = !(hl.proj === pid || (hl.cat && boardLinks.some(l => l.cat === hl.cat && l.proj === pid)) || (hl.ideaProjs && hl.ideaProjs.includes(pid)));
    }
    el.classList.toggle('bdim', dim);
  });
  // pinned element keeps a visible "selected" outline
  inner.querySelectorAll('.bpin').forEach(el => el.classList.remove('bpin'));
  if (boardPin) {
    const [k, id] = boardPin.key.split(':');
    const sel = k === 'idea' ? `.brow[data-brow="${id}"]` : k === 'cat' ? `.bcard[data-bcat="${id}"]` : `.pcard[data-bproj="${id}"]`;
    const el = inner.querySelector(sel); if (el) el.classList.add('bpin');
  }
}

function boardSetHL(h) { boardHL = h; drawBoardLinks(); }

(function wireBoard() {
  const root = document.getElementById('board');
  // highlight descriptor + pin key for whatever is under the pointer (null if nothing highlightable)
  const target = e => {
    const row = e.target.closest('.brow'), card = e.target.closest('.bcard'), pc = e.target.closest('.pcard');
    if (row) { const i = S.ideas.find(x => x.id === row.dataset.brow); return { key: 'idea:' + i.id, hl: { idea: i.id, ideaCat: i.category || '__none', ideaProjs: i.projects || [] } }; }
    const head = e.target.closest('[data-bhead]');
    if (head && card) return { key: 'cat:' + card.dataset.bcat, hl: { cat: card.dataset.bcat } };
    if (head && pc && pc.dataset.bproj !== '__np') return { key: 'proj:' + pc.dataset.bproj, hl: { proj: pc.dataset.bproj } };
    if (card) return { key: 'cat:' + card.dataset.bcat, hl: { cat: card.dataset.bcat } };
    if (pc && pc.dataset.bproj !== '__np') return { key: 'proj:' + pc.dataset.bproj, hl: { proj: pc.dataset.bproj } };
    return null;
  };
  root.addEventListener('mouseover', e => {
    if (boardPin) return;                       // a pinned selection stays put while you browse
    const t = target(e);
    if (t) boardSetHL(t.hl); else if (boardHL) boardSetHL(null);
  });
  root.addEventListener('mouseleave', () => { if (!boardPin) boardSetHL(null); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && boardPin) { boardPin = null; boardSetHL(null); } });
  root.addEventListener('click', e => {
    const more = e.target.closest('[data-bmore]');
    if (more) { const id = more.dataset.bmore; boardOpen.has(id) ? boardOpen.delete(id) : boardOpen.add(id); renderBoard(); return; }
    if (e.target.closest('tr[data-gocat]')) return;   // project-card category rows filter (handled globally)
    const t = target(e);
    if (!t) { return; }
    if (boardPin && boardPin.key === t.key) { boardPin = null; boardSetHL(t.hl); $('#detail').hidden = true; return; } // click again = deselect
    boardPin = t; boardSetHL(t.hl);
    $('#detail').classList.toggle('dock-left', !!e.target.closest('.pcard'));
    const row = e.target.closest('.brow'), head = e.target.closest('[data-bhead]');
    if (row) showDetail({ type: 'idea', data: S.ideas.find(x => x.id === row.dataset.brow) });
    else if (head) {
      const [k, id] = head.dataset.bhead.split(':');
      if (k === 'cat') { const c = S.categories.find(x => x.id === id); if (c) showDetail({ type: 'category', data: c }); }
      else { const p = S.projects.find(x => x.id === id); if (p) showDetail({ type: 'project', data: p }); }
    }
  });
  root.addEventListener('dblclick', e => { const row = e.target.closest('.brow'); if (row) openIdea(row.dataset.brow); });
  new ResizeObserver(() => { if (!root.hidden) boardLayout(); }).observe(root);
})();
