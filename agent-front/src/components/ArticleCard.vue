<template>
  <article class="article-card">
    <router-link :to="`/article/${article.id}`" class="card-link">
      <div class="cover" v-if="article.cover">
        <img :src="article.cover" :alt="article.title" />
      </div>
      <div class="cover placeholder" v-else>
        <span>{{ titleInitial }}</span>
      </div>

      <div class="card-body">
        <div class="card-top">
          <span v-if="article.isTop" class="top-badge">置顶</span>
          <span v-for="tag in visibleTags" :key="tag.id" class="tag">#{{ tag.name }}</span>
        </div>

        <h3 class="title">{{ article.title }}</h3>
        <p class="summary" v-if="article.summary">{{ article.summary }}</p>

        <div class="meta">
          <span class="meta-item">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            {{ formatDate(article.createTime) }}
          </span>
          <span class="meta-item">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            {{ article.viewCount || 0 }}
          </span>
          <span class="meta-item" v-if="readingTime">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            {{ readingTime }}
          </span>
        </div>
      </div>

      <span class="arrow" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
      </span>
    </router-link>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ article: Object })

const visibleTags = computed(() => (props.article?.tags || []).slice(0, 3))
const titleInitial = computed(() => (props.article?.title || 'A').trim().charAt(0).toUpperCase())

const readingTime = computed(() => {
  const text = props.article?.content || props.article?.summary || ''
  if (!text) return ''
  const minutes = Math.max(1, Math.ceil(text.length / 400))
  return `约 ${minutes} 分钟`
})

function formatDate(dateStr) {
  if (!dateStr) return ''
  return dateStr.substring(0, 10)
}
</script>

<style scoped>
.article-card {
  animation: cardEnter 0.28s ease forwards;
  animation-delay: calc(var(--i, 0) * 0.025s);
  opacity: 0;
}

.card-link {
  position: relative;
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr) 32px;
  gap: 18px;
  align-items: center;
  min-height: 142px;
  padding: 16px;
  color: inherit;
  text-decoration: none;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15,23,42,0.04);
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
}

.card-link:hover {
  border-color: rgba(37,99,235,0.28);
  box-shadow: var(--atlas-shadow);
  transform: translateY(-1px);
}

.cover {
  width: 132px;
  height: 104px;
  overflow: hidden;
  border-radius: 8px;
  background: #eef2f7;
  border: 1px solid var(--atlas-border);
}

.cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.35s ease;
}

.card-link:hover .cover img {
  transform: scale(1.04);
}

.cover.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
}

.cover.placeholder span {
  font-size: 34px;
  font-weight: 800;
}

.card-body {
  min-width: 0;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-height: 22px;
}

.top-badge,
.tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  border-radius: 3px;
  font-size: 12px;
  line-height: 1;
}

.top-badge {
  color: var(--atlas-warning);
  background: rgba(180,83,9,0.08);
  border: 1px solid rgba(180,83,9,0.18);
  padding: 0 8px;
  font-weight: 700;
}

.tag {
  color: var(--atlas-muted);
}

.title {
  color: var(--atlas-text);
  font-size: 20px;
  line-height: 1.38;
  margin: 6px 0 0;
  font-weight: 700;
  letter-spacing: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-link:hover .title {
  color: var(--atlas-primary);
}

.summary {
  color: var(--atlas-muted);
  font-size: 14px;
  line-height: 1.65;
  margin-top: 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  color: var(--atlas-subtle);
  font-size: 12px;
  margin-top: 12px;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.arrow {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--atlas-subtle);
  background: var(--atlas-surface-soft);
  transition: color 0.18s, transform 0.18s;
}

.card-link:hover .arrow {
  color: var(--atlas-primary);
  transform: translateX(2px);
}

[data-theme="dark"] .card-link {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
}

[data-theme="dark"] .cover {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-border);
}

[data-theme="dark"] .cover.placeholder {
  color: #dbeafe;
  background: var(--atlas-surface-soft);
}

@keyframes cardEnter {
  0% { opacity: 0; transform: translateY(10px); }
  100% { opacity: 1; transform: translateY(0); }
}

@media (max-width: 640px) {
  .card-link {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .cover {
    width: 100%;
    height: 148px;
  }

  .arrow {
    display: none;
  }
}
</style>
