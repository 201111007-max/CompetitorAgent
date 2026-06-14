<template>
  <div class="side-panel" :class="{ collapsed: collapsed }">
    <div class="panel-header">
      <button class="icon-btn" @click="$emit('toggle')" title="切换侧边栏">
        <span class="hamburger">☰</span>
      </button>
      <button v-if="!collapsed" class="new-chat-btn" @click="$emit('newChat')">
        + 新建对话
      </button>
    </div>

    <div v-if="!collapsed" class="search-area">
      <input
        class="dota-input search-input"
        type="text"
        placeholder="搜索对话..."
        v-model="searchQuery"
      />
    </div>

    <div class="chat-list" :class="{ 'icon-only': collapsed }">
      <div
        v-for="chat in filteredChats"
        :key="chat.id"
        class="chat-item"
        :class="{ active: chat.id === chatStore.currentConversationId }"
        @click="$emit('selectChat', chat.id)"
        :title="chat.title"
      >
        <span class="chat-icon">💬</span>
        <span v-if="!collapsed" class="chat-title">{{ chat.title }}</span>
        <span v-if="!collapsed" class="chat-time">{{ formatTime(chat.updatedAt) }}</span>
        <button
          v-if="!collapsed"
          class="delete-btn"
          @click.stop="$emit('deleteChat', chat.id)"
          title="删除对话"
        >×</button>
      </div>
      <div v-if="filteredChats.length === 0 && !collapsed" class="empty-hint">
        暂无对话
      </div>
    </div>

    <div class="panel-footer">
      <button
        class="footer-btn"
        :class="{ active: showHero }"
        @click="$emit('openHeroPanel')"
        title="英雄面板"
      >
        <span class="footer-icon">⚔</span>
        <span v-if="!collapsed" class="footer-label">英雄面板</span>
      </button>
      <button
        class="footer-btn"
        :class="{ active: showLog }"
        @click="$emit('openLogPanel')"
        title="日志面板"
      >
        <span class="footer-icon">📋</span>
        <span v-if="!collapsed" class="footer-label">日志面板</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useChatStore } from '@/stores/chat'

const props = withDefaults(defineProps<{
  collapsed: boolean
  showHero?: boolean
  showLog?: boolean
}>(), {
  showHero: false,
  showLog: false
})

defineEmits<{
  toggle: []
  newChat: []
  selectChat: [id: string]
  deleteChat: [id: string]
  openHeroPanel: []
  openLogPanel: []
}>()

const chatStore = useChatStore()
const searchQuery = ref('')

const filteredChats = computed(() => {
  const convs = chatStore.sortedConversations
  if (!searchQuery.value) return convs
  return convs.filter(c =>
    c.title.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

const formatTime = (ts: number) => {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.side-panel {
  width: var(--sidebar-expanded-width);
  background: var(--bg-sidebar-collapsed);
  border-right: 1px solid var(--border-primary);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-normal);
  flex-shrink: 0;
  overflow: hidden;
}

.side-panel.collapsed {
  width: var(--sidebar-collapsed-width);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--gap-md);
  padding: var(--gap-md);
  border-bottom: 1px solid var(--border-primary);
  min-height: 52px;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 16px;
  transition: background var(--transition-fast);
  flex-shrink: 0;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}

.hamburger {
  line-height: 1;
}

.new-chat-btn {
  padding: 6px 12px;
  background: rgba(191, 46, 26, 0.15);
  color: var(--dota-red-light);
  border: 1px solid rgba(191, 46, 26, 0.3);
  border-radius: var(--radius-md);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--transition-fast);
}

.new-chat-btn:hover {
  background: rgba(191, 46, 26, 0.25);
}

.search-area {
  padding: var(--gap-md);
}

.search-input {
  font-size: 12px;
  padding: 8px 12px;
}

.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-xs) var(--gap-md);
}

.chat-list.icon-only {
  padding: var(--gap-xs);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.chat-item {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  border-left: 2px solid transparent;
}

.chat-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.chat-item.active {
  background: rgba(191, 46, 26, 0.1);
  border-left-color: var(--dota-red);
}

.icon-only .chat-item {
  justify-content: center;
  padding: 8px;
}

.chat-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.chat-title {
  flex: 1;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-time {
  font-size: 11px;
  color: var(--text-disabled);
  flex-shrink: 0;
}

.delete-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-disabled);
  font-size: 14px;
  line-height: 1;
  opacity: 0;
  transition: opacity var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
}

.chat-item:hover .delete-btn {
  opacity: 1;
}

.delete-btn:hover {
  color: var(--dota-red);
  background: rgba(191, 46, 26, 0.15);
}

.empty-hint {
  text-align: center;
  color: var(--text-disabled);
  font-size: 12px;
  padding: 24px 0;
}

.panel-footer {
  padding: var(--gap-md);
  border-top: 1px solid var(--border-primary);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.collapsed .panel-footer {
  align-items: center;
}

.footer-btn {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-tertiary);
  font-size: 13px;
  transition: background var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
}

.footer-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.footer-btn.active {
  background: rgba(191, 46, 26, 0.12);
  color: var(--dota-red-light);
}

.footer-icon {
  font-size: 15px;
  flex-shrink: 0;
}

.footer-label {
  font-size: 13px;
}

/* 移动端隐藏侧边栏 */
@media (max-width: 767px) {
  .side-panel {
    display: none;
  }
}
</style>
