/* Password manager.
   - The server asks for a SECOND password (CONSTELLARIUM_VAULT_PASSWORD) before it sends anything.
   - Everything is also encrypted IN THIS BROWSER (AES-256-GCM, key from that password via PBKDF2-SHA256, 600,000 rounds).
     The database only ever holds ciphertext; the key exists only in memory while the vault is open and is dropped when you
     leave the page, press Lock, log out or are idle for 5 minutes.
   - Passwords are never put on the page until you click that row's eye icon (or Copy). The eye shows ONE item, for 20 s. */
const Vault = { key: null, salt: '', entries: [], shown: new Map(), q: '', idle: 0, pending: null, editing: null };
const IDLE_MS = 5 * 60 * 1000, SHOW_MS = 20 * 1000;
const te = new TextEncoder(), td = new TextDecoder();

const toB64 = buf => { const a = new Uint8Array(buf); let s = ''; for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000)); return btoa(s); };
const fromB64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function deriveKey(pw, saltB64) {
  const base = await crypto.subtle.importKey('raw', te.encode(pw), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt: fromB64(saltB64), iterations: 600000, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}
async function encObj(key, obj, aad) {            // aad ties each blob to its entry + field, so blobs can't be swapped around in the database
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: te.encode(aad) }, key, te.encode(JSON.stringify(obj)));
  return { iv: toB64(iv), ct: toB64(ct) };
}
async function decObj(key, blob, aad) {
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromB64(blob.iv), additionalData: te.encode(aad) }, key, fromB64(blob.ct));
  return JSON.parse(td.decode(pt));
}
const newId = () => [...crypto.getRandomValues(new Uint8Array(5))].map(b => b.toString(16).padStart(2, '0')).join('');

function vaultWipe(tellServer) {
  clearTimeout(Vault.idle);
  for (const s of Vault.shown.values()) clearTimeout(s.timer);
  Vault.shown.clear(); Vault.key = null; Vault.entries = []; Vault.pending = null; Vault.q = '';
  if (tellServer) api('POST', '/api/vault/lock', {}).catch(() => { });
}
function vaultTouch() {                          // idle timer: any activity restarts the 5 minutes
  if (!Vault.key) return;
  clearTimeout(Vault.idle);
  Vault.idle = setTimeout(() => { vaultWipe(true); if (current === 'vault') { toast('Passwords locked after 5 minutes of inactivity.'); Views.vault.render($('#view')); } }, IDLE_MS);
}
['pointerdown', 'keydown', 'scroll'].forEach(ev => document.addEventListener(ev, vaultTouch, { passive: true }));

async function loadEntries() {
  const d = await api('GET', '/api/vault');
  Vault.entries = [];
  for (const e of d.entries) {
    let meta; try { meta = await decObj(Vault.key, e.meta, e.id + ':meta'); } catch (x) { meta = { name: '(could not decrypt)', username: '', url: '' }; }
    Vault.entries.push({ id: e.id, meta, secret: e.secret, updatedAt: e.updatedAt });
  }
}

/* Returns 'ok' | 'mismatch' (the server password was changed since the vault was encrypted). */
async function unlockVault(pw) {
  const r = await api('POST', '/api/vault/unlock', { password: pw });
  Vault.salt = r.salt;
  const k = await deriveKey(pw, r.salt);
  if (!r.check) { await api('PUT', '/api/vault/check', { check: await encObj(k, { ok: 1 }, 'check') }); Vault.key = k; }
  else {
    try { await decObj(k, r.check, 'check'); Vault.key = k; }
    catch (e) { Vault.pending = { k, check: r.check }; return 'mismatch'; }
  }
  await loadEntries(); vaultTouch();
  return 'ok';
}

/* The vault password was changed on the server: open the old data with the old password and re-encrypt it with the new one. */
async function migrateVault(oldPw) {
  const { k: newKey } = Vault.pending;
  const oldKey = await deriveKey(oldPw, Vault.salt);
  try { await decObj(oldKey, Vault.pending.check, 'check'); } catch (e) { throw new Error('That is not the old vault password.'); }
  const d = await api('GET', '/api/vault');
  const entries = [];
  for (const e of d.entries) {
    const meta = await decObj(oldKey, e.meta, e.id + ':meta'), secret = await decObj(oldKey, e.secret, e.id + ':secret');
    entries.push({ id: e.id, createdAt: e.createdAt, meta: await encObj(newKey, meta, e.id + ':meta'), secret: await encObj(newKey, secret, e.id + ':secret') });
  }
  await api('POST', '/api/vault/rekey', { check: await encObj(newKey, { ok: 1 }, 'check'), entries });
  Vault.key = newKey; Vault.pending = null;
  await loadEntries(); vaultTouch();
}

/* ---------- the view ---------- */
Views.vault = {
  async render(el) {
    setCrumbs([{ label: 'Passwords' }]);
    if (Vault.key) return paintVault(el);
    let st;
    try { st = await api('GET', '/api/vault/status'); } catch (e) { if (e.status === 503) return showSetup(e.message); if (e.status === 401) return; toast(e.message, { ms: 5000 }); return; }
    if (!st.configured) {
      el.innerHTML = `<div class="pagehead"><h1 style="--cc:var(--c-vault)">${icon('key')} Passwords</h1></div>
        <div class="setup" style="margin-top:0"><h2 style="margin-top:0">One more step</h2>
        <p>The password manager has its own second password so that even a signed-in session can't open it.</p>
        <p>In Vercel open <b>Settings → Environment Variables</b>, add <code>CONSTELLARIUM_VAULT_PASSWORD</code> (it must be <b>different</b> from your main password, and long), then <b>Redeploy</b>.</p></div>`;
      return;
    }
    paintLock(el);
  },
  leave() { vaultWipe(true); },        // every time you come back in, the second password is asked again
};

function paintLock(el, mismatch) {
  el.innerHTML = `<div class="pagehead"><h1 style="--cc:var(--c-vault)">${icon('key')} Passwords</h1></div>
    <form class="lockbox" id="lockForm" autocomplete="off">
      <div class="bigmark">${icon('lock')}</div>
      ${mismatch ? `<h2>Vault password changed</h2><p class="muted">Your passwords were encrypted with an earlier vault password. Enter the <b>old</b> password once and everything is moved to the new one.</p>`
      : `<h2>Passwords are locked</h2><p class="muted">Enter your second password.</p>`}
      <div class="pwfield"><input type="password" id="vaultPw" name="vaultpw" autocomplete="off" required placeholder="${mismatch ? 'Old vault password' : 'Vault password'}" aria-label="Vault password"><button type="button" class="eyebtn" data-eye="vaultPw" aria-label="Show or hide what I typed"></button></div>
      <div class="errline" id="vaultErr" role="alert"></div>
      <button type="submit" class="primary" id="vaultGo">${mismatch ? 'Move my passwords' : 'Open passwords'}</button>
    </form>`;
  wireEyes(el);
  $('#vaultPw').focus();
  $('#lockForm').onsubmit = async e => {
    e.preventDefault();
    const pw = $('#vaultPw').value, go = $('#vaultGo'), err = $('#vaultErr');
    go.disabled = true; err.textContent = ''; go.textContent = 'Opening…';
    try {
      if (mismatch) { await migrateVault(pw); toast('Moved to the new vault password.'); paintVault($('#view')); }
      else { const r = await unlockVault(pw); if (r === 'mismatch') paintLock($('#view'), true); else paintVault($('#view')); }
    } catch (x) {
      err.textContent = x.message === 'wrong vault password' ? 'That is not the vault password.' : x.message;
      go.disabled = false; go.textContent = mismatch ? 'Move my passwords' : 'Open passwords';
      $('#vaultPw').select();
    }
  };
}

function paintVault(el) {
  el.innerHTML = `<div class="pagehead"><h1 style="--cc:var(--c-vault)">${icon('key')} Passwords</h1><div class="spacer"></div>
      <span class="lockline">${icon('unlock')} Open · locks after 5 min idle</span><button type="button" id="vLock">${icon('lock')} Lock now</button></div>
    <div class="vtools"><input type="search" id="vSearch" placeholder="Search by name, username or website…" autocomplete="off" aria-label="Search passwords"><button type="button" class="primary" id="vAdd">${icon('plus')} Add password</button></div>
    <div id="vlist"></div>`;
  $('#vLock').onclick = () => { vaultWipe(true); toast('Locked.'); Views.vault.render($('#view')); };
  $('#vAdd').onclick = () => openEntryDialog(null);
  $('#vSearch').oninput = e => { Vault.q = e.target.value.toLowerCase(); paintEntries(); };
  $('#vlist').onclick = onVaultClick;
  paintEntries();
}

function paintEntries() {
  const box = $('#vlist'); if (!box) return;
  const q = Vault.q;
  const list = Vault.entries.filter(e => !q || [e.meta.name, e.meta.username, e.meta.url].some(v => (v || '').toLowerCase().includes(q)))
    .sort((a, b) => (a.meta.name || '').localeCompare(b.meta.name || '', undefined, { sensitivity: 'base' }));
  if (!list.length) {
    box.innerHTML = `<div class="empty"><div class="big">${icon('key')}</div>${Vault.entries.length ? 'Nothing matches your search.' : 'No passwords saved yet. Add your first one.'}</div>`;
    return;
  }
  box.innerHTML = list.map(entryRow).join('') + `<p class="muted small" style="text-align:center">${list.length} of ${Vault.entries.length}</p>`;
}

function safeUrl(u) { try { const x = new URL(/^https?:\/\//i.test(u) ? u : 'https://' + u); return /^https?:$/.test(x.protocol) ? x.href : ''; } catch (e) { return ''; } }
function entryRow(e) {
  const sh = Vault.shown.get(e.id), url = e.meta.url ? safeUrl(e.meta.url) : '';
  return `<div class="entry" data-id="${esc(e.id)}">
    <div class="nm" title="${esc(e.meta.name)}">${esc(e.meta.name)}${url ? ` <a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="Open ${esc(url)}">${icon('ext')}</a>` : ''}</div>
    <div class="us">${e.meta.username ? `<span title="${esc(e.meta.username)}" style="overflow:hidden;text-overflow:ellipsis">${esc(e.meta.username)}</span><button type="button" class="iconbtn" data-act="copyuser" title="Copy username" aria-label="Copy username">${icon('copy')}</button>` : '<span class="muted">no username</span>'}</div>
    <div class="pw"><span class="pwtext ${sh ? 'shown' : ''}">${sh ? esc(sh.password || '(empty)') : '••••••••••'}</span>
      <button type="button" class="iconbtn" data-act="eye" title="${sh ? 'Hide' : 'Show this password'}" aria-label="${sh ? 'Hide password' : 'Show password'}" aria-pressed="${sh ? 'true' : 'false'}">${icon(sh ? 'eyeoff' : 'eye')}</button>
      <button type="button" class="iconbtn" data-act="copypw" title="Copy password" aria-label="Copy password">${icon('copy')}</button></div>
    <div class="acts"><button type="button" class="iconbtn" data-act="edit" title="Edit" aria-label="Edit">${icon('edit')}</button><button type="button" class="iconbtn del" data-act="del" title="Delete" aria-label="Delete">${icon('trash')}</button></div>
    ${sh && sh.notes ? `<div class="secretnote">${esc(sh.notes)}</div>` : ''}</div>`;
}

async function secretOf(e) { return decObj(Vault.key, e.secret, e.id + ':secret'); }
function repaintRow(id) {
  const e = Vault.entries.find(x => x.id === id), el = $(`.entry[data-id="${id}"]`);
  if (e && el) el.outerHTML = entryRow(e);
}
function hideSecret(id) {
  const s = Vault.shown.get(id); if (s) clearTimeout(s.timer);
  Vault.shown.delete(id); repaintRow(id);
}
async function copyText(text, what) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${what} copied` + (what === 'Password' ? ' · clipboard clears in 20 s' : ''));
    if (what === 'Password') setTimeout(() => navigator.clipboard.writeText('').catch(() => { }), SHOW_MS);
  } catch (e) { toast('Could not copy: your browser blocked clipboard access.', { ms: 5000 }); }
}

async function onVaultClick(ev) {
  const b = ev.target.closest('[data-act]'); if (!b) return;
  const id = b.closest('.entry').dataset.id, e = Vault.entries.find(x => x.id === id); if (!e) return;
  const act = b.dataset.act;
  try {
    if (act === 'eye') {
      if (Vault.shown.has(id)) return hideSecret(id);
      const sec = await secretOf(e);
      Vault.shown.set(id, { ...sec, timer: setTimeout(() => hideSecret(id), SHOW_MS) });     // only THIS entry is revealed
      repaintRow(id);
    } else if (act === 'copyuser') await copyText(e.meta.username, 'Username');
    else if (act === 'copypw') await copyText((await secretOf(e)).password || '', 'Password');
    else if (act === 'edit') openEntryDialog(e);
    else if (act === 'del') {
      if (!confirm(`Delete "${e.meta.name}"? This can't be undone (a backup of the vault is kept).`)) return;
      await api('DELETE', '/api/vault/entries/' + id);
      hideSecret(id); Vault.entries = Vault.entries.filter(x => x.id !== id); paintEntries(); toast('Deleted.');
    }
  } catch (err) {
    if (err.status === 401) { vaultWipe(false); Views.vault.render($('#view')); toast('Locked. Enter the vault password again.'); }
    else toast(err.message, { ms: 5000 });
  }
}

/* ---------- add / edit ---------- */
const PW_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+?';
function generatePassword(n = 20) {
  const out = []; const lim = 256 - (256 % PW_CHARS.length);
  while (out.length < n) for (const b of crypto.getRandomValues(new Uint8Array(n * 2))) { if (b < lim && out.length < n) out.push(PW_CHARS[b % PW_CHARS.length]); }
  return out.join('');
}
async function openEntryDialog(e) {
  Vault.editing = e;
  const f = $('#entryForm'); f.reset(); resetEye('entryPw'); $('#entryErr').textContent = '';
  $('#entryDlgTitle').textContent = e ? 'Edit password' : 'Add a password';
  f.name.value = e ? e.meta.name : ''; f.username.value = e ? e.meta.username || '' : ''; f.url.value = e ? e.meta.url || '' : '';
  if (e) { try { const s = await secretOf(e); f.password.value = s.password || ''; f.notes.value = s.notes || ''; } catch (x) { $('#entryErr').textContent = 'Could not decrypt this entry.'; } }
  wireEyes($('#entryDlg'));
  $('#entryDlg').showModal(); f.name.focus();
}
$('#entryGen').onclick = () => { const i = $('#entryPw'); i.value = generatePassword(); i.type = 'text'; $('[data-eye="entryPw"]').innerHTML = icon('eyeoff'); };
$('#entryCancel').onclick = () => { $('#entryForm').reset(); $('#entryDlg').close(); };
$('#entryDlg').addEventListener('close', () => { $('#entryForm').reset(); resetEye('entryPw'); });     // never leave a typed password in the form
$('#entryForm').onsubmit = async ev => {
  ev.preventDefault();
  const f = ev.target, cur = Vault.editing, id = cur ? cur.id : newId();
  const meta = { name: f.name.value.trim(), username: f.username.value.trim(), url: f.url.value.trim() };
  const secret = { password: f.password.value, notes: f.notes.value };
  if (!meta.name) { $('#entryErr').textContent = 'Give it a name.'; return; }
  $('#entrySave').disabled = true;
  try {
    const body = { id, meta: await encObj(Vault.key, meta, id + ':meta'), secret: await encObj(Vault.key, secret, id + ':secret') };
    if (cur) { await api('PUT', '/api/vault/entries/' + id, body); cur.meta = meta; cur.secret = body.secret; if (Vault.shown.has(id)) hideSecret(id); }
    else { await api('POST', '/api/vault/entries', body); Vault.entries.push({ id, meta, secret: body.secret }); }
    $('#entryDlg').close(); paintEntries(); toast(cur ? 'Saved.' : 'Added.');
  } catch (err) {
    if (err.status === 401) { $('#entryDlg').close(); vaultWipe(false); Views.vault.render($('#view')); toast('Locked. Enter the vault password again.'); }
    else $('#entryErr').textContent = err.message;
  } finally { $('#entrySave').disabled = false; }
};
