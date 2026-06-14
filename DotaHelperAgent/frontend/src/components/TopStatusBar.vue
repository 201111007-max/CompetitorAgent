<template>
  <div class="top-status-bar">
    <div class="bar-left">
      <div class="brand-icon">D</div>
      <span class="brand-title">DOTA HELPER AGENT</span>
      <span class="connection-status" :class="connected ? 'connected' : 'disconnected'">
        <span class="status-dot"></span>
        {{ connected ? '已连接' : '未连接' }}
      </span>
    </div>
    <div class="bar-right">
      <span v-if="traceId" class="trace-id" @click="copyTraceId" title="点击复制 Trace ID">
        Trace: {{ traceIdShort }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()

const connected = computed(() => !chatStore.isStreaming)
const traceId = computed(() => chatStore.traceId)
const traceIdShort = computed(() => {
  if (!traceId.value) return ''
  return traceId.value.length > 12
    ? `${traceId.value.slice(0, 6)}...${traceId.value.slice(-4)}`
    : traceId.value
})

const copyTraceId = async () => {
  if (traceId.value) {
    try {
      await navigator.clipboard.writeText(traceId.value)
    } catch {
      // 降级方案
      const ta = document.createElement('textarea')
      ta.value = traceId.value
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
  }
}
</script>

<style scoped>
.top-status-bar {
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--gap-xl);
  background: var(--bg-sidebar-collapsed);
  border-bottom: 1px solid var(--border-primary);
  flex-shrink: 0;
}

.bar-left {
  display: flex;
  align-items: center;
  gap: var(--gap-md);
}

.brand-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--dota-red), var(--dota-red-dark));
  border-radius: var(--radius-md);
  font-weight: 700;
  font-size: 14px;
  color: white;
}

.brand-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 1px;
  color: var(--dota-gold);
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-disabled);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.connected .status-dot {
  background: var(--status-success);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}

.disconnected .status-dot {
  background: var(--status-error);
  animation: pulse 2s infinite;
}

.bar-right {
  display: flex;
  align-items: center;
}

.trace-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-disabled);
  cursor: pointer;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.trace-id:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-tertiary);
}
</style>
