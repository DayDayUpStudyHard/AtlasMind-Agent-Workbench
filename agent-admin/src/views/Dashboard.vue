<template>
  <div class="dashboard">
    <div class="page-hero">
      <div>
        <span class="eyebrow">Overview</span>
        <h2>内容工作台</h2>
        <p>查看发布状态、评论反馈和近期内容，让知识运营有一个清晰入口。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="$router.push('/articles')">管理文章</el-button>
        <el-button type="primary" @click="$router.push('/articles/create')">新建文章</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="stat-row">
      <el-col :xs="24" :sm="12" :lg="6" v-for="item in statItems" :key="item.label">
        <div class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <span class="stat-hint">{{ item.hint }}</span>
        </div>
      </el-col>
    </el-row>

    <div class="dashboard-grid">
      <section class="panel work-panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Workflow</span>
            <h3>今日关注</h3>
          </div>
        </div>
        <div class="todo-list">
          <router-link to="/comments" class="todo-item">
            <span class="todo-dot warning"></span>
            <div>
              <strong>{{ stats.commentCount }}</strong>
              <p>条评论需要持续关注审核与回复。</p>
            </div>
          </router-link>
          <router-link to="/articles" class="todo-item">
            <span class="todo-dot primary"></span>
            <div>
              <strong>{{ stats.articleCount }}</strong>
              <p>篇文章构成当前公开内容池。</p>
            </div>
          </router-link>
          <router-link to="/moments" class="todo-item">
            <span class="todo-dot success"></span>
            <div>
              <strong>{{ stats.momentCount }}</strong>
              <p>条说说可用于补充日常动态。</p>
            </div>
          </router-link>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Recent</span>
            <h3>最近文章</h3>
          </div>
          <router-link to="/articles">全部</router-link>
        </div>
        <div class="article-list" v-loading="loading">
          <router-link
            v-for="article in recentArticles"
            :key="article.id"
            :to="`/articles/${article.id}/edit`"
            class="article-row"
          >
            <div>
              <strong>{{ article.title }}</strong>
              <span>{{ article.createTime ? article.createTime.substring(0, 16) : '-' }}</span>
            </div>
            <em :class="article.status === 1 ? 'published' : 'draft'">
              {{ article.status === 1 ? '已发布' : '草稿' }}
            </em>
          </router-link>
          <el-empty v-if="!loading && recentArticles.length === 0" description="暂无文章" :image-size="72" />
        </div>
      </section>

      <section class="panel comments-panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Feedback</span>
            <h3>最新评论</h3>
          </div>
          <router-link to="/comments">处理</router-link>
        </div>
        <div class="comment-list" v-loading="loading">
          <div v-for="comment in recentComments" :key="comment.id" class="comment-row">
            <div class="comment-avatar">{{ (comment.nickname || '访').charAt(0) }}</div>
            <div class="comment-body">
              <strong>{{ comment.nickname || '访客' }}</strong>
              <p>{{ comment.content || '暂无内容' }}</p>
            </div>
          </div>
          <el-empty v-if="!loading && recentComments.length === 0" description="暂无评论" :image-size="72" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDashboardOverview } from '../api/index.js'

const loading = ref(false)
const stats = ref({
  articleCount: 0,
  categoryCount: 0,
  commentCount: 0,
  momentCount: 0,
  knowledgeDocumentCount: 0,
  failedJobCount: 0
})
const recentArticles = ref([])
const recentComments = ref([])

const statItems = computed(() => {
  const items = [
  { label: '文章', value: stats.value.articleCount, hint: '公开内容资产' },
  { label: '分类', value: stats.value.categoryCount, hint: '知识结构入口' },
  { label: '评论', value: stats.value.commentCount, hint: '读者互动反馈' },
  { label: '说说', value: stats.value.momentCount, hint: '轻量动态记录' }
  ]
  return [
    ...items,
    { label: '知识文档', value: stats.value.knowledgeDocumentCount, hint: '可用于 RAG 的资料' },
    { label: '失败任务', value: stats.value.failedJobCount, hint: '需要重试的导入任务' }
  ]
})

onMounted(fetchDashboard)

async function fetchDashboard() {
  loading.value = true
  try {
    const response = await getDashboardOverview()
    const data = response.data.data || {}

    recentArticles.value = data.recentArticles || []
    recentComments.value = data.recentComments || []
    stats.value = {
      articleCount: Number(data.articleCount) || 0,
      categoryCount: Number(data.categoryCount) || 0,
      commentCount: Number(data.commentCount) || 0,
      momentCount: Number(data.momentCount) || 0,
      knowledgeDocumentCount: Number(data.knowledgeDocumentCount) || 0,
      failedJobCount: Number(data.failedJobCount) || 0
    }
  } finally {
    loading.value = false
  }
}

</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-hero,
.panel,
.stat-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.page-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 24px;
}

.eyebrow {
  color: #426fa6;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.page-hero h2 {
  color: #111827;
  font-size: 26px;
  line-height: 1.2;
  margin: 6px 0 8px;
}

.page-hero p {
  color: #64748b;
  margin: 0;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.stat-row {
  row-gap: 16px;
}

.stat-card {
  padding: 18px;
  min-height: 132px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.stat-label {
  color: #64748b;
  font-size: 13px;
  font-weight: 700;
}

.stat-card strong {
  color: #111827;
  font-size: 34px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.stat-hint {
  color: #94a3b8;
  font-size: 12px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 0.9fr 1.2fr;
  gap: 18px;
}

.panel {
  padding: 20px;
}

.work-panel {
  grid-row: span 2;
}

.comments-panel {
  grid-column: 2;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-head h3 {
  color: #111827;
  font-size: 18px;
  margin: 3px 0 0;
}

.panel-head a {
  color: #64748b;
  font-size: 13px;
  text-decoration: none;
}

.panel-head a:hover {
  color: #426fa6;
}

.todo-list,
.article-list,
.comment-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.todo-item {
  display: flex;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.18s, background 0.18s;
}

.todo-item:hover {
  border-color: #bfdbfe;
  background: #f8fafc;
}

.todo-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-top: 7px;
  flex-shrink: 0;
}

.todo-dot.warning { background: #f59e0b; }
.todo-dot.primary { background: #426fa6; }
.todo-dot.success { background: #10b981; }

.todo-item strong {
  color: #111827;
  font-size: 18px;
}

.todo-item p {
  color: #64748b;
  font-size: 13px;
  margin: 3px 0 0;
  line-height: 1.55;
}

.article-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 0;
  color: inherit;
  text-decoration: none;
  border-bottom: 1px solid #f1f5f9;
}

.article-row:last-child {
  border-bottom: none;
}

.article-row strong {
  color: #111827;
  display: block;
  font-size: 14px;
  line-height: 1.45;
}

.article-row span {
  color: #94a3b8;
  display: block;
  font-size: 12px;
  margin-top: 4px;
}

.article-row em {
  flex-shrink: 0;
  border-radius: 999px;
  font-style: normal;
  font-size: 12px;
  padding: 3px 8px;
}

.article-row em.published {
  color: #047857;
  background: #ecfdf5;
}

.article-row em.draft {
  color: #64748b;
  background: #f1f5f9;
}

.comment-row {
  display: flex;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.comment-row:last-child {
  border-bottom: none;
}

.comment-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #eef2ff;
  color: #426fa6;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  flex-shrink: 0;
}

.comment-body {
  min-width: 0;
}

.comment-body strong {
  display: block;
  color: #111827;
  font-size: 13px;
}

.comment-body p {
  color: #64748b;
  font-size: 13px;
  line-height: 1.55;
  margin: 3px 0 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .comments-panel {
    grid-column: auto;
  }
}

@media (max-width: 720px) {
  .page-hero {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
