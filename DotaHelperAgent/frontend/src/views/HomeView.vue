<template>
  <div class="home-view">
    <SidePanel
      :collapsed="sidePanelCollapsed"
      :show-hero="showHeroPanel"
      :show-log="showLogPanel"
      @toggle="sidePanelCollapsed = !sidePanelCollapsed"
      @newChat="handleNewChat"
      @selectChat="handleSelectChat"
      @deleteChat="handleDeleteChat"
      @openHeroPanel="showHeroPanel = !showHeroPanel"
      @openLogPanel="showLogPanel = !showLogPanel"
    />

    <div class="main-area">
      <TopStatusBar />
      <ChatBox ref="chatBoxRef" />
    </div>

    <RightDrawer
      :show-hero="showHeroPanel"
      :show-log="showLogPanel"
      @close-hero="showHeroPanel = false"
      @close-log="showLogPanel = false"
    >
      <template #hero>
        <HeroPanel @sendQuery="handleSendQuery" />
      </template>
      <template #log>
        <LogPanel />
      </template>
    </RightDrawer>

    <!-- 移动端浮动按钮 -->
    <div class="mobile-fab-group">
      <button
        class="fab-btn"
        :class="{ active: showHeroPanel }"
        @click="showHeroPanel = !showHeroPanel"
      >
        ⚔
      </button>
      <button
        class="fab-btn"
        :class="{ active: showLogPanel }"
        @click="showLogPanel = !showLogPanel"
      >
        📋
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import SidePanel from '@/components/SidePanel.vue'
import TopStatusBar from '@/components/TopStatusBar.vue'
import ChatBox from '@/components/ChatBox.vue'
import RightDrawer from '@/components/RightDrawer.vue'
import HeroPanel from '@/components/HeroPanel.vue'
import LogPanel from '@/components/LogPanel.vue'

const chatStore = useChatStore()
const sidePanelCollapsed = ref(true)
const showHeroPanel = ref(false)
const showLogPanel = ref(false)
const chatBoxRef = ref<InstanceType<typeof ChatBox> | null>(null)

const handleSendQuery = (query: string) => {
  if (chatBoxRef.value) {
    chatBoxRef.value.sendMessage(query)
  }
}

const handleNewChat = () => {
  chatStore.newChat()
}

const handleSelectChat = (id: string) => {
  chatStore.selectConversation(id)
}

const handleDeleteChat = (id: string) => {
  chatStore.deleteConversation(id)
}
</script>

<style scoped>
.home-view {
  height: 100vh;
  display: flex;
  background: var(--bg-deepest);
  overflow: hidden;
}

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

/* 移动端浮动按钮 */
.mobile-fab-group {
  display: none;
}

@media (max-width: 767px) {
  .mobile-fab-group {
    display: flex;
    flex-direction: column;
    gap: var(--gap-md);
    position: fixed;
    right: 16px;
    bottom: 16px;
    z-index: 50;
  }

  .fab-btn {
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-card);
    border: 1px solid var(--border-secondary);
    border-radius: 50%;
    font-size: 20px;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    transition: transform var(--transition-fast), background var(--transition-fast);
  }

  .fab-btn:hover {
    transform: scale(1.1);
  }

  .fab-btn.active {
    background: rgba(191, 46, 26, 0.2);
    border-color: var(--dota-red);
  }
}
</style>
