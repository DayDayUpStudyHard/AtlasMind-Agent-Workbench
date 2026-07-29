<template>
  <div class="observability-page">
    <div class="page-head">
      <div>
        <h2>AI Observability</h2>
        <p>User question -> retrieval -> sources -> tool calls -> answer.</p>
      </div>
      <div class="filters">
        <el-input
          v-model="keyword"
          placeholder="Search question or answer"
          clearable
          @keyup.enter="fetchTraces"
          @clear="fetchTraces"
        />
        <el-button type="primary" @click="fetchTraces">Search</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="records" class="trace-table" border>
      <el-table-column prop="traceId" label="Trace" width="86" />
      <el-table-column label="Question" min-width="260">
        <template #default="{ row }">
          <button class="question-link" @click="openTrace(row.traceId)">
            {{ row.question }}
          </button>
          <div class="muted">Session {{ row.sessionId }} · {{ formatDate(row.createTime) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="Retrieval" width="170">
        <template #default="{ row }">
          <el-tag :type="retrievalTag(row.retrievalType)" effect="plain">
            {{ row.retrievalType || 'NONE' }}
          </el-tag>
          <div v-if="row.fallbackReason" class="muted ellipsis">{{ row.fallbackReason }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="hitCount" label="Hits" width="80" />
      <el-table-column label="Latency" width="160">
        <template #default="{ row }">
          <span>{{ row.retrievalLatencyMs || 0 }}ms</span>
          <span class="muted"> / {{ row.llmLatencyMs || 0 }}ms</span>
        </template>
      </el-table-column>
      <el-table-column label="Answer" min-width="220">
        <template #default="{ row }">
          <span class="answer-preview">{{ row.answer || 'No answer recorded' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        :page-size="size"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="fetchTraces"
      />
    </div>

    <el-drawer v-model="drawerOpen" title="Answer Trace" size="54%">
      <div v-if="activeTrace" class="trace-detail">
        <section class="detail-section">
          <div class="section-title">User Question</div>
          <p class="question-text">{{ activeTrace.question }}</p>
          <div class="meta-row">
            <el-tag :type="retrievalTag(activeTrace.retrievalType)" effect="plain">
              {{ activeTrace.retrievalType || 'NONE' }}
            </el-tag>
            <span>topK {{ activeTrace.topK }}</span>
            <span>retrieval {{ activeTrace.retrievalLatencyMs || 0 }}ms</span>
            <span>LLM {{ activeTrace.llmLatencyMs || 0 }}ms</span>
          </div>
          <p v-if="activeTrace.fallbackReason" class="fallback">
            Fallback: {{ activeTrace.fallbackReason }}
          </p>
        </section>

        <section class="detail-section">
          <div class="section-title">Tool Calls</div>
          <el-timeline>
            <el-timeline-item
              v-for="tool in activeTrace.toolCalls || []"
              :key="tool.id"
              :type="tool.status === 'DONE' ? 'success' : tool.status === 'FAILED' ? 'danger' : 'info'"
              :timestamp="`${tool.latencyMs || 0}ms`"
            >
              <div class="tool-row">
                <strong>{{ tool.name }}</strong>
                <el-tag size="small" effect="plain">{{ tool.status }}</el-tag>
              </div>
              <p v-if="tool.inputSummary" class="muted">Input: {{ tool.inputSummary }}</p>
              <p v-if="tool.outputSummary" class="muted">Output: {{ tool.outputSummary }}</p>
              <p v-if="tool.errorMessage" class="error-text">{{ tool.errorMessage }}</p>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-if="!activeTrace.toolCalls?.length" description="No tool calls recorded" />
        </section>

        <section class="detail-section">
          <div class="section-title">Citations</div>
          <div v-if="activeTrace.hits?.length" class="hit-list">
            <div v-for="hit in activeTrace.hits" :key="hit.id" class="hit-row">
              <div class="hit-main">
                <strong>#{{ hit.rankNo }} {{ hit.title || 'Untitled source' }}</strong>
                <span>{{ hit.sourceType }} · {{ hit.sourceId }}<template v-if="hit.chunkId"> · chunk {{ hit.chunkId }}</template></span>
              </div>
              <div class="hit-score">{{ formatScore(hit.score) }}</div>
              <p>{{ hit.snippet }}</p>
            </div>
          </div>
          <el-empty v-else description="No citations recorded" />
        </section>

        <section class="detail-section">
          <div class="section-title">Final Answer</div>
          <div class="answer-box">{{ activeTrace.answer || 'No answer recorded' }}</div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAiObservabilityTrace, getAiObservabilityTraces } from '../api/index.js'

const loading = ref(false)
const drawerOpen = ref(false)
const records = ref([])
const activeTrace = ref(null)
const keyword = ref('')
const page = ref(1)
const size = 10
const total = ref(0)

onMounted(fetchTraces)

async function fetchTraces() {
  loading.value = true
  try {
    const response = await getAiObservabilityTraces({
      page: page.value,
      size,
      keyword: keyword.value || undefined,
    })
    records.value = response.data.data?.records || []
    total.value = Number(response.data.data?.total || 0)
  } finally {
    loading.value = false
  }
}

async function openTrace(id) {
  try {
    const response = await getAiObservabilityTrace(id)
    activeTrace.value = response.data.data
    drawerOpen.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.message || 'Failed to load trace')
  }
}

function retrievalTag(type) {
  if (type === 'VECTOR') return 'success'
  if (type === 'KEYWORD_FALLBACK') return 'warning'
  if (type === 'KEYWORD') return 'info'
  return ''
}

function formatDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : ''
}

function formatScore(value) {
  const score = Number(value || 0)
  return score ? score.toFixed(3) : '0'
}
</script>

<style scoped>
.observability-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
}

.page-head h2 {
  margin: 0;
  color: #1f2d3d;
  font-size: 24px;
}

.page-head p {
  margin: 6px 0 0;
  color: #607184;
  font-size: 13px;
}

.filters {
  display: flex;
  gap: 8px;
  width: min(420px, 100%);
}

.question-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #1f2d3d;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.question-link:hover {
  color: #426fa6;
}

.muted {
  margin-top: 4px;
  color: #8b9aaa;
  font-size: 12px;
  line-height: 1.5;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.answer-preview {
  display: -webkit-box;
  overflow: hidden;
  color: #607184;
  line-height: 1.5;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.pager {
  display: flex;
  justify-content: flex-end;
}

.trace-detail {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section {
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 16px;
}

.section-title {
  margin-bottom: 10px;
  color: #1f2d3d;
  font-weight: 700;
}

.question-text {
  margin: 0 0 10px;
  color: #1f2d3d;
  line-height: 1.7;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: #607184;
  font-size: 12px;
}

.fallback {
  margin: 10px 0 0;
  color: #a7793d;
  font-size: 13px;
}

.tool-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-text {
  margin: 4px 0 0;
  color: #f56c6c;
  font-size: 12px;
}

.hit-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hit-row {
  border: 1px solid #d4dde8;
  border-radius: 4px;
  padding: 12px;
  background: #fbfcfe;
}

.hit-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.hit-main strong {
  color: #1f2d3d;
}

.hit-main span {
  color: #8b9aaa;
  font-size: 12px;
}

.hit-score {
  float: right;
  color: #426fa6;
  font-family: monospace;
  font-size: 12px;
}

.hit-row p {
  margin: 8px 0 0;
  color: #607184;
  line-height: 1.6;
}

.answer-box {
  white-space: pre-wrap;
  color: #1f2d3d;
  background: #f3f6fa;
  border: 1px solid #d4dde8;
  border-radius: 4px;
  padding: 14px;
  line-height: 1.7;
}
</style>
