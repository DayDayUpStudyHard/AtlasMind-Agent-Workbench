<template>
  <n-spin :show="loading">
    <article v-if="article" class="article-detail">
      <div class="cover-hero" v-if="article.cover" ref="coverHeroRef">
        <div class="cover-img" :style="{ backgroundImage: `url(${article.cover})`, transform: `translateY(${parallaxY}px)` }"></div>
        <div class="cover-overlay"></div>
      </div>
      <div class="cover-hero gradient-hero" v-else>
        <div class="gradient-bg"></div>
      </div>

      <div class="article-header">
        <div class="header-top">
          <span v-if="article.isTop" class="top-badge">置顶</span>
        </div>
        <h1 class="article-title">{{ article.title }}</h1>
        <div class="meta">
          <div class="meta-item">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            {{ formatDate(article.createTime) }}
          </div>
          <span class="meta-sep">|</span>
          <div class="meta-item">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            {{ article.viewCount }} 阅读
          </div>
          <span class="meta-sep">|</span>
          <div class="meta-item" v-if="readingTime">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            {{ readingTime }}
          </div>
        </div>
      </div>

      <div class="divider"></div>

      <div class="content markdown-body" v-html="renderMarkdown(article.content || '')"></div>

      <div class="article-footer" v-if="article.tags && article.tags.length">
        <div class="tags-row">
          <span class="tags-label">标签:</span>
          <span v-for="tag in article.tags" :key="tag.id" class="tag-item">#{{ tag.name }}</span>
        </div>
      </div>

      <!-- 点赞区域 -->
      <div class="like-section">
        <button
          class="like-btn"
          :class="{ 'liked': liked }"
          @click="handleToggleLike"
          :disabled="likeLoading"
        >
          <svg width="22" height="22" viewBox="0 0 24 24"
            :fill="liked ? 'currentColor' : 'none'"
            :stroke="liked ? 'none' : 'currentColor'"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
          <span class="like-count">{{ likeCount }}</span>
        </button>
        <span class="like-hint" v-if="liked">感谢点赞！</span>
      </div>
    </article>

    <n-empty v-else-if="!loading" description="文章不存在" />

    <nav v-if="prevArticle || nextArticle" class="article-nav">
      <router-link v-if="prevArticle" :to="`/article/${prevArticle.id}`" class="nav-link prev">
        <span class="nav-label">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
          上一篇
        </span>
        <span class="nav-title">{{ prevArticle.title }}</span>
      </router-link>
      <router-link v-if="nextArticle" :to="`/article/${nextArticle.id}`" class="nav-link next">
        <span class="nav-label">
          下一篇
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
        </span>
        <span class="nav-title">{{ nextArticle.title }}</span>
      </router-link>
    </nav>

    <CommentList v-if="article" :article-id="article.id" :comments="comments" :total="commentTotal" @refresh="fetchComments" />

    <BackToTop />
  </n-spin>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getArticleDetail, getArticleNav, getComments, toggleLike, getArticleLikes } from '../api/index.js'
import CommentList from '../components/CommentList.vue'
import BackToTop from '../components/BackToTop.vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

marked.use({
  renderer: {
    code({ text, lang }) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      const highlighted = hljs.highlight(text, { language }).value
      return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
    }
  }
})

const route = useRoute()
const article = ref(null)
const loading = ref(false)
const comments = ref([])
const commentTotal = ref(0)
const prevArticle = ref(null)
const nextArticle = ref(null)
const coverHeroRef = ref(null)
const parallaxY = ref(0)

// 点赞状态
const liked = ref(false)
const likeCount = ref(0)
const likeLoading = ref(false)

const readingTime = computed(() => {
  const text = article.value?.content || ''
  if (!text) return ''
  const minutes = Math.max(1, Math.ceil(text.length / 400))
  return `约 ${minutes} 分钟`
})

function onParallax() {
  parallaxY.value = window.scrollY * 0.35
}
onMounted(() => {
  fetchArticle(); fetchComments()
  window.addEventListener('scroll', onParallax, { passive: true })
})
onUnmounted(() => {
  window.removeEventListener('scroll', onParallax)
})

watch(() => route.params.id, () => {
  fetchArticle()
  fetchComments()
  window.scrollTo(0, 0)
})

async function fetchArticle() {
  loading.value = true
  try {
    const [detailRes, navRes] = await Promise.all([
      getArticleDetail(route.params.id),
      getArticleNav(route.params.id)
    ])
    article.value = detailRes.data.data
    const nav = navRes.data.data
    prevArticle.value = nav.prev?.id ? nav.prev : null
    nextArticle.value = nav.next?.id ? nav.next : null
    fetchLikes()
  }
  finally { loading.value = false }
}

async function fetchLikes() {
  try {
    const res = await getArticleLikes(route.params.id)
    const data = res.data.data
    liked.value = data.liked
    likeCount.value = data.count
  } catch { /* 点赞功能不可用时静默降级 */ }
}

async function handleToggleLike() {
  if (likeLoading.value) return
  likeLoading.value = true
  try {
    const res = await toggleLike(route.params.id)
    const data = res.data.data
    liked.value = data.liked
    likeCount.value = data.count
  } catch {
    // 失败时静默忽略
  } finally {
    likeLoading.value = false
  }
}

async function fetchComments() {
  const res = await getComments(route.params.id)
  comments.value = res.data.data.records
  commentTotal.value = res.data.data.total
}

function renderMarkdown(content) { return marked(content || '') }
function formatDate(d) { return d ? d.substring(0, 10) : '' }
</script>

<style scoped>
.article-detail {
  max-width: 780px;
  margin: 0 auto;
  padding: 24px 0;
}

/* Cover Hero */
.cover-hero {
  width: 100%; height: 320px; border-radius: 8px; overflow: hidden;
  position: relative; margin-bottom: 28px;
  border: 1px solid var(--atlas-border);
}
.cover-img {
  width: 100%; height: 120%;
  background-size: cover; background-position: center;
  will-change: transform;
}
.cover-overlay {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 40%, rgba(0,0,0,0.35) 100%);
}

.gradient-hero {
  height: 200px;
  background: #111827;
  position: relative;
}
.gradient-bg {
  position: absolute; inset: 0;
  background:
    radial-gradient(circle at 20% 30%, rgba(255,255,255,0.15) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(255,255,255,0.1) 0%, transparent 50%);
}

.article-header { text-align: center; padding: 20px 0 16px; }
.header-top { margin-bottom: 10px; }
.top-badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  color: #e6a23c; padding: 3px 10px; border-radius: 4px;
  background: #fdf6ec; border: 1px solid #faecd8;
}

.article-title {
  font-size: 34px; color: var(--atlas-text); line-height: 1.28; margin: 0 0 14px;
  font-weight: 700;
  letter-spacing: 0;
}

.meta { display: flex; gap: 10px; justify-content: center; align-items: center; color: var(--atlas-muted); font-size: 13px; flex-wrap: wrap; }
.meta-item { display: flex; align-items: center; gap: 5px; }
.meta-sep { color: #d0d5dd; }

.divider {
  padding: 0 0 28px; display: flex; justify-content: center;
}
.divider::after {
  content: ''; width: 100%; max-width: 220px; height: 1px;
  background: var(--atlas-border);
}

.article-footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--atlas-border); }
.tags-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tags-label { font-size: 12px; color: #909399; font-weight: 500; }
.tag-item {
  font-size: 12px; color: var(--atlas-primary);
  padding: 3px 10px; border-radius: 4px;
  background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.16);
  transition: all 0.2s;
}
.tag-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(64,158,255,0.15);
}

.article-nav {
  display: flex; justify-content: space-between; gap: 16px;
  margin-top: 40px; padding-top: 24px;
  border-top: 1px solid var(--atlas-border);
}
.nav-link {
  flex: 1; text-decoration: none; padding: 16px 20px; border-radius: 10px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  transition: all 0.25s;
}
.nav-link:hover {
  background: var(--atlas-surface);
  box-shadow: var(--atlas-shadow);
  transform: translateY(-1px);
}
.nav-link.next { text-align: right; }
.nav-label {
  display: flex; align-items: center; gap: 4px;
  font-size: 11px; color: #909399; font-weight: 500; margin-bottom: 6px;
}
.nav-link.next .nav-label { justify-content: flex-end; }
.nav-title {
  font-size: 14px; color: var(--atlas-text); font-weight: 500; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

/* 点赞区域 */
.like-section {
  display: flex; align-items: center; gap: 12px;
  margin-top: 24px; padding-top: 20px;
  border-top: 1px solid var(--atlas-border);
}
.like-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 20px; border-radius: 999px; cursor: pointer;
  border: 1.5px solid #e4e7ed; background: #fff; color: #909399;
  font-size: 15px; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  outline: none; user-select: none;
}
.like-btn:hover {
  border-color: #f56c6c; color: #f56c6c;
  box-shadow: 0 4px 16px rgba(245, 108, 108, 0.15);
  transform: scale(1.04);
}
.like-btn:active { transform: scale(0.96); transition: transform 0.1s; }
.like-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.like-btn.liked {
  background: linear-gradient(135deg, #f56c6c, #e74c3c);
  border-color: #e74c3c; color: #fff;
  box-shadow: 0 2px 12px rgba(245, 108, 108, 0.3);
}
.like-btn.liked:hover {
  border-color: #c0392b;
  box-shadow: 0 6px 20px rgba(245, 108, 108, 0.25);
}
.like-count { font-weight: 600; min-width: 20px; text-align: center; }
.like-hint {
  font-size: 13px; color: #f56c6c; font-weight: 500;
  animation: fadeIn 0.5s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateX(-8px); }
  to { opacity: 1; transform: translateX(0); }
}

@media (max-width: 640px) {
  .cover-hero {
    height: 220px;
  }

  .article-title {
    font-size: 28px;
  }

  .article-nav {
    flex-direction: column;
  }
}
</style>
