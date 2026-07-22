<template>
  <div v-if="report" class="review-report">
    <div class="report-summary">
      <h3 class="summary-title">复盘总览</h3>
      <div class="summary-grid">
        <div class="summary-item">
          <span class="item-label">比赛 ID</span>
          <span class="item-value">{{ report.match_id }}</span>
        </div>
        <div class="summary-item">
          <span class="item-label">时长</span>
          <span class="item-value">{{ formattedDuration }}</span>
        </div>
        <div class="summary-item">
          <span class="item-label">比分</span>
          <span class="item-value" :class="{ win: report.match_summary.user_team_win }">
            {{ report.match_summary.radiant_score }} : {{ report.match_summary.dire_score }}
          </span>
        </div>
        <div class="summary-item">
          <span class="item-label">使用英雄</span>
          <span class="item-value">{{ report.match_summary.user_hero }}</span>
        </div>
        <div class="summary-item">
          <span class="item-label">综合评分</span>
          <span class="item-value score">{{ report.overall_score.toFixed(1) }}</span>
        </div>
        <div class="summary-item">
          <span class="item-label">置信度</span>
          <span class="item-value confidence">{{ (report.overall_confidence * 100).toFixed(0) }}%</span>
        </div>
      </div>

      <div v-if="report.key_findings.length" class="finding-section">
        <div class="section-label">关键发现</div>
        <ul class="finding-list">
          <li v-for="(finding, index) in report.key_findings" :key="`finding-${index}`">
            {{ finding }}
          </li>
        </ul>
      </div>

      <div v-if="report.improvement_areas.length" class="finding-section">
        <div class="section-label">改进方向</div>
        <ul class="finding-list improvement">
          <li v-for="(area, index) in report.improvement_areas" :key="`area-${index}`">
            {{ area }}
          </li>
        </ul>
      </div>
    </div>

    <div class="report-markdown">
      <div class="section-label">详细报告</div>
      <MarkdownRenderer :content="report.markdown_report" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import type { ReviewReport } from '@/types/review'

const props = defineProps<{
  report: ReviewReport
}>()

const formattedDuration = computed(() => {
  const seconds = props.report.match_summary.duration
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}分${secs.toString().padStart(2, '0')}秒`
})
</script>

<style scoped>
.review-report {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xl);
}

.report-summary {
  background: var(--bg-card);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  padding: var(--gap-xl);
}

.summary-title {
  font-size: 16px;
  color: var(--dota-gold);
  margin: 0 0 var(--gap-lg);
  font-weight: 600;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--gap-md);
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
}

.item-label {
  font-size: 11px;
  color: var(--text-tertiary);
}

.item-value {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
}

.item-value.win {
  color: var(--status-success);
}

.item-value.score {
  color: var(--dota-gold);
  font-size: 18px;
}

.item-value.confidence {
  color: var(--status-info);
}

.finding-section {
  margin-top: var(--gap-lg);
}

.section-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: var(--gap-sm);
  font-weight: 500;
}

.finding-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.finding-list.improvement li::marker {
  color: var(--status-warning);
}

.report-markdown {
  background: var(--bg-card);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-lg);
  padding: var(--gap-xl);
}
</style>
