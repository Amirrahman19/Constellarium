/* Minimal dependency-free force-directed graph on <canvas>.
   Nodes: {id, type:'category'|'project'|'idea'|'tag', label, color, r, ring?, data}
   Links: {source, target, kind:'tree'|'cat'|'proj'|'related'|'tag'|'map', w}
*/
class Graph {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = []; this.links = []; this.byId = new Map();
    this.k = 1; this.tx = 0; this.ty = 0;
    this.alpha = 0; this.running = false;
    this.hover = null; this.selected = null; this.drag = null; this.pan = null;
    this.onSelect = opts.onSelect || (() => {});
    this.onHover = opts.onHover || (() => {});
    this.onDouble = opts.onDouble || (() => {});
    this.pos = new Map(); // remembered positions across rebuilds
    this.theme = {};
    this._bind();
    this.readTheme();
    new ResizeObserver(() => { this.resize(); this.draw(); }).observe(canvas.parentElement);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { this.readTheme(); this.draw(); });
  }

  readTheme() {
    const cs = getComputedStyle(document.documentElement);
    this.theme = {
      edge: cs.getPropertyValue('--edge').trim() || 'rgba(120,130,150,.4)',
      text: cs.getPropertyValue('--text').trim() || '#222',
      halo: cs.getPropertyValue('--label-halo').trim() || 'rgba(255,255,255,.9)',
      bg: cs.getPropertyValue('--bg').trim() || '#fff',
    };
  }

  resize() {
    const r = this.c.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = r.width; this.h = r.height; this.dpr = dpr;
    this.c.width = Math.max(1, Math.round(r.width * dpr));
    this.c.height = Math.max(1, Math.round(r.height * dpr));
  }

  setData(nodes, links) {
    for (const n of this.nodes) this.pos.set(n.id, { x: n.x, y: n.y });
    this.byId = new Map();
    const fresh = [];
    nodes.forEach((n, i) => {
      const p = this.pos.get(n.id);
      if (p) { n.x = p.x; n.y = p.y; } else { fresh.push(n); }
      n.vx = 0; n.vy = 0;
      this.byId.set(n.id, n);
    });
    // place new nodes near a connected neighbour (or on a ring) so layout settles fast
    const neigh = new Map();
    for (const l of links) {
      (neigh.get(l.source) || neigh.set(l.source, []).get(l.source)).push(l.target);
      (neigh.get(l.target) || neigh.set(l.target, []).get(l.target)).push(l.source);
    }
    fresh.forEach((n, i) => {
      const nb = (neigh.get(n.id) || []).map(id => this.byId.get(id)).find(m => m && m.x !== undefined);
      if (nb) { n.x = nb.x + (Math.random() - .5) * 40; n.y = nb.y + (Math.random() - .5) * 40; }
      else { const a = i * 2.4, rad = 40 + 14 * Math.sqrt(i); n.x = Math.cos(a) * rad; n.y = Math.sin(a) * rad; }
    });
    this.nodes = nodes;
    this.links = links.filter(l => this.byId.has(l.source) && this.byId.has(l.target))
      .map(l => ({ ...l, s: this.byId.get(l.source), t: this.byId.get(l.target) }));
    this.adj = new Map(nodes.map(n => [n.id, new Set()]));
    for (const l of this.links) { this.adj.get(l.source).add(l.target); this.adj.get(l.target).add(l.source); }
    if (this.selected && !this.byId.has(this.selected)) this.selected = null;
    // pre-settle synchronously so the user never sees a hairball (and so layout doesn't depend on frame rate)
    const allFresh = fresh.length === nodes.length;
    this.alpha = allFresh ? 1 : 0.6;
    const budget = nodes.length > 500 ? 90 : 260;
    for (let i = 0; i < budget && this.alpha > 0.03; i++) this._tick();
    if (!this.w) this.resize();
    if (allFresh) { this.fit(); }
    this.heat(Math.max(this.alpha, 0.05));
  }

  heat(a = 1) { this.alpha = Math.max(this.alpha, a); this._loop(); }

  _loop() {
    if (this.running) return;
    this.running = true;
    const step = () => {
      const iters = this.nodes.length > 400 ? 1 : 2;
      for (let i = 0; i < iters && this.alpha > 0.004; i++) this._tick();
      if (this._pendingFit && this.alpha < 0.5 && !this._earlyFit) { this.fit(); this._earlyFit = true; }
      else if (this._pendingFit && this.alpha < 0.08 && !this.drag) this.fit();
      this.draw();
      if (this.alpha > 0.004 || this.drag) requestAnimationFrame(step);
      else { this.running = false; if (this._pendingFit) { this.fit(); this._pendingFit = false; this._earlyFit = false; this.draw(); } }
    };
    requestAnimationFrame(step);
  }

  _tick() {
    const N = this.nodes, a = this.alpha;
    // repulsion + collision
    for (let i = 0; i < N.length; i++) {
      const p = N[i];
      for (let j = i + 1; j < N.length; j++) {
        const q = N[j];
        let dx = q.x - p.x, dy = q.y - p.y, d2 = dx * dx + dy * dy;
        if (d2 > 640000) continue;
        if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
        const d = Math.sqrt(d2);
        const strength = 3200 * (0.5 + (p.r + q.r) / 30);
        let f = (strength / d2) * a;
        const min = p.r + q.r + 6;
        if (d < min) f += (min - d) * 0.08;
        const fx = dx / d * f, fy = dy / d * f;
        p.vx -= fx; p.vy -= fy; q.vx += fx; q.vy += fy;
      }
    }
    // springs
    for (const l of this.links) {
      const len = { tree: 130, cat: 55, proj: 85, related: 70, tag: 45, map: 230 }[l.kind] || 70;
      const str = { tree: .12, cat: .16, proj: .05, related: .04, tag: .05, map: .03 }[l.kind] || .06;
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1;
      const L = len + (l.s.r + l.t.r) * 0.5;
      const f = (d - L) * str * a * (l.w ? Math.min(2, 0.7 + 0.3 * l.w) : 1);
      const fx = dx / d * f, fy = dy / d * f;
      l.s.vx += fx; l.s.vy += fy; l.t.vx -= fx; l.t.vy -= fy;
    }
    // gravity + integrate
    for (const n of this.nodes) {
      n.vx -= n.x * 0.006 * a; n.vy -= n.y * 0.006 * a;
      if (n.fixed) { n.vx = n.vy = 0; continue; }
      n.vx *= 0.62; n.vy *= 0.62;
      n.x += Math.max(-40, Math.min(40, n.vx)); n.y += Math.max(-40, Math.min(40, n.vy));
    }
    this.alpha *= 0.978;
  }

  fit(pad = 60) {
    if (!this.nodes.length) return;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const n of this.nodes) { x0 = Math.min(x0, n.x - n.r); x1 = Math.max(x1, n.x + n.r); y0 = Math.min(y0, n.y - n.r); y1 = Math.max(y1, n.y + n.r); }
    const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
    this.k = Math.max(0.15, Math.min(2, Math.min((this.w - pad * 2) / w, (this.h - pad * 2) / h)));
    this.tx = this.w / 2 - ((x0 + x1) / 2) * this.k;
    this.ty = this.h / 2 - ((y0 + y1) / 2) * this.k;
    this.draw();
  }

  toWorld(px, py) { return [(px - this.tx) / this.k, (py - this.ty) / this.k]; }

  pick(px, py) {
    const [x, y] = this.toWorld(px, py);
    for (let i = this.nodes.length - 1; i >= 0; i--) {
      const n = this.nodes[i];
      const r = n.r + 4 / this.k;
      if ((n.x - x) ** 2 + (n.y - y) ** 2 <= r * r) return n;
    }
    return null;
  }

  _bind() {
    const c = this.c;
    const pt = e => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.addEventListener('pointerdown', e => {
      c.setPointerCapture(e.pointerId);
      const [px, py] = pt(e); const n = this.pick(px, py);
      this.down = { px, py, moved: false, node: n };
      if (n) { this.drag = n; n.fixed = true; this.heat(0.3); } else { this.pan = { px, py, tx: this.tx, ty: this.ty }; c.classList.add('dragging'); }
    });
    c.addEventListener('pointermove', e => {
      const [px, py] = pt(e);
      if (this.down) {
        if (Math.hypot(px - this.down.px, py - this.down.py) > 4) this.down.moved = true;
        if (this.drag && this.down.moved) { const [x, y] = this.toWorld(px, py); this.drag.x = x; this.drag.y = y; this.heat(0.3); }
        else if (this.pan) { this.tx = this.pan.tx + px - this.pan.px; this.ty = this.pan.ty + py - this.pan.py; this.draw(); }
        return;
      }
      const n = this.pick(px, py);
      if (n !== this.hover) { this.hover = n; c.classList.toggle('hovering', !!n); this.onHover(n, px, py); this.draw(); }
      else if (n) this.onHover(n, px, py);
    });
    const up = e => {
      if (!this.down) return;
      const { node, moved } = this.down;
      if (this.drag) { this.drag.fixed = false; }
      if (!moved) { this.selected = node ? node.id : null; this.onSelect(node); }
      this.drag = null; this.pan = null; this.down = null; c.classList.remove('dragging'); this.draw();
    };
    c.addEventListener('pointerup', up); c.addEventListener('pointercancel', up);
    c.addEventListener('pointerleave', () => { if (!this.down && this.hover) { this.hover = null; this.onHover(null); this.draw(); } });
    c.addEventListener('dblclick', e => { const [px, py] = pt(e); const n = this.pick(px, py); if (n) this.onDouble(n); });
    c.addEventListener('wheel', e => {
      e.preventDefault();
      const [px, py] = pt(e); const f = Math.exp(-e.deltaY * 0.0015);
      const nk = Math.max(0.1, Math.min(6, this.k * f));
      this.tx = px - (px - this.tx) * (nk / this.k); this.ty = py - (py - this.ty) * (nk / this.k); this.k = nk;
      this.draw();
    }, { passive: false });
  }

  zoomBy(f) {
    const px = this.w / 2, py = this.h / 2, nk = Math.max(0.1, Math.min(6, this.k * f));
    this.tx = px - (px - this.tx) * (nk / this.k); this.ty = py - (py - this.ty) * (nk / this.k); this.k = nk;
    this.draw();
  }

  select(id) { this.selected = id; this.draw(); }

  draw() {
    const ctx = this.ctx, T = this.theme, dpr = this.dpr || 1;
    if (!this.w) { this.resize(); }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.c.width, this.c.height);
    const focus = this.hover ? this.hover.id : this.selected;
    const near = focus ? this.adj.get(focus) : null;
    const on = id => !focus || id === focus || (near && near.has(id));
    const k = this.k;
    ctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * this.tx, dpr * this.ty);

    // links
    for (const l of this.links) {
      const lit = !focus || ((l.source === focus || l.target === focus));
      ctx.globalAlpha = lit ? (focus ? 0.9 : 1) : 0.08;
      let col = T.edge, lw = 1;
      if (l.kind === 'tree') { col = l.t.color; lw = 2; }
      else if (l.kind === 'cat') { col = l.t.type === 'category' ? l.t.color : l.s.color; lw = 1.2; }
      else if (l.kind === 'proj') { col = (l.s.type === 'project' ? l.s : l.t).color; lw = 1.2; ctx.setLineDash([4 / k, 3 / k]); }
      else if (l.kind === 'map') { col = (l.s.type === 'project' ? l.s : l.t).color; lw = 1 + Math.min(8, (l.w || 1) * 1.6); }
      else if (l.kind === 'related') { col = T.text; ctx.globalAlpha *= 0.35; lw = 1.2; ctx.setLineDash([2 / k, 3 / k]); }
      ctx.strokeStyle = col; ctx.lineWidth = lw / (l.kind === 'map' ? 1 : k) * (l.kind === 'map' ? 1 : 1);
      if (l.kind !== 'map') ctx.lineWidth = lw / Math.max(k, 0.6);
      if (l.kind === 'map') ctx.globalAlpha *= 0.55;
      ctx.beginPath(); ctx.moveTo(l.s.x, l.s.y); ctx.lineTo(l.t.x, l.t.y); ctx.stroke();
      ctx.setLineDash([]);
    }

    // nodes
    for (const n of this.nodes) {
      ctx.globalAlpha = on(n.id) ? 1 : 0.12;
      ctx.beginPath();
      if (n.type === 'project') {
        const r = n.r; ctx.moveTo(n.x, n.y - r); ctx.lineTo(n.x + r, n.y); ctx.lineTo(n.x, n.y + r); ctx.lineTo(n.x - r, n.y); ctx.closePath();
      } else if (n.type === 'category') {
        const r = n.r, s = r * 0.8; this._rr(ctx, n.x - r, n.y - s, r * 2, s * 2, r * 0.45);
      } else ctx.arc(n.x, n.y, n.r, 0, 6.2832);
      if (n.ring) { ctx.fillStyle = T.bg; ctx.fill(); ctx.lineWidth = 2 / k; ctx.strokeStyle = n.color; ctx.setLineDash([3 / k, 2 / k]); ctx.stroke(); ctx.setLineDash([]); }
      else { ctx.fillStyle = n.color; ctx.fill(); }
      if (n.id === this.selected || (this.hover && n.id === this.hover.id)) { ctx.lineWidth = 2.5 / k; ctx.strokeStyle = T.text; ctx.stroke(); }
    }

    // labels in screen space
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    const many = this.nodes.length > 60;
    for (const n of this.nodes) {
      const isFocus = focus && on(n.id);
      let show = n.type === 'category' || n.type === 'project';
      if (n.type === 'idea') show = isFocus || k > (many ? 1.15 : 0.6);
      if (n.type === 'tag') show = isFocus || k > 1.5;
      if (!show) continue;
      ctx.globalAlpha = on(n.id) ? 1 : 0.15;
      const big = n.type === 'category' || n.type === 'project';
      ctx.font = `${big ? '600 13px' : '11.5px'} system-ui, "Segoe UI", sans-serif`;
      const sx = n.x * k + this.tx, sy = n.y * k + this.ty + (n.r * k) + 3;
      const text = n.label.length > 30 ? n.label.slice(0, 29) + '…' : n.label;
      ctx.lineWidth = 4; ctx.strokeStyle = T.halo; ctx.lineJoin = 'round'; ctx.strokeText(text, sx, sy);
      ctx.fillStyle = T.text; ctx.fillText(text, sx, sy);
    }
    ctx.globalAlpha = 1;
  }

  _rr(ctx, x, y, w, h, r) {
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  png() {
    const a = document.createElement('a');
    const tmp = document.createElement('canvas'); tmp.width = this.c.width; tmp.height = this.c.height;
    const t = tmp.getContext('2d'); t.fillStyle = this.theme.bg; t.fillRect(0, 0, tmp.width, tmp.height); t.drawImage(this.c, 0, 0);
    a.href = tmp.toDataURL('image/png'); a.download = 'constellarium-graph.png'; a.click();
  }
}
