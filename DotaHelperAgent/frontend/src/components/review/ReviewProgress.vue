<template>
  <div class="review-progress">
    <div class="progress-header">
      <span class="phase-label">{{ displayLabel }}</span>
      <span class="progress-percent">{{ percentage }}%</span>
    </div>
    <div class="progress-track">
      <div class="progress-bar" :style="{ width: `${percentage}%` }"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  progress: number
  currentPhase?: string
}>()

const percentage = computed(() => Math.min(100, Math.max(0, Math.round(props.progress * 100))))
const displayLabel = computed(() => props.currentPhase || '等待开始')
</script>

<style scoped>
.review-progress {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.phase-label {
  color: var(--text-secondary);
  text-transform: capitalize;
}

.progress-percent {
  color: var(--dota-gold);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.progress-track {
  height: 8px;
  background: var(--bg-input);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--dota-red) 0%, var(--dota-gold) 100%);
  border-radius: var(--radius-pill);
  transition: width 0.3s ease;
}
</style>
