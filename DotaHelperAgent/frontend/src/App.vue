<template>
  <n-config-provider :theme="darkTheme">
    <n-message-provider>
      <div id="app">
        <router-view />
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { darkTheme, NConfigProvider, NMessageProvider } from 'naive-ui'
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-deepest);
  min-height: 100vh;
  color: var(--text-primary);
}

#app {
  width: 100%;
  height: 100vh;
  background: var(--bg-deepest);
}
</style>
