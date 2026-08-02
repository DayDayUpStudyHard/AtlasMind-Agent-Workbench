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
    </section>

    <!-- Quick actions -->
    <section class="quick-actions">
      <button class="action-btn" @click="$router.push('/contracts/new')">
        <span class="action-icon">+</span>
        <strong>发起新合同</strong>
        <small>填写交易信息，Agent 判断类型并生成材料清单</small>
      </button>
      <button class="action-btn" @click="filterStatus('READY_FOR_REVIEW')">
        <span class="action-icon">&#128269;</span>
        <strong>审查待签合同</strong>
        <small>查看待解析、待审查和待复核案件</small>
      </button>
      <button class="action-btn" @click="filterStatus('PENDING_APPROVAL')">
        <span class="action-icon">&#9998;</span>
        <strong>处理待办与审批</strong>
        <small>集中处理材料、协商、法务和风险例外</small>
      </button>
      <button class="action-btn" @click="filterStatus('IN_FULFILLMENT')">
        <span class="action-icon">&#128197;</span>
        <strong>查看履约和到期</strong>
        <small>义务日历、逾期事项和续签预警</small>
      </button>
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

function filterStatus(s) { statusFilter.value = s; loadCases() }

function statusClass(s) {
  const m = { DRAFT:'draft', READY_FOR_REVIEW:'review', REVIEWING:'review', PENDING_APPROVAL:'pending', APPROVED:'ok', SIGNED:'ok', IN_FULFILLMENT:'active', EXPIRED:'warn', TERMINATED:'warn' }
  return m[s] || ''
}
function statusLabel(s) {
  const m = { DRAFT:'草稿', MATERIAL_PENDING:'缺材料', READY_FOR_REVIEW:'待审查', REVIEWING:'审查中', NEEDS_REVISION:'需修改', PENDING_APPROVAL:'待审批', APPROVED:'已批准', READY_TO_SIGN:'待签署', SIGNED:'已签署', IN_FULFILLMENT:'履约中', EXPIRED:'已到期', TERMINATED:'已终止' }
  return m[s] || s || ''
}
function contractTypeLabel(t) { return { SERVICE_PROCUREMENT:'服务采购', GOODS_PURCHASE:'货物采购', NDA:'保密协议', LICENSE:'许可协议', EMPLOYMENT:'劳动合同' }[t] || t || '' }
function formatDate(v) { return v ? String(v).replace('T',' ').slice(0,16) : '' }
</script>

<style scoped>
.portfolio-page{max-width:1100px;margin:0 auto;padding:30px 24px 60px}
.portfolio-header{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}
.portfolio-header h1{margin:0;font-family:var(--atlas-font-display);font-size:32px;color:var(--atlas-text)}
.portfolio-header p{margin:6px 0 0;color:var(--atlas-muted);font-size:14px}
.primary-button{display:inline-flex;align-items:center;min-height:40px;padding:0 16px;border-radius:4px;border:1px solid var(--atlas-primary);background:var(--atlas-primary);color:#fff;font-size:13px;font-weight:800;cursor:pointer;white-space:nowrap}
.primary-button:hover{background:var(--atlas-primary-dark)}

.kpi-row{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:24px}
.kpi-card{display:flex;flex-direction:column;gap:4px;padding:14px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.kpi-card strong{font-family:var(--atlas-font-display);font-size:28px;color:var(--atlas-text)}
.kpi-card span{font-size:11px;color:var(--atlas-subtle);font-weight:800;text-transform:uppercase}
.kpi-card.warn strong{color:var(--atlas-warning)}.kpi-card.danger strong{color:#b35c56}

.quick-actions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:28px}
.action-btn{display:flex;flex-direction:column;gap:4px;padding:16px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer;text-align:left;transition:all .15s}
.action-btn:hover{border-color:var(--atlas-primary);box-shadow:0 2px 8px rgba(31,45,61,.06)}
.action-icon{font-size:20px;line-height:1;color:var(--atlas-primary)}
.action-btn strong{font-size:13px;color:var(--atlas-text)}
.action-btn small{font-size:11px;color:var(--atlas-muted);line-height:1.4}

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
.blank-state{padding:60px 0;text-align:center;color:var(--atlas-muted);font-size:14px}

@media(max-width:900px){.kpi-row{grid-template-columns:repeat(3,1fr)}.quick-actions{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.kpi-row{grid-template-columns:repeat(2,1fr)}.quick-actions{grid-template-columns:1fr}}
</style>
