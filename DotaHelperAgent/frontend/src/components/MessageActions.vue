<template>
  <div class="message-actions" v-if="role === 'assistant'">
    <button class="action-btn" @click="handleCopy" title="复制">
      <span v-if="copied">✓</span>
      <span v-else>📋</span>
    </button>
    <button class="action-btn" @click="$emit('regenerate', messageId)" title="重新生成">
      🔄
    </button>
    <button
      class="action-btn"
      :class="{ active: feedback === 'up' }"
      @click="handleFeedback('up')"
      title="有帮助"
    >
      👍
    </button>
    <button
      class="action-btn"
      :class="{ active: feedback === 'down' }"
      @click="handleFeedback('down')"
      title="没帮助"
    >
      👎
    </button>
  </div>
  <div class="message-actions user-actions" v-else>
    <button class="action-btn" @click="handleCopy" title="复制">
      <span v-if="copied">✓</span>
      <span v-else>📋</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  messageId: string
  role: 'user' | 'assistant'
}>()

const emit = defineEmits<{
  copy: [messageId: string]
  regenerate: [messageId: string]
  feedback: [messageId: string, score: 'up' | 'down']
}>()

const copied = ref(false)
const feedback = ref<'up' | 'down' | null>(null)

const handleCopy = async () => {
  emit('copy', props.messageId)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

const handleFeedback = (score: 'up' | 'down') => {
  feedback.value = feedback.value === score ? null : score
  if (feedback.value) {
    emit('feedback', props.messageId, feedback.value)
  }
}
</script>

<style scoped>
.message-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.message-actions:hover,
.user-actions {
  opacity: 1;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 13px;
  transition: background var(--transition-fast), transform var(--transition-fast);
  color: var(--text-disabled);
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: scale(1.1);
}

.action-btn.active {
  background: rgba(198, 164, 78, 0.15);
}
</style>
