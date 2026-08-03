<template>
  <div class="case-page" v-if="!loading">
    <router-link to="/contracts" class="back-link">返回合同工作台</router-link>

    <header class="case-header">
      <div>
        <span class="case-key">{{ c.caseKey }}</span>
        <span class="case-status" :class="statusClass(c.status)">{{ statusLabel(c.status) }}</span>
        <h1>{{ c.title }}</h1>
        <p>{{ c.description || '没有补充说明' }}</p>
      </div>
      <div class="case-actions">
        <button class="quiet-button" @click="startRun('CONTRACT_REVIEW')" :disabled="running">合同审查</button>
        <button class="primary-button" @click="startRun('CONTRACT_INTAKE')" :disabled="running">{{ running ? '运行中' : '发起任务' }}</button>
      </div>
    </header>

    <!-- Meta grid -->
    <section class="meta-grid">
      <div><span>相对方</span><strong>{{ c.counterparty || '待填写' }}</strong></div>
      <div><span>合同类型</span><strong>{{ typeLabel(c.contractType) }}</strong></div>
      <div><span>金额</span><strong>{{ c.amount ? c.amount + ' ' + (c.currency||'CNY') : '待填写' }}</strong></div>
      <div><span>部门</span><strong>{{ c.department || '待填写' }}</strong></div>
      <div><span>生效日期</span><strong>{{ c.effectiveDate || '待填写' }}</strong></div>
      <div><span>到期日期</span><strong>{{ c.expiryDate || '待填写' }}</strong></div>
    </section>

    <!-- Parties -->
    <section class="side-section" v-if="c.parties?.length">
      <h3>合同主体</h3>
      <div v-for="p in c.parties" :key="p.id" class="party-row">
        <span>{{ partyRoleLabel(p.partyRole) }}</span><strong>{{ p.partyName }}</strong>
        <small v-if="p.riskScore != null">风险分 {{ p.riskScore }}</small>
      </div>
    </section>

    <!-- Documents -->
    <section class="side-section">
      <div class="section-header">
        <h3>合同文件 · {{ c.documents?.length || 0 }} 份</h3>
        <button class="quiet-button small" @click="showUpload = !showUpload">{{ showUpload ? '取消' : '+ 上传文件' }}</button>
      </div>

      <!-- Upload form -->
      <div v-if="showUpload" class="upload-form">
        <div class="upload-row">
          <select v-model="upload.docType"><option value="MAIN">主合同</option><option value="ATTACHMENT">附件</option><option value="PRICING">报价单</option><option value="CERTIFICATE">资质证明</option></select>
          <input v-model.trim="upload.fileName" placeholder="文件名（如：服务采购合同 v3.pdf）" />
          <input v-model.trim="upload.filePath" placeholder="文件路径或 URL" />
          <button class="quiet-button small" @click="doUpload" :disabled="!upload.fileName">上传</button>
        </div>
        <small class="upload-hint">MVP 阶段：填写文件名和路径即可登记。完整文件解析（PDF/OCR/条款抽取）在 Phase 2。</small>
      </div>

      <div v-if="c.documents?.length">
        <div v-for="d in c.documents" :key="d.id" class="doc-row">
          <span>{{ docTypeLabel(d.documentType) }}</span><strong>{{ d.fileName }}</strong>
          <small>v{{ d.version }} · {{ d.parseStatus }}</small>
        </div>
      </div>
      <div v-else-if="!showUpload" class="blank-state">尚未上传合同文件。</div>
    </section>

    <!-- Runs -->
    <section class="side-section" v-if="c.runs?.length">
      <h3>Agent 运行记录</h3>
      <div v-for="r in c.runs" :key="r.id" class="run-row">
        <span :class="runStatusClass(r.status)">{{ runStatusLabel(r.status) }}</span>
        <strong>{{ runTypeLabel(r.runType) }}</strong>
        <small>{{ r.progress || 0 }}% · {{ formatDate(r.createTime) }}</small>
      </div>
    </section>

    <!-- Findings -->
    <section class="side-section" v-if="c.findings?.length">
      <h3>审查发现 · {{ c.findings.length }} 条</h3>
      <div v-for="f in c.findings" :key="f.id" class="finding-row">
        <span class="finding-sev" :class="'sev-'+ (f.severity||'MEDIUM').toLowerCase()">{{ f.severity }}</span>
        <strong>{{ f.title }}</strong>
        <small>{{ findingStatusLabel(f.status) }}</small>
      </div>
    </section>

    <!-- Obligations -->
    <section class="side-section" v-if="c.obligations?.length">
      <h3>履约义务 · {{ c.obligations.length }} 条</h3>
      <div v-for="o in c.obligations" :key="o.id" class="obligation-row">
        <span :class="'obl-'+ (o.status||'PLANNED').toLowerCase()">{{ obligationStatusLabel(o.status) }}</span>
        <strong>{{ o.title }}</strong>
        <small>{{ o.dueDate || '条件触发' }}</small>
      </div>
    </section>
  </div>
  <div v-else class="loading-block"><span class="loader"></span> 读取合同信息</div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api/index.js'

const route = useRoute(); const router = useRouter(); const message = useMessage()
const c = ref({}); const loading = ref(true); const running = ref(false)
const showUpload = ref(false)
const upload = ref({ docType: 'MAIN', fileName: '', filePath: '' })

onMounted(async () => {
  try {
    const r = await api.get(`/api/workspace/contracts/${route.params.id}`)
    c.value = r.data.data
  } catch (e) { message.error('加载合同失败') }
  finally { loading.value = false }
})

async function doUpload() {
  if (!upload.value.fileName) return
  try {
    await api.post(`/api/workspace/contracts/${route.params.id}/documents`, {
      documentType: upload.value.docType,
      fileName: upload.value.fileName,
      filePath: upload.value.filePath || `uploads/${upload.value.fileName}`
    })
    message.success('文件已登记')
    upload.value = { docType: 'MAIN', fileName: '', filePath: '' }
    showUpload.value = false
    // Refresh
    const r = await api.get(`/api/workspace/contracts/${route.params.id}`)
    c.value = r.data.data
  } catch (e) { message.error('上传失败') }
}

async function startRun(taskType) {
  running.value = true
  try {
    await api.post(`/api/workspace/contracts/${route.params.id}/runs`, { taskType, triggerType: 'MANUAL', question: taskType === 'CONTRACT_REVIEW' ? '审查当前合同版本' : '发起合同材料准备' })
    message.success('Agent 任务已创建')
    setTimeout(async () => { const r2 = await api.get(`/api/workspace/contracts/${route.params.id}`); c.value = r2.data.data }, 2000)
  } catch (e) { message.error('启动失败') }
  finally { running.value = false }
}

function statusClass(s) {
  return { DRAFT:'draft', MATERIAL_PENDING:'warn', READY_FOR_REVIEW:'review', REVIEWING:'review', NEEDS_REVISION:'warn', PENDING_APPROVAL:'pending', APPROVED:'ok', READY_TO_SIGN:'ok', SIGNED:'ok', IN_FULFILLMENT:'active', EXPIRED:'warn', TERMINATED:'warn' }[s] || ''
}
function statusLabel(s) {
  return { DRAFT:'草稿', MATERIAL_PENDING:'缺材料', READY_FOR_REVIEW:'待审查', REVIEWING:'审查中', NEEDS_REVISION:'需修改', PENDING_APPROVAL:'待审批', APPROVED:'已批准', READY_TO_SIGN:'待签署', SIGNED:'已签署', IN_FULFILLMENT:'履约中', EXPIRED:'已到期', TERMINATED:'已终止' }[s] || s
}
function typeLabel(t) { return { SERVICE_PROCUREMENT:'服务采购', GOODS_PURCHASE:'货物采购', NDA:'保密协议' }[t] || t }
function partyRoleLabel(r) { return { OUR_ENTITY:'我方', COUNTERPARTY:'对方', GUARANTOR:'担保方' }[r] || r }
function docTypeLabel(t) { return { MAIN:'主合同', ATTACHMENT:'附件', PRICING:'报价', CERTIFICATE:'资质', FULFILLMENT_EVIDENCE:'履约证据' }[t] || t }
function runStatusClass(s) { return { COMPLETED:'ok', FAILED:'error' }[s] || '' }
function runStatusLabel(s) { return { CREATED:'排队', CONTEXT_BUILDING:'分析中', ANALYZING:'审查中', VERIFYING:'验证中', COMPLETED:'完成', FAILED:'失败' }[s] || s }
function runTypeLabel(t) { return { CONTRACT_REVIEW:'合同审查', CONTRACT_INTAKE:'合同发起', APPROVAL_DECISION:'审批决策', VERSION_REVIEW:'版本复核', OBLIGATION_EXTRACTION:'义务提取' }[t] || t }
function findingStatusLabel(s) { return { OPEN:'未处理', REMEDIATED:'已修改', ACCEPTED_EXCEPTION:'已接受例外', DISMISSED:'已驳回' }[s] || s }
function obligationStatusLabel(s) { return { PLANNED:'计划中', DUE_SOON:'即将到期', COMPLETED:'已完成', OVERDUE:'已逾期', ESCALATED:'已升级', WAIVED:'已豁免' }[s] || s }
function formatDate(v) { return v ? String(v).replace('T',' ').slice(0,16) : '' }
</script>

<style scoped>
.case-page{max-width:1100px;margin:0 auto;padding:30px 24px 60px}
.back-link{color:var(--atlas-primary);font-size:12px;font-weight:800;text-decoration:none}
.case-header{display:flex;justify-content:space-between;align-items:end;gap:20px;margin:16px 0 20px}
.case-key{color:var(--atlas-primary);font-size:12px;font-weight:800;letter-spacing:.06em}
.case-status{padding:2px 7px;border-radius:2px;font-size:10px;font-weight:800;margin-left:8px}
.case-status.draft{color:var(--atlas-subtle);background:var(--atlas-bg)}
.case-status.review{color:var(--atlas-warning);background:rgba(167,121,61,.08)}
.case-status.pending{color:#b35c56;background:rgba(179,92,86,.08)}
.case-status.ok{color:#3f7f5d;background:rgba(63,127,93,.08)}
.case-status.active{color:var(--atlas-primary);background:rgba(66,111,166,.08)}
.case-status.warn{color:var(--atlas-subtle);background:var(--atlas-bg)}
.case-header h1{margin:8px 0 6px;font-family:var(--atlas-font-display);font-size:36px;color:var(--atlas-text)}
.case-header p{color:var(--atlas-muted);font-size:14px;max-width:600px}
.quiet-button,.primary-button{display:inline-flex;align-items:center;min-height:38px;padding:0 14px;border-radius:4px;font-size:12px;font-weight:800;cursor:pointer}
.quiet-button{color:var(--atlas-muted);background:var(--atlas-surface);border:1px solid var(--atlas-border)}
.quiet-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}
.primary-button{color:#fff;background:var(--atlas-primary);border:1px solid var(--atlas-primary)}
.primary-button:hover:not(:disabled){background:var(--atlas-primary-dark)}
button:disabled{cursor:not-allowed;opacity:.55}

.meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border-top:1px solid var(--atlas-border);border-bottom:1px solid var(--atlas-border);margin-bottom:24px}
.meta-grid div{padding:12px 14px;border-right:1px solid var(--atlas-border)}
.meta-grid div:nth-child(3n){border-right:0}
.meta-grid span{display:block;font-size:10px;font-weight:800;color:var(--atlas-subtle);text-transform:uppercase}
.meta-grid strong{display:block;margin-top:4px;font-size:13px;color:var(--atlas-text)}

.side-section{margin-bottom:20px;padding:18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.side-section h3{margin:0 0 12px;font-family:var(--atlas-font-display);font-size:16px;color:var(--atlas-text)}
.party-row,.doc-row,.run-row,.finding-row,.obligation-row{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--atlas-border);font-size:12px}
.party-row span,.doc-row span,.run-row span,.finding-row span,.obligation-row span{padding:2px 6px;border-radius:2px;font-size:9px;font-weight:800}
.party-row strong,.doc-row strong,.run-row strong,.finding-row strong,.obligation-row strong{flex:1;color:var(--atlas-text)}
.doc-row small,.run-row small,.finding-row small,.obligation-row small{color:var(--atlas-subtle);font-size:10px;white-space:nowrap}
.finding-sev.sev-high{color:#b35c56;background:rgba(179,92,86,.08)}
.finding-sev.sev-medium{color:var(--atlas-warning);background:rgba(167,121,61,.08)}
.finding-sev.sev-low{color:#7d9a87;background:rgba(125,154,135,.08)}
.run-row span.ok{color:#3f7f5d}.run-row span.error{color:#b35c56}
.section-header{display:flex;justify-content:space-between;align-items:center;gap:10px}
.section-header h3{margin:0!important}
.upload-form{margin:12px 0;padding:14px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.upload-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.upload-row select,.upload-row input{min-height:34px;padding:4px 8px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-text);font-size:12px}
.upload-row input{flex:1;min-width:150px}
.upload-hint{display:block;margin-top:8px;color:var(--atlas-subtle);font-size:10px}
.blank-state{padding:16px 0 4px;color:var(--atlas-muted);font-size:12px}
.loading-block{display:flex;align-items:center;justify-content:center;gap:9px;min-height:50vh;color:var(--atlas-muted)}
.loader{width:20px;height:20px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:700px){.meta-grid{grid-template-columns:repeat(2,1fr)}.meta-grid div:nth-child(2n){border-right:0}.meta-grid div:nth-child(3n){border-right:1px solid var(--atlas-border)}}
</style>
