<template>
  <div class="review-panel">
    <div class="panel-header">
      <h2 class="panel-title">赛后复盘</h2>
      <p class="panel-subtitle">输入比赛 ID，实时生成对局分析报告</p>
    </div>

    <div class="control-bar">
      <input
        v-model="inputMatchId"
        class="dota-input match-input"
        type="text"
        placeholder="请输入比赛 ID（例如 8905359313）"
        :disabled="reviewStore.isAnalyzing"
        @keyup.enter="handleStart"
      />
      <button
        class="dota-btn start-btn"
        :disabled="!canStart"
        @click="handleStart"
      >
        {{ reviewStore.isAnalyzing ? '分析中...' : '开始复盘' }}
      </button>
      <button
        v-if="reviewStore.isAnalyzing"
        class="dota-btn-ghost interrupt-btn"
        @click="handleInterrupt"
      >
        中断
      </button>
      <button
        v-else-if="reviewStore.status !== 'idle'"
        class="dota-btn-ghost reset-btn"
        @click="handleReset"
      >
        重置
      </button>
    </div>

    <div v-if="reviewStore.isError" class="error-banner">
      <span class="error-icon">⚠</span>
      <span class="error-message">{{ reviewStore.errorMessage }}</span>
    </div>

    <div class="review-body">
      <div class="review-main">
        <ReviewProgress
          :progress="reviewStore.progress"
          :current-phase="reviewStore.currentPhase"
        />
        <ReviewTimeline
          :phases="reviewStore.phaseList"
          :current-phase="reviewStore.currentPhase"
        />
        <ReviewReport v-if="reviewStore.report" :report="reviewStore.report" />
      </div>
      <div class="review-side">
        <ReviewHistory
          :history="reviewStore.history"
          :loading="isLoadingHistory"
          @select="handleSelectHistory"
          @refresh="loadHistory"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useReview } from '@/composables/useReview'
import ReviewProgress from './ReviewProgress.vue'
import ReviewTimeline from './ReviewTimeline.vue'
import ReviewReport from './ReviewReport.vue'
import ReviewHistory from './ReviewHistory.vue'

const inputMatchId = ref('')
const { reviewStore, startReview, interrupt, loadHistory, loadReport, reset, isLoadingHistory } = useReview()

const canStart = computed(() => {
  return inputMatchId.value.trim().length > 0 && !reviewStore.isAnalyzing
})

const handleStart = () => {
  const matchId = inputMatchId.value.trim()
  if (!matchId || reviewStore.isAnalyzing) return
  startReview(matchId)
}

const handleInterrupt = async () => {
  await interrupt()
}

const handleReset = () => {
  inputMatchId.value = ''
  reset()
}

const handleSelectHistory = (matchId: string) => {
  inputMatchId.value = matchId
  reviewStore.reset()
  loadReport(matchId)
  loadHistory()
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.review-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--gap-xl);
  gap: var(--gap-lg);
  overflow: hidden;
}

.panel-header {
  flex-shrink: 0;
}

.panel-title {
  font-size: 20px;
  color: var(--dota-gold);
  margin: 0 0 4px;
  font-weight: 600;
}

.panel-subtitle {
  font-size: 13px;
  color: var(--text-tertiary);
  margin: 0;
}

.control-bar {
  display: flex;
  gap: var(--gap-md);
  flex-shrink: 0;
  align-items: center;
}

.match-input {
  flex: 1;
  min-width: 0;
}

.start-btn {
  flex-shrink: 0;
}

.interrupt-btn,
.reset-btn {
  flex-shrink: 0;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 10px 14px;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.25);
  border-radius: var(--radius-lg);
  color: var(--status-error);
  font-size: 13px;
  flex-shrink: 0;
}

.error-icon {
  font-size: 14px;
}

.review-body {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: var(--gap-xl);
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.review-main {
  display: flex;
  flex-direction: column;
  gap: var(--gap-lg);
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}

.review-side {
  overflow-y: auto;
  min-height: 0;
}

@media (max-width: 1024px) {
  .review-body {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .review-main,
  .review-side {
    overflow: visible;
  }
}
</style>
