<template>
  <div class="review-history">
    <div class="history-header">
      <h3 class="history-title">复盘历史</h3>
      <button
        v-if="history.length > 0"
        class="refresh-btn"
        :disabled="loading"
        @click="$emit('refresh')"
      >
        {{ loading ? '加载中...' : '刷新' }}
      </button>
    </div>

    <div v-if="history.length === 0" class="empty-state">
      {{ loading ? '加载历史记录...' : '暂无复盘历史' }}
    </div>

    <div v-else class="history-list">
      <div
        v-for="item in history"
        :key="item.match_id"
        class="history-item"
        @click="$emit('select', item.match_id)"
      >
        <div class="history-main">
          <span class="match-id">{{ item.match_id }}</span>
          <span class="status-badge" :class="item.status">{{ statusText(item.status) }}</span>
        </div>
        <div class="history-meta">
          <span class="meta-score">评分 {{ item.overall_score.toFixed(1) }}</span>
          <span class="meta-confidence">置信 {{ (item.overall_confidence * 100).toFixed(0) }}%</span>
          <span class="meta-time">{{ formatTime(item.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ReviewHistoryItem } from '@/types/review'

defineProps<{
  history: ReviewHistoryItem[]
  loading?: boolean
}>()

defineEmits<{
  select: [matchId: string]
  refresh: []
}>()

const statusText = (status: string) => {
  const map: Record<string, string> = {
    completed: '已完成',
    error: '失败',
    interrupted: '已中断',
    running: '分析中'
  }
  return map[status] || status
}

const formatTime = (iso: string) => {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.review-history {
  background: var(--bg-card);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  padding: var(--gap-xl);
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-title {
  font-size: 15px;
  color: var(--dota-gold);
  margin: 0;
  font-weight: 600;
}

.refresh-btn {
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-secondary);
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.refresh-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.empty-state {
  text-align: center;
  color: var(--text-disabled);
  font-size: 13px;
  padding: 24px 0;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  max-height: 320px;
  overflow-y: auto;
}

.history-item {
  padding: 12px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.history-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.history-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--gap-md);
}

.match-id {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
  font-family: var(--font-mono);
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-tertiary);
}

.status-badge.completed {
  background: rgba(74, 222, 128, 0.12);
  color: var(--status-success);
}

.status-badge.error {
  background: rgba(248, 113, 113, 0.12);
  color: var(--status-error);
}

.status-badge.interrupted {
  background: rgba(251, 191, 36, 0.12);
  color: var(--status-warning);
}

.status-badge.running {
  background: rgba(96, 165, 250, 0.12);
  color: var(--status-info);
}

.history-meta {
  display: flex;
  gap: var(--gap-md);
  font-size: 11px;
  color: var(--text-tertiary);
}

.meta-score {
  color: var(--dota-gold);
}

.meta-confidence {
  color: var(--status-info);
}
</style>
