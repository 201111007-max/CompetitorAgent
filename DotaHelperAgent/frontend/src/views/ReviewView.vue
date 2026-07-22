<template>
  <div class="review-view">
    <SidePanel
      :collapsed="sidePanelCollapsed"
      @toggle="sidePanelCollapsed = !sidePanelCollapsed"
    />
    <main class="review-main-area">
      <ReviewPanel />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import SidePanel from '@/components/SidePanel.vue'
import ReviewPanel from '@/components/review/ReviewPanel.vue'

const sidePanelCollapsed = ref(true)
</script>

<style scoped>
.review-view {
  height: 100vh;
  display: flex;
  background: var(--bg-deepest);
  overflow: hidden;
}

.review-main-area {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
</style>
