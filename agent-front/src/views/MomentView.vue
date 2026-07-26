<template>
  <div class="moment-page">
    <div class="page-head">
      <h2 class="page-title">说说</h2>
      <p class="page-desc">随手记录，碎碎念</p>
      <div class="page-line"></div>
    </div>

    <n-spin :show="loading">
      <div class="moment-list">
        <div v-for="m in moments" :key="m.id" class="moment-card">
          <p class="moment-content">{{ m.content }}</p>
          <img v-if="m.image" :src="m.image" class="moment-img" />
          <span class="moment-time">{{ formatDate(m.createTime) }}</span>
        </div>
      </div>
    </n-spin>

    <div class="pagination" v-if="total > size">
      <n-pagination v-model:page="page" :page-size="size" :item-count="total" @update:page="fetchData" />
    </div>

    <n-empty v-if="!loading && moments.length === 0" description="还没有说说" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getMoments } from '../api/index.js'

const moments = ref([])
const loading = ref(false)
const page = ref(1)
const size = 10
const total = ref(0)

onMounted(() => fetchData())

function formatDate(t) {
  if (!t) return ''
  return t.substring(0, 16).replace('T', ' ')
}

async function fetchData() {
  loading.value = true
  try {
    const res = await getMoments({ page: page.value, size: size })
    moments.value = res.data.data.records
    total.value = res.data.data.total
  } finally { loading.value = false }
}
</script>

<style scoped>
.moment-page { padding: 28px 0; }
.page-head { margin-bottom: 28px; }
.page-title { font-size: 22px; color: #303133; margin-bottom: 6px; font-weight: 600; }
.page-desc { font-size: 14px; color: #909399; margin: 0 0 10px; }
.page-line { height: 1px; background: #e8ecf0; }

.moment-list { display: flex; flex-direction: column; gap: 14px; }
.moment-card {
  background: rgba(255,255,255,0.55);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px; padding: 20px 24px;
  transition: all 0.3s;
}
.moment-card:hover {
  border-color: #426fa6;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.moment-content { font-size: 15px; color: #303133; line-height: 1.7; margin: 0; white-space: pre-wrap; }
.moment-img { max-width: 100%; border-radius: 10px; margin-top: 12px; }
.moment-time { font-size: 12px; color: #c0c4cc; margin-top: 10px; display: block; }

.pagination { margin-top: 32px; display: flex; justify-content: center; }
</style>
