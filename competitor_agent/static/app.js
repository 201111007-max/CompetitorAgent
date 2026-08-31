'use strict';

/* 竞品分析 Agent · 情报档案台（设计文档 68）
 * - 流式对话引擎（doc 63/64/66）：text_delta 打字机 + 分段思考 + task todo 清单 + report 面板
 * - 报告库（doc 68）：GET /api/history 案例文件柜 + 重开 GET /api/reports/{name}
 * - 审批工作流（doc 67 §3.2 / doc 68）：GET /status 盖章徽章 + POST /review 批准/驳回（原因回灌）
 * - 时间线（doc 26 §3.4 / doc 68）：GET /api/timeline/{name} 变化事件列表
 */

let sessionId = null;
let eventSource = null;
let reportData = null;      // 最近一次 report 事件 payload（复制/下载用）
let busy = false;
let sessionDone = false;    // 终态标志：message.stop / report / cancelled / error 后置位
let activeMid = null;       // 当前正在流式展开 Lead 消息的 message_id
const streams = new Map();  // message_id → 流式消息状态
const library = new Map();  // 竞品名(raw) → {name, time, task, status, el}

function $id(x) { return document.getElementById(x); }

function sourceLabel(source) {
  if (!source) return 'Lead';
  if (source === 'lead') return 'Lead';
  if (source === 'report') return '报告';
  if (source.startsWith('sub.')) return '子任务';
  return source;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function fetchJSON(url) {
  return fetch(url).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  });
}

function timeAgo(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  const d = new Date(t);
  const pad = function (n) { return (n < 10 ? '0' : '') + n; };
  return (d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function formatWhen(iso) {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const d = new Date(t);
  const pad = function (n) { return (n < 10 ? '0' : '') + n; };
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

function nameFromUrl(url) {
  if (!url) return '';
  const m = url.match(/\/api\/reports\/([^/]+)\/download/);
  return m ? decodeURIComponent(m[1]) : '';
}

/* ── 消息区 DOM ─────────────────────────────────────────────── */

function addMessage(role, source) {
  const row = document.createElement('div');
  row.className = 'msg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  row.appendChild(bubble);
  if (role === 'assistant' && source) {
    const tag = document.createElement('span');
    tag.className = 'src-tag';
    tag.textContent = sourceLabel(source);
    bubble.appendChild(tag);
  }
  $id('messages').appendChild(row);
  scrollBottom();
  return bubble;
}

function scrollBottom() {
  const m = $id('messages');
  m.scrollTop = m.scrollHeight;
}

/* ── 流式 Lead 气泡（doc 63/64：text_delta 打字机 + 分段思考） ── */

// 消息 = 一段有序的 typed segment 列表（追加式 DOM）：
//   { kind: 'think', node: <details>, body: <div>, raw, open, turn }
//   { kind: 'text',  node: <div>, body: <div>, raw, done, turn }
function ensureStream(mid, source) {
  let s = streams.get(mid);
  if (!s) {
    s = {
      mid, source: source || 'lead', el: addMessage('assistant', source || 'lead'),
      segments: [], cur: null, toolsEl: null, streaming: false,
    };
    streams.set(mid, s);
  }
  return s;
}

function currentSegment(s) {
  return s.segments.length ? s.segments[s.segments.length - 1] : null;
}

function closeSegment(s, seg) {
  if (!seg || seg.done) return;
  seg.done = true;
  if (seg.kind === 'think') {
    seg.open = false;
    seg.node.open = false;
  } else if (!seg.rendered) {
    seg.node.innerHTML = DOMPurify.sanitize(marked.parse(seg.raw));
    seg.rendered = true;
  }
}

function normTurn(turn) {
  return (turn === undefined || turn === null) ? null : turn;
}

function appendSegment(s, kind, text, turn) {
  const t = normTurn(turn);
  let seg = currentSegment(s);
  if (!seg || seg.done || seg.kind !== kind || seg.turn !== t) {
    if (seg) closeSegment(s, seg);
    if (kind === 'think') {
      const details = document.createElement('details');
      details.className = 'thinking';
      details.open = true;
      const summary = document.createElement('summary');
      summary.textContent = '已思考';
      const body = document.createElement('div');
      body.className = 'thinking-body';
      details.appendChild(summary);
      details.appendChild(body);
      s.el.appendChild(details);
      seg = { kind, turn: t, node: details, body, raw: '', open: true, done: false, rendered: true };
    } else {
      const div = document.createElement('div');
      div.className = 'text-seg';
      div.textContent = '';
      s.el.appendChild(div);
      seg = { kind, turn: t, node: div, body: div, raw: '', done: false, rendered: false };
    }
    s.segments.push(seg);
  }
  seg.raw += text;
  seg.body.textContent += text;
  scrollBottom();
}

function ensureCursor(s) {
  if (!s.cursorEl) {
    const c = document.createElement('span');
    c.className = 'cursor';
    c.textContent = '▊';
    s.el.appendChild(c);
    s.cursorEl = c;
  }
}

function removeCursor(s) {
  if (s.cursorEl) { s.cursorEl.remove(); s.cursorEl = null; }
}

function finishStream(s) {
  const seg = currentSegment(s);
  if (seg) { closeSegment(s, seg); s.cur = seg; }
  removeCursor(s);
  s.streaming = false;
}

function ensureTools(s) {
  if (!s.toolsEl) {
    const tools = document.createElement('div');
    tools.className = 'tools';
    s.el.appendChild(tools);
    s.toolsEl = tools;
  }
  return s.toolsEl;
}

function addToolLine(s, kind, text) {
  const box = ensureTools(s);
  const line = document.createElement('div');
  line.className = 'tool ' + kind;
  line.textContent = text;
  box.appendChild(line);
  scrollBottom();
}

// doc 66 §3.5：Lead 推进动作 → todo 清单行（[✓]/[…] 任务文案）
function addTaskLine(s, text, status) {
  const box = ensureTools(s);
  const line = document.createElement('div');
  const done = status === 'done';
  line.className = 'task ' + (done ? 'done' : 'running');
  line.textContent = (done ? '[✓] ' : '[…] ') + text;
  box.appendChild(line);
  scrollBottom();
}

/* ── 审批状态映射（盖章 + 报告库状态点共用） ───────────────── */

function mapStatus(status) {
  if (status === 'pending_review') return { label: '待审批', cls: 'warn' };
  if (status === 'rejected') return { label: '已驳回', cls: 'err' };
  return { label: '已批准', cls: 'ok' }; // approved（含旧 JSON 缺省）
}

function fetchStatus(name) {
  return fetchJSON('/api/reports/' + encodeURIComponent(name) + '/status')
    .then(function (res) { return res.status || 'approved'; })
    .catch(function () { return 'approved'; });
}

/* ── 档案卡（报告 dossier，doc 68 签名元素） ────────────────── */

function makeBtn(cls, text, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn ' + cls;
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

function renderDossier(opts) {
  // opts: { name, title, markdown, conf, dims[], isComparison, hasCandidates, reportUrl, reportPath, terminalState }
  const bubble = addMessage('assistant', 'report');
  const dossier = document.createElement('div');
  dossier.className = 'dossier';
  bubble.appendChild(dossier);

  // 头部：眉题 + 标题 + 盖章徽章（占位，审批状态异步填充）
  const head = document.createElement('div');
  head.className = 'dossier-head';
  const headLeft = document.createElement('div');
  headLeft.innerHTML = '<span class="dossier-eyebrow">COMPETITOR BRIEF</span><h2 class="dossier-title"></h2>';
  headLeft.querySelector('.dossier-title').textContent = opts.title;
  head.appendChild(headLeft);
  const stampEl = document.createElement('span');
  stampEl.className = 'stamp void';
  stampEl.textContent = '…';
  head.appendChild(stampEl);
  dossier.appendChild(head);

  // 生成提示条（地址/落盘路径）
  const notice = document.createElement('div');
  notice.className = 'report-notice';
  const parts = [];
  if (opts.reportUrl) parts.push('地址: ' + opts.reportUrl);
  if (opts.reportPath) parts.push('已保存到: ' + opts.reportPath);
  if (parts.length) {
    notice.textContent = '报告已生成 · ' + parts.join(' · ');
    dossier.appendChild(notice);
  }

  // 正文（Markdown 消毒渲染）
  const body = document.createElement('div');
  body.className = 'dossier-body';
  const content = document.createElement('div');
  content.className = 'report';
  content.innerHTML = DOMPurify.sanitize(marked.parse(opts.markdown || '（无正文）'));
  body.appendChild(content);
  dossier.appendChild(body);

  // 元信息 chips
  const meta = document.createElement('div');
  meta.className = 'dossier-meta';
  let mh = '';
  // 设计文档 73 §3.4 + D1 方案 A：普查（零候选）→ 标「普查」而非「对比」，前端不显示矩阵
  if (opts.isComparison && opts.hasCandidates !== false) mh += '<span class="chip chip-compare">对比</span>';
  if (opts.hasCandidates === false) mh += '<span class="chip chip-compare">普查</span>';
  (opts.dims || []).forEach(function (d) { mh += '<span class="chip">' + escapeHtml(d) + '</span>'; });
  meta.innerHTML = mh;
  dossier.appendChild(meta);
  // 设计文档 70 §8.1 D1b：零候选对比 → 提示"未收集到候选数据"而非干巴巴 0%
  if (opts.hasCandidates === false) {
    const warn = document.createElement('div');
    warn.className = 'report-notice dossier-warn';
    warn.textContent = '未收集到候选数据，对比矩阵为空';
    dossier.appendChild(warn);
  }

  // 操作栏：复制 / 下载 + 审批（右对齐）
  const actions = document.createElement('div');
  actions.className = 'dossier-actions';
  actions.appendChild(makeBtn('ghost', '复制 Markdown', copyReport));
  actions.appendChild(makeBtn('ghost', '下载 .md', downloadReport));
  const spacer = document.createElement('span');
  spacer.className = 'spacer';
  actions.appendChild(spacer);
  const reviewActions = document.createElement('div');
  reviewActions.className = 'review-actions';
  actions.appendChild(reviewActions);
  dossier.appendChild(actions);

  // 变化时间线（doc 68：/api/timeline/{name}）
  const tl = document.createElement('details');
  tl.className = 'timeline';
  const tlSummary = document.createElement('summary');
  tlSummary.textContent = '变化时间线';
  const tlCount = document.createElement('span');
  tlSummary.appendChild(tlCount);
  tl.appendChild(tlSummary);
  const tlList = document.createElement('div');
  tlList.className = 'timeline-list';
  tlList.textContent = '加载中…';
  tl.appendChild(tlList);
  dossier.appendChild(tl);
  loadTimeline(opts.name, tlList, tlCount);

  // 审批状态 → 盖章 + 批准/驳回按钮
  const name = opts.name;
  fetchStatus(name).then(function (status) {
    stampEl.className = 'stamp ' + mapStatus(status).cls;
    stampEl.textContent = mapStatus(status).label;
    if (status === 'pending_review') {
      reviewActions.appendChild(makeBtn('ok sm', '批准', function () {
        review(name, 'approve', '', { stampEl: stampEl, reviewActions: reviewActions });
      }));
      reviewActions.appendChild(makeBtn('danger sm', '驳回', function () {
        showRejectForm(reviewActions, name, { stampEl: stampEl, reviewActions: reviewActions });
      }));
    }
    if (library.has(name)) { library.get(name).status = status; refreshRailStatus(name); }
  });

  scrollBottom();
  return dossier;
}

/* ── 审批动作（POST /api/reports/{name}/review） ────────────── */

function showRejectForm(reviewActions, name, ui) {
  if (reviewActions.querySelector('.review-note')) return;
  const form = document.createElement('div');
  form.className = 'review-note';
  const input = document.createElement('input');
  input.placeholder = '驳回原因（可选，将回灌 reviewer_note）';
  input.setAttribute('aria-label', '驳回原因');
  const ok = makeBtn('danger sm', '确认驳回', function () {
    review(name, 'reject', input.value.trim(), ui);
  });
  const cancel = makeBtn('ghost sm', '取消', function () { form.remove(); });
  form.appendChild(input);
  form.appendChild(ok);
  form.appendChild(cancel);
  reviewActions.appendChild(form);
  input.focus();
}

function review(name, action, note, ui) {
  setStatus(action === 'approve' ? '正在提交审批…' : '正在提交驳回…');
  fetch('/api/reports/' + encodeURIComponent(name) + '/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: action, note: note }),
  })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
    })
    .then(function (res) {
      if (!res.ok) {
        setStatus('审批提交失败: ' + (res.data.detail || ('HTTP ' + res.status)), true);
        return;
      }
      const status = res.data.status || 'approved';
      ui.stampEl.className = 'stamp ' + mapStatus(status).cls;
      ui.stampEl.textContent = mapStatus(status).label;
      ui.reviewActions.innerHTML = '';
      setStatus(action === 'approve' ? '已批准' : '已驳回' + (note ? '（原因已记录）' : ''));
      if (library.has(name)) { library.get(name).status = status; refreshRailStatus(name); }
    })
    .catch(function (e) {
      setStatus('审批提交失败: ' + e.message, true);
    });
}

/* ── 时间线（GET /api/timeline/{name}） ─────────────────────── */

function loadTimeline(name, listEl, countEl) {
  fetchJSON('/api/timeline/' + encodeURIComponent(name) + '?limit=20')
    .then(function (res) {
      const events = (res && res.events) || [];
      countEl.textContent = events.length ? '· ' + events.length : '';
      if (!events.length) {
        listEl.innerHTML = '<div class="empty">暂无时间线事件</div>';
        return;
      }
      listEl.innerHTML = '';
      events.forEach(function (e) {
        const row = document.createElement('div');
        row.className = 'tl-event';
        row.innerHTML =
          '<span class="tl-dot"></span>' +
          '<span class="tl-main"><span class="tl-type"></span><div class="tl-summary"></div></span>' +
          '<span class="tl-when"></span>';
        row.querySelector('.tl-type').textContent = e.event_type || 'event';
        const ev = (e.evidence_urls || []).length ? ' · ' + e.evidence_urls.length + ' 证据' : '';
        row.querySelector('.tl-summary').textContent = (e.summary || '') + ev;
        row.querySelector('.tl-when').textContent = formatWhen(e.occurred_at || e.timestamp);
        listEl.appendChild(row);
      });
    })
    .catch(function () {
      countEl.textContent = '';
      listEl.innerHTML = '<div class="empty">时间线加载失败</div>';
    });
}

/* ── 复制 / 下载 ────────────────────────────────────────────── */

function copyReport() {
  if (!reportData || !reportData.markdown_report) return;
  const text = reportData.markdown_report;
  const done = function () { setStatus('已复制 Markdown'); };
  const fail = function () { setStatus('复制失败', true); };
  const fallback = function () {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(ta); ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(ta);
    ok ? done() : fail();
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else { fallback(); }
}

function downloadReport() {
  if (!reportData || !reportData.markdown_report) return;
  const name = (reportData.competitor || 'report').replace(/[/\\ ]+/g, '_');
  const blob = new Blob([reportData.markdown_report], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name + '.md';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
  setStatus('已下载 ' + name + '.md');
}

function addInfo(text, cls) {
  const bubble = addMessage('assistant', 'notice');
  bubble.innerHTML = '<span class="src-tag">系统</span><span class="' + (cls || 'info') + '">' + escapeHtml(text) + '</span>';
}

/* ── 报告库（案例文件柜） ───────────────────────────────────── */

function buildLibItem(it) {
  const li = document.createElement('li');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'lib-item';
  btn.innerHTML =
    '<span class="lib-dot"></span>' +
    '<span class="lib-main"><span class="lib-name"></span><span class="lib-meta"></span></span>' +
    '<span class="lib-pill"></span>';
  btn.querySelector('.lib-name').textContent = it.name;
  btn.querySelector('.lib-meta').textContent = timeAgo(it.time) + (it.task ? ' · ' + it.task : '');
  btn.addEventListener('click', function () { openLibrary(it.name, btn); });
  li.appendChild(btn);
  return li;
}

function renderLibrary(items) {
  const list = $id('library');
  list.innerHTML = '';
  library.clear();
  if (!items.length) {
    $id('lib-empty').hidden = false;
    $id('lib-count').textContent = '';
    return;
  }
  $id('lib-empty').hidden = true;
  $id('lib-count').textContent = items.length;
  items.forEach(function (it) {
    const li = buildLibItem(it);
    list.appendChild(li);
    const rec = { name: it.name, time: it.time, task: it.task, status: null, el: li };
    library.set(it.name, rec);
    fetchStatus(it.name).then(function (status) {
      const cur = library.get(it.name);
      if (cur) { cur.status = status; refreshRailStatus(it.name); }
    });
  });
}

function refreshRailStatus(name) {
  const rec = library.get(name);
  if (!rec || !rec.el) return;
  const dot = rec.el.querySelector('.lib-dot');
  const pill = rec.el.querySelector('.lib-pill');
  if (!rec.status) return;
  const m = mapStatus(rec.status);
  dot.className = 'lib-dot ' + m.cls;
  pill.textContent = m.label;
  pill.className = 'lib-pill ' + m.cls;
}

function loadLibrary() {
  fetchJSON('/api/history')
    .then(function (items) {
      const seen = new Set();
      const arr = [];
      (items || []).forEach(function (s) {
        const name = s.competitor || s.task || '未知';
        if (seen.has(name)) return;
        seen.add(name);
        arr.push({ name: name, time: s.created_at, task: s.task });
      });
      arr.sort(function (a, b) { return (b.time || '').localeCompare(a.time || ''); });
      renderLibrary(arr);
    })
    .catch(function () {
      renderLibrary([]);
    });
}

// 实时报告完成后：更新/插入报告库条目
function upsertLibrary(name, payload) {
  const it = {
    name: name,
    time: payload ? new Date().toISOString() : null,
    task: payload && payload.terminal_state ? 'terminal: ' + payload.terminal_state : '',
  };
  const existing = library.get(name);
  const list = $id('library');
  if (existing) {
    existing.time = it.time;
    existing.el.querySelector('.lib-meta').textContent = timeAgo(it.time) + (it.task ? ' · ' + it.task : '');
    list.prepend(existing.el);
  } else {
    const li = buildLibItem(it);
    list.prepend(li);
    library.set(name, { name: name, time: it.time, task: it.task, status: null, el: li });
    fetchStatus(name).then(function (status) {
      const cur = library.get(name);
      if (cur) { cur.status = status; refreshRailStatus(name); }
    });
  }
  $id('lib-empty').hidden = true;
  $id('lib-count').textContent = library.size;
}

function setActiveLib(btnEl) {
  document.querySelectorAll('.lib-item').forEach(function (b) { b.classList.remove('active'); });
  if (btnEl) btnEl.classList.add('active');
}

function openLibrary(name, btnEl) {
  setActiveLib(btnEl);
  setStatus('打开报告: ' + name);
  fetch('/api/reports/' + encodeURIComponent(name))
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.text();
    })
    .then(function (md) {
      reportData = { markdown_report: md, competitor: name };
      renderDossier({
        name: name,
        title: name,
        markdown: md,
        conf: null,
        dims: [],
        isComparison: false,
        reportUrl: '/api/reports/' + encodeURIComponent(name) + '/download',
        reportPath: null,
        terminalState: 'archive',
      });
      setStatus('');
      closeRailOnMobile();
    })
    .catch(function (e) {
      setStatus('打开报告失败: ' + e.message, true);
    });
}

/* ── 事件处理（doc 63/64/66 协议原样保留） ─────────────────── */

function handleEvent(data) {
  const payload = data.payload || {};
  switch (data.event) {
    case 'message.start':
      activeMid = payload.message_id || null;
      ensureStream(activeMid, payload.source || 'lead');
      break;
    case 'thinking_delta': {
      const mid = payload.message_id || activeMid;
      const s = ensureStream(mid, (streams.has(mid) ? streams.get(mid).source : 'lead'));
      s.streaming = true;
      appendSegment(s, 'think', (payload.delta || data.message || ''), payload.turn);
      ensureCursor(s);
      break;
    }
    case 'text_delta': {
      const mid = payload.message_id || activeMid;
      const s = ensureStream(mid, (streams.has(mid) ? streams.get(mid).source : 'lead'));
      s.streaming = true;
      appendSegment(s, 'text', (payload.delta || data.message || ''), payload.turn);
      ensureCursor(s);
      break;
    }
    case 'text.stop': {
      const mid = payload.message_id || activeMid;
      const s = streams.get(mid);
      if (s) { finishStream(s); }
      break;
    }
    case 'message.stop': {
      const mid = payload.message_id || activeMid;
      const s = streams.get(mid);
      if (s) { finishStream(s); }
      setBusy(false);
      sessionDone = true;
      break;
    }
    case 'discovery.candidate':
      if (activeMid) addToolLine(streams.get(activeMid), 'discovery', '发现候选: ' + (payload.candidate || ''));
      break;
    case 'task': {
      const mid = payload.message_id || activeMid;
      const s = streams.get(mid) || ensureStream(mid, 'lead');
      addTaskLine(s, payload.task || payload.message || '', payload.status);
      break;
    }
    case 'discovery': {
      const names = (payload.candidates || []).join(', ');
      if (activeMid) addToolLine(streams.get(activeMid), 'discovery', '发现候选清单: ' + (names || data.message));
      break;
    }
    case 'report': {
      const p = data.payload;
      reportData = p;
      const name = p.competitor || nameFromUrl(p.report_url) || 'report';
      renderDossier({
        name: name,
        title: name,
        markdown: p.markdown_report,
        conf: p.overall_confidence,
        dims: p.dimensions || [],
        isComparison: !!p.is_comparison,
        hasCandidates: p.has_candidates,
        reportUrl: p.report_url,
        reportPath: p.report_path,
        terminalState: p.terminal_state,
      });
      upsertLibrary(name, p);
      setBusy(false);
      sessionDone = true;
      break;
    }
    case 'error':
      addInfo(data.message || '发生错误', 'error');
      setBusy(false);
      sessionDone = true;
      closeEventSource();
      break;
    case 'cancelled':
      addInfo(data.message || '分析已取消', 'info');
      setBusy(false);
      sessionDone = true;
      closeEventSource();
      break;
    default:
      break; // session_started / phase 事件不单独呈现
  }
}

/* ── 会话控制 ───────────────────────────────────────────────── */

function startAnalysis(task) {
  if (!task) return;
  if (!sessionId) sessionId = 'sess_' + Date.now();
  closeEventSource();
  const ub = addMessage('user');
  ub.innerHTML = escapeHtml(task);
  setStatus('分析中…');
  setBusy(true);

  eventSource = new EventSource(
    '/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + encodeURIComponent(sessionId)
  );
  sessionDone = false;
  eventSource.onmessage = function (e) {
    let data;
    try { data = JSON.parse(e.data); } catch (err) { return; }
    handleEvent(data);
  };
  eventSource.onerror = function () {
    if (sessionDone) {
      closeEventSource();
      return;
    }
    addInfo('连接中断', 'error');
    setBusy(false);
    closeEventSource();
  };
}

function closeEventSource() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

function stopAnalysis() {
  if (sessionId) {
    fetch('/api/cancel/' + sessionId, { method: 'POST' }).catch(function () {});
    setStatus('正在停止…');
  }
  closeEventSource();
}

function newSession() {
  closeEventSource();
  streams.clear();
  activeMid = null;
  reportData = null;
  sessionId = 'sess_' + Date.now();
  $id('messages').innerHTML = '';
  setBusy(false);
  setStatus('', false);
  loadLibrary();
}

function setBusy(on) {
  busy = on;
  $id('send-btn').disabled = on;
  $id('stop-btn').disabled = !on;
  if (on) {
    $id('input').setAttribute('disabled', 'disabled');
  } else {
    $id('input').removeAttribute('disabled');
    $id('input').focus();
  }
}

function setStatus(text, isError) {
  const el = $id('status');
  if (!text) { el.hidden = true; el.textContent = ''; return; }
  el.hidden = false;
  el.textContent = text;
  el.className = 'status ' + (isError ? 'err' : '');
}

/* ── 报告目录设置（设计文档 70：rail 齿轮 → GET/PUT /api/settings） ───── */

function openSettings() {
  $id('settings-modal').hidden = false;
  $id('settings-hint').textContent = '';
  fetchJSON('/api/settings')
    .then(function (s) {
      $id('set-output').value = s.report_output_dir || '';
      $id('set-download').value = s.report_download_dir || '';
    })
    .catch(function (e) {
      $id('settings-hint').textContent = '读取设置失败: ' + e.message;
    });
}

function closeSettings() {
  $id('settings-modal').hidden = true;
  $id('settings-hint').textContent = '';
}

function resetSettings() {
  $id('set-output').value = '';
  $id('set-download').value = '';
  $id('settings-hint').textContent = '已清空，保存后将使用默认目录（项目 output/ 与 download/）。';
}

function pickDir(input) {
  if (window.showDirectoryPicker) {
    window.showDirectoryPicker()
      .then(function () {
        // 浏览器出于安全不暴露目录完整路径——提示手动填写服务端可用的绝对路径
        $id('settings-hint').textContent = '已打开目录选择器；浏览器不提供完整路径，请在输入框手动填写（如 D:\\reports）。';
        input.focus();
      })
      .catch(function (e) { if (!e || e.name !== 'AbortError') $id('settings-hint').textContent = '目录选择未完成。'; });
  } else {
    $id('settings-hint').textContent = '当前浏览器不支持目录选择器，请在输入框手动填写目录路径。';
    input.focus();
  }
}

function saveSettings() {
  const body = {
    report_output_dir: $id('set-output').value.trim(),
    report_download_dir: $id('set-download').value.trim(),
  };
  setStatus('正在保存设置…');
  fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
    })
    .then(function (res) {
      if (!res.ok) {
        setStatus('设置保存失败: ' + (res.data.detail || ('HTTP ' + res.status)), true);
        return;
      }
      closeSettings();
      setStatus('报告目录设置已保存');
    })
    .catch(function (e) {
      setStatus('设置保存失败: ' + e.message, true);
    });
}

/* ── 响应式抽屉 ────────────────────────────────────────────── */

function closeRailOnMobile() {
  if (window.matchMedia('(max-width: 900px)').matches) {
    $id('rail').classList.remove('open');
    $id('rail-scrim').hidden = true;
  }
}

/* ── 绑定 ───────────────────────────────────────────────────── */

function sendCurrent() {
  const val = $id('input').value.trim();
  if (val) { startAnalysis(val); $id('input').value = ''; }
}

$id('send-btn').addEventListener('click', sendCurrent);
$id('stop-btn').addEventListener('click', stopAnalysis);
$id('new-btn').addEventListener('click', newSession);
$id('input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendCurrent();
  }
});
$id('rail-toggle').addEventListener('click', function () {
  $id('rail').classList.add('open');
  $id('rail-scrim').hidden = false;
});
$id('rail-close').addEventListener('click', closeRailOnMobile);
$id('rail-scrim').addEventListener('click', closeRailOnMobile);

$id('settings-btn').addEventListener('click', openSettings);
$id('settings-close').addEventListener('click', closeSettings);
$id('settings-cancel').addEventListener('click', closeSettings);
$id('settings-save').addEventListener('click', saveSettings);
$id('settings-reset').addEventListener('click', resetSettings);
$id('set-output-pick').addEventListener('click', function () { pickDir($id('set-output')); });
$id('set-download-pick').addEventListener('click', function () { pickDir($id('set-download')); });
$id('settings-modal').addEventListener('click', function (e) {
  if (e.target === $id('settings-modal')) closeSettings();
});

loadLibrary();
