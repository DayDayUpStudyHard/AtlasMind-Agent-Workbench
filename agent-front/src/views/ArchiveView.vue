<template>
  <div class="archive-page">
    <div class="page-head">
      <h2 class="page-title">文章时间线</h2>
      <p class="page-desc">{{ totalCount }} 篇文章</p>
    </div>

    <div v-if="groups.length" class="timeline">
      <div v-for="group in groups" :key="group.yearMonth" class="tl-group">
        <div class="tl-dot"></div>
        <div class="tl-label-row">
          <span class="tl-year">{{ formatYearMonth(group.yearMonth) }}</span>
          <span class="tl-count">{{ group.articles.length }} 篇</span>
        </div>
        <div class="tl-articles">
          <router-link
            v-for="a in group.articles"
            :key="a.id"
            :to="`/article/${a.id}`"
            class="tl-card"
          >
            <span class="tl-day">{{ formatDay(a.createTime) }}</span>
            <span class="tl-title">{{ a.title }}</span>
          </router-link>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">暂无文章</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getArchive } from '../api/index.js'

const groups = ref([])
const totalCount = computed(() => groups.value.reduce((s, g) => s + (g.articles || []).length, 0))

onMounted(async () => {
  const res = await getArchive()
  groups.value = res.data.data || []
})

function formatYearMonth(ym) {
  if (!ym) return ''
  const parts = ym.split('-')
  return `${parts[0]} 年 ${parseInt(parts[1])} 月`
}
function formatDay(d) {
  return d ? d.substring(5, 10) : ''
}
</script>

<style scoped>
.archive-page {
  max-width: 720px; margin: 0 auto; padding: 60px 20px 80px;
}

.page-head { text-align: center; margin-bottom: 48px; }
.page-title { font-size: 28px; font-weight: 700; color: #303133; margin: 0 0 8px; letter-spacing: -0.5px; }
.page-desc { font-size: 14px; color: #909399; margin: 0; }

/* ═══ Timeline ═══ */
.timeline { position: relative; padding-left: 28px; }
.timeline::before {
  content: '';
  position: absolute; left: 7px; top: 0; bottom: 0;
  width: 2px;
  background: #426fa6;
  border-radius: 0;
  opacity: 0.3;
}

.tl-group { position: relative; margin-bottom: 36px; }
.tl-group:last-child { margin-bottom: 0; }

.tl-dot {
  position: absolute; left: -24px; top: 8px;
  width: 12px; height: 12px; border-radius: 50%;
  background: #fff;
  border: 2.5px solid #426fa6;
  box-shadow: 0 0 0 3px rgba(66,111,166,0.12);
  z-index: 1;
}

.tl-label-row { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; }
.tl-year { font-size: 16px; font-weight: 700; color: #303133; }
.tl-count { font-size: 12px; color: #909399; }

.tl-articles { display: flex; flex-direction: column; gap: 6px; }

.tl-card {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 16px; border-radius: 8px;
  text-decoration: none;
  background: rgba(255,255,255,0.5);
  border: 1px solid rgba(0,0,0,0.04);
  transition: all 0.2s;
}
.tl-card:hover {
  background: rgba(64,158,255,0.04);
  border-color: rgba(64,158,255,0.2);
  transform: translateX(4px);
  box-shadow: 0 2px 8px rgba(64,158,255,0.08);
}

.tl-day {
  font-size: 13px; color: #909399; font-family: 'SF Mono', 'Fira Code', monospace;
  flex-shrink: 0; width: 42px;
}
.tl-title {
  font-size: 14px; color: #303133; flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.empty-state { text-align: center; color: #c0c4cc; font-size: 14px; padding: 48px 0; }
</style>
