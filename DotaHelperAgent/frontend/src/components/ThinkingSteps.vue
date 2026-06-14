<template>
  <div class="thinking-steps">
    <div class="steps-header" @click="toggle">
      <div class="steps-summary">
        <span class="steps-icon" :class="{ expanded: !isCollapsed }">▶</span>
        <span class="steps-label">思考过程</span>
        <span class="steps-count">{{ steps.length }} 步</span>
        <span v-if="duration" class="steps-duration">{{ duration }}</span>
        <span v-if="hasRunning" class="steps-running">
          <span class="dot-pulse"></span>
          执行中
        </span>
      </div>
    </div>
    <div class="steps-body" v-show="!isCollapsed">
      <div
        v-for="(step, index) in steps"
        :key="index"
        class="step-item"
        :class="[`step-${step.type}`, `step-${step.status}`]"
      >
        <div class="step-header">
          <span class="step-icon">{{ getStepIcon(step) }}</span>
          <span class="step-type">{{ getStepLabel(step) }}</span>
          <span class="step-status" :class="`status-${step.status}`">
            <template v-if="step.status === 'running'">
              <span class="spinner"></span>
            </template>
            <template v-else-if="step.status === 'done'">✓</template>
            <template v-else-if="step.status === 'error'">✗</template>
          </span>
        </div>
        <div class="step-content">
          <span class="step-text">{{ step.content }}</span>
          <span v-if="step.tool" class="step-tool">{{ step.tool }}</span>
        </div>
        <div v-if="step.result" class="step-result">
          <span class="result-label">结果:</span>
          <span class="result-text">{{ step.result }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ThinkingStep } from '@/types/chat'

const props = withDefaults(defineProps<{
  steps: ThinkingStep[]
  collapsed?: boolean
  duration?: string
}>(), {
  collapsed: true
})

const isCollapsed = ref(props.collapsed)

const hasRunning = computed(() => props.steps.some(s => s.status === 'running'))

const toggle = () => {
  isCollapsed.value = !isCollapsed.value
}

const getStepIcon = (step: ThinkingStep): string => {
  const icons: Record<string, string> = {
    think: '💭',
    plan: '📋',
    action: '🔧',
    observation: '👀',
    goal: '🎯'
  }
  return icons[step.type] || '•'
}

const getStepLabel = (step: ThinkingStep): string => {
  const labels: Record<string, string> = {
    think: '思考',
    plan: '计划',
    action: '执行',
    observation: '观察',
    goal: '目标'
  }
  return labels[step.type] || step.type
}
</script>

<style scoped>
.thinking-steps {
  background: var(--bg-card);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  margin-bottom: 10px;
  overflow: hidden;
}

.steps-header {
  padding: 10px 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: background var(--transition-fast);
}

.steps-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.steps-summary {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: 13px;
}

.steps-icon {
  font-size: 10px;
  color: var(--text-tertiary);
  transition: transform var(--transition-fast);
}

.steps-icon.expanded {
  transform: rotate(90deg);
}

.steps-label {
  color: var(--text-tertiary);
  font-weight: 500;
}

.steps-count {
  color: var(--dota-gold);
  font-size: 12px;
  background: rgba(198, 164, 78, 0.1);
  padding: 1px 8px;
  border-radius: var(--radius-pill);
}

.steps-duration {
  color: var(--text-disabled);
  font-size: 12px;
}

.steps-running {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--status-warning);
  font-size: 12px;
}

.dot-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--status-warning);
  animation: pulse 1.5s infinite;
}

.steps-body {
  padding: 0 14px 10px;
  border-top: 1px solid var(--border-primary);
}

.step-item {
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.step-item:last-child {
  border-bottom: none;
}

.step-header {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  font-size: 12px;
}

.step-icon {
  font-size: 13px;
}

.step-type {
  color: var(--text-secondary);
  font-weight: 500;
}

.step-status {
  margin-left: auto;
  font-size: 12px;
}

.status-running {
  color: var(--status-warning);
}

.status-done {
  color: var(--status-success);
}

.status-error {
  color: var(--status-error);
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(251, 191, 36, 0.3);
  border-top-color: var(--status-warning);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.step-content {
  margin-top: 4px;
  padding-left: 22px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.step-tool {
  color: var(--dota-gold);
  font-family: var(--font-mono);
  font-size: 11px;
  background: rgba(198, 164, 78, 0.1);
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  margin-left: 6px;
}

.step-result {
  margin-top: 4px;
  padding-left: 22px;
  font-size: 12px;
  color: var(--text-disabled);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-label {
  color: var(--text-tertiary);
  margin-right: 4px;
}

.result-text {
  color: var(--text-disabled);
}
</style>
