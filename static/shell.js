/* Shared helpers for the home page: DOM, escaping, API calls, toast, icons. No inline scripts anywhere (CSP: script-src 'self'). */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const ICON_PATHS = {
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7c1.8 0 3.4-.5 4.8-1.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  unlock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
  tasks: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M3.5 6l1.5 1.5L7 5M3.5 12l1.5 1.5L7 11M3.5 18l1.5 1.5L7 17"/>',
  banks: '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="8" r="2"/><circle cx="12" cy="18" r="2"/><path d="M6.8 6.7l10.4 1M17.9 9.8l-4.8 6.4M10.7 16.6L6 7.9"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`;

/* The browser's own calendar date (YYYY-MM-DD), sent to the server so 'due today / overdue' uses your day, not the server's. */
const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

let onLoginNeeded = () => { };
async function api(method, url, body) {
  const r = await fetch(url, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Today': todayStr() }, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let j = {};
  try { j = text ? JSON.parse(text) : {}; } catch (e) { throw Object.assign(new Error(`Unexpected reply from the server (${r.status}).`), { status: r.status }); }
  if (r.status === 401 && j.login) onLoginNeeded();            // main session missing / expired
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { status: r.status, data: j });
  return j;
}

let toastTimer = 0;
function toast(msg, opts = {}) {
  const t = $('#toast');
  t.innerHTML = `<span>${esc(msg)}</span>${opts.action ? `<button type="button">${esc(opts.action)}</button>` : ''}`;
  t.hidden = false;
  if (opts.action) t.querySelector('button').onclick = () => { t.hidden = true; opts.onAction && opts.onAction(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, opts.ms || 3200);
}

/* eye buttons next to password inputs: <button data-eye="inputId"> toggles that one input only */
function wireEyes(root = document) {
  $$('[data-eye]', root).forEach(b => {
    if (b._wired) return; b._wired = true;
    const input = document.getElementById(b.dataset.eye);
    const paint = () => { b.innerHTML = icon(input.type === 'password' ? 'eye' : 'eyeoff'); };
    b.onclick = () => { input.type = input.type === 'password' ? 'text' : 'password'; paint(); input.focus(); };
    paint();
  });
}
const resetEye = id => { const i = document.getElementById(id); if (i) { i.type = 'password'; const b = $(`[data-eye="${id}"]`); if (b) b.innerHTML = icon('eye'); } };

const Views = {};      // name -> { render(el), leave() }  (home, banks in hub.js; todo in todo.js; vault in vault.js)
const bankLabel = b => (b === "problembank" ? "ProblemBank" : "IdeaBank");
