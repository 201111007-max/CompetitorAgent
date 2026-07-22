<template>
  <div class="review-timeline">
    <div
      v-for="item in normalizedPhases"
      :key="item.phase"
      class="timeline-item"
      :class="{ active: item.phase === currentPhase, completed: item.completed }"
    >
      <div class="timeline-marker">
        <span v-if="item.completed" class="marker-icon">✓</span>
        <span v-else-if="item.phase === currentPhase" class="marker-icon pulsing">●</span>
        <span v-else class="marker-icon">○</span>
      </div>
      <div class="timeline-content">
        <div class="phase-name">{{ item.label }}</div>
        <div class="phase-status">{{ item.statusText }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PhaseProgress } from '@/stores/review'

const props = defineProps<{
  phases: PhaseProgress[]
  currentPhase?: string
}>()

const phaseLabelMap: Record<string, string> = {
  laning: '对线期',
  teamfight: '团战分析',
  economy: '经济发育',
  decisions: '决策判断',
  vision: '视野控制'
}

const normalizedPhases = computed(() => {
  return props.phases.map((p) => ({
    phase: p.phase,
    label: phaseLabelMap[p.phase] || p.phase,
    completed: p.completed,
    statusText: p.completed ? '已完成' : p.started ? '分析中' : '待开始'
  }))
})
</script>

<style scoped>
.review-timeline {
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
}

.timeline-item {
  display: flex;
  align-items: center;
  gap: var(--gap-md);
  padding: 10px 12px;
  background: var(--bg-input);
  border-radius: var(--radius-lg);
  border: 1px solid transparent;
  transition: border-color 0.2s ease, background 0.2s ease;
}

.timeline-item.completed {
  border-color: rgba(74, 222, 128, 0.25);
  background: rgba(74, 222, 128, 0.08);
}

.timeline-item.active {
  border-color: rgba(191, 46, 26, 0.4);
  background: rgba(191, 46, 128, 0.08);
}

.timeline-marker {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--bg-card);
  border: 1px solid var(--border-secondary);
  flex-shrink: 0;
  font-size: 12px;
}

.timeline-item.completed .timeline-marker {
  background: rgba(74, 222, 128, 0.15);
  border-color: rgba(74, 222, 128, 0.4);
  color: var(--status-success);
}

.timeline-item.active .timeline-marker {
  background: rgba(191, 46, 26, 0.15);
  border-color: var(--dota-red);
  color: var(--dota-red-light);
}

.marker-icon.pulsing {
  animation: pulse 1.5s infinite;
}

.timeline-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.phase-name {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}

.phase-status {
  font-size: 11px;
  color: var(--text-tertiary);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
