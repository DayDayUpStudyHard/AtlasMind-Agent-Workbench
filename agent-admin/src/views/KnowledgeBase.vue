<template>
  <div class="knowledge-page">
    <section class="page-hero">
      <div>
        <span class="eyebrow">Knowledge Base</span>
        <h2>企业知识库</h2>
        <p>把研发文档、制度 SOP、项目复盘和 FAQ 导入 RAG，统一进入 AtlasMind AI 的引用式问答。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="openSpaceDialog()">
          <el-icon><Plus /></el-icon>
          新建空间
        </el-button>
        <el-button type="primary" :loading="debugImporting" @click="doImportDebugRecord">
          <el-icon><Upload /></el-icon>
          导入 Debug 记录
        </el-button>
      </div>
    </section>

    <section class="space-strip" v-loading="spaceLoading">
      <button
        v-for="space in spaces"
        :key="space.id"
        class="space-chip"
        :class="{ active: selectedSpaceId === space.id }"
        @click="selectSpace(space.id)"
      >
        <span class="space-mark" :style="{ background: space.color || '#426fa6' }"></span>
        <span>
          <strong>{{ space.name }}</strong>
          <em>{{ space.description || '暂无描述' }}</em>
        </span>
      </button>
      <button class="space-chip all-chip" :class="{ active: selectedSpaceId === null }" @click="selectSpace(null)">
        <span class="space-mark neutral"></span>
        <span>
          <strong>全部文档</strong>
          <em>跨空间查看</em>
        </span>
      </button>
    </section>

    <div class="workspace-grid">
      <section class="panel upload-panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Ingest</span>
            <h3>导入资料</h3>
          </div>
        </div>
        <el-form label-position="top" class="compact-form">
          <el-form-item label="空间">
            <el-select v-model="uploadForm.spaceId" placeholder="选择知识空间">
              <el-option v-for="space in spaces" :key="space.id" :label="space.name" :value="space.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="uploadForm.title" placeholder="不填则使用文件名" />
          </el-form-item>
          <el-form-item label="解析模式">
            <el-segmented
              v-model="uploadForm.parseMode"
              :options="parseModeOptions"
              class="parse-mode-control"
            />
          </el-form-item>
          <el-upload
            ref="uploadRef"
            drag
            :auto-upload="false"
            :limit="1"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
            accept=".md,.markdown,.txt,.pdf"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入 Markdown、TXT 或 PDF，或点击选择</div>
          </el-upload>
          <p class="upload-hint">单文件上限 300MB，大文件会异步解析，完成后在消息中心提醒。</p>
          <el-progress
            v-if="uploading"
            class="upload-progress"
            :percentage="uploadProgress"
            :stroke-width="6"
          />
          <el-button class="upload-button" type="primary" :disabled="!canUpload" :loading="uploading" @click="doUpload">
            开始导入
          </el-button>
        </el-form>
      </section>

      <section class="panel qa-panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Retrieval Test</span>
            <h3>检索测试</h3>
          </div>
          <el-select v-model="qaForm.documentId" clearable placeholder="指定文档" size="small" class="doc-filter">
            <el-option v-for="doc in documents" :key="doc.id" :label="doc.title" :value="doc.id" />
          </el-select>
        </div>
        <div class="qa-box">
          <el-input v-model="qaForm.message" type="textarea" :rows="3" placeholder="输入一个面试题、项目问题或笔记关键词" />
          <div class="qa-actions">
            <div class="top-k-control">
              <span class="top-k-label">Top-K</span>
              <el-tooltip
                content="Top-K 表示最多返回的检索结果数量。数值越大，召回范围越广，但噪声也可能增加。"
                placement="top"
              >
                <el-icon class="top-k-help"><InfoFilled /></el-icon>
              </el-tooltip>
              <el-input-number v-model="qaForm.topK" :min="1" :max="maxTopK" size="small" />
            </div>
            <el-button type="primary" :loading="qaLoading" @click="runQaTest">
              <el-icon><Search /></el-icon>
              测试召回
            </el-button>
          </div>
        </div>
        <div v-if="qaResult" class="qa-result">
          <div class="result-meta">
            <span>{{ qaResult.retrievalType || 'UNKNOWN' }}</span>
            <span>{{ qaResult.embeddingModel || '关键词检索' }}</span>
          </div>
          <div v-if="qaHits.length === 0" class="empty-line">没有召回结果</div>
          <article v-for="hit in qaHits" :key="hit.chunkId || hit.id" class="hit-row">
            <strong>{{ hit.title }}</strong>
            <p>{{ hit.snippet }}</p>
            <span>score {{ formatScore(hit.score) }}</span>
          </article>
        </div>
      </section>
    </div>

    <section class="panel document-panel">
      <div class="panel-head document-head">
        <div>
          <span class="eyebrow">Documents</span>
          <h3>文档索引</h3>
        </div>
        <div class="table-tools">
          <el-select v-model="filterStatus" clearable placeholder="状态" size="small" @change="fetchDocuments">
            <el-option label="就绪" value="READY" />
            <el-option label="解析中" value="PARSING" />
            <el-option label="OCR 中" value="OCR" />
            <el-option label="索引中" value="INDEXING" />
            <el-option label="失败" value="FAILED" />
            <el-option label="禁用" value="DISABLED" />
          </el-select>
          <el-checkbox v-model="includeDeleted" @change="fetchDocuments">显示已删除</el-checkbox>
          <el-button :loading="documentLoading" @click="fetchDocuments">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </div>
      <el-table :data="documents" v-loading="documentLoading" stripe>
        <el-table-column prop="title" label="标题" min-width="240">
          <template #default="{ row }">
            <div class="doc-title">
              <strong>{{ row.title }}</strong>
              <span>{{ row.fileName }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="空间" width="120">
          <template #default="{ row }">{{ spaceName(row.spaceId) }}</template>
        </el-table-column>
        <el-table-column prop="fileType" label="类型" width="80" align="center" />
        <el-table-column label="解析" width="110" align="center">
          <template #default="{ row }">{{ parseModeLabel(row.parseMode) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <span class="status-badge" :class="statusClass(row)">{{ statusLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="任务进度" min-width="210">
          <template #default="{ row }">
            <div v-if="row.latestJobId" class="job-progress">
              <div class="job-progress-head">
                <span>{{ jobStatusLabel(row) }}</span>
                <em>{{ row.latestJobProgress || 0 }}%</em>
              </div>
              <el-progress
                :percentage="Number(row.latestJobProgress) || 0"
                :status="jobProgressStatus(row)"
                :stroke-width="6"
                :show-text="false"
              />
              <p :class="{ danger: row.latestJobStatus === 'FAILED' }">{{ jobMessage(row) }}</p>
            </div>
            <span v-else class="muted">暂无任务</span>
          </template>
        </el-table-column>
        <el-table-column label="切片" width="90" align="center">
          <template #default="{ row }">{{ row.chunkCount || 0 }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updateTime || row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="360" align="center">
          <template #default="{ row }">
            <div class="actions">
              <button class="action-btn preview" @click="openChunks(row)">切片</button>
              <button v-if="row.deleted !== 1" class="action-btn edit" @click="doReparse(row)">重解析</button>
              <button v-if="row.deleted !== 1" class="action-btn edit" @click="doReindex(row)">重索引</button>
              <button v-if="row.deleted === 1" class="action-btn restore" @click="doRestore(row)">恢复</button>
              <el-popconfirm v-if="row.deleted !== 1" title="确定删除并移出检索？" @confirm="doDelete(row)">
                <template #reference>
                  <button class="action-btn delete" @click.stop>删除</button>
                </template>
              </el-popconfirm>
              <el-popconfirm title="永久删除后无法恢复，确定继续？" @confirm="doPermanentDelete(row)">
                <template #reference>
                  <button class="action-btn danger" @click.stop>永久删除</button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination" v-if="total > pageSize">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="fetchDocuments" />
      </div>
    </section>

    <el-dialog v-model="spaceDialogVisible" :title="editingSpace ? '编辑空间' : '新建空间'" width="460px">
      <el-form :model="spaceForm" label-width="70px">
        <el-form-item label="名称">
          <el-input v-model="spaceForm.name" placeholder="例如：项目复盘" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="spaceForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="spaceForm.color" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="spaceForm.sort" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="spaceDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSpace">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="chunkDialogVisible" :title="chunkDialogTitle" width="760px">
      <div v-loading="chunkLoading" class="chunk-list">
        <article v-for="chunk in chunks" :key="chunk.id" class="chunk-row">
          <div class="chunk-head">
            <strong>#{{ chunk.chunkIndex + 1 }} {{ chunk.sectionTitle || '未命名段落' }}</strong>
            <span>{{ chunk.charCount || 0 }} 字</span>
          </div>
          <p>{{ chunk.chunkText }}</p>
        </article>
        <el-empty v-if="!chunkLoading && chunks.length === 0" description="暂无切片" :image-size="72" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, Plus, Refresh, Search, Upload, UploadFilled } from '@element-plus/icons-vue'
import {
  completeKbDocumentUpload,
  createKbSpace,
  deleteKbDocument,
  getRuntimeSettings,
  getKbDocumentChunks,
  getKbDocuments,
  getKbSpaces,
  importDebugRecord,
  permanentDeleteKbDocument,
  reindexKbDocument,
  reparseKbDocument,
  restoreKbDocument,
  testKbQa,
  uploadKbDocumentChunk
} from '../api/index.js'

const spaces = ref([])
const documents = ref([])
const chunks = ref([])
const selectedSpaceId = ref(null)
const filterStatus = ref('')
const includeDeleted = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)
const spaceLoading = ref(false)
const documentLoading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const debugImporting = ref(false)
const chunkLoading = ref(false)
const qaLoading = ref(false)
const uploadRef = ref(null)
const selectedFile = ref(null)
const documentPollTimer = ref(null)
const chunkDialogVisible = ref(false)
const chunkDialogTitle = ref('切片预览')
const spaceDialogVisible = ref(false)
const editingSpace = ref(null)
const spaceForm = ref({ name: '', description: '', icon: 'book', color: '#426fa6', sort: 0, enabled: 1 })
const uploadForm = ref({ spaceId: null, title: '', parseMode: 'OCR' })
const parseModeOptions = [
  { label: '快速', value: 'FAST' },
  { label: 'OCR', value: 'OCR' },
  { label: 'MinerU', value: 'MINERU' }
]
const qaForm = ref({ message: '', documentId: null, topK: 5 })
const maxTopK = ref(10)
const qaResult = ref(null)
const MAX_UPLOAD_SIZE_MB = 300
const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
const KB_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024

const canUpload = computed(() => uploadForm.value.spaceId && selectedFile.value)
const qaHits = computed(() => qaResult.value?.hits || [])
const hasActiveJobs = computed(() => documents.value.some(row => isActiveJob(row.latestJobStatus)))

onMounted(async () => {
  await fetchSpaces()
  await fetchDocuments()
  await fetchRuntimeSettings()
  startDocumentPolling()
})

onUnmounted(() => {
  stopDocumentPolling()
})

async function fetchRuntimeSettings() {
  try {
    const res = await getRuntimeSettings()
    const settings = res.data.data || []
    const values = Object.fromEntries(settings.map(item => [item.settingKey, item.settingValue]))
    maxTopK.value = Number(values['ai.retrieval.max-top-k']) || 10
    qaForm.value.topK = Math.min(Number(values['ai.retrieval.top-k']) || 5, maxTopK.value)
  } catch {}
}

async function fetchSpaces() {
  spaceLoading.value = true
  try {
    const res = await getKbSpaces()
    spaces.value = res.data.data || []
    if (!uploadForm.value.spaceId && spaces.value.length) {
      uploadForm.value.spaceId = spaces.value[0].id
    }
  } finally {
    spaceLoading.value = false
  }
}

async function fetchDocuments() {
  documentLoading.value = true
  try {
    const params = {
      page: page.value,
      size: pageSize,
      includeDeleted: includeDeleted.value
    }
    if (selectedSpaceId.value) params.spaceId = selectedSpaceId.value
    if (filterStatus.value) params.status = filterStatus.value
    const res = await getKbDocuments(params)
    documents.value = res.data.data?.records || []
    total.value = Number(res.data.data?.total) || 0
  } finally {
    documentLoading.value = false
  }
}

function startDocumentPolling() {
  stopDocumentPolling()
  documentPollTimer.value = window.setInterval(() => {
    if (hasActiveJobs.value && !documentLoading.value) {
      fetchDocuments()
    }
  }, 5000)
}

function stopDocumentPolling() {
  if (documentPollTimer.value) {
    window.clearInterval(documentPollTimer.value)
    documentPollTimer.value = null
  }
}

function selectSpace(spaceId) {
  selectedSpaceId.value = spaceId
  if (spaceId) uploadForm.value.spaceId = spaceId
  page.value = 1
  fetchDocuments()
}

function openSpaceDialog(space = null) {
  editingSpace.value = space
  spaceForm.value = space
    ? { ...space }
    : { name: '', description: '', icon: 'book', color: '#426fa6', sort: 0, enabled: 1 }
  spaceDialogVisible.value = true
}

async function saveSpace() {
  if (!spaceForm.value.name?.trim()) {
    ElMessage.warning('请填写空间名称')
    return
  }
  await createKbSpace(spaceForm.value)
  spaceDialogVisible.value = false
  ElMessage.success('空间已创建')
  await fetchSpaces()
}

function onFileChange(file) {
  const rawFile = file.raw
  if (!rawFile) {
    selectedFile.value = null
    return
  }
  if (rawFile.size > MAX_UPLOAD_SIZE_BYTES) {
    selectedFile.value = null
    uploadRef.value?.clearFiles()
    ElMessage.warning(`单个知识库文件不能超过 ${MAX_UPLOAD_SIZE_MB}MB`)
    return
  }
  selectedFile.value = rawFile
}

function onFileRemove() {
  selectedFile.value = null
}

async function doUpload() {
  if (!canUpload.value) return
  uploading.value = true
  uploadProgress.value = 0
  try {
    const file = selectedFile.value
    const uploadId = createUploadId()
    const totalChunks = Math.ceil(file.size / KB_UPLOAD_CHUNK_SIZE)
    for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
      const start = chunkIndex * KB_UPLOAD_CHUNK_SIZE
      const end = Math.min(start + KB_UPLOAD_CHUNK_SIZE, file.size)
      await uploadKbDocumentChunk({
        uploadId,
        fileName: file.name,
        fileSize: file.size,
        chunkIndex,
        totalChunks,
        chunk: file.slice(start, end)
      })
      uploadProgress.value = Math.min(90, Math.round(((chunkIndex + 1) / totalChunks) * 90))
    }
    await completeKbDocumentUpload({
      spaceId: uploadForm.value.spaceId,
      uploadId,
      fileName: file.name,
      fileSize: file.size,
      totalChunks,
      title: uploadForm.value.title,
      parseMode: uploadForm.value.parseMode
    })
    uploadProgress.value = 100
    ElMessage.success('导入任务已创建，完成后会在消息中心提醒')
    uploadForm.value.title = ''
    uploadForm.value.parseMode = 'OCR'
    selectedFile.value = null
    uploadRef.value?.clearFiles()
    await fetchDocuments()
  } catch (error) {
    ElMessage.error(errorMessage(error, '上传失败，请检查文件或服务状态'))
  } finally {
    uploading.value = false
    uploadProgress.value = 0
  }
}

function createUploadId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID().replaceAll('-', '')
  }
  return `${Date.now()}_${Math.random().toString(36).slice(2, 12)}`
}

async function doImportDebugRecord() {
  debugImporting.value = true
  try {
    await importDebugRecord()
    ElMessage.success('Debug 修复记录导入任务已创建')
    await fetchSpaces()
    await fetchDocuments()
  } finally {
    debugImporting.value = false
  }
}

async function openChunks(row) {
  chunkDialogTitle.value = `${row.title} - 切片预览`
  chunkDialogVisible.value = true
  chunkLoading.value = true
  try {
    const res = await getKbDocumentChunks(row.id)
    chunks.value = res.data.data || []
  } finally {
    chunkLoading.value = false
  }
}

async function doReparse(row) {
  await reparseKbDocument(row.id)
  ElMessage.success('已提交重解析任务')
  await fetchDocuments()
}

async function doReindex(row) {
  await reindexKbDocument(row.id)
  ElMessage.success('已提交重建索引任务')
  await fetchDocuments()
}

async function doDelete(row) {
  await deleteKbDocument(row.id)
  ElMessage.success('已删除并移出检索')
  await fetchDocuments()
}

async function doRestore(row) {
  await restoreKbDocument(row.id)
  ElMessage.success('已恢复并提交索引任务')
  await fetchDocuments()
}

async function doPermanentDelete(row) {
  await permanentDeleteKbDocument(row.id)
  ElMessage.success('已永久删除')
  await fetchDocuments()
}

async function runQaTest() {
  if (!qaForm.value.message.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  qaLoading.value = true
  try {
    const payload = {
      message: qaForm.value.message,
      spaceId: selectedSpaceId.value,
      documentId: qaForm.value.documentId,
      topK: qaForm.value.topK
    }
    const res = await testKbQa(payload)
    qaResult.value = res.data.data || res.data
  } finally {
    qaLoading.value = false
  }
}

function spaceName(id) {
  return spaces.value.find(item => item.id === id)?.name || '-'
}

function statusLabel(row) {
  if (row.deleted === 1) return '已删除'
  const labels = {
    UPLOADED: '已上传',
    PARSING: '解析中',
    OCR: 'OCR 中',
    MINERU: 'MinerU',
    CHUNKING: '切片中',
    EMBEDDING: '生成向量',
    INDEXING: '索引中',
    READY: '就绪',
    FAILED: '失败',
    DISABLED: '禁用'
  }
  return labels[row.status] || row.status || '-'
}

function statusClass(row) {
  if (row.deleted === 1) return 'deleted'
  return String(row.status || '').toLowerCase()
}

function jobStatusLabel(row) {
  const labels = {
    PENDING: '等待处理',
    RUNNING: '已提交',
    PARSING: '解析中',
    OCR: 'OCR 识别',
    MINERU: 'MinerU 解析',
    CHUNKING: '切片中',
    EMBEDDING: '生成向量',
    INDEXING: '写入索引',
    DONE: '已完成',
    FAILED: '失败'
  }
  return labels[row.latestJobStatus] || row.latestJobStatus || '暂无任务'
}

function jobProgressStatus(row) {
  if (row.latestJobStatus === 'FAILED') return 'exception'
  if (row.latestJobStatus === 'DONE') return 'success'
  return undefined
}

function jobMessage(row) {
  return row.latestJobStatus === 'FAILED'
    ? row.latestJobErrorMessage || row.errorMessage || row.latestJobMessage || '任务失败'
    : row.latestJobMessage || '等待任务状态更新'
}

function isActiveJob(status) {
  return ['PENDING', 'RUNNING', 'PARSING', 'OCR', 'MINERU', 'CHUNKING', 'EMBEDDING', 'INDEXING'].includes(status)
}

function parseModeLabel(mode) {
  const labels = {
    FAST: '快速',
    OCR: 'OCR',
    MINERU: 'MinerU'
  }
  return labels[String(mode || 'OCR').toUpperCase()] || mode || 'OCR'
}

function errorMessage(error, fallback) {
  return error?.response?.data?.message || error?.message || fallback
}

function formatTime(value) {
  return value ? String(value).substring(0, 16) : '-'
}

function formatScore(value) {
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(3) : '-'
}
</script>

<style scoped>
.knowledge-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-hero,
.panel,
.space-strip {
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

.page-hero h2,
.panel-head h3 {
  color: #111827;
  margin: 4px 0 0;
}

.page-hero h2 {
  font-size: 26px;
  line-height: 1.2;
}

.page-hero p {
  color: #64748b;
  margin: 8px 0 0;
}

.hero-actions,
.table-tools,
.actions,
.qa-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.space-strip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding: 14px;
}

.space-chip {
  min-width: 210px;
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s;
}

.space-chip.active {
  border-color: #93c5fd;
  background: #eff6ff;
}

.space-mark {
  width: 10px;
  height: 38px;
  border-radius: 999px;
  flex-shrink: 0;
}

.space-mark.neutral {
  background: #64748b;
}

.space-chip strong,
.space-chip em {
  display: block;
}

.space-chip strong {
  color: #111827;
  font-size: 14px;
}

.space-chip em {
  color: #64748b;
  font-size: 12px;
  font-style: normal;
  margin-top: 4px;
  max-width: 160px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workspace-grid {
  display: grid;
  grid-template-columns: 0.9fr 1.3fr;
  gap: 18px;
}

.panel {
  padding: 20px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}

.compact-form {
  display: flex;
  flex-direction: column;
}

.upload-icon {
  color: #426fa6;
  font-size: 28px;
}

.upload-hint {
  margin: 8px 0 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.6;
}

.upload-progress {
  margin-top: 12px;
}

.job-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.job-progress-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #374151;
  font-size: 12px;
  font-weight: 700;
}

.job-progress-head em {
  color: #6b7280;
  font-style: normal;
  font-weight: 700;
}

.job-progress p {
  margin: 0;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.5;
}

.job-progress p.danger {
  color: #dc2626;
}

.muted {
  color: #9ca3af;
  font-size: 12px;
}

.upload-button {
  margin-top: 14px;
}

.doc-filter {
  width: 220px;
}

.qa-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.qa-actions {
  justify-content: space-between;
}

.top-k-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.top-k-label {
  color: #334155;
  font-size: 13px;
  font-weight: 700;
}

.top-k-help {
  color: #94a3b8;
  cursor: help;
  font-size: 15px;
}

.qa-result {
  border-top: 1px solid #e5e7eb;
  margin-top: 16px;
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-meta {
  display: flex;
  gap: 8px;
}

.result-meta span {
  color: #315987;
  background: #eff6ff;
  border-radius: 999px;
  font-size: 12px;
  padding: 4px 9px;
}

.hit-row,
.chunk-row {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}

.hit-row strong,
.chunk-row strong {
  color: #111827;
  font-size: 13px;
}

.hit-row p,
.chunk-row p {
  color: #64748b;
  font-size: 13px;
  line-height: 1.65;
  margin: 6px 0;
}

.hit-row span {
  color: #94a3b8;
  font-size: 12px;
}

.document-head {
  align-items: flex-start;
}

.doc-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.doc-title strong {
  color: #111827;
}

.doc-title span {
  color: #94a3b8;
  font-size: 12px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  font-size: 12px;
  padding: 4px 10px;
}

.status-badge.ready {
  color: #047857;
  background: #ecfdf5;
}

.status-badge.failed,
.status-badge.deleted {
  color: #dc2626;
  background: #fef2f2;
}

.status-badge.parsing,
.status-badge.indexing,
.status-badge.uploaded {
  color: #92400e;
  background: #fffbeb;
}

.status-badge.disabled {
  color: #64748b;
  background: #f1f5f9;
}

.action-btn {
  border: 1px solid transparent;
  border-radius: 6px;
  background: none;
  cursor: pointer;
  font-size: 12px;
  padding: 6px 9px;
}

.action-btn.preview { color: #047857; border-color: #d1fae5; }
.action-btn.edit { color: #315987; border-color: #dbeafe; }
.action-btn.restore { color: #7c3aed; border-color: #ede9fe; }
.action-btn.delete { color: #b45309; border-color: #fde68a; }
.action-btn.danger { color: #dc2626; border-color: #fee2e2; }

.action-btn:hover {
  background: #f8fafc;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 62vh;
  overflow: auto;
}

.chunk-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.chunk-head span,
.empty-line {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .page-hero,
  .document-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .space-chip {
    min-width: 180px;
  }
}
</style>
