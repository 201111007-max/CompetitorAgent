<template>
  <div class="markdown-renderer" v-html="renderedHtml"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Marked } from 'marked'
import hljs from 'highlight.js'

const props = defineProps<{
  content: string
}>()

const marked = new Marked({
  breaks: true,
  gfm: true
})

marked.use({
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      const highlighted = hljs.highlight(text, { language }).value
      return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
    }
  }
})

const renderedHtml = computed(() => {
  if (!props.content) return ''
  return marked.parse(props.content) as string
})
</script>

<style scoped>
.markdown-renderer {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
}

.markdown-renderer :deep(h1),
.markdown-renderer :deep(h2),
.markdown-renderer :deep(h3),
.markdown-renderer :deep(h4) {
  color: var(--dota-gold);
  margin: 16px 0 8px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.markdown-renderer :deep(h1) { font-size: 20px; }
.markdown-renderer :deep(h2) { font-size: 17px; }
.markdown-renderer :deep(h3) { font-size: 15px; }
.markdown-renderer :deep(h4) { font-size: 14px; }

.markdown-renderer :deep(p) {
  margin: 8px 0;
}

.markdown-renderer :deep(ul),
.markdown-renderer :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.markdown-renderer :deep(li) {
  margin: 4px 0;
}

.markdown-renderer :deep(code) {
  background: rgba(191, 46, 26, 0.15);
  color: var(--dota-red-light);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 13px;
}

.markdown-renderer :deep(pre) {
  background: var(--bg-deepest);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  padding: 14px;
  margin: 12px 0;
  overflow-x: auto;
}

.markdown-renderer :deep(pre code) {
  background: none;
  color: var(--text-primary);
  padding: 0;
  font-size: 13px;
  line-height: 1.5;
}

.markdown-renderer :deep(blockquote) {
  border-left: 3px solid var(--dota-red);
  background: rgba(191, 46, 26, 0.06);
  margin: 12px 0;
  padding: 8px 16px;
  color: var(--text-secondary);
}

.markdown-renderer :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}

.markdown-renderer :deep(th),
.markdown-renderer :deep(td) {
  border: 1px solid var(--border-primary);
  padding: 8px 12px;
  text-align: left;
}

.markdown-renderer :deep(th) {
  background: var(--bg-card);
  color: var(--dota-gold);
  font-weight: 600;
}

.markdown-renderer :deep(a) {
  color: var(--dota-gold);
  text-decoration: none;
}

.markdown-renderer :deep(a:hover) {
  text-decoration: underline;
}

.markdown-renderer :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}

.markdown-renderer :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-primary);
  margin: 16px 0;
}
</style>
