/**
 * Dota Helper 统一聊天前端
 *
 * 原生 HTML + JavaScript 实现，无构建工具依赖。
 * 通过 SSE 与后端 /api/chat 交互，展示 ReAct Agent 的完整推理链。
 */

// ── JSDoc 类型定义 ──

/**
 * @typedef {'session'|'thought'|'action'|'observation'|'progress'|'phase_complete'|'report'|'final'|'error'} ChatEventType
 */

/**
 * @typedef {'user'|'agent'} ChatMessageRole
 */

/**
 * @typedef {'text'|'thought'|'action'|'observation'|'progress'|'phase_complete'|'report'|'final'|'error'} ChatMessageType
 */

/**
 * @typedef {Object} ChatMessage
 * @property {string} id
 * @property {ChatMessageRole} role
 * @property {ChatMessageType} type
 * @property {string} content
 * @property {Object.<string, any>|undefined} [input]
 * @property {string|undefined} [wardHtml]
 * @property {number|undefined} [progress]
 * @property {string|undefined} [phase]
 * @property {Object.<string, any>|undefined} [payload]
 * @property {string} createdAt
 */

/**
 * @typedef {Object} ChatSession
 * @property {string} session_id
 * @property {string|undefined} [conversation_id]
 * @property {string} title
 * @property {number} updated_at
 */

/**
 * @typedef {Object} ChatEvent
 * @property {ChatEventType} type
 * @property {string|undefined} [session_id]
 * @property {string|undefined} [conversation_id]
 * @property {string|undefined} [content]
 * @property {Object.<string, any>|undefined} [input]
 * @property {string|undefined} [ward_html]
 * @property {number|undefined} [progress]
 * @property {string|undefined} [phase]
 * @property {string|undefined} [message]
 * @property {Object.<string, any>|undefined} [payload]
 */

// ── 状态管理 ──

/** @type {{ sessionId?: string, conversationId?: string, messages: ChatMessage[], sessions: ChatSession[], isStreaming: boolean, activeWardHtml?: string }} */
const chatState = {
  sessionId: undefined,
  conversationId: undefined,
  messages: [],
  sessions: [],
  isStreaming: false,
  activeWardHtml: undefined,
};

// ── DOM 元素缓存 ──

const elements = {
  app: /** @type {HTMLElement} */ (document.getElementById('app')),
  sidebar: /** @type {HTMLElement} */ (document.getElementById('sidebar')),
  sessionList: /** @type {HTMLElement} */ (document.getElementById('session-list')),
  newChatBtn: /** @type {HTMLButtonElement} */ (document.getElementById('new-chat-btn')),
  menuToggle: /** @type {HTMLButtonElement} */ (document.getElementById('menu-toggle')),
  clearChatBtn: /** @type {HTMLButtonElement} */ (document.getElementById('clear-chat-btn')),
  chatTitle: /** @type {HTMLElement} */ (document.getElementById('chat-title')),
  messageList: /** @type {HTMLElement} */ (document.getElementById('message-list')),
  welcome: /** @type {HTMLElement} */ (document.getElementById('welcome')),
  presetCards: /** @type {HTMLElement} */ (document.getElementById('preset-cards')),
  messageInput: /** @type {HTMLTextAreaElement} */ (document.getElementById('message-input')),
  sendBtn: /** @type {HTMLButtonElement} */ (document.getElementById('send-btn')),
  vizPanel: /** @type {HTMLElement} */ (document.getElementById('viz-panel')),
  vizContent: /** @type {HTMLElement} */ (document.getElementById('viz-content')),
  vizPlaceholder: /** @type {HTMLElement} */ (document.getElementById('viz-placeholder')),
  vizIframe: /** @type {HTMLIFrameElement} */ (document.getElementById('viz-iframe')),
  closeVizBtn: /** @type {HTMLButtonElement} */ (document.getElementById('close-viz-btn')),
};

// ── API 客户端 ──

/**
 * 发送聊天消息，返回 Response 对象用于流式读取。
 * @param {string} message
 * @param {string|undefined} [sessionId]
 * @returns {Promise<Response>}
 */
async function sendChatMessage(message, sessionId) {
  return fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
}

/**
 * 解析 SSE 流，产出 ChatEvent 对象。
 * @param {Response} response
 * @returns {AsyncGenerator<ChatEvent>}
 */
async function* streamChatEvents(response) {
  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const payload = trimmed.slice(5).trim();
        if (!payload) continue;
        try {
          yield JSON.parse(payload);
        } catch (e) {
          console.error('解析聊天事件失败:', e);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * 获取会话历史列表。
 * @returns {Promise<ChatSession[]>}
 */
async function listChatHistory() {
  const res = await fetch('/api/history');
  if (!res.ok) throw new Error(`获取聊天历史失败: ${res.status}`);
  return res.json();
}

/**
 * 获取单个会话详情。
 * @param {string} sessionId
 * @returns {Promise<ChatSession & { messages: any[] }>}
 */
async function getChatSession(sessionId) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`获取会话详情失败: ${res.status}`);
  return res.json();
}

// ── 状态操作 ──

/**
 * 生成唯一消息 ID。
 * @returns {string}
 */
function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * 添加用户消息到状态。
 * @param {string} content
 * @returns {ChatMessage}
 */
function addUserMessage(content) {
  /** @type {ChatMessage} */
  const message = {
    id: generateId(),
    role: 'user',
    type: 'text',
    content,
    createdAt: new Date().toISOString(),
  };
  chatState.messages.push(message);
  renderMessages();
  return message;
}

/**
 * 追加 Agent 推理片段到消息列表。
 * @param {ChatEvent} event
 */
function appendAgentChunk(event) {
  const id = generateId();
  /** @type {ChatMessage} */
  const message = {
    id,
    role: 'agent',
    type: event.type,
    content: event.content ?? event.message ?? '',
    input: event.input,
    progress: event.progress,
    phase: event.phase,
    payload: event.payload,
    createdAt: new Date().toISOString(),
  };

  if (event.type === 'final' && event.ward_html) {
    message.wardHtml = event.ward_html;
    chatState.activeWardHtml = event.ward_html;
  }

  chatState.messages.push(message);
  renderMessages();
  renderWardIframe();
}

/**
 * 更新会话信息。
 * @param {ChatEvent} event
 */
function updateSession(event) {
  if (event.session_id) {
    chatState.sessionId = event.session_id;
  }
  if (event.conversation_id) {
    chatState.conversationId = event.conversation_id;
  }
  if (chatState.messages.length > 0) {
    const firstUser = chatState.messages.find((m) => m.role === 'user');
    if (firstUser) {
      elements.chatTitle.textContent = firstUser.content.slice(0, 24) || '新会话';
    }
  }
}

// ── DOM 渲染 ──

/**
 * 渲染完整消息列表。
 */
function renderMessages() {
  if (chatState.messages.length > 0 && elements.welcome) {
    elements.welcome.style.display = 'none';
  }

  elements.messageList.innerHTML = '';

  for (const message of chatState.messages) {
    const node = createMessageNode(message);
    elements.messageList.appendChild(node);
  }

  scrollToBottom();
}

/**
 * 创建单个消息 DOM 节点。
 * @param {ChatMessage} message
 * @returns {HTMLElement}
 */
function createMessageNode(message) {
  if (message.role === 'user') {
    return createUserMessageNode(message);
  }

  // agent 消息：推理链统一展示
  return createAgentMessageNode(message);
}

/**
 * 创建用户消息节点。
 * @param {ChatMessage} message
 * @returns {HTMLElement}
 */
function createUserMessageNode(message) {
  const wrapper = document.createElement('div');
  wrapper.className = 'message user';
  wrapper.innerHTML = `
    <div class="message-avatar">我</div>
    <div>
      <div class="message-content">${escapeHtml(message.content)}</div>
      <div class="message-meta">${formatTime(message.createdAt)}</div>
    </div>
  `;
  return wrapper;
}

/**
 * 创建 Agent 消息节点。
 * @param {ChatMessage} message
 * @returns {HTMLElement}
 */
function createAgentMessageNode(message) {
  const wrapper = document.createElement('div');
  wrapper.className = 'message agent';

  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.textContent = 'AI';

  const body = document.createElement('div');
  body.style.flex = '1';
  body.style.minWidth = '0';

  const step = document.createElement('div');
  step.className = `reasoning-step ${message.type}`;

  const label = document.createElement('div');
  label.className = 'step-label';
  label.textContent = getStepLabel(message.type);

  const content = document.createElement('div');
  content.className = 'step-content';

  const text = document.createElement('div');
  text.innerHTML = simpleMarkdown(message.content);
  content.appendChild(text);

  if (message.input && Object.keys(message.input).length > 0) {
    const inputBlock = document.createElement('div');
    inputBlock.className = 'step-input';
    inputBlock.textContent = JSON.stringify(message.input, null, 2);
    content.appendChild(inputBlock);
  }

  if (message.progress !== undefined && message.progress > 0) {
    const bar = document.createElement('div');
    bar.className = 'progress-bar';
    const fill = document.createElement('div');
    fill.className = 'progress-fill';
    fill.style.width = `${Math.min(100, Math.max(0, message.progress * 100))}%`;
    bar.appendChild(fill);
    content.appendChild(bar);
  }

  if (message.type === 'final') {
    step.classList.add('final-answer');
  }

  step.appendChild(label);
  step.appendChild(content);
  body.appendChild(step);

  const meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = formatTime(message.createdAt);
  body.appendChild(meta);

  wrapper.appendChild(avatar);
  wrapper.appendChild(body);
  return wrapper;
}

/**
 * 获取步骤显示标签。
 * @param {ChatMessageType} type
 * @returns {string}
 */
function getStepLabel(type) {
  const labels = {
    thought: '思考',
    action: '行动',
    observation: '观察',
    progress: '进度',
    phase_complete: '阶段完成',
    report: '报告',
    final: '最终回答',
    error: '错误',
    text: '文本',
  };
  return labels[type] || type;
}

/**
 * 渲染会话历史侧边栏。
 */
function renderSessions() {
  elements.sessionList.innerHTML = '';

  if (chatState.sessions.length === 0) {
    elements.sessionList.innerHTML = '<div class="hint" style="padding:16px">暂无历史会话</div>';
    return;
  }

  for (const session of chatState.sessions) {
    const item = document.createElement('div');
    item.className = 'session-item';
    if (session.session_id === chatState.sessionId) {
      item.classList.add('active');
    }
    item.innerHTML = `
      <div class="session-title">${escapeHtml(session.title)}</div>
      <div class="session-time">${formatRelativeTime(session.updated_at)}</div>
    `;
    item.addEventListener('click', () => loadSession(session.session_id));
    elements.sessionList.appendChild(item);
  }
}

/**
 * 渲染 Ward iframe。
 */
function renderWardIframe() {
  if (!chatState.activeWardHtml) {
    elements.vizPlaceholder.classList.remove('hidden');
    elements.vizIframe.classList.add('hidden');
    return;
  }

  elements.vizPlaceholder.classList.add('hidden');
  elements.vizIframe.classList.remove('hidden');

  const src = chatState.activeWardHtml.startsWith('http') || chatState.activeWardHtml.startsWith('/')
    ? chatState.activeWardHtml
    : `/ward_analysis/${chatState.activeWardHtml}`;
  elements.vizIframe.src = src;
  elements.vizPanel.classList.remove('hidden');
  elements.vizPanel.classList.add('open');
}

// ── 工具函数 ──

/**
 * HTML 转义。
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * 简易 Markdown 渲染（支持代码块、行内代码、列表、粗体、斜体、换行）。
 * @param {string} text
 * @returns {string}
 */
function simpleMarkdown(text) {
  if (!text) return '';

  let html = escapeHtml(text);

  // 代码块
  html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code.trim()}</code></pre>`);
  // 行内代码
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // 粗体
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // 斜体
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // 无序列表
  html = html.replace(/(^|\n)- (.+)/g, '$1<li>$2</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  // 换行
  html = html.replace(/\n/g, '<br>');

  return `<div class="markdown">${html}</div>`;
}

/**
 * 格式化 ISO 时间为本地时间。
 * @param {string} iso
 * @returns {string}
 */
function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/**
 * 格式化为相对时间。
 * @param {number} timestamp
 * @returns {string}
 */
function formatRelativeTime(timestamp) {
  if (!timestamp) return '';
  const seconds = Math.floor((Date.now() / 1000 - timestamp));
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

/**
 * 滚动到底部。
 */
function scrollToBottom() {
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

// ── 交互逻辑 ──

/**
 * 发送当前输入框内容。
 */
async function handleSend() {
  const content = elements.messageInput.value.trim();
  if (!content || chatState.isStreaming) return;

  elements.messageInput.value = '';
  autoResizeTextarea();
  addUserMessage(content);

  await streamChat(content);
}

/**
 * 流式请求后端并渲染事件。
 * @param {string} content
 */
async function streamChat(content) {
  chatState.isStreaming = true;
  elements.sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const response = await sendChatMessage(content, chatState.sessionId);
    if (!response.ok) {
      throw new Error(`请求失败: ${response.status}`);
    }

    removeTypingIndicator();

    for await (const event of streamChatEvents(response)) {
      handleChatEvent(event);
    }

    await refreshHistory();
  } catch (err) {
    removeTypingIndicator();
    appendAgentChunk({
      type: 'error',
      content: `连接出错：${err instanceof Error ? err.message : String(err)}`,
    });
  } finally {
    chatState.isStreaming = false;
    elements.sendBtn.disabled = false;
  }
}

/**
 * 处理单个 ChatEvent。
 * @param {ChatEvent} event
 */
function handleChatEvent(event) {
  if (event.type === 'session') {
    updateSession(event);
    return;
  }

  updateSession(event);
  appendAgentChunk(event);
}

/**
 * 显示输入中指示器。
 */
function showTypingIndicator() {
  removeTypingIndicator();
  const indicator = document.createElement('div');
  indicator.id = 'typing-indicator';
  indicator.className = 'message agent';
  indicator.innerHTML = `
    <div class="message-avatar">AI</div>
    <div class="typing-indicator"><span></span><span></span><span></span></div>
  `;
  elements.messageList.appendChild(indicator);
  scrollToBottom();
}

/**
 * 移除输入中指示器。
 */
function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

/**
 * 刷新会话历史。
 */
async function refreshHistory() {
  try {
    chatState.sessions = await listChatHistory();
    renderSessions();
  } catch (err) {
    console.error('刷新会话历史失败:', err);
  }
}

/**
 * 加载指定会话。
 * @param {string} sessionId
 */
async function loadSession(sessionId) {
  if (chatState.isStreaming) return;
  try {
    const session = await getChatSession(sessionId);
    chatState.sessionId = session.session_id;
    chatState.conversationId = session.conversation_id;
    chatState.messages = (session.messages || []).map((m) => ({
      id: generateId(),
      role: m.role,
      type: m.role === 'user' ? 'text' : 'final',
      content: m.content,
      createdAt: new Date(m.created_at * 1000).toISOString(),
    }));
    chatState.activeWardHtml = undefined;
    elements.chatTitle.textContent = session.title || '历史会话';
    renderMessages();
    renderWardIframe();
    renderSessions();
  } catch (err) {
    console.error('加载会话失败:', err);
  }
}

/**
 * 新建会话。
 */
function newChat() {
  if (chatState.isStreaming) return;
  chatState.sessionId = undefined;
  chatState.conversationId = undefined;
  chatState.messages = [];
  chatState.activeWardHtml = undefined;
  elements.chatTitle.textContent = '新会话';
  elements.welcome.style.display = 'block';
  elements.messageList.innerHTML = '';
  elements.messageList.appendChild(elements.welcome);
  renderWardIframe();
  renderSessions();
}

/**
 * 清空当前会话。
 */
function clearChat() {
  if (chatState.isStreaming) return;
  chatState.messages = [];
  chatState.activeWardHtml = undefined;
  elements.chatTitle.textContent = '新会话';
  elements.welcome.style.display = 'block';
  elements.messageList.innerHTML = '';
  elements.messageList.appendChild(elements.welcome);
  renderWardIframe();
}

/**
 * 自动调整输入框高度。
 */
function autoResizeTextarea() {
  const textarea = elements.messageInput;
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

/**
 * 切换侧边栏。
 */
function toggleSidebar() {
  elements.sidebar.classList.toggle('open');
}

/**
 * 关闭可视化面板。
 */
function closeVizPanel() {
  elements.vizPanel.classList.add('hidden');
  elements.vizPanel.classList.remove('open');
}

// ── 事件绑定 ──

function bindEvents() {
  elements.sendBtn.addEventListener('click', handleSend);

  elements.messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  elements.messageInput.addEventListener('input', autoResizeTextarea);

  elements.newChatBtn.addEventListener('click', newChat);
  elements.clearChatBtn.addEventListener('click', clearChat);
  elements.menuToggle.addEventListener('click', toggleSidebar);
  elements.closeVizBtn.addEventListener('click', closeVizPanel);

  if (elements.presetCards) {
    elements.presetCards.addEventListener('click', (e) => {
      const target = /** @type {HTMLElement} */ (e.target);
      if (target.classList.contains('preset-card')) {
        const message = target.dataset.message;
        if (message) {
          elements.messageInput.value = message;
          autoResizeTextarea();
          handleSend();
        }
      }
    });
  }

  // 点击侧边栏外部关闭移动端侧边栏
  document.addEventListener('click', (e) => {
    const target = /** @type {Node} */ (e.target);
    if (
      window.innerWidth <= 768 &&
      elements.sidebar.classList.contains('open') &&
      !elements.sidebar.contains(target) &&
      !elements.menuToggle.contains(target)
    ) {
      elements.sidebar.classList.remove('open');
    }
  });
}

// ── 初始化 ──

async function init() {
  bindEvents();
  autoResizeTextarea();
  await refreshHistory();
  console.log('Dota Helper 聊天前端已初始化');
}

init();
