<template>
  <div class="home-page">
    <section class="home-hero">
      <div class="identity">
        <n-avatar v-if="siteInfo.avatar" :src="siteInfo.avatar" :size="64" class="hero-avatar" />
        <n-avatar v-else :size="64" class="hero-avatar" :style="{ background: 'var(--atlas-primary)' }">
          <span style="font-size:26px;font-weight:700">{{ (siteInfo.nickname || 'B').charAt(0) }}</span>
        </n-avatar>

        <div class="identity-copy">
          <span class="eyebrow">AtlasMind / Knowledge Base</span>
          <h1>{{ siteInfo.nickname || 'AtlasMind' }}</h1>
          <p>{{ siteInfo.bio || '记录工程实践、系统设计与生活里的长期思考。' }}</p>
          <div class="hero-social" v-if="socialLinks.length > 0">
            <a v-for="(link, i) in socialLinks" :key="i" :href="link.url" :title="link.name" target="_blank" class="social-link">
              <svg v-if="link.icon === 'github'" width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.605-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12 24 5.37 18.63 0 12 0z"/></svg>
              <svg v-else-if="link.icon === 'email'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
          </div>
        </div>
      </div>

      <aside class="hero-panel">
        <div class="panel-top">
          <span class="panel-kicker">AI/RAG</span>
          <span class="panel-status">可检索</span>
        </div>
        <h2>把文章变成可对话的知识库</h2>
        <p>右下角 AI 助手会基于公开与 RAG_ONLY 内容回答问题，小工具入口则承载旅行规划、加密解密等实验。</p>
        <div class="metric-row">
          <div>
            <strong>{{ total }}</strong>
            <span>文章</span>
          </div>
          <div>
            <strong>{{ recentMoments.length }}</strong>
            <span>近况</span>
          </div>
        </div>
      </aside>
    </section>

    <div class="search-hint" v-if="keyword">
      <span>搜索 "{{ keyword }}" 的结果</span>
      <button class="clear-search" @click="keyword = ''; page = 1; fetchData(); router.replace({ path: '/' })">清除</button>
    </div>

    <section class="content-grid">
      <main class="article-stream">
        <div class="section-head">
          <div>
            <span class="section-kicker">Articles</span>
            <h2>{{ keyword ? '搜索结果' : '最新文章' }}</h2>
          </div>
          <router-link to="/archive" class="archive-link">查看时间线</router-link>
        </div>

        <n-spin :show="loading">
          <transition-group name="list" tag="div" class="article-list">
            <ArticleCard v-for="(article, i) in articles" :key="article.id" :article="article" :style="{ '--i': i }" />
          </transition-group>
        </n-spin>

        <div class="pagination" v-if="total > size">
          <n-pagination v-model:page="page" :page-size="size" :item-count="total" @update:page="fetchData" />
        </div>

        <n-empty v-if="!loading && articles.length === 0" description="暂无文章" class="empty-state" />
      </main>

      <aside class="side-rail">
        <div class="rail-card" v-if="featuredArticle">
          <span class="rail-title">精选入口</span>
          <router-link :to="`/article/${featuredArticle.id}`" class="featured-link">
            <span class="featured-label">最新发布</span>
            <strong>{{ featuredArticle.title }}</strong>
            <p>{{ featuredArticle.summary || '暂无摘要' }}</p>
          </router-link>
        </div>

        <div class="rail-card" v-if="recentMoments.length > 0">
          <router-link to="/moments" class="rail-title rail-title-link">最新说说</router-link>
          <div class="moments-list">
            <router-link v-for="m in recentMoments" :key="m.id" to="/moments" class="moment-card">
              <p>{{ m.content }}</p>
              <span>{{ formatDate(m.createTime) }}</span>
            </router-link>
          </div>
        </div>
      </aside>
    </section>

    <BackToTop />
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getArticles, getSiteInfo, getMoments } from '../api/index.js'
import ArticleCard from '../components/ArticleCard.vue'
import BackToTop from '../components/BackToTop.vue'

const route = useRoute()
const router = useRouter()
const articles = ref([])
const loading = ref(false)
const page = ref(1)
const size = 10
const total = ref(0)
const keyword = ref('')
const siteInfo = ref({})
const socialLinks = ref([])
const recentMoments = ref([])

const featuredArticle = computed(() => articles.value[0] || null)

function formatDate(t) {
  if (!t) return ''
  return t.substring(0, 10)
}

onMounted(() => {
  keyword.value = route.query.keyword || ''
  fetchData()
  fetchSiteInfo()
  fetchMoments()
})

watch(() => route.query.keyword, (val) => {
  keyword.value = val || ''
  page.value = 1
  fetchData()
})

async function fetchSiteInfo() {
  try {
    const res = await getSiteInfo()
    siteInfo.value = res.data.data
    try { socialLinks.value = JSON.parse(res.data.data.socialLinks || '[]') } catch { socialLinks.value = [] }
  } catch {}
}

async function fetchMoments() {
  try {
    const res = await getMoments({ page: 1, size: 3 })
    recentMoments.value = res.data.data.records
  } catch {}
}

async function fetchData() {
  loading.value = true
  try {
    const params = { page: page.value, size: size }
    if (keyword.value) params.keyword = keyword.value
    const res = await getArticles(params)
    articles.value = res.data.data.records
    total.value = res.data.data.total
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 20px;
  align-items: stretch;
}

.identity,
.hero-panel,
.rail-card {
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 8px;
  box-shadow: var(--atlas-shadow);
}

.identity {
  display: flex;
  gap: 18px;
  align-items: center;
  padding: 34px;
}

.hero-avatar {
  flex-shrink: 0;
  box-shadow: 0 10px 28px rgba(15,23,42,0.12);
}

.identity-copy {
  min-width: 0;
}

.eyebrow,
.section-kicker,
.panel-kicker,
.featured-label {
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.identity h1 {
  color: var(--atlas-text);
  font-size: 42px;
  line-height: 1.1;
  margin: 8px 0 10px;
  letter-spacing: 0;
}

.identity p,
.hero-panel p,
.featured-link p {
  color: var(--atlas-muted);
  line-height: 1.7;
}

.identity p {
  font-size: 16px;
  max-width: 620px;
}

.hero-social {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.social-link {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--atlas-muted);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  transition: color 0.15s, border-color 0.15s, transform 0.15s;
}

.social-link:hover {
  color: var(--atlas-primary);
  border-color: rgba(37,99,235,0.32);
  transform: translateY(-1px);
}

.hero-panel {
  padding: 26px;
  display: flex;
  flex-direction: column;
}

.panel-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.panel-status {
  color: var(--atlas-accent);
  font-size: 12px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(15,118,110,0.08);
}

.hero-panel h2 {
  color: var(--atlas-text);
  font-size: 24px;
  line-height: 1.25;
  margin: 18px 0 10px;
}

.metric-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: auto;
  padding-top: 22px;
}

.metric-row div {
  border: 1px solid var(--atlas-border);
  border-radius: 8px;
  padding: 14px;
  background: var(--atlas-surface-soft);
}

.metric-row strong {
  display: block;
  color: var(--atlas-text);
  font-size: 24px;
  line-height: 1;
}

.metric-row span {
  display: block;
  color: var(--atlas-muted);
  font-size: 12px;
  margin-top: 6px;
}

.search-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--atlas-muted);
  font-size: 14px;
}

.clear-search {
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  color: var(--atlas-primary);
  cursor: pointer;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 28px;
  align-items: start;
}

.article-stream {
  min-width: 0;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 16px;
  margin-bottom: 14px;
}

.section-head h2 {
  color: var(--atlas-text);
  font-size: 24px;
  margin-top: 4px;
}

.archive-link {
  color: var(--atlas-muted);
  text-decoration: none;
  font-size: 13px;
  border-bottom: 1px solid transparent;
}

.archive-link:hover {
  color: var(--atlas-primary);
  border-bottom-color: rgba(37,99,235,0.25);
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.side-rail {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rail-card {
  padding: 18px;
}

.rail-title {
  display: block;
  color: var(--atlas-text);
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}

.rail-title-link {
  text-decoration: none;
}

.rail-title-link:hover {
  color: var(--atlas-primary);
}

.featured-link,
.moment-card {
  text-decoration: none;
  display: block;
}

.featured-link strong {
  display: block;
  color: var(--atlas-text);
  font-size: 17px;
  line-height: 1.45;
  margin-top: 8px;
}

.featured-link p {
  font-size: 13px;
  margin-top: 8px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.moments-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.moment-card {
  border-top: 1px solid var(--atlas-border);
  padding-top: 10px;
}

.moment-card:first-child {
  border-top: none;
  padding-top: 0;
}

.moment-card p {
  color: var(--atlas-text);
  font-size: 13px;
  line-height: 1.65;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.moment-card span {
  display: block;
  color: var(--atlas-subtle);
  font-size: 12px;
  margin-top: 6px;
}

.pagination {
  margin-top: 28px;
  display: flex;
  justify-content: center;
}

.empty-state {
  margin-top: 40px;
}

.list-enter-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.list-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

[data-theme="dark"] .identity,
[data-theme="dark"] .hero-panel,
[data-theme="dark"] .rail-card {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
}

[data-theme="dark"] .hero-avatar {
  box-shadow: none;
}

[data-theme="dark"] .metric-row div,
[data-theme="dark"] .social-link {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-border);
}

@media (max-width: 960px) {
  .home-hero,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .side-rail {
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .identity {
    align-items: flex-start;
    flex-direction: column;
    padding: 24px;
  }

  .identity h1 {
    font-size: 34px;
  }

  .section-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .side-rail {
    grid-template-columns: 1fr;
  }
}

/* Hallmark | Workbench surface: editorial type with restrained blue accents */
.home-page {
  gap: 32px;
}

.identity,
.hero-panel,
.rail-card {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
  border-radius: 4px;
  box-shadow: none;
}

.identity h1,
.hero-panel h2,
.section-head h2,
.rail-title,
.featured-link strong {
  font-family: var(--atlas-font-display);
  font-weight: 700;
}

.eyebrow,
.section-kicker,
.panel-kicker,
.featured-label {
  color: var(--atlas-primary);
  letter-spacing: 0;
  text-transform: none;
}

.hero-avatar {
  box-shadow: none;
}

.social-link,
.metric-row div {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-border);
  border-radius: 4px;
}

.social-link:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
  transform: none;
}

.panel-status {
  color: var(--atlas-primary);
  background: rgba(66, 111, 166, 0.1);
  border-radius: 3px;
}

.archive-link {
  color: var(--atlas-primary);
}

.rail-card {
  padding: 20px;
}

.moment-card,
.featured-link {
  border-color: var(--atlas-border);
}

[data-theme="dark"] .identity,
[data-theme="dark"] .hero-panel,
[data-theme="dark"] .rail-card {
  box-shadow: none;
}
</style>
