<template>
  <div class="portfolio-page">
    <header class="portfolio-header">
      <div>
        <h1>合同工作台</h1>
        <p>企业合同全生命周期管理 — 发起、审查、审批、履约</p>
      </div>
      <button class="primary-button" @click="$router.push('/contracts/new')">发起新合同</button>
    </header>

    <!-- KPI row -->
    <section class="kpi-row">
      <div class="kpi-card"><strong>{{ portfolio.total || 0 }}</strong><span>全部合同</span></div>
      <div class="kpi-card warn"><strong>{{ portfolio.pendingReview || 0 }}</strong><span>待审查</span></div>
      <div class="kpi-card warn"><strong>{{ portfolio.pendingApproval || 0 }}</strong><span>待审批</span></div>
      <div class="kpi-card"><strong>{{ portfolio.inFulfillment || 0 }}</strong><span>履约中</span></div>
      <div class="kpi-card danger"><strong>{{ portfolio.expiringSoon || 0 }}</strong><span>30天内到期</span></div>
      <div class="kpi-card danger"><strong>{{ portfolio.overdue || 0 }}</strong><span>已逾期</span></div>
      <div class="kpi-card"><strong>{{ portfolio.obligationsTotal || 0 }}</strong><span>履约义务</span></div>
      <div class="kpi-card danger"><strong>{{ portfolio.obligationsOverdue || 0 }}</strong><span>已逾期义务</span></div>
      <div class="kpi-card warn"><strong>{{ portfolio.obligationsDueSoon || 0 }}</strong><span>7天内到期义务</span></div>
      <div class="kpi-card"><strong>{{ portfolio.totalAmount ? (portfolio.totalAmount/10000).toFixed(0)+'万' : '0' }}</strong><span>合同总额</span></div>
      <div class="kpi-card"><strong>{{ portfolio.activeRuns || 0 }}</strong><span>运行中任务</span></div>
      <div class="kpi-card warn"><strong>{{ portfolio.openFindings || 0 }}</strong><span>未解决发现</span></div>
    </section>

    <!-- Quick actions -->
    <section class="quick-actions">
      <button class="action-btn" @click="$router.push('/contracts/new')">
        <span class="action-icon">+</span>
        <strong>发起新合同</strong>
        <small>填写交易信息，Agent 判断类型并生成材料清单</small>
      </button>
      <button :class="['action-btn', { active: activeQueue === 'REVIEW' }]" @click="openQueue('REVIEW')">
        <span class="action-icon">⌕</span>
        <strong>审查待签合同</strong>
        <small>{{ queueCount('review') }} 项：待解析、待审查、待复核</small>
      </button>
      <button :class="['action-btn', { active: activeQueue === 'APPROVAL' }]" @click="openQueue('APPROVAL')">
        <span class="action-icon">✎</span>
        <strong>处理待办与审批</strong>
        <small>{{ queueCount('approval') }} 项：开放发现、待审批动作、草稿报告</small>
      </button>
      <button :class="['action-btn', { active: activeQueue === 'FULFILLMENT' }]" @click="openQueue('FULFILLMENT')">
        <span class="action-icon">□</span>
        <strong>查看履约和到期</strong>
        <small>{{ queueCount('fulfillment') }} 项：义务、逾期、续签预警</small>
      </button>
    </section>

    <section class="queue-panel" v-if="activeQueue">
      <div class="case-list-header">
        <h2>{{ queueTitle(activeQueue) }}</h2>
        <button class="quiet-button" @click="activeQueue = ''; loadCases()">查看全部合同</button>
      </div>
      <template v-if="queueItems.length">
        <article v-for="item in queueItems" :key="item.itemType + '-' + item.itemId" class="queue-item" @click="router.push(`/contracts/${item.caseId}`)">
          <span>{{ itemTypeLabel(item.itemType) }}</span>
          <div>
            <strong>{{ item.title }}</strong>
            <small>{{ item.caseKey }} · {{ item.caseTitle }}</small>
          </div>
          <em v-if="item.severity">{{ severityLabel(item.severity) }}</em>
          <em v-else-if="item.dueDate">{{ item.dueDate }}</em>
        </article>
      </template>
      <div v-else class="blank-state compact">当前队列没有待处理事项。</div>
    </section>

    <!-- Case list -->
    <section class="case-list" v-if="cases.length">
      <div class="case-list-header">
        <h2>合同案件</h2>
        <select v-model="statusFilter" @change="loadCases">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </div>
      <article v-for="c in cases" :key="c.id" class="case-card" @click="$router.push(`/contracts/${c.id}`)">
        <div class="case-topline">
          <span class="case-key">{{ c.caseKey }}</span>
          <span class="case-status" :class="statusClass(c.status)">{{ statusLabel(c.status) }}</span>
          <small>{{ formatDate(c.createTime) }}</small>
        </div>
        <h3>{{ c.title }}</h3>
        <div class="case-meta">
          <span v-if="c.counterparty">{{ c.counterparty }}</span>
          <span v-if="c.amount">{{ c.amount }} {{ c.currency || 'CNY' }}</span>
          <span v-if="c.department">{{ c.department }}</span>
          <span>{{ contractTypeLabel(c.contractType) }}</span>
        </div>
        <div v-if="timelineNodes(c).length" class="case-timeline" @click.stop>
          <div class="timeline-head">
            <strong>时间节点</strong>
            <small>已识别 {{ timelineNodes(c).length }} 个</small>
          </div>
          <div class="timeline-track">
            <div
              v-for="node in visibleTimelineNodes(c)"
              :key="timelineKey(node)"
              class="timeline-node"
              :class="timelineStatusClass(node)"
              :title="timelineTooltip(node)"
            >
              <i></i>
              <div>
                <strong>{{ node.label }}</strong>
                <span>{{ timelineDateLabel(node) }}</span>
                <small>{{ timelineSourceLabel(node) }}</small>
              </div>
            </div>
            <div v-if="timelineNodes(c).length > 5" class="timeline-more">
              +{{ timelineNodes(c).length - 5 }}
            </div>
          </div>
        </div>
        <div v-else class="case-timeline empty" @click.stop>
          <div class="timeline-head">
            <strong>时间节点</strong>
            <small>{{ timelineEmptyLabel(c) }}</small>
          </div>
        </div>
      </article>
    </section>
    <div v-else class="blank-state">暂无合同案件。点击"发起新合同"开始。</div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api/index.js'

const router = useRouter()
const message = useMessage()
const portfolio = ref({})
const cases = ref([])
const statusFilter = ref('')
const activeQueue = ref('')
const queueItems = ref([])

const statuses = [
  { value: 'DRAFT', label: '草稿' },
  { value: 'READY_FOR_REVIEW', label: '待审查' },
  { value: 'REVIEWING', label: '审查中' },
  { value: 'PENDING_APPROVAL', label: '待审批' },
  { value: 'APPROVED', label: '已批准' },
  { value: 'SIGNED', label: '已签署' },
  { value: 'IN_FULFILLMENT', label: '履约中' },
  { value: 'EXPIRED', label: '已到期' },
  { value: 'TERMINATED', label: '已终止' },
]

onMounted(async () => {
  try {
    const p = await api.get('/api/workspace/contracts/portfolio')
    portfolio.value = p.data.data
    await loadCases()
  } catch (e) { message.error('加载合同组合失败') }
})

async function loadCases() {
  try {
    const params = statusFilter.value ? { status: statusFilter.value } : {}
    const r = await api.get('/api/workspace/contracts', { params })
    cases.value = r.data.data || []
  } catch {}
}

function filterStatus(s) { activeQueue.value = ''; statusFilter.value = s; loadCases() }

async function openQueue(type) {
  activeQueue.value = type
  statusFilter.value = ''
  try {
    const r = await api.get('/api/workspace/contracts/work-queues', { params: { type } })
    queueItems.value = r.data.data || []
  } catch (e) {
    queueItems.value = []
    message.error('加载工作队列失败')
  }
}

function queueCount(key) {
  return portfolio.value.workQueues?.[key] ?? 0
}

function queueTitle(type) {
  return { REVIEW:'审查队列', APPROVAL:'待办与审批队列', FULFILLMENT:'履约与到期队列' }[type] || '工作队列'
}

function itemTypeLabel(t) {
  return {
    DOCUMENT_PARSE:'文档解析',
    READY_REVIEW:'待审查',
    OPEN_FINDING:'审查发现',
    PENDING_ACTION:'待审批动作',
    OBLIGATION:'履约义务',
    EXPIRING_CONTRACT:'到期预警',
    MISSING_OBLIGATIONS:'待建义务'
  }[t] || t
}

function statusClass(s) {
  const m = { DRAFT:'draft', INTAKE_PARSING:'review', INTAKE_CONFIRMING:'review', MATERIAL_PENDING:'warn', READY_FOR_REVIEW:'review', REVIEWING:'review', NEEDS_REVISION:'warn', PENDING_APPROVAL:'pending', APPROVED:'ok', READY_TO_SIGN:'ok', SIGNED:'ok', IN_FULFILLMENT:'active', EXPIRED:'warn', TERMINATED:'warn' }
  return m[s] || ''
}
function statusLabel(s) {
  const m = { DRAFT:'草稿', INTAKE_PARSING:'录入解析中', INTAKE_CONFIRMING:'待确认录入', MATERIAL_PENDING:'缺材料', READY_FOR_REVIEW:'待审查', REVIEWING:'审查中', NEEDS_REVISION:'需修改', PENDING_APPROVAL:'待审批', APPROVED:'已批准', READY_TO_SIGN:'待签署', SIGNED:'已签署', IN_FULFILLMENT:'履约中', EXPIRED:'已到期', TERMINATED:'已终止' }
  return m[s] || s || ''
}
function contractTypeLabel(t) { return { SERVICE_PROCUREMENT:'服务采购', GOODS_PURCHASE:'货物采购', NDA:'保密协议', LICENSE:'许可协议', EMPLOYMENT:'劳动合同' }[t] || t || '' }
function severityLabel(s) { return { HIGH:'高危', MEDIUM:'中危', LOW:'低危' }[s] || s }
function formatDate(v) { return v ? String(v).replace('T',' ').slice(0,16) : '' }
function timelineNodes(c) { return Array.isArray(c.timelineNodes) ? c.timelineNodes : [] }
function visibleTimelineNodes(c) { return timelineNodes(c).slice(0, 5) }
function timelineKey(node) { return `${node.sourceType}-${node.sourceId}-${node.label}-${node.date || node.condition || ''}` }
function timelineDateLabel(node) { return node.date || node.condition || '待确认' }
function timelineSourceLabel(node) {
  return {
    CASE_FIELD: '案件字段',
    OBLIGATION: '履约义务',
    CLAUSE_DATE: '合同原文',
    CLAUSE_RELATIVE_TERM: '相对期限'
  }[node.sourceType] || node.extractionMode || '时间节点'
}
function timelineTooltip(node) {
  return [node.description, node.sourceTitle, node.extractionMode].filter(Boolean).join('\n')
}
function timelineEmptyLabel(c) {
  return ['INTAKE_PARSING', 'INTAKE_CONFIRMING'].includes(c.status)
    ? '解析完成后自动展示'
    : '暂未识别到明确节点'
}
function timelineStatusClass(node) {
  const status = node.status || ''
  if (status === 'OVERDUE') return 'danger'
  if (status === 'DUE_SOON') return 'warn'
  if (status === 'COMPLETED') return 'done'
  if (!node.date) return 'condition'
  return ''
}
</script>

<style scoped>
.portfolio-page{max-width:1100px;margin:0 auto;padding:30px 24px 60px}
.portfolio-header{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}
.portfolio-header h1{margin:0;font-family:var(--atlas-font-display);font-size:32px;color:var(--atlas-text)}
.portfolio-header p{margin:6px 0 0;color:var(--atlas-muted);font-size:14px}
.primary-button{display:inline-flex;align-items:center;min-height:40px;padding:0 16px;border-radius:4px;border:1px solid var(--atlas-primary);background:var(--atlas-primary);color:#fff;font-size:13px;font-weight:800;cursor:pointer;white-space:nowrap}
.primary-button:hover{background:var(--atlas-primary-dark)}
.quiet-button{display:inline-flex;align-items:center;min-height:32px;padding:0 12px;border-radius:4px;border:1px solid var(--atlas-border);background:var(--atlas-surface);color:var(--atlas-muted);font-size:12px;font-weight:800;cursor:pointer}
.quiet-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}

.kpi-row{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:24px}
.kpi-card{display:flex;flex-direction:column;gap:4px;padding:14px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.kpi-card strong{font-family:var(--atlas-font-display);font-size:28px;color:var(--atlas-text)}
.kpi-card span{font-size:11px;color:var(--atlas-subtle);font-weight:800;text-transform:uppercase}
.kpi-card.warn strong{color:var(--atlas-warning)}.kpi-card.danger strong{color:#b35c56}

.quick-actions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:28px}
.action-btn{display:flex;flex-direction:column;gap:4px;padding:16px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer;text-align:left;transition:all .15s}
.action-btn:hover{border-color:var(--atlas-primary);box-shadow:0 2px 8px rgba(31,45,61,.06)}
.action-btn.active{border-color:var(--atlas-primary);background:rgba(66,111,166,.07)}
.action-icon{font-size:20px;line-height:1;color:var(--atlas-primary)}
.action-btn strong{font-size:13px;color:var(--atlas-text)}
.action-btn small{font-size:11px;color:var(--atlas-muted);line-height:1.4}

.queue-panel{margin-bottom:28px;padding:18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:6px}
.queue-item{display:grid;grid-template-columns:86px 1fr auto;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--atlas-border);cursor:pointer}
.queue-item:first-of-type{border-top:0}
.queue-item:hover strong{color:var(--atlas-primary)}
.queue-item>span{padding:3px 7px;border-radius:3px;background:var(--atlas-bg);color:var(--atlas-muted);font-size:10px;font-weight:900;text-align:center}
.queue-item strong{display:block;color:var(--atlas-text);font-size:13px}
.queue-item small{display:block;margin-top:3px;color:var(--atlas-subtle);font-size:11px}
.queue-item em{font-style:normal;color:#b35c56;font-size:11px;font-weight:900}
.blank-state.compact{padding:22px 0 6px}

.case-list-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.case-list-header h2{margin:0;font-family:var(--atlas-font-display);font-size:20px;color:var(--atlas-text)}
.case-list-header select{min-height:32px;padding:4px 8px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-bg);color:var(--atlas-text);font-size:12px}

.case-card{padding:16px 18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer;margin-bottom:8px;transition:all .15s}
.case-card:hover{border-color:var(--atlas-primary);border-left:3px solid var(--atlas-primary)}
.case-topline{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.case-key{color:var(--atlas-primary);font-size:11px;font-weight:800;letter-spacing:.04em}
.case-status{padding:2px 7px;border-radius:2px;font-size:10px;font-weight:800}
.case-status.draft{color:var(--atlas-subtle);background:var(--atlas-bg)}
.case-status.review{color:var(--atlas-warning);background:rgba(167,121,61,.08)}
.case-status.pending{color:#b35c56;background:rgba(179,92,86,.08)}
.case-status.ok{color:#3f7f5d;background:rgba(63,127,93,.08)}
.case-status.active{color:var(--atlas-primary);background:rgba(66,111,166,.08)}
.case-status.warn{color:var(--atlas-subtle);background:var(--atlas-bg)}
.case-topline small{color:var(--atlas-subtle);font-size:10px;margin-left:auto}
.case-card h3{margin:0;font-size:16px;color:var(--atlas-text)}
.case-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.case-meta span{padding:2px 6px;border:1px solid var(--atlas-border);border-radius:3px;font-size:10px;color:var(--atlas-muted)}
.case-timeline{margin-top:14px;padding-top:12px;border-top:1px solid var(--atlas-border)}
.case-timeline.empty{padding:10px 0 0}
.timeline-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.timeline-head strong{color:var(--atlas-text);font-size:12px}
.timeline-head small{color:var(--atlas-subtle);font-size:10px}
.timeline-track{display:grid;grid-template-columns:repeat(5,minmax(0,1fr)) auto;gap:8px;align-items:stretch}
.timeline-node{position:relative;display:grid;grid-template-columns:12px 1fr;gap:6px;padding:8px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px;min-width:0}
.timeline-node i{width:8px;height:8px;margin-top:3px;border-radius:50%;background:var(--atlas-primary)}
.timeline-node strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--atlas-text);font-size:11px}
.timeline-node span{display:block;margin-top:2px;color:var(--atlas-primary);font-size:10px;font-weight:900}
.timeline-node small{display:block;margin-top:2px;color:var(--atlas-subtle);font-size:9px}
.timeline-node.warn i{background:var(--atlas-warning)}
.timeline-node.danger i{background:#b35c56}
.timeline-node.done i{background:#3f7f5d}
.timeline-node.condition i{background:var(--atlas-muted)}
.timeline-more{display:flex;align-items:center;justify-content:center;min-width:34px;padding:0 8px;border:1px dashed var(--atlas-border);border-radius:4px;color:var(--atlas-muted);font-size:11px;font-weight:900}
.blank-state{padding:60px 0;text-align:center;color:var(--atlas-muted);font-size:14px}

@media(max-width:900px){.kpi-row{grid-template-columns:repeat(3,1fr)}.quick-actions{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.timeline-track{grid-template-columns:1fr 1fr}.timeline-more{min-height:44px}}
@media(max-width:500px){.kpi-row{grid-template-columns:repeat(2,1fr)}.quick-actions{grid-template-columns:1fr}.queue-item{grid-template-columns:1fr}.queue-item>span{text-align:left;width:max-content}}
</style>
