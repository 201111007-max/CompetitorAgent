<template>
  <div class="log-panel">
    <div class="log-controls">
      <select v-model="logStore.filter.level" class="dota-input level-select">
        <option value="ALL">ALL</option>
        <option value="DEBUG">DEBUG</option>
        <option value="INFO">INFO</option>
        <option value="WARNING">WARNING</option>
        <option value="ERROR">ERROR</option>
      </select>
      <button @click="handleClear" class="dota-btn-ghost">清空</button>
    </div>

    <div class="log-content" ref="logContainer">
      <div
        v-for="(entry, index) in validEntries"
        :key="index"
        class="log-entry"
        :class="getLevelClass(entry.level)"
      >
        <span class="timestamp">{{ formatTime(entry.timestamp) }}</span>
        <span class="level">[{{ entry.level }}]</span>
        <span v-if="entry.component" class="component">[{{ entry.component }}]</span>
        <span class="message">{{ entry.message }}</span>
      </div>
      <div v-if="validEntries.length === 0" class="empty">
        暂无日志
      </div>
    </div>

    <div class="log-footer">
      <span :class="isConnected ? 'connected' : 'disconnected'">
        <span class="status-dot" :class="isConnected ? 'on' : 'off'"></span>
        {{ isConnected ? '已连接' : '未连接' }}
      </span>
      <span class="count">{{ validEntries.length }} 条</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useLogStore } from '@/stores/log'
import { useLogStream, clearLogs } from '@/composables/useLogStream'
import type { LogEntry } from '@/types/log'

const logStore = useLogStore()
const { connect, isConnected } = useLogStream()
const logContainer = ref<HTMLElement | null>(null)

const validEntries = computed(() => {
  return logStore.filteredEntries.filter(
    (entry: LogEntry) => entry.level && entry.message
  )
})

const getLevelClass = (level: string): string => {
  const levelMap: Record<string, string> = {
    DEBUG: 'debug',
    INFO: 'info',
    WARNING: 'warning',
    ERROR: 'error'
  }
  return levelMap[level] || 'info'
}

const formatTime = (timestamp: string) => {
  try {
    return new Date(timestamp).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch {
    return timestamp
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

const handleClear = async () => {
  await clearLogs()
  logStore.clearEntries()
}

watch(
  () => logStore.entries.length,
  () => scrollToBottom()
)

onMounted(() => {
  connect()
})
</script>

<style scoped>
.log-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.log-controls {
  display: flex;
  gap: var(--gap-md);
  padding: var(--gap-md) var(--gap-xl);
  border-bottom: 1px solid var(--border-primary);
}

.level-select {
  padding: 6px 10px;
  font-size: 12px;
  width: auto;
  min-width: 90px;
}

.level-select option {
  background: var(--bg-card);
  color: var(--text-primary);
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-md) var(--gap-xl);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
}

.log-entry {
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  margin-bottom: 2px;
}

.log-entry.debug {
  color: var(--text-disabled);
}

.log-entry.info {
  color: var(--status-success);
}

.log-entry.warning {
  color: var(--status-warning);
  background: rgba(251, 191, 36, 0.06);
}

.log-entry.error {
  color: var(--status-error);
  background: rgba(248, 113, 113, 0.06);
}

.timestamp {
  color: var(--text-disabled);
  margin-right: var(--gap-md);
}

.level {
  font-weight: bold;
  margin-right: var(--gap-xs);
}

.component {
  color: var(--status-info);
  margin-right: var(--gap-xs);
}

.message {
  color: var(--text-secondary);
}

.empty {
  color: var(--text-disabled);
  text-align: center;
  padding: 20px;
}

.log-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--gap-md) var(--gap-xl);
  background: var(--bg-sidebar-collapsed);
  border-top: 1px solid var(--border-primary);
  font-size: 11px;
}

.connected,
.disconnected {
  display: flex;
  align-items: center;
  gap: 5px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-dot.on {
  background: var(--status-success);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}

.status-dot.off {
  background: var(--status-error);
  animation: pulse 2s infinite;
}

.connected {
  color: var(--status-success);
}

.disconnected {
  color: var(--status-error);
}

.count {
  color: var(--text-disabled);
}
</style>
