<template>
  <div class="gsi-status-panel">
    <div v-if="!connected" class="gsi-disconnected-msg">
      <p>GSI 未连接</p>
      <p class="hint">请确保 Dota 2 正在运行且 GSI 配置正确</p>
    </div>
    <div v-else-if="!currentState" class="gsi-waiting">
      <p>等待游戏数据...</p>
    </div>
    <div v-else class="gsi-data">
      <div class="gsi-section">
        <h4>英雄信息</h4>
        <div class="gsi-row">
          <span class="label">英雄</span>
          <span class="value">{{ heroName }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">等级</span>
          <span class="value">{{ currentState.level }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">状态</span>
          <span class="value" :class="currentState.alive ? 'alive' : 'dead'">
            {{ currentState.alive ? '存活' : `复活: ${currentState.respawn_seconds}s` }}
          </span>
        </div>
        <div class="gsi-bar-row">
          <span class="label">血量</span>
          <div class="gsi-bar hp-bar">
            <div class="bar-fill" :style="{ width: hpPercent + '%' }"></div>
            <span class="bar-text">{{ currentState.health }}/{{ currentState.max_health }}</span>
          </div>
        </div>
        <div class="gsi-bar-row">
          <span class="label">蓝量</span>
          <div class="gsi-bar mp-bar">
            <div class="bar-fill" :style="{ width: mpPercent + '%' }"></div>
            <span class="bar-text">{{ currentState.mana }}/{{ currentState.max_mana }}</span>
          </div>
        </div>
      </div>

      <div class="gsi-section">
        <h4>经济数据</h4>
        <div class="gsi-row">
          <span class="label">金钱</span>
          <span class="value gold">{{ currentState.gold }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">GPM</span>
          <span class="value">{{ currentState.gpm }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">XPM</span>
          <span class="value">{{ currentState.xpm }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">KDA</span>
          <span class="value">{{ currentState.kills }}/{{ currentState.deaths }}/{{ currentState.assists }}</span>
        </div>
        <div class="gsi-row">
          <span class="label">正/反补</span>
          <span class="value">{{ currentState.last_hits }}/{{ currentState.denies }}</span>
        </div>
      </div>

      <div class="gsi-section" v-if="events.length > 0">
        <h4>最近事件</h4>
        <div class="gsi-events">
          <div
            v-for="(evt, idx) in recentEvents"
            :key="idx"
            class="gsi-event"
            :class="evt.priority"
          >
            <span class="event-type">{{ evt.event_type }}</span>
            <span class="event-msg">{{ evt.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useGsiStream } from '@/composables/useGsiStream'

const { connected, currentState, events, connect, disconnect, fetchState } = useGsiStream()

const heroName = computed(() => {
  if (!currentState.value) return ''
  return currentState.value.hero_name.replace('npc_dota_hero_', '').replace(/_/g, ' ')
})

const hpPercent = computed(() => {
  if (!currentState.value || !currentState.value.max_health) return 0
  return Math.round((currentState.value.health / currentState.value.max_health) * 100)
})

const mpPercent = computed(() => {
  if (!currentState.value || !currentState.value.max_mana) return 0
  return Math.round((currentState.value.mana / currentState.value.max_mana) * 100)
})

const recentEvents = computed(() => events.value.slice(-10).reverse())

let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  connect()
  pollTimer = setInterval(fetchState, 5000)
})

onUnmounted(() => {
  disconnect()
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.gsi-status-panel {
  padding: 12px;
  font-size: 13px;
}

.gsi-disconnected-msg,
.gsi-waiting {
  text-align: center;
  padding: 24px 12px;
  color: var(--text-disabled);
}

.hint {
  font-size: 11px;
  margin-top: 4px;
}

.gsi-section {
  margin-bottom: 16px;
}

.gsi-section h4 {
  font-size: 12px;
  font-weight: 600;
  color: var(--dota-gold);
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border-primary);
}

.gsi-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
}

.gsi-row .label {
  color: var(--text-disabled);
}

.gsi-row .value {
  color: var(--text-primary);
  font-weight: 500;
}

.gsi-row .value.gold {
  color: var(--dota-gold);
}

.gsi-row .value.alive {
  color: var(--status-success);
}

.gsi-row .value.dead {
  color: var(--status-error);
}

.gsi-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.gsi-bar-row .label {
  color: var(--text-disabled);
  min-width: 28px;
}

.gsi-bar {
  flex: 1;
  height: 16px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.gsi-bar .bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.hp-bar .bar-fill {
  background: linear-gradient(90deg, #22c55e, #4ade80);
}

.mp-bar .bar-fill {
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
}

.gsi-bar .bar-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}

.gsi-events {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.gsi-event {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.04);
}

.gsi-event.warning {
  background: rgba(234, 179, 8, 0.1);
  border-left: 2px solid var(--dota-gold);
}

.gsi-event.critical {
  background: rgba(239, 68, 68, 0.1);
  border-left: 2px solid var(--status-error);
}

.gsi-event .event-type {
  color: var(--text-disabled);
  margin-right: 6px;
}

.gsi-event .event-msg {
  color: var(--text-secondary);
}
</style>
