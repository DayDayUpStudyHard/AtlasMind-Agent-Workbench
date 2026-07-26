<template>
  <div class="category-page">
    <div class="page-head">
      <h2 class="page-title">分类浏览</h2>
      <div class="page-line"></div>
    </div>

    <n-spin :show="loading">
      <div class="category-grid" v-if="categories.length">
        <button
          v-for="cat in categories" :key="cat.id"
          class="cat-btn" :class="{ active: activeCat === cat.id }"
          @click="selectCategory(cat.id)"
        >
          <div class="cat-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div class="cat-info">
            <span class="cat-name">{{ cat.name }}</span>
            <span class="cat-desc" v-if="cat.description">{{ cat.description }}</span>
          </div>
          <span class="cat-arrow">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </span>
        </button>
      </div>
      <n-empty v-else description="暂无分类" />
    </n-spin>

    <div v-if="articles.length" class="result">
      <div class="result-head">
        <span class="result-count">找到 {{ articles.length }} 篇文章</span>
      </div>
      <ArticleCard v-for="(article, i) in articles" :key="article.id" :article="article" :style="{ '--i': i }" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getArticles, getCategories } from '../api/index.js'
import ArticleCard from '../components/ArticleCard.vue'

const categories = ref([])
const articles = ref([])
const loading = ref(false)
const activeCat = ref(null)

onMounted(async () => {
  loading.value = true
  categories.value = (await getCategories()).data.data
  loading.value = false
})

async function selectCategory(id) {
  activeCat.value = id
  loading.value = true
  try {
    articles.value = (await getArticles({ categoryId: id, size: 50 })).data.data.records
  } finally { loading.value = false }
}
</script>

<style scoped>
.category-page { padding: 28px 0; }
.page-head { margin-bottom: 24px; }
.page-title { font-size: 22px; color: #303133; margin-bottom: 10px; font-weight: 600; }
.page-line { height: 1px; background: #e8ecf0; }

.category-grid { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 32px; }
.cat-btn {
  display: flex; align-items: center; gap: 12px;
  background: #ffffff; border: 1px solid #e8ecf0;
  padding: 14px 18px; border-radius: 10px; cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); text-align: left;
}
.cat-btn:hover, .cat-btn.active {
  border-color: #426fa6;
  background: #ecf5ff;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.cat-btn.active {
  border-color: #426fa6;
  background: #eaf0f7;
}

.cat-icon { color: #909399; transition: color 0.2s; flex-shrink: 0; }
.cat-btn.active .cat-icon { color: #426fa6; }
.cat-info { display: flex; flex-direction: column; gap: 2px; }
.cat-name { font-size: 15px; color: #303133; font-weight: 500; }
.cat-desc { font-size: 12px; color: #909399; }
.cat-arrow {
  color: #c0c4cc; transition: all 0.2s; display: flex; margin-left: auto;
}
.cat-btn.active .cat-arrow { color: #426fa6; transform: translateX(2px); }

.result { margin-top: 4px; }
.result-head { margin-bottom: 12px; }
.result-count { font-size: 13px; color: #909399; }
</style>
