<template>
  <div class="log-panel">
    <div class="log-header">
      <h3>实时日志</h3>
      <div class="log-controls">
        <select v-model="logStore.filter.level" class="level-select">
          <option value="ALL">ALL</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <button @click="handleClear" class="clear-btn">清空</button>
      </div>
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
  background: rgba(0, 0, 0, 0.4);
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.3);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.log-header h3 {
  margin: 0;
  font-size: 14px;
  color: white;
}

.log-controls {
  display: flex;
  gap: 8px;
}

.level-select {
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  color: white;
  font-size: 12px;
  cursor: pointer;
}

.level-select option {
  background: #1a1a2e;
  color: white;
}

.clear-btn {
  padding: 4px 12px;
  background: rgba(233, 69, 96, 0.8);
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.clear-btn:hover {
  background: rgba(233, 69, 96, 1);
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 11px;
  line-height: 1.6;
}

.log-entry {
  padding: 2px 4px;
  border-radius: 2px;
  margin-bottom: 2px;
}

.log-entry.debug {
  color: #888;
}

.log-entry.info {
  color: #4ade80;
}

.log-entry.warning {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.1);
}

.log-entry.error {
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.timestamp {
  color: rgba(255, 255, 255, 0.5);
  margin-right: 8px;
}

.level {
  font-weight: bold;
  margin-right: 4px;
}

.component {
  color: #60a5fa;
  margin-right: 4px;
}

.message {
  color: rgba(255, 255, 255, 0.9);
}

.empty {
  color: rgba(255, 255, 255, 0.4);
  text-align: center;
  padding: 20px;
}

.log-footer {
  display: flex;
  justify-content: space-between;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.2);
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 11px;
}

.connected {
  color: #4ade80;
}

.disconnected {
  color: #f87171;
}

.count {
  color: rgba(255, 255, 255, 0.5);
}
</style>
