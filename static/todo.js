/* To-do list. Tasks live in the database (one document); a task can be linked to an idea / problem of either bank.
   The server resolves each link when it sends the list, so renames, status changes, moves between banks and deletes are always current. */
const Todo = { tasks: [], tab: 'open', items: null, editing: null, link: null, quickHigh: false };

const parseDay = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
function dayLabel(s) {
  const t = todayStr();
  const diff = Math.round((parseDay(s) - parseDay(t)) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return parseDay(s).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}
const byPriorityThenCreated = (a, b) => (b.priority === 'high') - (a.priority === 'high') || (a.createdAt || '').localeCompare(b.createdAt || '');

Views.todo = {
  async render(el) {
    setCrumbs([{ label: 'To-do list' }]);
    el.innerHTML = `
      <div class="pagehead"><h1 style="--cc:var(--c-todo)">${icon('tasks')} To-do list</h1></div>
      <form class="quick" id="quick" autocomplete="off">
        <input type="text" id="qTitle" placeholder="Add a task and press Enter…" maxlength="300" aria-label="New task">
        <input type="date" id="qDue" aria-label="Due date (optional)" title="Due date (optional)">
        <button type="button" class="opt" id="qHigh" title="Mark as high priority">${icon('flag')} High</button>
        <button type="submit" class="primary">Add</button>
      </form>
      <div class="seg" id="seg" role="tablist"></div>
      <div id="tlist"></div>`;
    $('#quick').onsubmit = quickAdd;
    $('#qHigh').onclick = () => { Todo.quickHigh = !Todo.quickHigh; $('#qHigh').classList.toggle('on', Todo.quickHigh); };
    Todo.quickHigh = false;
    $('#seg').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) { Todo.tab = b.dataset.tab; paintTodo(); } };
    $('#tlist').onclick = onListClick;
    $('#tlist').onchange = onListChange;
    $('#qTitle').focus();
    try { await loadTasks(); } catch (e) { if (e.status === 503) return showSetup(e.message); if (e.status !== 401) toast(e.message, { ms: 5000 }); }
  },
};

async function loadTasks() {
  const r = await api('GET', '/api/todos');
  Todo.tasks = r.tasks;
  paintTodo();
}

function paintTodo() {
  if (current !== 'todo' || !$('#tlist')) return;
  const today = todayStr();
  const open = Todo.tasks.filter(t => !t.done), done = Todo.tasks.filter(t => t.done);
  const dueNow = open.filter(t => t.due && t.due <= today);
  const tabs = [['open', 'Open', open.length], ['today', 'Due now', dueNow.length], ['done', 'Done', done.length]];
  $('#seg').innerHTML = tabs.map(([k, l, n]) => `<button type="button" role="tab" data-tab="${k}" class="${Todo.tab === k ? 'active' : ''}">${l}<span class="n">${n}</span></button>`).join('');
  let html = '';
  if (Todo.tab === 'done') {
    done.sort((a, b) => (b.doneAt || '').localeCompare(a.doneAt || ''));
    html = done.map(row).join('') || empty('Nothing finished yet.', '');
    if (done.length) html += `<p style="text-align:right"><button type="button" class="ghost" data-clear>Clear all completed</button></p>`;
  } else {
    const list = Todo.tab === 'today' ? dueNow : open;
    const groups = [['Overdue', list.filter(t => t.due && t.due < today), 'over'], ['Today', list.filter(t => t.due === today), ''],
      ['Upcoming', list.filter(t => t.due && t.due > today).sort((a, b) => a.due.localeCompare(b.due) || byPriorityThenCreated(a, b)), ''],
      ['No date', list.filter(t => !t.due), '']];
    for (const g of groups) g[1].sort((a, b) => (a.due || '').localeCompare(b.due || '') || byPriorityThenCreated(a, b));
    html = groups.filter(g => g[1].length).map(([name, arr, cls]) => `<div class="grp ${cls}">${name} <span>${arr.length}</span></div>${arr.map(row).join('')}`).join('');
    if (!html) html = Todo.tab === 'today' ? empty('Nothing due. Enjoy it.', '&#127881;') : empty('No open tasks. Add one above.', '&#10024;');
  }
  $('#tlist').innerHTML = html;
}
const empty = (msg, emoji) => `<div class="empty"><div class="big">${emoji}</div>${esc(msg)}</div>`;

function row(t) {
  const today = todayStr();
  const ref = t.ref;
  const chips = [];
  if (t.due) chips.push(`<span class="chipl ${!t.done && t.due < today ? 'over' : (!t.done && t.due === today ? 'today' : '')}">${esc(dayLabel(t.due))}</span>`);
  if (t.priority === 'high') chips.push(`<span class="chipl high">${icon('flag')} High</span>`);
  if (ref) chips.push(ref.exists
    ? `<a class="chipl link trunc" href="banks.html?bank=${esc(ref.bank)}&q=${encodeURIComponent(ref.title)}" title="Open in ${esc(bankLabel(ref.bank))}">${icon('link')}<span class="tt">${esc(bankLabel(ref.bank))} · ${esc(ref.title)}</span></a>`
    : `<span class="chipl gone" title="The linked item was deleted (Undo in the bank brings it back)">${icon('link')} linked item removed</span>`);
  return `<div class="task ${t.done ? 'done' : ''}" data-id="${esc(t.id)}">
    <input type="checkbox" ${t.done ? 'checked' : ''} data-done aria-label="Done">
    <div class="body" data-edit><div class="t">${esc(t.title)}</div>${t.notes ? `<div class="notes">${esc(t.notes.length > 160 ? t.notes.slice(0, 160) + '…' : t.notes)}</div>` : ''}${chips.length ? `<div class="meta">${chips.join('')}</div>` : ''}</div>
    <button type="button" class="iconbtn" data-edit title="Edit" aria-label="Edit task">${icon('edit')}</button>
    <button type="button" class="iconbtn del" data-del title="Delete" aria-label="Delete task">${icon('trash')}</button></div>`;
}

async function quickAdd(e) {
  e.preventDefault();
  const title = $('#qTitle').value.trim();
  if (!title) return;
  const due = $('#qDue').value, high = Todo.quickHigh;
  $('#qTitle').value = ''; $('#qDue').value = ''; Todo.quickHigh = false; $('#qHigh').classList.remove('on');   // clear first: you can type the next one at once
  try {
    const t = await api('POST', '/api/todos', { title, due, priority: high ? 'high' : 'normal' });
    Todo.tasks.push(t);
    if (Todo.tab === 'done') Todo.tab = 'open';
    paintTodo();
  } catch (err) {
    if (!$('#qTitle').value) { $('#qTitle').value = title; $('#qDue').value = due; }      // put it back so nothing typed is lost
    toast(err.message, { ms: 5000 });
  }
}

async function onListChange(e) {
  const box = e.target.closest('[data-done]'); if (!box) return;
  const id = box.closest('.task').dataset.id, t = Todo.tasks.find(x => x.id === id);
  const want = box.checked;
  try {
    const r = await api('PUT', '/api/todos/' + id, { done: want });
    Object.assign(t, r);
    setTimeout(paintTodo, 220);     // let the tick show before the row moves
  } catch (err) { box.checked = !want; toast(err.message, { ms: 5000 }); }
}

async function onListClick(e) {
  if (e.target.closest('a')) return;
  if (e.target.closest('[data-clear]')) {
    if (!confirm('Remove every completed task? (A backup is kept.)')) return;
    try { await api('POST', '/api/todos/clear-done', {}); await loadTasks(); } catch (err) { toast(err.message, { ms: 5000 }); }
    return;
  }
  const el = e.target.closest('.task'); if (!el) return;
  const t = Todo.tasks.find(x => x.id === el.dataset.id); if (!t) return;
  if (e.target.closest('[data-del]')) return deleteTask(t);
  if (e.target.closest('[data-edit]')) openTaskDialog(t);
}

async function deleteTask(t) {
  try {
    await api('DELETE', '/api/todos/' + t.id);
    Todo.tasks = Todo.tasks.filter(x => x.id !== t.id); paintTodo();
    toast('Task deleted', {
      action: 'Undo', ms: 8000, onAction: async () => {
        try {
          const r = await api('POST', '/api/todos', { title: t.title, notes: t.notes, due: t.due, priority: t.priority, link: t.link });
          if (t.done) await api('PUT', '/api/todos/' + r.id, { done: true });
          await loadTasks();
        } catch (err) { toast(err.message, { ms: 5000 }); }
      },
    });
  } catch (err) { toast(err.message, { ms: 5000 }); }
}

/* ---------- edit dialog + link picker ---------- */
async function openTaskDialog(t) {
  Todo.editing = t; Todo.link = t.link ? { ...t.link, title: t.ref && t.ref.exists ? t.ref.title : '' } : null;
  const f = $('#taskForm');
  $('#taskDlgTitle').textContent = 'Edit task';
  f.title.value = t.title; f.notes.value = t.notes || ''; f.due.value = t.due || ''; f.priority.value = t.priority || 'normal';
  $('#taskDelete').hidden = false; $('#taskErr').textContent = '';
  $('#linkSearch').value = ''; $('#linkList').hidden = true;
  paintLinkChosen();
  $('#taskDlg').showModal();
  if (!Todo.items) { try { Todo.items = (await api('GET', '/api/items')).items; } catch (e) { /* picker just stays empty */ } }
}
function paintLinkChosen() {
  const l = Todo.link;
  $('#linkChosen').innerHTML = l ? `<span class="chipl link">${icon('link')} ${esc(bankLabel(l.bank))} · ${esc(l.title || '(missing item)')}</span> <button type="button" class="iconbtn" id="linkClear" title="Remove the link" aria-label="Remove the link">&times;</button>`
    : '<span class="muted">Not linked to anything.</span>';
  const c = $('#linkClear'); if (c) c.onclick = () => { Todo.link = null; paintLinkChosen(); };
}
$('#linkSearch').oninput = () => {
  const q = $('#linkSearch').value.trim().toLowerCase(), box = $('#linkList');
  if (!q || !Todo.items) { box.hidden = true; return; }
  const hits = Todo.items.filter(i => i.title.toLowerCase().includes(q)).slice(0, 40);
  box.hidden = false;
  box.innerHTML = hits.length ? hits.map(i => `<button type="button" data-bank="${esc(i.bank)}" data-iid="${esc(i.id)}"><span class="bk">${esc(bankLabel(i.bank))}</span><span>${esc(i.title)}</span></button>`).join('') : '<div class="muted small" style="padding:10px">Nothing matches.</div>';
};
$('#linkList').onclick = e => {
  const b = e.target.closest('[data-iid]'); if (!b) return;
  Todo.link = { bank: b.dataset.bank, id: b.dataset.iid, title: Todo.items.find(i => i.id === b.dataset.iid && i.bank === b.dataset.bank).title };
  $('#linkList').hidden = true; $('#linkSearch').value = ''; paintLinkChosen();
};
$('#taskCancel').onclick = () => $('#taskDlg').close();
$('#taskDelete').onclick = () => { const t = Todo.editing; $('#taskDlg').close(); if (t) deleteTask(t); };
$('#taskForm').onsubmit = async e => {
  e.preventDefault();
  const f = e.target, t = Todo.editing;
  try {
    const r = await api('PUT', '/api/todos/' + t.id, { title: f.title.value, notes: f.notes.value, due: f.due.value, priority: f.priority.value, link: Todo.link ? { bank: Todo.link.bank, id: Todo.link.id } : null });
    Object.assign(t, r, { ref: r.ref });
    if (!r.ref) delete t.ref;
    $('#taskDlg').close(); paintTodo();
  } catch (err) { $('#taskErr').textContent = err.message; }
};
