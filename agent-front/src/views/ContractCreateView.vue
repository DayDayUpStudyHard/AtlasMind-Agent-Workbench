<template>
  <main class="intake-page">
    <router-link to="/contracts" class="back-link">返回合同工作台</router-link>

    <header class="intake-header">
      <div>
        <span class="docket-label">CONTRACT INTAKE</span>
        <h1>{{ phase === 'REVIEW' ? '确认合同信息' : '合同录入' }}</h1>
      </div>
      <div v-if="intake" class="intake-reference">
        <span>识别单</span>
        <strong>#{{ intake.id }}</strong>
      </div>
    </header>

    <section v-if="phase === 'INPUT'" class="input-workspace">
      <div class="source-entry">
        <div class="source-toolbar">
          <label class="file-name-field">
            <span>文件名称</span>
            <input v-model.trim="source.fileName" maxlength="512" placeholder="合同正文.txt" />
          </label>
          <input ref="fileInput" class="hidden-file" type="file" accept=".txt,.md,.pdf,.doc,.docx,text/plain,text/markdown,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" @change="readContractFile" />
          <button type="button" class="quiet-button" @click="fileInput?.click()">选择合同文件</button>
        </div>
        <div v-if="selectedFile" class="selected-file">
          <strong>{{ selectedFile.name }}</strong>
          <span>{{ fileModeLabel }} · {{ formatFileSize(selectedFile.size) }}</span>
        </div>
        <textarea
          v-model="source.contentText"
          class="source-textarea"
          maxlength="2000000"
          :placeholder="selectedFile && !isSelectedTextFile ? 'PDF / DOC / DOCX 将由后台文档管线解析，解析完成后进入结构化确认。' : '粘贴合同全文，或选择 TXT / MD / PDF / DOC / DOCX 合同文件'"
          autofocus
        ></textarea>
        <footer class="source-footer">
          <span>{{ source.contentText.length.toLocaleString() }} / 2,000,000</span>
          <p v-if="pageError" class="inline-error" role="alert">{{ pageError }}</p>
          <button class="primary-button identify-button" :disabled="!canIdentify" @click="startIntake">
            {{ submitting ? '正在提交' : '识别合同' }}
          </button>
        </footer>
      </div>

      <aside class="intake-docket" aria-label="识别阶段">
        <div class="docket-rule"></div>
        <div v-for="step in extractionSteps" :key="step.key" class="docket-step">
          <span>{{ step.index }}</span>
          <div><strong>{{ step.title }}</strong><small>{{ step.note }}</small></div>
        </div>
      </aside>
    </section>

    <section v-else-if="phase === 'PROCESSING'" class="processing-state">
      <div class="document-pulse" aria-hidden="true">
        <i></i><i></i><i></i><i></i>
      </div>
      <span class="processing-kicker">{{ intakeStatusLabel }}</span>
      <h2>正在读取合同事实</h2>
      <p>{{ intake?.fileName }}</p>
      <p class="processing-action">{{ intakePipelineAction }}</p>
      <div class="progress-track"><i :style="{ width: processingProgress + '%' }"></i></div>
      <span class="processing-progress-label">{{ processingProgress }}%</span>
      <router-link to="/contracts" class="processing-back">返回合同工作台，后台继续处理</router-link>
    </section>

    <section v-else-if="phase === 'FAILED'" class="failed-state">
      <span>识别未完成</span>
      <h2>{{ intake?.errorMessage || '合同识别服务暂时不可用' }}</h2>
      <div>
        <button class="quiet-button" @click="resetInput">返回正文</button>
        <button class="primary-button" :disabled="submitting" @click="retryIntake">重新识别</button>
      </div>
    </section>

    <section v-else class="review-workspace">
      <article class="evidence-pane">
        <header class="pane-header">
          <div><span>原文证据</span><strong>{{ intake.fileName }}</strong></div>
          <button class="quiet-button compact" @click="showFullText = !showFullText">
            {{ showFullText ? '聚焦引用' : '查看全文' }}
          </button>
        </header>

        <pre class="source-preview"><template v-for="(part, index) in previewParts" :key="index"><mark v-if="part.highlight">{{ part.text }}</mark><span v-else>{{ part.text }}</span></template></pre>

        <footer class="evidence-footer">
          <span v-if="activeCitation">字符 {{ activeCitation.startOffset }}-{{ activeCitation.endOffset }}</span>
          <span v-else>当前字段没有可验证引用</span>
        </footer>
      </article>

      <form class="confirmation-pane" @submit.prevent="confirmIntake">
        <header class="pane-header confirmation-head">
          <div>
            <span>结构化结果</span>
            <strong>{{ reviewSummary }}</strong>
          </div>
          <button type="button" class="quiet-button compact" :disabled="submitting" @click="retryIntake">重新识别</button>
        </header>

        <div v-if="validated.warnings?.length" class="warning-strip">
          <p v-for="warning in validated.warnings" :key="warning">{{ warning }}</p>
        </div>

        <div class="field-stack">
          <label class="review-field" :class="fieldClass('contractTitle')" @click="activateField('contractTitle')">
            <span>合同标题 <FieldState :label="fieldStateLabel('contractTitle')" /></span>
            <input v-model.trim="form.title" maxlength="512" @input="markEdited('contractTitle')" />
            <button v-if="fieldCitation('contractTitle')" type="button" class="citation-button" @click.stop="activateField('contractTitle')">查看原文</button>
          </label>

          <label class="review-field" :class="fieldClass('contractType')" @click="activateField('contractType')">
            <span>合同类型 <FieldState :label="fieldStateLabel('contractType')" /></span>
            <select v-model="form.contractType" @change="markEdited('contractType')">
              <option value="SERVICE_PROCUREMENT">服务采购</option>
              <option value="GOODS_PURCHASE">货物采购</option>
              <option value="NDA">保密协议</option>
              <option value="OTHER">其他</option>
            </select>
          </label>

          <div class="party-block">
            <label class="review-field" :class="fieldClass('partyA')" @click="activateField('partyA')">
              <span>甲方 <FieldState :label="fieldStateLabel('partyA')" /></span>
              <input v-model.trim="form.partyA" maxlength="256" @input="markEdited('partyA')" />
              <button v-if="fieldCitation('partyA')" type="button" class="citation-button" @click.stop="activateField('partyA')">查看原文</button>
            </label>
            <label class="review-field" :class="fieldClass('partyB')" @click="activateField('partyB')">
              <span>乙方 <FieldState :label="fieldStateLabel('partyB')" /></span>
              <input v-model.trim="form.partyB" maxlength="256" @input="markEdited('partyB')" />
              <button v-if="fieldCitation('partyB')" type="button" class="citation-button" @click.stop="activateField('partyB')">查看原文</button>
            </label>
          </div>

          <fieldset class="our-side-field">
            <legend>确认我方主体 *</legend>
            <div class="side-segment">
              <button type="button" :class="{ active: form.ourSide === 'A' }" @click="form.ourSide = 'A'">甲方是我方</button>
              <button type="button" :class="{ active: form.ourSide === 'B' }" @click="form.ourSide = 'B'">乙方是我方</button>
            </div>
          </fieldset>

          <div class="field-pair">
            <label class="review-field" :class="fieldClass('amount')" @click="activateField('amount')">
              <span>合同金额 <FieldState :label="fieldStateLabel('amount')" /></span>
              <input v-model="form.amount" type="number" min="0" step="0.01" @input="markEdited('amount')" />
            </label>
            <label class="review-field" :class="fieldClass('currency')" @click="activateField('currency')">
              <span>币种 <FieldState :label="fieldStateLabel('currency')" /></span>
              <select v-model="form.currency" @change="markEdited('currency')">
                <option value="CNY">CNY</option><option value="USD">USD</option><option value="EUR">EUR</option>
                <option value="GBP">GBP</option><option value="JPY">JPY</option><option value="HKD">HKD</option>
              </select>
            </label>
          </div>

          <div class="field-pair">
            <label class="review-field" :class="fieldClass('signedDate')" @click="activateField('signedDate')">
              <span>签订日期 <FieldState :label="fieldStateLabel('signedDate')" /></span>
              <input v-model="form.signedDate" type="date" @input="markEdited('signedDate')" />
            </label>
            <label class="review-field" :class="fieldClass('effectiveDate')" @click="activateField('effectiveDate')">
              <span>生效日期 <FieldState :label="fieldStateLabel('effectiveDate')" /></span>
              <input v-model="form.effectiveDate" type="date" @input="markEdited('effectiveDate')" />
            </label>
          </div>

          <div class="field-pair">
            <label class="review-field" :class="fieldClass('expiryDate')" @click="activateField('expiryDate')">
              <span>到期日期 <FieldState :label="fieldStateLabel('expiryDate')" /></span>
              <input v-model="form.expiryDate" type="date" @input="markEdited('expiryDate')" />
            </label>
          </div>
        </div>

        <div class="business-fields">
          <span class="group-label">业务补充</span>
          <div class="field-pair">
            <label><span>所属部门</span><input v-model.trim="form.department" maxlength="128" placeholder="例如：采购部" /></label>
            <label><span>优先级</span><select v-model="form.priority"><option value="NORMAL">普通</option><option value="HIGH">高</option><option value="CRITICAL">紧急</option><option value="LOW">低</option></select></label>
          </div>
          <label><span>审查背景</span><textarea v-model.trim="form.description" rows="3" maxlength="2000"></textarea></label>
        </div>

        <p v-if="pageError" class="confirm-error" role="alert">{{ pageError }}</p>
        <footer class="confirm-actions">
          <button type="button" class="quiet-button" :disabled="submitting" @click="resetInput">更换合同</button>
          <button type="submit" class="primary-button" :disabled="!canConfirm">
            {{ submitting ? '正在创建' : '确认并创建案件' }}
          </button>
        </footer>
      </form>
    </section>
  </main>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api/index.js'

const FieldState = defineComponent({
  props: { label: { type: String, required: true } },
  setup(props) { return () => h('small', { class: ['field-state', stateTone(props.label)] }, props.label) },
})

const router = useRouter()
const message = useMessage()
const fileInput = ref(null)
const phase = ref('INPUT')
const submitting = ref(false)
const intake = ref(null)
const selectedFile = ref(null)
const pageError = ref('')
const activeField = ref('contractTitle')
const showFullText = ref(false)
const editedFields = ref(new Set())
let pollTimer = null

const source = reactive({ fileName: '', contentText: '' })
const form = reactive({
  title: '', contractType: 'OTHER', partyA: '', partyB: '', ourSide: '',
  amount: '', currency: 'CNY', signedDate: '', effectiveDate: '', expiryDate: '',
  department: '', priority: 'NORMAL', description: '',
})

const extractionSteps = [
  { key:'parse', index:'A', title:'正文解析', note:'形成可定位文本' },
  { key:'extract', index:'B', title:'字段提取', note:'生成结构化候选' },
  { key:'verify', index:'C', title:'引用核验', note:'只保留原文证据' },
]

const isSelectedTextFile = computed(() => {
  const file = selectedFile.value
  if (!file) return false
  return /\.(txt|md|markdown)$/i.test(file.name) || /^text\//i.test(file.type || '')
})
const fileModeLabel = computed(() => isSelectedTextFile.value ? '文本合同' : '文件解析')
const canIdentify = computed(() => !submitting.value && (
  source.contentText.trim().length > 0 || Boolean(selectedFile.value && !isSelectedTextFile.value)
))
const validated = computed(() => intake.value?.validated || {})
const validatedFields = computed(() => validated.value.fields || {})
const intakeStatusLabel = computed(() => {
  const stage = String(intake.value?.pipelineStage || '').toUpperCase()
  if (stage === 'PDF_RECOGNITION_OPTIMIZATION') return '正在优化 PDF 文字识别'
  if (stage === 'DOC_CONVERSION') return '正在整理 Word 文档'
  if (stage === 'DOCX_PARSING') return '正在读取 Word 文档'
  if (stage === 'CLAUSE_SPLITTING' || stage === 'CLAUSE_PERSISTING') return '正在识别合同条款'
  if (stage === 'TIMELINE_EXTRACTING') return '正在提取合同时间节点'
  if (stage === 'LIFECYCLE_EXTRACTING') return '正在识别合同结束条件'
  if (stage === 'EMBEDDING' || stage === 'INDEXING') return '正在建立合同检索能力'
  if (intake.value?.status === 'FILE_PARSING') return '正在解析合同文件'
  if (intake.value?.status === 'EXTRACTING') return '正在结构化提取'
  return '等待解析服务'
})
const processingProgress = computed(() => {
  const value = Number(intake.value?.pipelineProgress)
  if (Number.isFinite(value)) return Math.max(0, Math.min(100, value))
  if (intake.value?.status === 'FILE_PARSING') return 38
  return intake.value?.status === 'EXTRACTING' ? 68 : 24
})
const intakePipelineAction = computed(() => {
  if (intake.value?.pipelineAction) return intake.value.pipelineAction
  const labels = {
    UPLOADED: '合同文件已提交，等待后台处理',
    DOCUMENT_START: '正在读取合同文件',
    PDF_PARSING: '正在读取 PDF 文字',
    PDF_RECOGNITION_OPTIMIZATION: '正在优化 PDF 文字识别',
    DOC_CONVERSION: '正在整理 Word 文档',
    DOCX_PARSING: '正在读取 Word 文档',
    CLAUSE_SPLITTING: '正在识别合同条款',
    CLAUSE_PERSISTING: '正在保存条款证据',
    TIMELINE_EXTRACTING: '正在提取合同时间节点',
    LIFECYCLE_EXTRACTING: '正在识别合同结束条件',
    EMBEDDING: '正在建立合同语义检索',
    INDEXING: '正在整理合同检索索引',
  }
  return labels[String(intake.value?.pipelineStage || '').toUpperCase()] || '后台正在处理合同文件'
})
const reviewSummary = computed(() => {
  const count = validated.value.needsConfirmation?.length || 0
  return count ? `${count} 项需要确认` : '字段已完成核验'
})
const canConfirm = computed(() => !submitting.value && Boolean(
  form.title.trim() && form.contractType && form.partyA.trim() && form.partyB.trim() && form.ourSide
))

const activeCitation = computed(() => fieldCitation(activeField.value))
const previewParts = computed(() => {
  const text = intake.value?.contentText || ''
  const citation = activeCitation.value
  let rangeStart = 0
  let rangeEnd = text.length
  if (!showFullText.value) {
    const anchor = citation?.startOffset ?? 0
    rangeStart = Math.max(0, anchor - 700)
    rangeEnd = Math.min(text.length, (citation?.endOffset ?? 0) + 1400)
    if (!citation) rangeEnd = Math.min(text.length, 4500)
  }
  if (!citation || citation.startOffset < rangeStart || citation.endOffset > rangeEnd) {
    return [{ text: text.slice(rangeStart, rangeEnd), highlight: false }]
  }
  return [
    { text: text.slice(rangeStart, citation.startOffset), highlight: false },
    { text: text.slice(citation.startOffset, citation.endOffset), highlight: true },
    { text: text.slice(citation.endOffset, rangeEnd), highlight: false },
  ]
})

async function readContractFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  selectedFile.value = file
  source.fileName = file.name
  if (isSelectedTextFile.value) {
    source.contentText = await file.text()
  } else {
    source.contentText = ''
  }
  event.target.value = ''
}

async function startIntake() {
  if (!canIdentify.value) return
  submitting.value = true
  pageError.value = ''
  try {
    let response
    if (selectedFile.value && !isSelectedTextFile.value) {
      const formData = new FormData()
      formData.append('file', selectedFile.value)
      response = await api.post('/api/workspace/contracts/intakes/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 60000,
      })
    } else {
      response = await api.post('/api/workspace/contracts/intakes', {
        fileName: source.fileName.trim() || '合同正文.txt',
        contentText: source.contentText,
      })
    }
    intake.value = response.data.data
    phase.value = 'PROCESSING'
    schedulePoll(300)
  } catch (error) {
    pageError.value = apiErrorMessage(error)
  } finally {
    submitting.value = false
  }
}

function schedulePoll(delay = 800) {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(loadIntake, delay)
}

async function loadIntake() {
  if (!intake.value?.id) return
  try {
    const response = await api.get(`/api/workspace/contracts/intakes/${intake.value.id}`)
    intake.value = response.data.data
    if (intake.value.status === 'NEEDS_CONFIRMATION') {
      hydrateForm()
      phase.value = 'REVIEW'
    } else if (intake.value.status === 'FAILED') {
      phase.value = 'FAILED'
    } else {
      phase.value = 'PROCESSING'
      schedulePoll()
    }
  } catch (error) {
    pageError.value = apiErrorMessage(error)
    phase.value = 'FAILED'
  }
}

function hydrateForm() {
  const fields = intake.value?.validated?.fields || {}
  form.title = fieldValue(fields.contractTitle) || source.fileName.replace(/\.(txt|md|markdown|pdf|docx?)$/i, '') || ''
  form.contractType = fieldValue(fields.contractType) || 'OTHER'
  form.partyA = fieldValue(fields.partyA) || ''
  form.partyB = fieldValue(fields.partyB) || ''
  form.amount = fieldValue(fields.amount) ?? ''
  form.currency = fieldValue(fields.currency) || 'CNY'
  form.signedDate = fieldValue(fields.signedDate) || ''
  form.effectiveDate = fieldValue(fields.effectiveDate) || ''
  form.expiryDate = fieldValue(fields.expiryDate) || ''
  form.department = fieldValue(fields.department) || ''
  activeField.value = fields.contractTitle?.citations?.length ? 'contractTitle' : 'partyA'
}

async function retryIntake() {
  if (!intake.value?.id || submitting.value) return
  submitting.value = true
  pageError.value = ''
  try {
    const response = await api.post(`/api/workspace/contracts/intakes/${intake.value.id}/retry`)
    intake.value = response.data.data
    phase.value = 'PROCESSING'
    schedulePoll(300)
  } catch (error) {
    pageError.value = apiErrorMessage(error)
    phase.value = 'FAILED'
  } finally {
    submitting.value = false
  }
}

async function confirmIntake() {
  if (!canConfirm.value) return
  if (form.effectiveDate && form.expiryDate && form.expiryDate < form.effectiveDate) {
    pageError.value = '到期日期不能早于生效日期'
    return
  }
  submitting.value = true
  pageError.value = ''
  try {
    const ourEntity = form.ourSide === 'A' ? form.partyA : form.partyB
    const counterparty = form.ourSide === 'A' ? form.partyB : form.partyA
    const response = await api.post(`/api/workspace/contracts/intakes/${intake.value.id}/confirm`, {
      title: form.title.trim(), contractType: form.contractType,
      ourEntity: ourEntity.trim(), counterparty: counterparty.trim(),
      ourSide: form.ourSide,
      amount: form.amount === '' ? null : Number(form.amount), currency: form.currency,
      signedDate: form.signedDate || null,
      effectiveDate: form.effectiveDate || null, expiryDate: form.expiryDate || null,
      department: form.department.trim(), priority: form.priority,
      description: form.description.trim(),
    })
    const caseId = response.data.data?.case?.id
    if (!caseId) throw new Error('服务未返回合同案件 ID')
    message.success('合同案件已创建')
    await router.replace(`/contracts/${caseId}`)
  } catch (error) {
    pageError.value = apiErrorMessage(error)
  } finally {
    submitting.value = false
  }
}

function resetInput() {
  clearTimeout(pollTimer)
  phase.value = 'INPUT'
  intake.value = null
  selectedFile.value = null
  pageError.value = ''
  showFullText.value = false
  editedFields.value = new Set()
}

function fieldValue(field) { return field?.value ?? null }
function fieldCitation(key) { return validatedFields.value[key]?.citations?.[0] || null }
function activateField(key) { activeField.value = key; showFullText.value = false }
function markEdited(key) { editedFields.value = new Set([...editedFields.value, key]) }
function fieldStateLabel(key) {
  if (editedFields.value.has(key)) return '已修改'
  const field = validatedFields.value[key]
  if (!field?.value) return '缺失'
  return Number(field.confidence || 0) >= 0.85 ? '已识别' : '需确认'
}
function fieldClass(key) { return { active: activeField.value === key, attention: fieldStateLabel(key) === '需确认' || fieldStateLabel(key) === '缺失' } }
function stateTone(label) { return label === '已识别' ? 'ok' : label === '已修改' ? 'edited' : 'warn' }
function apiErrorMessage(error) {
  if (error.response?.data?.message) return error.response.data.message
  if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (!error.response) return error.message || '无法连接合同服务'
  return '合同录入失败'
}

function formatFileSize(size) {
  const value = Number(size) || 0
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

onBeforeUnmount(() => clearTimeout(pollTimer))
</script>

<style scoped>
.intake-page{width:min(1180px,100%);margin:0 auto;padding:4px 0 52px;color:var(--atlas-text)}
.back-link{display:inline-flex;margin-bottom:22px;color:var(--atlas-primary);font-size:12px;font-weight:800;text-decoration:none}
.intake-header{display:flex;align-items:end;justify-content:space-between;padding-bottom:20px;border-bottom:1px solid var(--atlas-border)}
.docket-label{display:block;margin-bottom:7px;color:var(--atlas-primary);font-size:10px;font-weight:900}
.intake-header h1{margin:0;font-family:var(--atlas-font-display);font-size:34px;line-height:1.1;letter-spacing:0}
.intake-reference{text-align:right}.intake-reference span{display:block;color:var(--atlas-subtle);font-size:9px;font-weight:800}.intake-reference strong{font-family:var(--atlas-font-display);font-size:20px}
.input-workspace{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:38px;padding-top:30px}
.source-entry{min-width:0;background:var(--atlas-surface);border:1px solid var(--atlas-border)}
.source-toolbar{display:flex;align-items:end;gap:12px;padding:14px;border-bottom:1px solid var(--atlas-border)}
.file-name-field{display:flex;min-width:0;flex:1;flex-direction:column;gap:5px}.file-name-field span{color:var(--atlas-muted);font-size:9px;font-weight:800}.file-name-field input{height:34px;padding:0 9px;border:1px solid var(--atlas-border);border-radius:3px;background:var(--atlas-bg);color:var(--atlas-text)}
.selected-file{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;border-bottom:1px solid var(--atlas-border);background:var(--atlas-bg);font-size:11px}.selected-file strong{min-width:0;color:var(--atlas-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.selected-file span{flex:0 0 auto;color:var(--atlas-muted);font-size:10px;font-weight:800}
.hidden-file{display:none}.source-textarea{display:block;width:100%;height:480px;padding:24px;border:0;outline:0;resize:vertical;background:var(--atlas-surface);color:var(--atlas-text);font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;line-height:1.8}
.source-footer{display:flex;align-items:center;gap:14px;min-height:60px;padding:10px 14px;border-top:1px solid var(--atlas-border);color:var(--atlas-subtle);font-size:10px}.source-footer>span{white-space:nowrap}.inline-error{flex:1;color:#a9362f;font-size:11px}.identify-button{margin-left:auto;min-width:138px}
.intake-docket{position:relative;align-self:start;padding:18px 0 0 24px}.docket-rule{position:absolute;top:22px;bottom:20px;left:9px;width:1px;background:var(--atlas-border-strong)}
.docket-step{position:relative;display:grid;grid-template-columns:28px minmax(0,1fr);gap:10px;margin-bottom:28px}.docket-step>span{display:grid;place-items:center;width:20px;height:20px;margin-left:-24px;border:1px solid var(--atlas-primary);background:var(--atlas-bg);color:var(--atlas-primary);font-family:monospace;font-size:9px;font-weight:900}.docket-step strong{display:block;font-size:12px}.docket-step small{display:block;margin-top:4px;color:var(--atlas-muted);font-size:10px}
.processing-state,.failed-state{display:flex;min-height:540px;flex-direction:column;align-items:center;justify-content:center;text-align:center}.processing-kicker,.failed-state>span{color:var(--atlas-primary);font-size:10px;font-weight:900}.processing-state h2,.failed-state h2{max-width:620px;margin:10px 0 8px;font-family:var(--atlas-font-display);font-size:28px;letter-spacing:0}.processing-state p{color:var(--atlas-muted);font-size:12px}.processing-state .processing-action{margin-top:4px;color:var(--atlas-primary);font-weight:800}.processing-progress-label{margin-top:8px;color:var(--atlas-primary);font-family:monospace;font-size:11px;font-weight:900}
.document-pulse{display:grid;width:70px;height:86px;grid-template-rows:repeat(4,1fr);gap:7px;margin-bottom:24px;padding:18px 14px;border:1px solid var(--atlas-border-strong);background:var(--atlas-surface)}.document-pulse i{height:3px;background:var(--atlas-border);animation:scan 1.4s ease-in-out infinite}.document-pulse i:nth-child(2){animation-delay:.12s}.document-pulse i:nth-child(3){animation-delay:.24s}.document-pulse i:nth-child(4){animation-delay:.36s}
.progress-track{width:min(360px,70vw);height:3px;margin-top:24px;background:var(--atlas-border)}.progress-track i{display:block;height:100%;background:var(--atlas-primary);transition:width .4s ease}.processing-back{margin-top:24px;color:var(--atlas-primary);font-size:12px;text-decoration:none}.processing-back:hover{text-decoration:underline}.failed-state>div{display:flex;gap:10px;margin-top:20px}
.review-workspace{display:grid;grid-template-columns:minmax(0,1fr) 430px;gap:0;margin-top:28px;border:1px solid var(--atlas-border);background:var(--atlas-surface)}
.evidence-pane{display:flex;min-width:0;min-height:720px;flex-direction:column;border-right:1px solid var(--atlas-border)}.pane-header{display:flex;min-height:66px;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--atlas-border)}.pane-header span{display:block;color:var(--atlas-subtle);font-size:9px;font-weight:900}.pane-header strong{display:block;margin-top:4px;font-size:12px}.compact{min-height:30px!important;padding:0 10px!important;font-size:10px!important}
.source-preview{flex:1;overflow:auto;max-height:760px;margin:0;padding:24px;white-space:pre-wrap;word-break:break-word;background:var(--atlas-bg);color:var(--atlas-text);font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;line-height:1.85}.source-preview mark{padding:2px 0;background:#fff0a8;color:#392f18}.evidence-footer{display:flex;min-height:42px;align-items:center;padding:0 16px;border-top:1px solid var(--atlas-border);color:var(--atlas-subtle);font-family:monospace;font-size:9px}
.confirmation-pane{min-width:0}.confirmation-head{position:sticky;top:0;z-index:2;background:var(--atlas-surface)}.warning-strip{padding:10px 16px;border-bottom:1px solid #e1c894;background:#fff9e8;color:#765922;font-size:10px}.warning-strip p+p{margin-top:4px}
.field-stack{padding:16px}.review-field{position:relative;display:flex;flex-direction:column;gap:6px;margin-bottom:13px;padding:10px;border:1px solid transparent;background:var(--atlas-bg);cursor:text}.review-field.active{border-color:var(--atlas-primary)}.review-field.attention:not(.active){border-color:#dec98d}.review-field>span,.business-fields label>span{display:flex;align-items:center;justify-content:space-between;color:var(--atlas-muted);font-size:9px;font-weight:900}.review-field input,.review-field select,.business-fields input,.business-fields select,.business-fields textarea{width:100%;box-sizing:border-box;border:0;border-bottom:1px solid var(--atlas-border-strong);border-radius:0;outline:0;background:transparent;color:var(--atlas-text);font:inherit;font-size:12px}.review-field input,.review-field select,.business-fields input,.business-fields select{height:32px}.business-fields textarea{padding:8px 0;resize:vertical}.review-field input:focus,.review-field select:focus,.business-fields input:focus,.business-fields select:focus,.business-fields textarea:focus{border-bottom-color:var(--atlas-primary)}
.field-state{padding:2px 5px;border-radius:2px;font-size:8px!important}.field-state.ok{color:#36714b;background:#e8f4ec}.field-state.warn{color:#8a6429;background:#fff2cc}.field-state.edited{color:var(--atlas-primary);background:var(--atlas-surface-soft)}.citation-button{align-self:flex-start;border:0;background:transparent;color:var(--atlas-primary);font-size:9px;font-weight:800;cursor:pointer}.party-block,.field-pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.our-side-field{margin:4px 0 16px;padding:0;border:0}.our-side-field legend{margin-bottom:7px;color:var(--atlas-muted);font-size:9px;font-weight:900}.side-segment{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--atlas-border)}.side-segment button{height:34px;border:0;background:var(--atlas-surface);color:var(--atlas-muted);font-size:10px;font-weight:800;cursor:pointer}.side-segment button+button{border-left:1px solid var(--atlas-border)}.side-segment button.active{background:var(--atlas-primary);color:#fff}
.business-fields{padding:18px 16px;border-top:1px solid var(--atlas-border);background:var(--atlas-bg)}.group-label{display:block;margin-bottom:13px;color:var(--atlas-primary);font-size:9px;font-weight:900}.business-fields label{display:flex;flex-direction:column;gap:6px;margin-bottom:12px}.confirm-error{margin:12px 16px;padding:9px 10px;border-left:3px solid #c7473d;background:rgba(199,71,61,.08);color:#a9362f;font-size:10px}.confirm-actions{position:sticky;bottom:0;display:flex;justify-content:flex-end;gap:9px;padding:14px 16px;border-top:1px solid var(--atlas-border);background:var(--atlas-surface)}
.quiet-button,.primary-button{display:inline-flex;align-items:center;justify-content:center;min-height:38px;padding:0 14px;border-radius:4px;font-size:11px;font-weight:800;cursor:pointer}.quiet-button{border:1px solid var(--atlas-border);background:var(--atlas-surface);color:var(--atlas-muted)}.quiet-button:hover:not(:disabled){border-color:var(--atlas-primary);color:var(--atlas-primary)}.primary-button{border:1px solid var(--atlas-primary);background:var(--atlas-primary);color:#fff}.primary-button:hover:not(:disabled){background:var(--atlas-primary-dark)}button:disabled{cursor:not-allowed;opacity:.55}
@keyframes scan{0%,100%{transform:scaleX(.45);transform-origin:left;opacity:.45}50%{transform:scaleX(1);opacity:1}}
@media (prefers-reduced-motion:reduce){.document-pulse i{animation:none}}
@media (max-width:900px){.input-workspace{grid-template-columns:1fr}.intake-docket{display:none}.review-workspace{grid-template-columns:1fr}.evidence-pane{min-height:430px;border-right:0;border-bottom:1px solid var(--atlas-border)}.source-preview{max-height:440px}}
@media (max-width:600px){.intake-page{padding:0 0 36px}.intake-header h1{font-size:28px}.source-toolbar{align-items:stretch;flex-direction:column}.source-textarea{height:420px;padding:16px}.source-footer{align-items:stretch;flex-direction:column}.identify-button{margin-left:0}.party-block,.field-pair{grid-template-columns:1fr}.review-workspace{margin-right:-8px;margin-left:-8px}.confirmation-head{position:static}.side-segment button,.quiet-button,.primary-button{min-height:44px}.confirm-actions{padding-right:84px}}
</style>
