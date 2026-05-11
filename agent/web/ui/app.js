const log = document.getElementById('log');
const cursor = document.getElementById('cursor');
const taskInput = document.getElementById('task');
const sendBtn = document.getElementById('send');
const stopBtn = document.getElementById('stop');
const resumeBtn = document.getElementById('resume');
const statusLabel = document.getElementById('status-label');
const dot = document.getElementById('dot');
const conn = document.getElementById('conn');
let isBusy = false;
let hasResumable = false;

function updateResumeBtn() {
  resumeBtn.classList.toggle('visible', !isBusy && hasResumable);
}

function appendNode(node) {
  // Insertar antes del cursor para que siempre quede al final
  log.insertBefore(node, cursor);
  log.scrollTop = log.scrollHeight;
}
function append(text, cls) {
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text;
  appendNode(span);
}
function appendBlock(text, cls) {
  append(text + '\n', cls);
}

function setBusy(busy) {
  isBusy = busy;
  // Input siempre habilitado: cuando busy → modo INJECT
  taskInput.disabled = false;
  sendBtn.disabled = false;
  sendBtn.textContent = busy ? 'INJECT' : 'EXEC';
  sendBtn.classList.toggle('inject', busy);
  stopBtn.classList.toggle('visible', busy);
  stopBtn.classList.remove('armed');
  taskInput.placeholder = busy
    ? 'inject instruction (will reach agent at next turn)…'
    : 'target / task...';
  statusLabel.textContent = busy ? 'executing' : 'idle';
  dot.classList.toggle('busy', busy);
  updateResumeBtn();
  if (!busy) taskInput.focus();
}

// Al cargar, consultar si hay sesión resumable (tras refresh, etc.)
fetch('/session').then(r => r.json()).then(s => {
  hasResumable = !!s.resumable;
  updateResumeBtn();
}).catch(() => {});

let evt = null;
function connectStream() {
  evt = new EventSource('/events');
  evt.onopen = () => {
    conn.textContent = 'linked';
    conn.className = 'live';
  };
  evt.onerror = () => {
    conn.textContent = 'reconnecting…';
    conn.className = 'reconnecting';
    evt.close();
    setTimeout(connectStream, 1500);
  };
  evt.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === 'text') {
      append(m.text, 'agent');
    } else if (m.type === 'action') {
      appendBlock('▸ ' + m.action + ' ' + JSON.stringify(m.input), 'action');
    } else if (m.type === 'tool_result_error') {
      appendBlock('✗ ' + m.message, 'err');
    } else if (m.type === 'error') {
      appendBlock('[err] ' + m.message, 'err');
      setBusy(false);
    } else if (m.type === 'log') {
      appendBlock('· ' + m.message, 'sys');
    } else if (m.type === 'turn_end') {
      appendBlock('── turn end :: ' + m.stop_reason + ' ──', 'turn');
    } else if (m.type === 'done') {
      appendBlock('✓ ' + m.message, 'sys');
      setBusy(false);
    } else if (m.type === 'status') {
      setBusy(m.busy);
    } else if (m.type === 'task_started') {
      appendBlock('\n>>> ' + m.task, 'user');
    } else if (m.type === 'session_resumable') {
      hasResumable = true;
      updateResumeBtn();
      appendBlock('· session saved — RESUME enabled (' + m.messages_count + ' msgs)', 'sys');
    } else if (m.type === 'refusal' || m.type === 'refusal_final') {
      const div = document.createElement('div');
      div.className = 'refusal-block' + (m.type === 'refusal_final' ? ' final' : '');
      const title = document.createElement('span');
      title.className = 'title';
      title.textContent = m.type === 'refusal_final'
        ? '⛔ anthropic safeguard — final (max retries)'
        : '⚠ anthropic safeguard triggered — retry ' + m.retry + '/' + m.max_retries;
      div.appendChild(title);
      if (m.category) {
        const cat = document.createElement('div');
        cat.textContent = 'category: ' + m.category;
        div.appendChild(cat);
      }
      if (m.type === 'refusal_final') {
        const tip = document.createElement('div');
        tip.style.marginTop = '6px';
        tip.textContent = 'la sesión está guardada — reformula y pulsa RESUME, o solicita ajuste:';
        div.appendChild(tip);
      }
      if (m.form_url) {
        const link = document.createElement('a');
        link.href = m.form_url;
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = m.form_url;
        const wrap = document.createElement('div');
        wrap.style.marginTop = '4px';
        wrap.appendChild(link);
        div.appendChild(wrap);
      }
      appendNode(div);
    } else if (m.type === 'user_inject_queued') {
      const div = document.createElement('div');
      div.className = 'inject-block';
      div.textContent = '>> [inject queued] ' + m.message;
      appendNode(div);
    } else if (m.type === 'user_inject_applied') {
      appendBlock('   ↳ inject delivered to agent', 'inject-applied');
    } else if (m.type === 'helper_plan') {
      const div = document.createElement('div');
      div.className = 'helper-block';
      div.textContent = '[plan]\n' + m.plan;
      appendNode(div);
    } else if (m.type === 'helper_answer') {
      const div = document.createElement('div');
      div.className = 'helper-block';
      div.textContent = '[?] ' + m.question + '\n→ ' + m.answer;
      appendNode(div);
    } else if (m.type === 'bash_output') {
      const div = document.createElement('div');
      div.className = 'bash-block';

      if (m.from_user) {
        const tag = document.createElement('div');
        tag.className = 'by-user';
        tag.textContent = '── manual ──';
        div.appendChild(tag);
      }
      const cmd = document.createElement('div');
      cmd.className = 'cmd';
      cmd.textContent = m.command;
      div.appendChild(cmd);

      if (m.stdout) {
        const out = document.createElement('div');
        out.textContent = m.stdout;
        div.appendChild(out);
      }
      if (m.stderr) {
        const err = document.createElement('div');
        err.className = 'stderr';
        err.textContent = m.stderr;
        div.appendChild(err);
      }
      if (m.error) {
        const er = document.createElement('div');
        er.className = 'exit-fail';
        er.textContent = '└─ ✗ ' + m.error;
        div.appendChild(er);
      } else {
        const e = document.createElement('div');
        e.className = m.exit_code === 0 ? 'exit-ok' : 'exit-fail';
        e.textContent = '└─ exit ' + m.exit_code;
        div.appendChild(e);
      }
      appendNode(div);
    }
  };
}
connectStream();

async function submitTask() {
  const task = taskInput.value.trim();
  if (!task) return;
  setBusy(true);
  try {
    const res = await fetch('/task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task })
    });
    if (!res.ok) {
      const txt = await res.text();
      appendBlock('[err] ' + txt, 'err');
      setBusy(false);
      return;
    }
    taskInput.value = '';
    taskInput.style.height = 'auto';
  } catch (e) {
    appendBlock('[err] ' + e.message, 'err');
    setBusy(false);
  }
}

async function injectMessage() {
  const message = taskInput.value.trim();
  if (!message) return;
  try {
    const res = await fetch('/inject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    if (!res.ok) {
      const txt = await res.text();
      appendBlock('[inject err] ' + txt, 'err');
      return;
    }
    taskInput.value = '';
    taskInput.style.height = 'auto';
  } catch (e) {
    appendBlock('[inject err] ' + e.message, 'err');
  }
}

async function stopTask() {
  if (!isBusy) return;
  stopBtn.classList.add('armed');
  try {
    const res = await fetch('/interrupt', { method: 'POST' });
    if (!res.ok) {
      appendBlock('[stop err] ' + await res.text(), 'err');
      stopBtn.classList.remove('armed');
    }
  } catch (e) {
    appendBlock('[stop err] ' + e.message, 'err');
    stopBtn.classList.remove('armed');
  }
}

function dispatchSubmit() {
  if (isBusy) injectMessage();
  else submitTask();
}

async function resumeTask() {
  if (isBusy) return;
  const followUp = taskInput.value.trim();
  try {
    const res = await fetch('/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task: followUp })
    });
    if (!res.ok) {
      const txt = await res.text();
      appendBlock('[resume err] ' + txt, 'err');
      return;
    }
    taskInput.value = '';
    taskInput.style.height = 'auto';
    // hasResumable se mantiene; la sesión se sobrescribe cuando termine.
  } catch (e) {
    appendBlock('[resume err] ' + e.message, 'err');
  }
}

sendBtn.onclick = dispatchSubmit;
stopBtn.onclick = stopTask;
resumeBtn.onclick = resumeTask;
taskInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    dispatchSubmit();
  }
});

// Auto-resize del textarea
taskInput.addEventListener('input', () => {
  taskInput.style.height = 'auto';
  taskInput.style.height = Math.min(140, taskInput.scrollHeight) + 'px';
});
