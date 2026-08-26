'use strict';

/* 竞品分析 Agent — 前端逻辑（设计文档 50：事件消费 + markdown 渲染 + 进度可视化） */

let eventSource = null;
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

function startAnalysis() {
  const task = document.getElementById('task').value.trim();
  if (!task) return;
  sessionId = 'sess_' + Date.now();
  const log = document.getElementById('log');
  log.innerHTML = '';
  log.textContent = '等待分析...';
  clearCandidates();
  clearReport();
  clearPhaseBadges();
  document.getElementById('start-btn').disabled = true;
  document.getElementById('cancel-btn').disabled = false;

  eventSource = new EventSource('/api/analyze?task=' + encodeURIComponent(task) + '&session_id=' + sessionId);
  eventSource.onmessage = function (e) {
    const data = JSON.parse(e.data);
    addLog(data.event, data.message || (data.phase || '') + ' [' + (data.progress * 100).toFixed(0) + '%]');
    if (data.phase) addPhaseBadge(data.phase);
    if (data.event === 'discovery.candidate' && data.payload && data.payload.candidate) {
      addCandidate(data.payload.candidate);
    }
    if (data.event === 'report') renderReport(data.payload);
    if (data.event === 'report' || data.event === 'error' || data.event === 'cancelled') {
      eventSource.close();
      document.getElementById('start-btn').disabled = false;
      document.getElementById('cancel-btn').disabled = true;
      if (data.event !== 'report') clearReport();
    }
  };
  eventSource.onerror = function () {
    addLog('error', '连接断开');
    eventSource.close();
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
  renderMeta(payload);
  showReportAddress();
}

function showReportAddress() {
  const notice = document.getElementById('report-notice');
  if (!lastReport) return;
  const parts = [];
  const url = lastReport.report_url;
  if (url) parts.push('地址: ' + url);
  if (lastReport.report_path) parts.push('已保存到: ' + lastReport.report_path);
  if (!parts.length) return;
  notice.textContent = '报告已生成 · ' + parts.join(' · ');
  notice.hidden = false;
}

function copyReport() {
  if (!lastReport || !lastReport.markdown_report) return;
  const text = lastReport.markdown_report;
  const done = function () { addLog('report', '已复制 Markdown'); };
  const fail = function () { addLog('error', '复制失败'); };
  const fallback = function () {
    // 非安全上下文（http / 非 localhost）下 navigator.clipboard 不可用：textarea + execCommand 兜底
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    document.body.removeChild(ta);
    ok ? done() : fail();
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

function downloadReport() {
  if (!lastReport || !lastReport.markdown_report) return;
  const name = (lastReport.competitor || 'report').replace(/[/\\ ]+/g, '_');
  // 直接用内存中的 markdown 生成 Blob 下载，不依赖服务端落盘路径/竞态，单竞品与对比报告通用
  const blob = new Blob([lastReport.markdown_report], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name + '.md';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  addLog('report', '已下载 ' + name + '.md');
}

function clearReport() {
  lastReport = null;
  const report = document.getElementById('report');
  report.innerHTML = '';
  report.hidden = true;
  document.getElementById('report-toolbar').hidden = true;
  document.getElementById('report-meta').hidden = true;
  document.getElementById('report-notice').hidden = true;
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