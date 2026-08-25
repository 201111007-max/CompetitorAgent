'use strict';

/* 竞品分析 Agent — 前端逻辑（设计文档 50：事件消费 + markdown 渲染 + 进度可视化） */

let eventSource = null;
let logSource = null;
let sessionId = null;
let discoveredCandidates = [];
let lastReport = null;

function addLog(event, message) {
  const log = document.getElementById('log');
  const div = document.createElement('div');
  div.className = 'event ' + (event || '');
  div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + message;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function setProgress(value) {
  const wrap = document.getElementById('progress-wrap');
  const bar = document.getElementById('progress-bar');
  const label = document.getElementById('progress-label');
  const pct = Math.max(0, Math.min(1, value || 0)) * 100;
  bar.style.width = pct.toFixed(0) + '%';
  label.textContent = pct.toFixed(0) + '%';
  wrap.hidden = false;
}

function addPhaseBadge(name) {
  if (!name) return;
  const box = document.getElementById('phase-badges');
  for (const chip of box.querySelectorAll('.phase-badge')) {
    if (chip.dataset.phase === name) return;
  }
  const chip = document.createElement('span');
  chip.className = 'phase-badge';
  chip.dataset.phase = name;
  chip.textContent = name;
  box.appendChild(chip);
}

function clearPhaseBadges() {
  document.getElementById('phase-badges').textContent = '';
}

function openLogStream() {
  if (!sessionId) return;
  document.getElementById('session-log').textContent = '';
  logSource = new EventSource('/api/logs/stream/' + sessionId);
  logSource.onmessage = function (e) {
    const data = JSON.parse(e.data);
    if (data.event === 'log_end') { logSource.close(); return; }
    const line = '[' + (data.ts || '') + '] ' + (data.event || '') + ' ' + (data.message || JSON.stringify(data));
    const box = document.getElementById('session-log');
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
  };
  logSource.onerror = function () { if (logSource) logSource.close(); };
}

function closeLogStream() {
  if (logSource) { logSource.close(); logSource = null; }
}

function startAnalysis() {
  const task = document.getElementById('task').value.trim();
  if (!task) return;
  sessionId = 'sess_' + Date.now();
  const log = document.getElementById('log');
  log.innerHTML = '';
  log.textContent = '等待分析...';
  clearCandidates();
  clearReport();
  setProgress(0);
  clearPhaseBadges();
  document.getElementById('start-btn').disabled = true;
  document.getElementById('cancel-btn').disabled = false;
  openLogStream();

  eventSource = new EventSource('/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + sessionId);
  eventSource.onmessage = function (e) {
    const data = JSON.parse(e.data);
    addLog(data.event, data.message || (data.phase || '') + ' [' + (data.progress * 100).toFixed(0) + '%]');
    if (data.progress !== undefined) setProgress(data.progress);
    if (data.phase) addPhaseBadge(data.phase);
    if (data.event === 'discovery.candidate' && data.payload && data.payload.candidate) {
      addCandidate(data.payload.candidate);
    }
    if (data.event === 'report') renderReport(data.payload);
    if (data.event === 'report' || data.event === 'error' || data.event === 'cancelled') {
      eventSource.close();
      closeLogStream();
      document.getElementById('start-btn').disabled = false;
      document.getElementById('cancel-btn').disabled = true;
      if (data.event !== 'report') clearReport();
    }
  };
  eventSource.onerror = function () {
    addLog('error', '连接断开');
    eventSource.close();
    closeLogStream();
    document.getElementById('start-btn').disabled = false;
    document.getElementById('cancel-btn').disabled = true;
    clearReport();
  };
}

function addCandidate(name) {
  if (discoveredCandidates.indexOf(name) === -1) {
    discoveredCandidates.push(name);
    document.getElementById('candidates').hidden = false;
    document.getElementById('candidate-list').textContent = discoveredCandidates.join(', ');
  }
}

function clearCandidates() {
  discoveredCandidates = [];
  document.getElementById('candidates').hidden = true;
  document.getElementById('candidate-list').textContent = '';
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function renderMeta(payload) {
  const meta = document.getElementById('report-meta');
  const dims = payload.dimensions || [];
  const conf = payload.overall_confidence || 0;
  let html = '';
  if (payload.is_comparison) html += '<span class="chip chip-compare">对比</span>';
  html += dims.map(function (d) { return '<span class="chip">' + escapeHtml(d) + '</span>'; }).join('');
  html += '<span class="chip chip-conf">置信度 ' + (conf * 100).toFixed(0) + '%</span>';
  meta.innerHTML = html;  // 全部来自 escapeHtml 与固定字符串，无 SSE 原文注入
  meta.hidden = false;
}

function renderReport(payload) {
  if (!payload || !payload.markdown_report) return;
  lastReport = payload;
  // markdown → HTML（marked），再经 DOMPurify 净化后注入（防 XSS，SSE 原文不直接 innerHTML）
  const html = marked.parse(payload.markdown_report);
  const clean = DOMPurify.sanitize(html);
  const container = document.getElementById('report');
  container.innerHTML = clean;
  container.hidden = false;
  document.getElementById('report-toolbar').hidden = false;
  const dl = document.getElementById('download-btn');
  dl.disabled = !payload.competitor;
  renderMeta(payload);
  setProgress(1);
}

function copyReport() {
  if (!lastReport || !lastReport.markdown_report) return;
  navigator.clipboard.writeText(lastReport.markdown_report)
    .then(function () { addLog('report', '已复制 Markdown'); })
    .catch(function () { addLog('error', '复制失败'); });
}

function downloadReport() {
  if (!lastReport || !lastReport.competitor) return;
  window.location.href = '/api/reports/' + encodeURIComponent(lastReport.competitor) + '/download';
}

function clearReport() {
  lastReport = null;
  const report = document.getElementById('report');
  report.innerHTML = '';
  report.hidden = true;
  document.getElementById('report-toolbar').hidden = true;
  document.getElementById('report-meta').hidden = true;
  clearCandidates();
}

function cancelAnalysis() {
  if (sessionId) {
    fetch('/api/cancel/' + sessionId, { method: 'POST' });
    addLog('cancelled', '正在取消...');
  }
}

/* 绑定按钮事件（index.html 依赖 JS 绑定，非内联 onclick） */
document.getElementById('start-btn').addEventListener('click', startAnalysis);
document.getElementById('cancel-btn').addEventListener('click', cancelAnalysis);