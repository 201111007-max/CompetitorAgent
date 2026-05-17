<template>
  <div class="home-view">
    <div class="main-content">
      <ChatBox ref="chatBoxRef" />
    </div>

    <div class="hero-sidebar" :class="{ show: showHeroPanel }">
      <HeroPanel 
        @close="showHeroPanel = false" 
        @sendQuery="handleSendQuery"
      />
    </div>

    <div class="log-sidebar" :class="{ show: showLogPanel }">
      <LogPanel @close="showLogPanel = false" />
    </div>

    <div class="toggle-buttons">
      <button 
        class="toggle-btn hero-btn" 
        @click="showHeroPanel = !showHeroPanel"
        :class="{ active: showHeroPanel }"
      >
        {{ showHeroPanel ? '隐藏助手' : '测试助手' }}
      </button>
      <button 
        class="toggle-btn log-btn" 
        @click="showLogPanel = !showLogPanel"
        :class="{ active: showLogPanel }"
      >
        {{ showLogPanel ? '隐藏日志' : '显示日志' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ChatBox from '@/components/ChatBox.vue'
import HeroPanel from '@/components/HeroPanel.vue'
import LogPanel from '@/components/LogPanel.vue'

const showHeroPanel = ref(false)
const showLogPanel = ref(false)
const chatBoxRef = ref<InstanceType<typeof ChatBox> | null>(null)

const handleSendQuery = (query: string) => {
  if (chatBoxRef.value) {
    chatBoxRef.value.sendMessage(query)
  }
}
</script>

<style scoped>
.home-view {
  height: 100vh;
  display: flex;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  overflow: hidden;
}

.main-content {
  flex: 1;
  min-width: 400px;
  display: flex;
  flex-direction: column;
  padding: 16px;
  transition: flex 0.3s ease;
}

.hero-sidebar {
  width: 0;
  flex-shrink: 0;
  border-left: 1px solid transparent;
  background: rgba(0, 0, 0, 0.2);
  transition: width 0.3s ease, border-color 0.3s ease;
  overflow: hidden;
}

.hero-sidebar.show {
  width: 350px;
  border-left-color: rgba(255, 255, 255, 0.1);
}

.log-sidebar {
  width: 0;
  flex-shrink: 0;
  border-left: 1px solid transparent;
  background: rgba(0, 0, 0, 0.2);
  transition: width 0.3s ease, border-color 0.3s ease;
  overflow: hidden;
}

.log-sidebar.show {
  width: 400px;
  border-left-color: rgba(255, 255, 255, 0.1);
}

.toggle-buttons {
  position: fixed;
  right: 20px;
  bottom: 20px;
  display: flex;
  gap: 10px;
  z-index: 1000;
}

.toggle-btn {
  padding: 10px 20px;
  border: none;
  border-radius: 20px;
  font-size: 13px;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.toggle-btn:hover {
  transform: translateY(-2px);
}

.hero-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.hero-btn:hover {
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.hero-btn.active {
  background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
}

.log-btn {
  background: linear-gradient(135deg, #e94560 0%, #ff6b6b 100%);
  color: white;
}

.log-btn:hover {
  box-shadow: 0 4px 12px rgba(233, 69, 96, 0.4);
}

.log-btn.active {
  background: linear-gradient(135deg, #ff6b6b 0%, #e94560 100%);
}
</style>
