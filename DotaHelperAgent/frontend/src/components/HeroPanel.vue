<template>
  <div class="hero-panel">
    <div class="hero-header">
      <h3>测试助手</h3>
      <button @click="$emit('close')" class="close-btn">×</button>
    </div>

    <div class="hero-content">
      <div class="query-section">
        <button 
          @click="handleGenerate" 
          class="generate-btn"
          :disabled="heroStore.isLoading"
        >
          {{ heroStore.isLoading ? '生成中...' : '随机生成查询' }}
        </button>
      </div>

      <div v-if="heroStore.error" class="error-message">
        {{ heroStore.error }}
      </div>

      <div v-if="heroStore.currentQuery" class="query-result">
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
                class="hero-tag our"
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
                class="hero-tag enemy"
              >
                {{ hero }}
              </span>
            </div>
          </div>
        </div>

        <div class="action-section">
          <button 
            @click="handleSendQuery" 
            class="send-btn"
            :disabled="isSending"
          >
            {{ isSending ? '发送中...' : '发送到聊天' }}
          </button>
          <button @click="handleClear" class="clear-btn">清空</button>
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
            class="clear-history-btn"
          >
            清空历史
          </button>
        </div>

        <div v-if="historyList.length > 0" class="history-list">
          <div 
            v-for="(item, index) in historyList" 
            :key="index" 
            class="history-item"
          >
            <div class="history-content">
              <div class="history-query">{{ item.query }}</div>
              <div class="history-meta">
                <span class="history-time">{{ formatHistoryTime(item.timestamp) }}</span>
                <span v-if="item.our_heroes.length" class="history-heroes our">
                  我方: {{ item.our_heroes.join(', ') }}
                </span>
                <span v-if="item.enemy_heroes.length" class="history-heroes enemy">
                  敌方: {{ item.enemy_heroes.join(', ') }}
                </span>
              </div>
            </div>
            <div class="history-actions">
              <button @click="handleCopy(item.query)" class="copy-btn" title="复制">
                📋
              </button>
              <button @click="handleUseHistory(item)" class="use-btn" title="使用">
                使用
              </button>
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
import { ref, computed, onMounted } from 'vue'
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
  background: rgba(0, 0, 0, 0.4);
}

.hero-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.3);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.hero-header h3 {
  margin: 0;
  font-size: 14px;
  color: white;
}

.close-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: background 0.2s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.hero-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.query-section {
  margin-bottom: 16px;
}

.generate-btn {
  width: 100%;
  padding: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.generate-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.generate-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-message {
  padding: 12px;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  border-radius: 8px;
  color: #f87171;
  font-size: 13px;
  margin-bottom: 16px;
}

.query-result {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.query-text {
  margin-bottom: 16px;
}

.query-text p {
  margin: 0;
  color: rgba(255, 255, 255, 0.9);
  font-size: 14px;
  line-height: 1.6;
}

.heroes-section {
  margin-bottom: 16px;
}

.hero-group {
  margin-bottom: 12px;
}

.hero-group:last-child {
  margin-bottom: 0;
}

.hero-group h4 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hero-tag {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.hero-tag.our {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.3);
}

.hero-tag.enemy {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.3);
}

.action-section {
  display: flex;
  gap: 8px;
}

.send-btn {
  flex: 1;
  padding: 10px;
  background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.2s;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.send-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.clear-btn {
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: white;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}

.clear-btn:hover {
  background: rgba(255, 255, 255, 0.15);
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: rgba(255, 255, 255, 0.4);
  font-size: 13px;
  margin-bottom: 16px;
}

.history-section {
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding-top: 16px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.history-header h4 {
  margin: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.7);
}

.clear-history-btn {
  padding: 4px 8px;
  background: rgba(248, 113, 113, 0.2);
  border: none;
  border-radius: 4px;
  color: #f87171;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}

.clear-history-btn:hover {
  background: rgba(248, 113, 113, 0.3);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 300px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  gap: 8px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  transition: background 0.2s;
}

.history-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.history-content {
  flex: 1;
  min-width: 0;
}

.history-query {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  margin-bottom: 4px;
}

.history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10px;
}

.history-time {
  color: rgba(255, 255, 255, 0.4);
}

.history-heroes {
  color: rgba(255, 255, 255, 0.5);
}

.history-heroes.our {
  color: #4ade80;
}

.history-heroes.enemy {
  color: #f87171;
}

.history-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.copy-btn,
.use-btn {
  padding: 4px 8px;
  border: none;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}

.copy-btn {
  background: rgba(255, 255, 255, 0.1);
}

.copy-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.use-btn {
  background: rgba(102, 126, 234, 0.3);
  color: #a5b4fc;
}

.use-btn:hover {
  background: rgba(102, 126, 234, 0.5);
}

.no-history {
  text-align: center;
  padding: 20px;
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
}
</style>
