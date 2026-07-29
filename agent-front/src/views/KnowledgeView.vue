<template>
  <div class="knowledge-page">
    <section class="knowledge-head">
      <div>
        <span class="page-kicker">Knowledge Base</span>
        <h1>浏览已上传的知识文档</h1>
        <p>这里展示后台上传并完成解析的文档。点击任一文档可查看分块内容和所在知识空间。</p>
      </div>
      <div class="page-stats">
        <strong>{{ visibleDocuments.length }}</strong>
        <span>可见文档</span>
      </div>
    </section>

    <section class="knowledge-toolbar">
      <div class="search-box">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input v-model="keyword" type="text" placeholder="搜索标题或文件名" />
      </div>
      <div class="space-filters">
        <button
          type="button"
          class="space-chip"
          :class="{ active: activeSpace === 'all' }"
          @click="activeSpace = 'all'"
        >
          全部
        </button>
        <button
          v-for="space in spaces"
          :key="space.id"
          type="button"
          class="space-chip"
          :class="{ active: String(activeSpace) === String(space.id) }"
          @click="activeSpace = String(space.id)"
        >
          {{ space.name }}
        </button>
      </div>
    </section>

    <section class="knowledge-grid">
      <main class="document-list">
        <div v-if="loading" class="loading-state">正在加载知识文档...</div>
        <template v-else>
          <button
            v-for="doc in visibleDocuments"
            :key="doc.id"
            type="button"
            class="document-card"
            :class="{ active: selectedDocumentId === doc.id }"
            @click="selectDocument(doc.id)"
          >
            <div class="document-card-head">
              <div>
                <span class="doc-space">{{ doc.spaceName || '未命名空间' }}</span>
                <strong>{{ doc.title }}</strong>
              </div>
              <span class="doc-status">{{ doc.status }}</span>
            </div>
            <p>{{ doc.fileName }} · {{ doc.fileType || 'FILE' }}</p>
            <div class="document-meta">
              <span>Chunks {{ doc.chunkCount || 0 }}</span>
              <span>{{ formatSize(doc.fileSize) }}</span>
              <span>{{ formatDate(doc.createTime) }}</span>
            </div>
          </button>
          <div v-if="!visibleDocuments.length" class="empty-state">没有匹配的知识文档</div>
        </template>
      </main>

      <aside class="document-detail">
        <div v-if="detailLoading" class="loading-state">正在读取文档详情...</div>
        <template v-else-if="selectedDocument">
          <div class="detail-head">
            <div>
              <span class="doc-space">{{ selectedDocument.spaceName || '未命名空间' }}</span>
              <h2>{{ selectedDocument.title }}</h2>
              <p>{{ selectedDocument.fileName }}</p>
            </div>
            <span class="doc-status">{{ selectedDocument.status }}</span>
          </div>

          <div class="detail-meta">
            <span>类型：{{ selectedDocument.fileType || 'FILE' }}</span>
            <span>分块：{{ selectedDocument.chunkCount || chunks.length || 0 }}</span>
            <span>解析：{{ selectedDocument.parseMode || '-' }}</span>
            <span>更新时间：{{ formatDate(selectedDocument.updateTime || selectedDocument.createTime) }}</span>
          </div>

          <div class="chunk-list">
            <article v-for="chunk in chunks" :key="chunk.id" class="chunk-card">
              <div class="chunk-head">
                <strong>Chunk {{ chunk.chunkIndex + 1 }}</strong>
                <span v-if="chunk.sourcePage != null">P{{ chunk.sourcePage }}</span>
              </div>
              <p>{{ chunk.sectionTitle || '未命名章节' }}</p>
              <div class="chunk-text">{{ chunk.chunkText }}</div>
            </article>
          </div>
        </template>
        <div v-else class="empty-detail">
          请选择一篇文档查看详情
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getKbDocument, getKbDocumentChunks, getKbDocuments } from '../api/index.js'

const route = useRoute()
const spaces = ref([])
const documents = ref([])
const keyword = ref('')
const activeSpace = ref('all')
const loading = ref(false)
const detailLoading = ref(false)
const selectedDocumentId = ref(null)
const selectedDocument = ref(null)
const chunks = ref([])

const visibleDocuments = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return documents.value.filter((doc) => {
    const matchesSpace = activeSpace.value === 'all' || String(doc.spaceId) === String(activeSpace.value)
    if (!matchesSpace) return false
    if (!q) return true
    return [doc.title, doc.fileName, doc.spaceName, doc.fileType]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(q))
  })
})

onMounted(loadDocuments)

watch(visibleDocuments, (docs) => {
  if (!docs.length) {
    selectedDocumentId.value = null
    selectedDocument.value = null
    chunks.value = []
    return
  }
  if (!selectedDocumentId.value || !docs.some((doc) => doc.id === selectedDocumentId.value)) {
    selectDocument(docs[0].id)
  }
}, { immediate: true })

watch(() => route.query.doc, (docId) => {
  const id = Number(docId || 0)
  if (!id || !documents.value.some((doc) => doc.id === id)) return
  selectDocument(id)
})

async function loadDocuments() {
  loading.value = true
  try {
    const response = await getKbDocuments({ page: 1, size: 100 })
    const data = response.data.data || {}
    documents.value = data.records || []
    spaces.value = data.spaces || []
    const routedDocumentId = Number(route.query.doc || 0)
    const initialDocument = documents.value.find((doc) => doc.id === routedDocumentId) || documents.value[0]
    if (initialDocument && !selectedDocumentId.value) {
      await selectDocument(initialDocument.id)
    }
  } finally {
    loading.value = false
  }
}

async function selectDocument(id) {
  if (!id) return
  selectedDocumentId.value = id
  detailLoading.value = true
  try {
    const [detailRes, chunksRes] = await Promise.all([
      getKbDocument(id),
      getKbDocumentChunks(id),
    ])
    selectedDocument.value = detailRes.data.data || null
    chunks.value = chunksRes.data.data || []
  } finally {
    detailLoading.value = false
  }
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).slice(0, 10)
}

function formatSize(bytes) {
  const size = Number(bytes || 0)
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.knowledge-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
}

.page-kicker {
  display: block;
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
}

.knowledge-head h1 {
  margin: 8px 0 10px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 34px;
  line-height: 1.15;
}

.knowledge-head p {
  max-width: 720px;
  color: var(--atlas-muted);
  font-size: 15px;
  line-height: 1.7;
}

.page-stats {
  min-width: 120px;
  padding: 14px 16px;
  text-align: right;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.page-stats strong {
  display: block;
  color: var(--atlas-text);
  font-size: 26px;
  line-height: 1;
}

.page-stats span {
  display: block;
  margin-top: 6px;
  color: var(--atlas-muted);
  font-size: 12px;
}

.knowledge-toolbar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  min-height: 40px;
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
}

.search-box input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--atlas-text);
  font: inherit;
}

.space-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.space-chip {
  padding: 7px 11px;
  color: var(--atlas-muted);
  background: transparent;
  border: 1px solid var(--atlas-border);
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
}

.space-chip.active {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
  background: rgba(66, 111, 166, 0.08);
}

.knowledge-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(320px, 1.08fr);
  gap: 20px;
  align-items: start;
}

.document-list,
.document-detail {
  min-width: 0;
}

.document-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.document-card {
  width: 100%;
  padding: 16px;
  text-align: left;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.18s, transform 0.18s;
}

.document-card:hover,
.document-card.active {
  border-color: var(--atlas-primary);
  transform: translateY(-1px);
}

.document-card-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 16px;
}

.document-card strong,
.detail-head h2 {
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  line-height: 1.25;
}

.document-card strong {
  display: block;
  margin-top: 6px;
  font-size: 20px;
}

.document-card p {
  margin: 10px 0 12px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
}

.document-meta,
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  color: var(--atlas-subtle);
  font-size: 12px;
}

.doc-space {
  display: block;
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
}

.doc-status {
  flex: 0 0 auto;
  padding: 4px 8px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}

.document-detail {
  padding: 18px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.detail-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 16px;
}

.detail-head h2 {
  margin: 6px 0 6px;
  font-size: 26px;
}

.detail-head p {
  color: var(--atlas-muted);
  font-size: 13px;
}

.detail-meta {
  margin: 16px 0 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--atlas-border);
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chunk-card {
  padding: 14px;
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
}

.chunk-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
}

.chunk-card p {
  margin: 8px 0 10px;
  color: var(--atlas-text);
  font-size: 14px;
  font-weight: 600;
}

.chunk-text {
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.loading-state,
.empty-state,
.empty-detail {
  padding: 40px 16px;
  color: var(--atlas-muted);
  text-align: center;
}

@media (max-width: 960px) {
  .knowledge-head,
  .knowledge-grid {
    grid-template-columns: 1fr;
    display: grid;
  }

  .page-stats {
    justify-self: start;
    text-align: left;
  }
}

@media (max-width: 640px) {
  .knowledge-head h1 {
    font-size: 28px;
  }

  .knowledge-toolbar,
  .document-detail {
    padding: 14px;
  }
}
</style>
