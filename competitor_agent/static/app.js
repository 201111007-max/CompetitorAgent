'use strict';

/* 竞品分析 Agent — 对话式前端（设计文档 63：消息流 + text_delta 打字机 + 工具折叠 + 报告面板） */

let sessionId = null;
let eventSource = null;
let reportData = null;      // 最近一次 report 事件 payload（复制/下载用）
let busy = false;

// activeLeadMid：当前正在流式展开 Lead 消息的 message_id
let activeMid = null;

// message_id → 流式消息状态
const streams = new Map();

function $id(x) { return document.getElementById(x); }

function sourceLabel(source) {
  if (!source) return 'Lead';
  if (source === 'lead') return 'Lead';
  if (source.startsWith('sub.')) return '子任务';
  return source;
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

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

/* ── 流式 Lead 气泡（text_delta 打字机 + 分段思考渲染，设计文档 63/64）────── */

// 设计文档 64 §4：消息 = 一段有序的 typed segment 列表（追加式 DOM，不做整体 innerHTML 重建）：
//   { kind: 'think', node: <details>, body: <div>, raw, open, turn }
//   { kind: 'text',  node: <div>, body: <div>, raw, done, turn }
// turn 为 assistant 步序号（payload.turn）；kind 或 turn 变化 → 关闭当前段、push 新兄弟节点。
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
    // 思考段收尾默认折叠（设计文档 64 §4.2）
    seg.open = false;
    seg.node.open = false;
  } else {
    // 正文段收尾：marked 只渲染一次（避免每次 delta 全量重渲）
    if (!seg.rendered) {
      seg.node.innerHTML = DOMPurify.sanitize(marked.parse(seg.raw));
      seg.rendered = true;
    }
  }
}

// turn 归一化：缺省（undefined/null）视为 null → 同一 kind 且同为 null 时合并为单块（向后兼容）
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
      div.textContent = ''; // 打字机纯文本；收尾时 marked 一次
      s.el.appendChild(div);
      seg = { kind, turn: t, node: div, body: div, raw: '', done: false, rendered: false };
    }
    s.segments.push(seg);
  }
  seg.raw += text;
  if (kind === 'think') {
    seg.body.textContent += text;
  } else {
    seg.body.textContent += text;
  }
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
  // text.stop / message.stop：关闭当前段并收光标
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

/* ── 报告面板（report 事件一次性渲染 + 地址/复制/下载）──────── */

function renderMeta(payload, container) {
  const dims = payload.dimensions || [];
  const conf = payload.overall_confidence || 0;
  let html = '';
  if (payload.is_comparison) html += '<span class="chip chip-compare">对比</span>';
  html += dims.map(function (d) { return '<span class="chip">' + escapeHtml(d) + '</span>'; }).join('');
  html += '<span class="chip chip-conf">置信度 ' + (conf * 100).toFixed(0) + '%</span>';
  const meta = document.createElement('div');
  meta.className = 'report-meta';
  meta.innerHTML = html;
  container.appendChild(meta);
}

function renderReport(payload) {
  if (!payload || !payload.markdown_report) return;
  reportData = payload;
  const bubble = addMessage('assistant', 'report');

  // 报告地址
  const notice = document.createElement('div');
  notice.className = 'report-notice';
  const parts = [];
  if (payload.report_url) parts.push('地址: ' + payload.report_url);
  if (payload.report_path) parts.push('已保存到: ' + payload.report_path);
  if (parts.length) {
    notice.textContent = '报告已生成 · ' + parts.join(' · ');
    bubble.appendChild(notice);
  }

  const content = document.createElement('div');
  const clean = DOMPurify.sanitize(marked.parse(payload.markdown_report));
  content.className = 'report';
  content.innerHTML = clean;
  bubble.appendChild(content);
  renderMeta(payload, bubble);

  // 工具条：复制 Markdown / 下载 .md
  const toolbar = document.createElement('div');
  toolbar.className = 'report-toolbar';
  const copyBtn = document.createElement('button');
  copyBtn.className = 'ghost';
  copyBtn.textContent = '复制 Markdown';
  copyBtn.addEventListener('click', copyReport);
  const dlBtn = document.createElement('button');
  dlBtn.className = 'ghost';
  dlBtn.textContent = '下载 .md';
  dlBtn.addEventListener('click', downloadReport);
  toolbar.appendChild(copyBtn);
  toolbar.appendChild(dlBtn);
  bubble.appendChild(toolbar);
  scrollBottom();
}

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

/* ── 事件处理 ───────────────────────────────────────────────── */

function handleEvent(data) {
  const payload = data.payload || {};
  switch (data.event) {
    case 'message.start':
      activeMid = payload.message_id || null;
      ensureStream(activeMid, payload.source || 'lead');
      break;
    case 'thinking_delta': {
      // Lead 推理链增量（设计文档 63 §6.3）→ 折叠"已思考"块（设计文档 64 §4 分段）
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
      break;
    }
    case 'discovery.candidate':
      if (activeMid) addToolLine(streams.get(activeMid), 'discovery', '发现候选: ' + (payload.candidate || ''));
      break;
    case 'discovery': {
      const names = (payload.candidates || []).join(', ');
      if (activeMid) addToolLine(streams.get(activeMid), 'discovery', '发现候选清单: ' + (names || data.message));
      break;
    }
    case 'report':
      renderReport(data.payload);
      setBusy(false);
      break;
    case 'error':
      addInfo(data.message || '发生错误', 'error');
      setBusy(false);
      closeEventSource();
      break;
    case 'cancelled':
      addInfo(data.message || '分析已取消', 'info');
      setBusy(false);
      closeEventSource();
      break;
    default:
      break; // session_started / phase 事件（后端已收敛为 text_delta）不单独呈现
  }
}

/* ── 会话控制 ───────────────────────────────────────────────── */

function startAnalysis(task) {
  if (!task) return;
  if (!sessionId) sessionId = 'sess_' + Date.now();
  closeEventSource();
  // 用户气泡
  const ub = addMessage('user');
  ub.innerHTML = escapeHtml(task);
  setStatus('分析中…');
  setBusy(true);

  eventSource = new EventSource(
    '/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + encodeURIComponent(sessionId)
  );
  eventSource.onmessage = function (e) {
    let data;
    try { data = JSON.parse(e.data); } catch (err) { return; }
    handleEvent(data);
  };
  eventSource.onerror = function () {
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

/* ── 绑定 ───────────────────────────────────────────────────── */

$id('send-btn').addEventListener('click', function () {
  const val = $id('input').value.trim();
  if (val) { startAnalysis(val); $id('input').value = ''; }
});
$id('stop-btn').addEventListener('click', stopAnalysis);
$id('new-btn').addEventListener('click', newSession);
$id('input').addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const val = $id('input').value.trim();
    if (val) { startAnalysis(val); $id('input').value = ''; }
  }
});