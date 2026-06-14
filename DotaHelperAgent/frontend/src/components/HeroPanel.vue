<template>
  <div class="hero-panel">
    <div class="hero-content">
      <div class="query-section">
        <button
          @click="handleGenerate"
          class="dota-btn generate-btn"
          :disabled="heroStore.isLoading"
        >
          <span class="btn-icon">⚡</span>
          {{ heroStore.isLoading ? '生成中...' : '随机生成查询' }}
        </button>
      </div>

      <div v-if="heroStore.error" class="error-message">
        {{ heroStore.error }}
      </div>

      <div v-if="heroStore.currentQuery" class="query-result dota-card">
        <div class="query-text">
          <p>{{ heroStore.currentQuery.query }}</p>
        </div>

        <div class="heroes-section">
          <div v-if="heroStore.currentQuery.our_heroes.length > 0" class="hero-group">
            <h4>我方英雄</h4>
            <div class="hero-tags">
              <span
                v-for="hero in heroStore.currentQuery.our_heroes"
                :key="hero"
                class="dota-tag dota-tag-ally"
              >
                {{ hero }}
              </span>
            </div>
          </div>

          <div v-if="heroStore.currentQuery.enemy_heroes.length > 0" class="hero-group">
            <h4>敌方英雄</h4>
            <div class="hero-tags">
              <span
                v-for="hero in heroStore.currentQuery.enemy_heroes"
                :key="hero"
                class="dota-tag dota-tag-enemy"
              >
                {{ hero }}
              </span>
            </div>
          </div>
        </div>

        <div class="action-section">
          <button
            @click="handleSendQuery"
            class="dota-btn"
            :disabled="isSending"
          >
            {{ isSending ? '发送中...' : '发送到聊天' }}
          </button>
          <button @click="handleClear" class="dota-btn-ghost">清空</button>
        </div>
      </div>

      <div v-else class="empty-state">
        <p>点击上方按钮随机生成英雄推荐查询</p>
      </div>

      <div class="history-section">
        <div class="history-header">
          <h4>历史记录 ({{ historyList.length }}/20)</h4>
          <button
            v-if="historyList.length > 0"
            @click="handleClearHistory"
            class="dota-btn-ghost clear-history-btn"
          >
            清空历史
          </button>
        </div>

        <div v-if="historyList.length > 0" class="history-list">
          <div
            v-for="(item, index) in historyList"
            :key="index"
            class="history-item dota-card"
          >
            <div class="history-content">
              <div class="history-query">{{ item.query }}</div>
              <div class="history-meta">
                <span class="history-time">{{ formatHistoryTime(item.timestamp) }}</span>
                <span v-if="item.our_heroes.length" class="dota-tag dota-tag-ally history-hero-tag">
                  我方: {{ item.our_heroes.join(', ') }}
                </span>
                <span v-if="item.enemy_heroes.length" class="dota-tag dota-tag-enemy history-hero-tag">
                  敌方: {{ item.enemy_heroes.join(', ') }}
                </span>
              </div>
            </div>
            <div class="history-actions">
              <button @click="handleCopy(item.query)" class="dota-btn-ghost" title="复制">📋</button>
              <button @click="handleUseHistory(item)" class="use-btn" title="使用">使用</button>
            </div>
          </div>
        </div>

        <div v-else class="no-history">
          暂无历史记录
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from '@/utils/message'
import { useHeroStore } from '@/stores/hero'
import { useHeroQuery } from '@/composables/useHeroQuery'
import { useChatStore } from '@/stores/chat'
import type { HeroQuery } from '@/types/hero'

const emit = defineEmits<{
  close: []
  sendQuery: [query: string]
}>()

const heroStore = useHeroStore()
const { generateQuery, clearQuery } = useHeroQuery()
const chatStore = useChatStore()
const isSending = ref(false)
const historyList = ref<(HeroQuery & { timestamp: string })[]>([])

const loadHistory = () => {
  historyList.value = heroStore.getHistory()
}

const formatHistoryTime = (timestamp: string) => {
  try {
    const date = new Date(timestamp)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return timestamp
  }
}

const handleGenerate = async () => {
  await generateQuery()
  loadHistory()
}

const handleClear = () => {
  clearQuery()
}

const handleSendQuery = () => {
  if (heroStore.currentQuery && !chatStore.isStreaming) {
    isSending.value = true
    emit('sendQuery', heroStore.currentQuery.query)
    setTimeout(() => {
      isSending.value = false
    }, 500)
  }
}

const handleCopy = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制到剪贴板')
  } catch (e) {
    console.error('Copy failed:', e)
    message.error('复制失败')
  }
}

const handleUseHistory = (item: HeroQuery) => {
  heroStore.setCurrentQuery({
    query: item.query,
    our_heroes: item.our_heroes,
    enemy_heroes: item.enemy_heroes
  }, false)
}

const handleClearHistory = () => {
  heroStore.clearHistory()
  historyList.value = []
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.hero-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.hero-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--gap-xl);
}

.query-section {
  margin-bottom: var(--gap-xl);
}

.generate-btn {
  width: 100%;
  padding: 14px;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--gap-sm);
  background: linear-gradient(135deg, var(--dota-red), var(--dota-red-dark));
  box-shadow: var(--shadow-btn);
}

.generate-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(191, 46, 26, 0.4);
}

.btn-icon {
  font-size: 16px;
}

.error-message {
  padding: var(--gap-xl);
  background: rgba(248, 113, 113, 0.08);
  border: 1px solid rgba(248, 113, 113, 0.2);
  border-radius: var(--radius-lg);
  color: var(--status-error);
  font-size: 13px;
  margin-bottom: var(--gap-xl);
}

.query-result {
  margin-bottom: var(--gap-xl);
}

.query-text p {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.6;
}

.heroes-section {
  margin: var(--gap-xl) 0;
}

.hero-group {
  margin-bottom: var(--gap-lg);
}

.hero-group h4 {
  margin: 0 0 var(--gap-sm) 0;
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
}

.action-section {
  display: flex;
  gap: var(--gap-md);
}

.action-section .dota-btn {
  flex: 1;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-disabled);
  font-size: 13px;
  margin-bottom: var(--gap-xl);
}

.history-section {
  border-top: 1px solid var(--border-primary);
  padding-top: var(--gap-xl);
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--gap-lg);
}

.history-header h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.clear-history-btn {
  font-size: 11px;
  color: var(--status-error);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: var(--gap-md);
  max-height: 300px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  gap: var(--gap-md);
  padding: var(--gap-lg);
}

.history-item:hover {
  box-shadow: var(--shadow-card-hover);
}

.history-content {
  flex: 1;
  min-width: 0;
}

.history-query {
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  margin-bottom: var(--gap-xs);
}

.history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-sm);
  font-size: 10px;
}

.history-time {
  color: var(--text-disabled);
}

.history-hero-tag {
  font-size: 10px;
  padding: 1px 6px;
}

.history-actions {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.use-btn {
  padding: 4px 10px;
  background: rgba(198, 164, 78, 0.15);
  border: 1px solid rgba(198, 164, 78, 0.3);
  border-radius: var(--radius-md);
  color: var(--dota-gold);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.use-btn:hover {
  background: rgba(198, 164, 78, 0.25);
}

.no-history {
  text-align: center;
  padding: 20px;
  color: var(--text-disabled);
  font-size: 12px;
}
</style>
