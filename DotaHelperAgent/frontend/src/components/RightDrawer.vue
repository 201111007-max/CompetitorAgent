<template>
  <div class="right-drawer" :class="{ 'has-panels': showHero || showLog || showGsi }">
    <!-- 英雄面板 -->
    <transition name="slide-right">
      <div v-if="showHero" class="drawer-panel hero-panel">
        <div class="panel-header">
          <span class="panel-icon">⚔</span>
          <span class="panel-title">英雄查询助手</span>
          <button class="close-btn" @click="$emit('closeHero')">×</button>
        </div>
        <div class="panel-body">
          <slot name="hero"></slot>
        </div>
      </div>
    </transition>

    <!-- 日志面板 -->
    <transition name="slide-right">
      <div v-if="showLog" class="drawer-panel log-panel">
        <div class="panel-header">
          <span class="panel-icon">📋</span>
          <span class="panel-title">实时日志</span>
          <button class="close-btn" @click="$emit('closeLog')">×</button>
        </div>
        <div class="panel-body">
          <slot name="log"></slot>
        </div>
      </div>
    </transition>

    <!-- GSI 状态面板 -->
    <transition name="slide-right">
      <div v-if="showGsi" class="drawer-panel gsi-panel">
        <div class="panel-header">
          <span class="panel-icon">🎮</span>
          <span class="panel-title">游戏状态</span>
          <button class="close-btn" @click="$emit('closeGsi')">×</button>
        </div>
        <div class="panel-body">
          <slot name="gsi"></slot>
        </div>
      </div>
    </transition>

    <!-- 移动端底部抽屉 -->
    <transition name="slide-bottom">
      <div v-if="isMobile && (showHero || showLog || showGsi)" class="mobile-drawer">
        <div class="mobile-tabs">
          <button
            class="mobile-tab"
            :class="{ active: mobileTab === 'hero' }"
            @click="mobileTab = 'hero'"
          >
            ⚔ 英雄
          </button>
          <button
            class="mobile-tab"
            :class="{ active: mobileTab === 'log' }"
            @click="mobileTab = 'log'"
          >
            📋 日志
          </button>
          <button
            class="mobile-tab"
            :class="{ active: mobileTab === 'gsi' }"
            @click="mobileTab = 'gsi'"
          >
            🎮 GSI
          </button>
          <button class="mobile-close" @click="closeMobile">×</button>
        </div>
        <div class="mobile-content">
          <slot v-if="mobileTab === 'hero'" name="hero"></slot>
          <slot v-else-if="mobileTab === 'log'" name="log"></slot>
          <slot v-else name="gsi"></slot>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  showHero: boolean
  showLog: boolean
  showGsi: boolean
}>()

const emit = defineEmits<{
  closeHero: []
  closeLog: []
  closeGsi: []
}>()

const mobileTab = ref<'hero' | 'log' | 'gsi'>('hero')
const windowWidth = ref(window.innerWidth)

const isMobile = computed(() => windowWidth.value < 768)

const onResize = () => {
  windowWidth.value = window.innerWidth
}

onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const closeMobile = () => {
  emit('closeHero')
  emit('closeLog')
  emit('closeGsi')
}
</script>

<style scoped>
.right-drawer {
  display: flex;
  flex-shrink: 0;
  height: 100%;
}

.right-drawer:not(.has-panels) {
  width: 0;
}

/* 面板通用样式 */
.drawer-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-left: 1px solid var(--border-primary);
  box-shadow: var(--shadow-drawer);
}

.hero-panel {
  width: var(--drawer-hero-width);
}

.log-panel {
  width: var(--drawer-log-width);
  border-left: 1px solid var(--border-primary);
}

.gsi-panel {
  width: var(--drawer-log-width);
  border-left: 1px solid var(--border-primary);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-primary);
  flex-shrink: 0;
}

.panel-icon {
  font-size: 16px;
}

.panel-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--text-disabled);
  font-size: 18px;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
}

/* 滑入动画 */
.slide-right-enter-active,
.slide-right-leave-active {
  transition: transform var(--transition-normal), opacity var(--transition-normal);
}

.slide-right-enter-from,
.slide-right-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* 平板端：垂直堆叠 */
@media (min-width: 768px) and (max-width: 1279px) {
  .right-drawer {
    flex-direction: column;
  }

  .hero-panel,
  .log-panel {
    width: min(360px, 40vw);
  }

  .log-panel {
    border-left: none;
    border-top: 1px solid var(--border-primary);
  }
}

/* 移动端：底部抽屉 */
@media (max-width: 767px) {
  .right-drawer {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    pointer-events: none;
    z-index: 100;
    width: auto;
    height: auto;
  }

  .right-drawer.has-panels {
    pointer-events: auto;
  }

  .drawer-panel {
    display: none;
  }

  .mobile-drawer {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 70vh;
    background: var(--bg-panel);
    border-top: 1px solid var(--border-primary);
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
    box-shadow: var(--shadow-bottom-drawer);
    display: flex;
    flex-direction: column;
  }

  .mobile-tabs {
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--border-primary);
    padding: 0 8px;
  }

  .mobile-tab {
    flex: 1;
    padding: 12px 16px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-tertiary);
    font-size: 14px;
    cursor: pointer;
    transition: color var(--transition-fast), border-color var(--transition-fast);
  }

  .mobile-tab.active {
    color: var(--dota-red-light);
    border-bottom-color: var(--dota-red);
  }

  .mobile-close {
    padding: 8px 12px;
    background: transparent;
    border: none;
    color: var(--text-disabled);
    font-size: 20px;
    cursor: pointer;
  }

  .mobile-content {
    flex: 1;
    overflow-y: auto;
  }
}

/* 底部抽屉动画 */
.slide-bottom-enter-active,
.slide-bottom-leave-active {
  transition: transform var(--transition-normal);
}

.slide-bottom-enter-from,
.slide-bottom-leave-to {
  transform: translateY(100%);
}
</style>
