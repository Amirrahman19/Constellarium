/* Home: sign in, the three cards, the Banks chooser, routing between the views. */
let current = '';

function setCrumbs(parts) {      // [{label, href?}] after "Home"
  $('#crumbs').innerHTML = parts.map(p => `<span>/</span>${p.href ? `<a href="${p.href}">${esc(p.label)}</a>` : `<b>${esc(p.label)}</b>`}`).join('');
}

function showLogin() {
  $('#app').hidden = true; $('#login').hidden = false;
  if (Views[current] && Views[current].leave) Views[current].leave();
  $('#loginPw').value = ''; resetEye('loginPw');
  setTimeout(() => $('#loginPw').focus(), 30);
}
onLoginNeeded = showLogin;

function showSetup(msg) {
  $('#login').hidden = true; $('#app').hidden = false; setCrumbs([]);
  let fix = 'Check the deployment logs in Vercel.';
  if (/CONSTELLARIUM_PASSWORD/.test(msg)) fix = 'In Vercel open <b>Settings → Environment Variables</b>, add <code>CONSTELLARIUM_PASSWORD</code> (the main password you will log in with), then <b>Redeploy</b>.';
  else if (/No database/i.test(msg)) fix = 'In Vercel open <b>Storage</b>, create or connect a <b>Neon</b> database to this project, then <b>Redeploy</b>. Your ideas are loaded into it automatically the first time you sign in.';
  else if (/database|storage/i.test(msg)) fix = 'The database could not be reached. Check that the Neon connection variables are present under <b>Settings → Environment Variables</b>, then redeploy.';
  $('#view').innerHTML = `<div class="setup"><h2 style="margin-top:0">Constellarium isn't ready yet</h2><p style="color:var(--danger)">${esc(msg)}</p><p>${fix}</p></div>`;
}

/* ---------- home: three cards ---------- */
Views.home = {
  async render(el) {
    setCrumbs([]);
    el.innerHTML = `
      <div class="hello"><h1>Welcome back</h1><p class="muted">Where to?</p></div>
      <div class="cards">
        <a class="card" href="#banks" style="--cc:var(--c-banks)" id="cardBanks"><span class="kbd">1</span>
          <div class="ico">${icon('banks')}</div><h2>Banks</h2><div class="sub">IdeaBank and ProblemBank: every idea and problem, with the map that connects them.</div>
          <div class="stats" id="stBanks"><span class="pill muted">…</span></div><span class="go">${icon('arrow')}</span></a>
        <a class="card" href="#todo" style="--cc:var(--c-todo)" id="cardTodo"><span class="kbd">2</span>
          <div class="ico">${icon('tasks')}</div><h2>To-do list</h2><div class="sub">What needs doing, with dates, linked to the ideas and problems behind it.</div>
          <div class="stats" id="stTodo"><span class="pill muted">…</span></div><span class="go">${icon('arrow')}</span></a>
        <a class="card" href="#vault" style="--cc:var(--c-vault)" id="cardVault"><span class="kbd">3</span>
          <div class="ico">${icon('key')}</div><h2>Passwords</h2><div class="sub">Your password manager. Encrypted, and opened with its own second password.</div>
          <div class="stats" id="stVault"><span class="pill">${icon('lock')} Locked</span></div><span class="go">${icon('arrow')}</span></a>
      </div>
      <p class="hint keys muted small">Tip: press <b>1</b>, <b>2</b> or <b>3</b> to jump straight in.</p>`;
    try {
      const s = await api('GET', '/api/summary');
      if (current !== 'home') return;
      $('#stBanks').innerHTML = `<span class="pill"><b>${s.banks.ideabank.ideas}</b> ideas</span><span class="pill"><b>${s.banks.problembank.ideas}</b> problems</span>`;
      const t = s.todos;
      $('#stTodo').innerHTML = `<span class="pill"><b>${t.open}</b> open</span>`
        + (t.overdue ? `<span class="pill warn"><b>${t.overdue}</b> overdue</span>` : '')
        + (t.today ? `<span class="pill"><b>${t.today}</b> due today</span>` : '')
        + (!t.open ? '<span class="pill good">all clear</span>' : '');
      $('#stVault').innerHTML = s.vault.configured ? `<span class="pill">${icon('lock')} Locked · second password</span>` : `<span class="pill warn">Not set up yet</span>`;
    } catch (e) {
      if (e.status === 503) showSetup(e.message);
      else if (e.status !== 401) toast(e.message, { ms: 5000 });
    }
  },
};

/* ---------- Banks: IdeaBank | ProblemBank ---------- */
Views.banks = {
  async render(el) {
    setCrumbs([{ label: 'Banks' }]);
    el.innerHTML = `
      <div class="pagehead"><h1 style="--cc:var(--c-banks)">${icon('banks')} Banks</h1></div>
      <div class="cards two">
        <a class="card" href="banks.html?bank=ideabank" style="--cc:#3b6df0"><div class="ico">&#128161;</div><h2>IdeaBank</h2>
          <div class="sub">Ideas, opportunities and solutions to build, mapped by category and project.</div>
          <div class="stats"><span class="pill" id="nIdeas"><b>…</b> ideas</span></div><span class="go">${icon('arrow')}</span></a>
        <a class="card" href="banks.html?bank=problembank" style="--cc:#f2994a"><div class="ico">&#129517;</div><h2>ProblemBank</h2>
          <div class="sub">Problems, pain points and challenges worth solving.</div>
          <div class="stats"><span class="pill" id="nProbs"><b>…</b> problems</span></div><span class="go">${icon('arrow')}</span></a>
      </div>
      <p class="hint muted small">Inside a bank you can add a task to any idea or problem; it shows up in your To-do list, and follows the item if you rename or move it.</p>`;
    try {
      const b = await api('GET', '/api/banks');
      if ($('#nIdeas')) { $('#nIdeas').innerHTML = `<b>${b.ideabank.ideas}</b> ideas`; $('#nProbs').innerHTML = `<b>${b.problembank.ideas}</b> problems`; }
    } catch (e) { if (e.status === 503) showSetup(e.message); }
  },
};

/* ---------- routing ---------- */
async function route() {
  const name = location.hash.replace('#', '');
  const next = Views[name] ? name : 'home';
  if (current && Views[current] && Views[current].leave && current !== next) Views[current].leave();
  current = next;
  window.scrollTo(0, 0);
  await Views[next].render($('#view'));
}
window.addEventListener('hashchange', () => { if (!$('#app').hidden) route(); });
document.addEventListener('visibilitychange', () => {       // coming back to the tab: show fresh counts / tasks
  if (document.visibilityState === 'visible' && !$('#app').hidden && (current === 'home' || current === 'todo') && !$('dialog[open]')) route();
});
document.addEventListener('keydown', e => {
  if (current !== 'home' || e.ctrlKey || e.metaKey || e.altKey || $('dialog[open]') || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  const to = { 1: 'banks', 2: 'todo', 3: 'vault' }[e.key];
  if (to) location.hash = to;
});

async function enter() {
  $('#login').hidden = true; $('#app').hidden = false;
  await route();
}

$('#loginForm').onsubmit = async e => {
  e.preventDefault();
  const go = $('#loginGo'); go.disabled = true; $('#loginErr').textContent = '';
  try {
    await api('POST', '/api/login', { password: $('#loginPw').value });
    $('#loginPw').value = '';
    await enter();
  } catch (err) {
    $('#loginErr').textContent = err.status === 503 ? '' : (err.message === 'wrong password' ? 'That password is not right.' : err.message);
    if (err.status === 503) showSetup(err.message);
  } finally { go.disabled = false; }
};
$('#btnLogout').onclick = async () => {
  try { await api('POST', '/api/logout', {}); } catch (e) { /* signed out anyway */ }
  location.hash = ''; showLogin();
};
wireEyes();

(async function boot() {
  try {
    const a = await api('GET', '/api/auth');
    $('#btnLogout').hidden = !a.required;
    if (a.ok) await enter(); else showLogin();
  } catch (e) {
    if (e.status === 503) showSetup(e.message);
    else { $('#login').hidden = false; $('#loginErr').textContent = 'Could not reach the server: ' + e.message; }
  }
})();
