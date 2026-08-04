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
        <button class="primary-button" @click="handlePrimaryAction" :disabled="running || primaryAction.disabled">{{ running ? '运行中' : primaryAction.label }}</button>
        <div class="task-menu">
          <select v-model="selectedTask" :disabled="running">
            <option value="VERSION_REVIEW">版本复核</option>
            <option value="APPROVAL_DECISION">生成审批意见</option>
            <option value="OBLIGATION_EXTRACTION">提取履约义务</option>
          </select>
          <button class="quiet-button" @click="startRun(selectedTask)" :disabled="running">运行</button>
        </div>
      </div>
    </header>

    <!-- Meta grid -->
    <section class="meta-grid">
      <div><span>相对方</span><strong>{{ c.counterparty || '待填写' }}</strong></div>
      <div><span>合同类型</span><strong>{{ typeLabel(c.contractType) }}</strong></div>
      <div><span>金额</span><strong>{{ c.amount ? c.amount + ' ' + (c.currency||'CNY') : '待填写' }}</strong></div>
      <div><span>部门</span><strong>{{ c.department || '待填写' }}</strong></div>
      <div><span>签订日期</span><strong>{{ c.signedDate || '待填写' }}</strong></div>
      <div><span>生效日期</span><strong>{{ c.effectiveDate || '待填写' }}</strong></div>
      <div><span>到期日期</span><strong>{{ c.expiryDate || '待填写' }}</strong></div>
    </section>

    <section class="timeline-panel">
      <div class="timeline-panel-head">
        <div>
          <span>时间节点</span>
          <h3>合同履约时间线</h3>
        </div>
        <strong>{{ caseTimelineNodes.length }} 个节点</strong>
      </div>
      <div v-if="caseTimelineNodes.length" class="detail-timeline">
        <article
          v-for="node in caseTimelineNodes"
          :key="timelineKey(node)"
          class="detail-timeline-node"
          :class="timelineStatusClass(node)"
        >
          <i></i>
          <div class="timeline-node-main">
            <div class="timeline-node-top">
              <strong>{{ node.label || timelineTypeLabel(node.nodeType) }}</strong>
              <span class="timeline-date-badge">{{ timelineDateLabel(node) }}</span>
            </div>
            <p class="timeline-meaning">{{ timelineMeaning(node) }}</p>
            <div class="timeline-node-meta">
              <small>{{ timelineSourceLabel(node) }}</small>
              <small v-if="node.sourceTitle"> · {{ node.sourceTitle }}</small>
              <small v-if="node.responsibleParty"> · {{ timelinePartyLabel(node.responsibleParty) }}</small>
              <small v-if="node.confidence != null"> · 置信度 {{ confidenceLabel(node.confidence) }}</small>
            </div>
            <div v-if="timelineCondition(node)" class="timeline-date-resolution">
              <strong>{{ relativeDateResult(node).label }}</strong>
              <select
                v-if="relativeDateResult(node).needsChoice"
                v-model="timelineBaseSelection[timelineKey(node)]"
              >
                <option value="">选择基准日期</option>
                <option v-for="candidate in relativeDateResult(node).candidates" :key="candidate.key" :value="candidate.value">
                  {{ candidate.label }} · {{ candidate.value }}
                </option>
              </select>
              <small>{{ relativeDateResult(node).hint }}</small>
            </div>
            <details v-if="timelineQuote(node) || timelineCondition(node)" class="timeline-evidence">
              <summary>原文依据与复核</summary>
              <blockquote v-if="timelineQuote(node)">“{{ timelineQuote(node) }}”</blockquote>
              <p v-if="timelineCondition(node)" class="timeline-condition">触发条件：{{ timelineCondition(node) }}</p>
              <p v-if="timelineEnrichmentReason(node)" class="timeline-review-note">
                Agent 复核：{{ timelineEnrichmentReason(node) }}
              </p>
            </details>
            <div v-if="timelineConsequence(node).explicit || timelineConsequence(node).ai" class="timeline-consequence">
              <div v-if="timelineConsequence(node).explicit">
                <span>合同原文明确约定</span>
                <p>{{ timelineConsequence(node).explicit }}</p>
              </div>
              <div v-if="timelineConsequence(node).ai">
                <span>AI 推断，仅供参考，不代表合同约定</span>
                <p>{{ timelineConsequence(node).ai }}</p>
              </div>
            </div>
            <div v-if="canFulfillmentCheck(node)" class="fulfillment-box">
              <div class="fulfillment-head">
                <div>
                  <span>履约核验</span>
                  <strong>{{ fulfillmentConclusionLabel(latestFulfillmentCheck(node)?.conclusion) }}</strong>
                </div>
                <div class="fulfillment-actions">
                  <button class="quiet-button tiny" @click="openEvidenceLinks(node)">调整证据</button>
                  <button
                    class="quiet-button tiny"
                    :disabled="running || fulfillmentCheckRunning(node)"
                    @click="startTimelineFulfillmentCheck(node)"
                  >
                    {{ fulfillmentCheckRunning(node) ? '核验中' : '发起核验' }}
                  </button>
                </div>
              </div>
              <div v-if="latestFulfillmentCheck(node)" class="fulfillment-result">
                <p>{{ latestFulfillmentCheck(node).summary || '等待核验结果生成。' }}</p>
                <div class="fulfillment-tags">
                  <span>风险 {{ levelLabel(latestFulfillmentCheck(node).riskLevel) }}</span>
                  <span>可信度 {{ levelLabel(latestFulfillmentCheck(node).confidenceLevel) }}</span>
                  <span v-if="latestFulfillmentCheck(node).manualResult">人工：{{ manualResultLabel(latestFulfillmentCheck(node).manualResult) }}</span>
                  <span v-if="latestFulfillmentCheck(node).needsRecheck">新证据待重新核验</span>
                </div>
                <div v-if="latestFulfillmentCheck(node).explicitConsequence || latestFulfillmentCheck(node).aiRisk" class="timeline-consequence">
                  <div v-if="latestFulfillmentCheck(node).explicitConsequence">
                    <span>合同原文明确约定</span>
                    <p>{{ latestFulfillmentCheck(node).explicitConsequence }}</p>
                  </div>
                  <div v-if="latestFulfillmentCheck(node).aiRisk">
                    <span>AI 推断，仅供参考，不代表合同约定</span>
                    <p>{{ latestFulfillmentCheck(node).aiRisk }}</p>
                  </div>
                </div>
                <div v-if="requirementRows(latestFulfillmentCheck(node)).length" class="fulfillment-requirements">
                  <small>合同要求 · 证据 · 判断 · 缺口</small>
                  <article v-for="(row, index) in requirementRows(latestFulfillmentCheck(node))" :key="index">
                    <div><span>合同要求</span><p>{{ row.requirement || '待人工复核合同要求' }}</p></div>
                    <div><span>证据</span><p>{{ row.evidence || '暂无充分证据' }}</p></div>
                    <div><span>判断</span><p>{{ row.judgement || row.judgment || '需人工复核' }}</p></div>
                    <div><span>缺口</span><p>{{ row.gap || '暂无明确缺口' }}</p></div>
                    <em>{{ row.required === false ? '辅助项' : '必需项' }}</em>
                  </article>
                </div>
                <div v-if="arrayField(latestFulfillmentCheck(node).missingEvidenceJson).length" class="fulfillment-list">
                  <small>缺失证据</small>
                  <ul><li v-for="item in arrayField(latestFulfillmentCheck(node).missingEvidenceJson)" :key="item">{{ item }}</li></ul>
                </div>
                <div v-if="arrayField(latestFulfillmentCheck(node).evidenceSnapshotJson).length" class="fulfillment-list evidence-snapshot">
                  <small>证据快照</small>
                  <ul>
                    <li v-for="item in arrayField(latestFulfillmentCheck(node).evidenceSnapshotJson)" :key="item.documentId || item.fileName || item.snippet">
                      {{ evidenceSnapshotLabel(item) }}
                    </li>
                  </ul>
                </div>
                <details class="fulfillment-history">
                  <summary>查看 {{ fulfillmentHistory(node).length }} 次核验历史</summary>
                  <article v-for="check in fulfillmentHistory(node)" :key="check.id">
                    <strong>#{{ check.id }} · {{ fulfillmentConclusionLabel(check.conclusion) }}</strong>
                    <p>{{ check.summary || check.runCurrentStep || '等待 Agent 生成结果' }}</p>
                    <small>{{ formatDate(check.createTime) }} · {{ check.runStatus || check.status }}</small>
                  </article>
                </details>
                <div class="fulfillment-confirm">
                  <button class="quiet-button tiny" @click="confirmFulfillmentCheck(latestFulfillmentCheck(node), 'COMPLETED')">人工确认完成</button>
                  <button class="quiet-button tiny" @click="confirmFulfillmentCheck(latestFulfillmentCheck(node), 'FAILED')">人工确认失败</button>
                  <button class="quiet-button tiny" @click="confirmFulfillmentCheck(latestFulfillmentCheck(node), 'NEEDS_MORE_EVIDENCE')">继续补证</button>
                </div>
              </div>
              <p v-else class="fulfillment-empty">到达节点前后都可以发起预核验；AI 只给建议，最终结果由人工确认。</p>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="timeline-empty">{{ timelineEmptyText() }}</div>
    </section>

    <section class="side-section" v-if="availableKnowledge.length">
      <h3>本合同可用知识 · {{ availableKnowledge.length }} 份</h3>
      <div v-for="doc in availableKnowledge" :key="doc.id" class="knowledge-row">
        <span :class="'knowledge-scope ' + scopeClass(doc.contractUsageScope)">{{ knowledgeScopeLabel(doc.contractUsageScope) }}</span>
        <strong>{{ doc.title }}</strong>
        <small>{{ doc.contractUsageSummary || '用于合同风险审查与履约核验' }}</small>
      </div>
    </section>

    <!-- Review overview -->
    <section class="review-panel" v-if="c.reviewSummary?.id">
      <div class="review-score">
        <span>{{ riskStatusLabel(c.reviewSummary.riskStatus) }}</span>
        <strong>{{ c.reviewSummary.riskScore ?? 0 }}</strong>
        <small>规则引擎评分 · Agent 生成解释</small>
      </div>
      <div class="review-main">
        <h3>{{ c.reviewSummary.title || '合同审查报告' }}</h3>
        <p>{{ c.reviewSummary.summary || '暂无摘要' }}</p>
        <div class="dimension-strip" v-if="Array.isArray(c.reviewSummary.dimensionsJson)">
          <div v-for="d in c.reviewSummary.dimensionsJson" :key="d.name">
            <span>{{ d.name }}</span>
            <strong>{{ d.score }}</strong>
          </div>
        </div>
      </div>
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
        <!-- Mode toggle -->
        <div class="upload-tabs">
          <button type="button" :class="['tab-btn', { active: upload.mode === 'file' }]" :disabled="uploading" @click="upload.mode = 'file'">文件登记</button>
          <button type="button" :class="['tab-btn', { active: upload.mode === 'text' }]" :disabled="uploading" @click="upload.mode = 'text'">纯文字</button>
        </div>

        <!-- File upload mode -->
        <div v-if="upload.mode === 'file'" class="upload-file-mode">
          <div class="upload-row">
            <select v-model="upload.docType"><option value="MAIN">主合同</option><option value="ATTACHMENT">附件</option><option value="PRICING">报价单</option><option value="CERTIFICATE">资质证明</option></select>
            <input v-model.trim="upload.fileName" placeholder="文件名（默认使用所选文件名）" />
            <label class="file-picker">
              <input type="file" accept=".doc,.docx,.pdf,.txt,.md,.markdown" @change="chooseContractFile" />
              <span>{{ upload.file ? '已选择文件' : '选择 DOC / DOCX / PDF / TXT / MD' }}</span>
            </label>
            <button class="quiet-button small" @click="doUpload" :disabled="uploading || (!upload.file && !upload.filePath.trim())">{{ uploading ? '提交中' : '上传并解析' }}</button>
          </div>
          <div class="upload-row path-row">
            <input v-model.trim="upload.filePath" placeholder="可选：已有本地路径或 /upload/... 路径" />
          </div>
          <small class="upload-hint">
            {{ upload.file ? upload.file.name + ' · ' + formatBytes(upload.file.size) : '选择文件后会先上传到后端，再进入合同文档解析流水线。' }}
          </small>
        </div>

        <!-- Text paste mode -->
        <div v-else class="upload-text-mode">
          <div class="upload-row">
            <select v-model="upload.docType"><option value="MAIN">主合同</option><option value="ATTACHMENT">附件</option></select>
            <input v-model.trim="upload.fileName" placeholder="合同标题（如：XX公司服务采购合同）" />
          </div>
          <textarea
            v-model="upload.contentText"
            placeholder="在此粘贴或输入合同全文内容……&#10;&#10;支持纯文本格式。粘贴后可直接用于 Agent 审查、条款抽取和风险分析。"
            rows="16"
            class="upload-textarea"
          ></textarea>
          <div class="upload-text-actions">
            <small>{{ upload.contentText ? '已输入 ' + upload.contentText.length + ' 字符' : '尚未输入内容' }}</small>
            <button class="primary-button small" @click="doUpload" :disabled="uploading || !upload.fileName || !upload.contentText.trim()">{{ uploading ? '提交并解析中' : '提交文字合同' }}</button>
          </div>
        </div>
      </div>

      <div v-if="c.documents?.length">
        <div v-for="d in c.documents" :key="d.id" class="doc-row">
          <span>{{ docTypeLabel(d.documentType) }}</span>
          <strong>{{ d.fileName }}</strong>
          <small>v{{ d.version }} · {{ d.hasInlineText ? parseStatusLabel(d) + ' · ' + (d.textLength || 0) + ' 字' : parseStatusLabel(d) }}</small>
          <button v-if="d.hasInlineText" class="quiet-button tiny" @click="openTextPreview(d)">预览</button>
        </div>
      </div>
      <div v-else-if="!showUpload" class="blank-state">尚未上传合同文件。支持文件登记或直接粘贴合同全文。</div>
    </section>

    <!-- Text preview modal -->
    <div v-if="viewTextDoc" class="modal-overlay" @click.self="viewTextDoc = null">
      <div class="modal-content text-preview">
        <div class="modal-head">
          <h3>{{ viewTextDoc.fileName }}</h3>
          <button class="quiet-button small" @click="viewTextDoc = null">✕ 关闭</button>
        </div>
        <pre class="contract-text-body">{{ viewTextDoc.contentText }}</pre>
        <div class="modal-foot">
          <small>{{ (viewTextDoc.contentText||'').length }} 字符 · 用于 Agent 审查和条款分析</small>
        </div>
      </div>
    </div>

    <!-- Intake confirmation modal -->
    <div v-if="showIntakeModal && intakeFields" class="modal-overlay" @click.self="showIntakeModal = false">
      <div class="modal-content intake-confirm">
        <div class="modal-head">
          <h3>确认合同识别结果</h3>
          <button class="quiet-button small" @click="showIntakeModal = false">✕ 关闭</button>
        </div>
        <div class="intake-body">
          <p class="intake-hint">AI 已从合同正文中提取以下字段。请核对并修正，特别是确认<strong>哪一方是我方主体</strong>。</p>
          <div class="intake-grid">
            <div class="intake-field">
              <label>合同标题</label>
              <input v-model="intakeFields.title" placeholder="合同标题" />
            </div>
            <div class="intake-field">
              <label>合同类型</label>
              <select v-model="intakeFields.contractType">
                <option value="SERVICE_PROCUREMENT">服务采购</option>
                <option value="GOODS_PURCHASE">货物采购</option>
                <option value="NDA">保密协议</option>
                <option value="OTHER">其他</option>
              </select>
            </div>
            <div class="intake-field">
              <label>合同金额</label>
              <input v-model.number="intakeFields.amount" type="number" placeholder="0" />
            </div>
            <div class="intake-field">
              <label>币种</label>
              <input v-model="intakeFields.currency" placeholder="CNY" />
            </div>
            <div class="intake-field">
              <label>签订日期</label>
              <input v-model="intakeFields.signedDate" type="date" />
            </div>
            <div class="intake-field">
              <label>生效日期</label>
              <input v-model="intakeFields.effectiveDate" type="date" />
            </div>
            <div class="intake-field">
              <label>到期日期</label>
              <input v-model="intakeFields.expiryDate" type="date" />
            </div>
            <div class="intake-field">
              <label>所属部门</label>
              <input v-model="intakeFields.department" placeholder="如：采购部" />
            </div>
          </div>
          <!-- Our side selector -->
          <div class="our-side-select" v-if="intakeFields.partyA && intakeFields.partyB">
            <label>我方主体（选择哪一方是我们自己）</label>
            <div class="side-options">
              <label :class="['side-card', { active: intakeFields.ourSide === 'partyA' }]">
                <input type="radio" v-model="intakeFields.ourSide" value="partyA" />
                <strong>{{ intakeFields.partyA }}</strong>
                <span>甲方</span>
              </label>
              <label :class="['side-card', { active: intakeFields.ourSide === 'partyB' }]">
                <input type="radio" v-model="intakeFields.ourSide" value="partyB" />
                <strong>{{ intakeFields.partyB }}</strong>
                <span>乙方</span>
              </label>
            </div>
          </div>
          <div v-else-if="intakeFields.partyA || intakeFields.partyB" class="our-side-single">
            <label>我方主体</label>
            <input v-model="intakeFields.ourEntity" placeholder="请输入我方公司全称" />
            <label style="margin-top:10px">相对方</label>
            <input v-model="intakeFields.counterparty" placeholder="请输入对方公司全称" />
          </div>
        </div>
        <div class="modal-foot intake-actions">
          <el-button @click="showIntakeModal = false">暂不处理</el-button>
          <el-button type="primary" @click="doConfirmIntake" :loading="confirming">
            确认无误，更新合同信息
          </el-button>
        </div>
      </div>
    </div>

    <!-- Evidence link modal -->
    <div v-if="evidenceDialog.visible" class="modal-overlay" @click.self="closeEvidenceLinks">
      <div class="modal-content evidence-link-modal">
        <div class="modal-head">
          <div>
            <h3>调整节点证据</h3>
            <small>{{ evidenceDialog.node?.label || '合同时间节点' }}</small>
          </div>
          <button class="quiet-button small" @click="closeEvidenceLinks">✕ 关闭</button>
        </div>
        <div class="evidence-link-body">
          <p>证据可以先上传到合同文件，不必一开始绑定节点。这里的绑定只影响下一次履约核验，不会自动调用 Agent。</p>
          <div v-if="evidenceDialog.loading" class="blank-state">正在读取证据列表</div>
          <div v-else-if="!evidenceDialog.available.length" class="blank-state">暂无可用履约证据。请先上传履约证据、附件、资质或报价文件。</div>
          <label v-for="doc in evidenceDialog.available" :key="doc.id" class="evidence-link-row">
            <input type="checkbox" :value="doc.id" v-model="evidenceDialog.selectedIds" />
            <span>{{ docTypeLabel(doc.documentType) }}</span>
            <strong>{{ doc.fileName }}</strong>
            <small>v{{ doc.version }} · {{ parseStatusLabel(doc) }}</small>
          </label>
        </div>
        <div class="modal-foot intake-actions">
          <el-button @click="closeEvidenceLinks">取消</el-button>
          <el-button type="primary" :loading="evidenceDialog.saving" @click="saveEvidenceLinks">
            保存绑定
          </el-button>
        </div>
      </div>
    </div>

    <!-- Runs -->
    <section class="side-section" data-section="runs" v-if="c.runs?.length">
      <h3>Agent 运行记录</h3>
      <div v-for="r in c.runs" :key="r.id" class="run-row">
        <span :class="runStatusClass(r.status)">{{ runStatusLabel(r.status) }}</span>
        <strong>{{ runTypeLabel(r.runType) }}</strong>
        <small>{{ r.progress || 0 }}% · {{ formatDate(r.createTime) }}</small>
      </div>
    </section>

    <!-- Findings -->
    <section class="side-section" data-section="findings" v-if="c.findings?.length">
      <h3>审查发现 · {{ c.findings.length }} 条</h3>
      <article v-for="f in c.findings" :key="f.id" class="finding-card">
        <div class="finding-head">
          <span class="finding-sev" :class="'sev-'+ (f.severity||'MEDIUM').toLowerCase()">{{ severityLabel(f.severity) }}</span>
          <span class="clause-pill">{{ clauseTypeLabel(f.clauseType) }}</span>
          <small>{{ findingStatusLabel(f.status) }}</small>
        </div>
        <strong>{{ f.title }}</strong>
        <p v-if="f.description">{{ f.description }}</p>
        <p v-if="f.impact" class="impact-text">影响：{{ f.impact }}</p>
        <div class="advice-grid" v-if="f.remediationAdvice || f.negotiationAdvice">
          <div v-if="f.remediationAdvice">
            <span>修改建议</span>
            <p>{{ f.remediationAdvice }}</p>
          </div>
          <div v-if="f.negotiationAdvice">
            <span>谈判口径</span>
            <p>{{ f.negotiationAdvice }}</p>
          </div>
        </div>
        <div class="verification-list" v-if="Array.isArray(f.verificationPoints) && f.verificationPoints.length">
          <span>复核点</span>
          <ul>
            <li v-for="point in f.verificationPoints" :key="point">{{ point }}</li>
          </ul>
        </div>
        <div class="citation-grid">
          <div>
            <span>合同依据</span>
            <small>{{ citationLabel(f.contractCitation) }}</small>
          </div>
          <div>
            <span>制度依据</span>
            <small>{{ policyLabel(f.policyCitation, f.ruleKey) }}</small>
          </div>
        </div>
        <div class="finding-action-line" v-if="f.suggestedAction">
          <span>建议动作</span>
          <strong>{{ suggestedActionLabel(f.suggestedAction) }}</strong>
        </div>
        <div class="finding-buttons" v-if="f.status === 'OPEN'">
          <button class="quiet-button tiny" @click="updateFinding(f.id, 'REMEDIATED')">标记已修改</button>
          <button class="quiet-button tiny" @click="updateFinding(f.id, 'ACCEPTED_EXCEPTION')">接受例外</button>
          <button class="quiet-button tiny" @click="updateFinding(f.id, 'DISMISSED')">驳回</button>
        </div>
      </article>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api/index.js'

const route = useRoute(); const router = useRouter(); const message = useMessage()
const c = ref({}); const loading = ref(true); const running = ref(false)
const showUpload = ref(false)
const uploading = ref(false)
const upload = ref({ mode: 'file', docType: 'MAIN', fileName: '', filePath: '', contentText: '', file: null })
const viewTextDoc = ref(null)
const showIntakeModal = ref(false)
const intakeFields = ref(null)
const confirming = ref(false)
const selectedTask = ref('VERSION_REVIEW')
const timelineBaseSelection = reactive({})
const evidenceDialog = reactive({
  visible: false,
  loading: false,
  saving: false,
  node: null,
  available: [],
  selectedIds: [],
})
const caseTimelineNodes = computed(() => Array.isArray(c.value.timelineNodes) ? c.value.timelineNodes : [])
const availableKnowledge = computed(() => Array.isArray(c.value.availableKnowledge) ? c.value.availableKnowledge : [])

const primaryAction = computed(() => {
  const status = c.value.status
  const hasRunning = c.value.runs?.some(r => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(r.status))
  if (hasRunning || status === 'REVIEWING') return { label: '查看审查进度', taskType: null, disabled: false, scrollTo: 'runs' }
  if (c.value.findings?.some(f => f.status === 'OPEN')) return { label: '处理审查发现', taskType: null, disabled: false, scrollTo: 'findings' }
  if (status === 'PENDING_APPROVAL') return { label: '生成审批意见', taskType: 'APPROVAL_DECISION', disabled: false }
  if (['SIGNED', 'IN_FULFILLMENT'].includes(status)) return { label: '提取履约义务', taskType: 'OBLIGATION_EXTRACTION', disabled: false }
  if (!c.value.documents?.length) return { label: '先上传合同', taskType: null, disabled: true }
  return { label: '开始合同审查', taskType: 'CONTRACT_REVIEW', disabled: false }
})

onMounted(loadCase)

async function loadCase() {
  loading.value = true
  try {
    const r = await api.get(`/api/workspace/contracts/${route.params.id}`)
    c.value = r.data.data
    checkPendingIntake()
  } catch (e) { message.error('加载合同失败') }
  finally { loading.value = false }
}

async function doUpload() {
  if (uploading.value) return
  if (upload.value.mode === 'text' && !upload.value.contentText.trim()) return
  uploading.value = true
  try {
    let uploadedPath = upload.value.filePath.trim()
    let uploadedSize = null
    let fileName = upload.value.fileName.trim()
    if (upload.value.mode === 'file' && upload.value.file) {
      const form = new FormData()
      form.append('file', upload.value.file)
      const response = await api.post('/api/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000
      })
      uploadedPath = response.data.data?.url || ''
      uploadedSize = upload.value.file.size
      if (!fileName) fileName = upload.value.file.name
    }
    if (!fileName) throw new Error('请填写文件名或选择合同文件')
    if (upload.value.mode === 'file' && !uploadedPath) throw new Error('请选择文件，或填写已有本地路径')

    const body = {
      documentType: upload.value.docType,
      fileName,
    }
    if (upload.value.mode === 'text') {
      body.contentText = upload.value.contentText
      body.filePath = 'inline:text'
    } else {
      body.filePath = uploadedPath
      if (uploadedSize != null) body.fileSize = uploadedSize
    }
    await api.post(`/api/workspace/contracts/${route.params.id}/documents`, body)
    message.success(upload.value.mode === 'text' ? '文字合同已提交，正在提取条款' : '合同文件已上传，正在进入文档流水线')
    upload.value = { mode: 'file', docType: 'MAIN', fileName: '', filePath: '', contentText: '', file: null }
    showUpload.value = false
    // Refresh
    await refreshCase()
  } catch (e) {
    message.error(uploadErrorMessage(e))
  } finally {
    uploading.value = false
  }
}

function chooseContractFile(event) {
  const file = event.target.files?.[0] || null
  upload.value.file = file
  if (file && !upload.value.fileName.trim()) {
    upload.value.fileName = file.name
  }
}

async function openTextPreview(document) {
  try {
    const response = await api.get(`/api/workspace/contracts/${route.params.id}/documents/${document.id}/content`)
    viewTextDoc.value = response.data.data
  } catch (e) {
    message.error(uploadErrorMessage(e, '合同正文加载失败'))
  }
}

async function refreshCase() {
  const r = await api.get(`/api/workspace/contracts/${route.params.id}`)
  c.value = r.data.data
  checkPendingIntake()
}

function checkPendingIntake() {
  const intake = c.value?.pendingIntake
  if (!intake || !intake.validatedJson) return
  let v
  try {
    v = typeof intake.validatedJson === 'string' ? JSON.parse(intake.validatedJson) : intake.validatedJson
  } catch { return }
  const fields = v.fields || {}
  const partyA = (fields.partyA || {}).value || ''
  const partyB = (fields.partyB || {}).value || ''
  // Determine our side: if case already has ourEntity set, match it
  let ourSide = ''
  const ourEntity = c.value?.ourEntity || ''
  const counterparty = c.value?.counterparty || ''
  if (ourEntity && partyA && ourEntity.includes(partyA.slice(0, 4))) ourSide = 'partyA'
  else if (ourEntity && partyB && ourEntity.includes(partyB.slice(0, 4))) ourSide = 'partyB'
  else if (counterparty && partyA && counterparty.includes(partyA.slice(0, 4))) ourSide = 'partyB'
  else if (counterparty && partyB && counterparty.includes(partyB.slice(0, 4))) ourSide = 'partyA'

  intakeFields.value = {
    intakeId: intake.id,
    title: (fields.contractTitle || {}).value || c.value?.title || '',
    contractType: (fields.contractType || {}).value || c.value?.contractType || 'OTHER',
    amount: c.value?.amount || (fields.amount || {}).value || null,
    currency: (fields.currency || {}).value || c.value?.currency || 'CNY',
    signedDate: ((fields.signedDate || {}).value || c.value?.signedDate || '').toString().slice(0, 10),
    effectiveDate: ((fields.effectiveDate || {}).value || c.value?.effectiveDate || '').toString().slice(0, 10),
    expiryDate: ((fields.expiryDate || {}).value || c.value?.expiryDate || '').toString().slice(0, 10),
    department: (fields.department || {}).value || c.value?.department || '',
    partyA,
    partyB,
    ourSide,
    ourEntity: ourEntity || (ourSide === 'partyA' ? partyA : (ourSide === 'partyB' ? partyB : '')),
    counterparty: counterparty || (ourSide === 'partyB' ? partyA : (ourSide === 'partyA' ? partyB : '')),
  }
  showIntakeModal.value = true
}

async function doConfirmIntake() {
  if (!intakeFields.value) return
  const f = intakeFields.value
  confirming.value = true
  try {
    // Determine our entity and counterparty based on side selection
    let ourEntity = f.ourEntity
    let counterparty = f.counterparty
    if (f.partyA && f.partyB && f.ourSide) {
      if (f.ourSide === 'partyA') { ourEntity = f.partyA; counterparty = f.partyB }
      else { ourEntity = f.partyB; counterparty = f.partyA }
    }
    await api.post(`/api/workspace/contracts/intakes/${f.intakeId}/confirm`, {
      title: f.title,
      contractType: f.contractType,
      ourEntity: ourEntity || '',
      counterparty: counterparty || '',
      ourSide: f.ourSide === 'partyA' ? 'A' : (f.ourSide === 'partyB' ? 'B' : ''),
      amount: f.amount || null,
      currency: f.currency || 'CNY',
      signedDate: f.signedDate || null,
      effectiveDate: f.effectiveDate || null,
      expiryDate: f.expiryDate || null,
      department: f.department || '',
    })
    message.success('合同信息已确认')
    showIntakeModal.value = false
    refreshCase()
  } catch (e) {
    message.error(e.response?.data?.message || '确认失败')
  } finally { confirming.value = false }
}

function uploadErrorMessage(error, fallback = '合同提交失败') {
  if (error.response?.data?.message) return error.response.data.message
  if (error.code === 'ECONNABORTED') return '请求超时，请检查后端服务后重试'
  if (!error.response) return '无法连接合同服务，请确认 Java 后端已启动'
  return fallback
}

function parseStatusLabel(document) {
  const labels = { PENDING:'等待解析', PARSING:'解析中', READY:'已就绪', FAILED:'解析失败' }
  return labels[document.parseStatus] || document.parseStatus
}

async function startRun(taskType) {
  running.value = true
  try {
    await api.post(`/api/workspace/contracts/${route.params.id}/runs`, { taskType, triggerType: 'MANUAL', question: taskQuestion(taskType) })
    message.success('Agent 任务已创建')
    setTimeout(refreshCase, 2000)
  } catch (e) { message.error('启动失败') }
  finally { running.value = false }
}

function handlePrimaryAction() {
  const action = primaryAction.value
  if (action.scrollTo) {
    document.querySelector(`[data-section="${action.scrollTo}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  if (action.taskType) startRun(action.taskType)
}

async function updateFinding(findingId, status) {
  try {
    const r = await api.patch(`/api/workspace/contracts/findings/${findingId}`, { status })
    c.value = r.data.data
    message.success('审查发现已更新')
  } catch (e) {
    message.error('更新审查发现失败')
  }
}

function canFulfillmentCheck(node) {
  return (node.sourceType || node.source) === 'PIPELINE_TIMELINE' && Number(node.sourceId || 0) > 0
}
function fulfillmentHistory(node) {
  return Array.isArray(node.fulfillmentCheckHistory) ? node.fulfillmentCheckHistory : []
}
function latestFulfillmentCheck(node) {
  return node.latestFulfillmentCheck || fulfillmentHistory(node)[0] || null
}
function fulfillmentCheckRunning(node) {
  const check = latestFulfillmentCheck(node)
  if (!check) return false
  const checkStatus = String(check.status || '').toUpperCase()
  const runStatus = String(check.runStatus || '').toUpperCase()
  if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(runStatus)) return false
  return ['PENDING', 'CREATED', 'CONTEXT_BUILDING', 'ANALYZING', 'VERIFYING'].includes(checkStatus)
    || ['CREATED', 'CONTEXT_BUILDING', 'ANALYZING', 'VERIFYING'].includes(runStatus)
}
async function startTimelineFulfillmentCheck(node) {
  if (!canFulfillmentCheck(node)) {
    message.warning('该时间节点缺少可核验的合同条款记录')
    return
  }
  running.value = true
  try {
    await api.post(`/api/workspace/contracts/${route.params.id}/timeline/${node.sourceId}/fulfillment-checks`)
    message.success('履约核验已发起，Agent 会检查合同要求、证据和缺口')
    await refreshCase()
    setTimeout(refreshCase, 2500)
  } catch (e) {
    message.error(e.response?.data?.message || '履约核验启动失败')
  } finally {
    running.value = false
  }
}
async function openEvidenceLinks(node) {
  if (!canFulfillmentCheck(node)) {
    message.warning('该时间节点缺少可绑定的合同条款记录')
    return
  }
  evidenceDialog.visible = true
  evidenceDialog.loading = true
  evidenceDialog.node = node
  evidenceDialog.available = []
  evidenceDialog.selectedIds = []
  try {
    const response = await api.get(`/api/workspace/contracts/${route.params.id}/timeline/${node.sourceId}/evidence-links`)
    const data = response.data.data || {}
    evidenceDialog.available = Array.isArray(data.available) ? data.available : []
    evidenceDialog.selectedIds = Array.isArray(data.linkedDocumentIds)
      ? data.linkedDocumentIds.map(id => Number(id))
      : []
  } catch (e) {
    message.error(e.response?.data?.message || '证据列表加载失败')
    evidenceDialog.visible = false
  } finally {
    evidenceDialog.loading = false
  }
}
function closeEvidenceLinks() {
  evidenceDialog.visible = false
  evidenceDialog.node = null
  evidenceDialog.available = []
  evidenceDialog.selectedIds = []
}
async function saveEvidenceLinks() {
  const node = evidenceDialog.node
  if (!node?.sourceId || evidenceDialog.saving) return
  evidenceDialog.saving = true
  try {
    await api.put(`/api/workspace/contracts/${route.params.id}/timeline/${node.sourceId}/evidence-links`, {
      documentIds: evidenceDialog.selectedIds.map(id => Number(id)).filter(Boolean)
    })
    message.success('证据绑定已保存。下次履约核验会优先使用这些证据。')
    closeEvidenceLinks()
    await refreshCase()
  } catch (e) {
    message.error(e.response?.data?.message || '证据绑定保存失败')
  } finally {
    evidenceDialog.saving = false
  }
}
async function confirmFulfillmentCheck(check, result) {
  if (!check?.id) return
  const note = window.prompt('请填写人工确认说明。AI 只提供建议，最终结果以人工确认为准。')
  if (!note || !note.trim()) {
    message.warning('人工确认需要填写说明')
    return
  }
  try {
    const r = await api.patch(`/api/workspace/contracts/fulfillment-checks/${check.id}/confirmation`, {
      manualResult: result,
      manualNote: note.trim()
    })
    c.value = r.data.data
    message.success('人工确认已记录')
  } catch (e) {
    message.error(e.response?.data?.message || '人工确认失败')
  }
}
function arrayField(value) {
  if (Array.isArray(value)) return value
  if (!value) return []
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return value.trim() ? [value] : []
    }
  }
  return []
}
function requirementRows(check) {
  return arrayField(check?.requirementJson).map(item => typeof item === 'object' ? item : { requirement: String(item) })
}
function fulfillmentConclusionLabel(value) {
  return {
    BASICALLY_SATISFIED: '基本满足',
    HAS_ISSUES: '发现问题',
    INSUFFICIENT_EVIDENCE: '证据不足',
    UNCLEAR_TERMS: '条款不清',
    NEEDS_REVIEW: '需人工复核',
  }[value] || '未核验'
}
function levelLabel(value) {
  return { HIGH: '高', MEDIUM: '中', LOW: '低' }[value] || '待判断'
}
function manualResultLabel(value) {
  return {
    COMPLETED: '已完成',
    FAILED: '未通过',
    PENDING: '继续观察',
    NEEDS_MORE_EVIDENCE: '继续补证',
  }[value] || value
}

function timelineKey(node) { return `${node.id || ''}-${node.label || ''}-${timelineDateValue(node) || timelineCondition(node) || ''}` }
function timelineDateValue(node) { return node.nodeDate || node.date || '' }
function timelineCondition(node) { return node.conditionText || node.condition || '' }
function timelineDateLabel(node) {
  const result = relativeDateResult(node)
  if (result.display) return result.display
  if (timelineDateValue(node)) return timelineDateValue(node)
  return '待确认'
}
function timelineMeaning(node) {
  return node.businessMeaning || node.description || timelineCondition(node)
    || (timelineDateValue(node) ? '来自合同正文提取的履约时间点。' : '来自合同正文或案件字段的时间节点。')
}
function timelineCitation(node) {
  const value = node.citation || node.citationJson
  if (!value) return null
  if (typeof value === 'object') return value
  try { return JSON.parse(value) } catch (e) { return null }
}
function timelineQuote(node) {
  const citation = timelineCitation(node)
  return citation?.quote || citation?.snippet || ''
}
function timelineEnrichmentReason(node) {
  const citation = timelineCitation(node)
  return citation?.timelineEnrichment?.reason || ''
}
function timelineConsequence(node) {
  const check = latestFulfillmentCheck(node) || {}
  return {
    explicit: check.explicitConsequence || '',
    ai: check.aiRisk || '',
  }
}
function relativeDateResult(node) {
  const condition = timelineCondition(node)
  const raw = String(condition || '').replace(/\s+/g, '')
  if (!raw) return { display: '', hint: '', candidates: [], needsChoice: false }
  const amountMatch = raw.match(/(\d{1,3})/)
  const amount = amountMatch ? Number(amountMatch[1]) : null
  const candidates = []
  const addCandidate = (key, label, value, direction = 'after') => {
    if (!value) return
    candidates.push({ key, label, value, direction })
  }
  if (raw.includes('期满前') || raw.includes('到期前') || raw.includes('合同期满前')) {
    addCandidate('expiryDate', '合同到期/期满日', c.value?.expiryDate)
  }
  if (raw.includes('生效后') || raw.includes('生效日起') || raw.includes('自生效')) {
    addCandidate('effectiveDate', '合同生效日', c.value?.effectiveDate)
  }
  if (raw.includes('签订合同后') || raw.includes('签署后') || raw.includes('签订后')) {
    if (c.value?.signedDate) addCandidate('signedDate', '合同签订日', c.value.signedDate)
  }
  if (raw.includes('合同期内') || raw.includes('有效期内')) {
    if (c.value?.effectiveDate) addCandidate('effectiveDate', '合同生效日', c.value.effectiveDate)
    if (c.value?.expiryDate) addCandidate('expiryDate', '合同到期/期满日', c.value.expiryDate)
  }
  const selected = timelineBaseSelection[timelineKey(node)] || (candidates.length === 1 ? candidates[0].value : '')
  const resolved = selected ? resolveRelativeDate(raw, selected) : null
  if (resolved) {
    return {
      display: `计算结果：${resolved}`,
      hint: `基准日期：${selected}`,
      candidates,
      needsChoice: candidates.length > 1,
    }
  }
  if (candidates.length > 1) {
    return {
      display: `相对期限：${condition}`,
      hint: '存在多个基准日期候选，请先选择后再计算。AI 不会替你猜。',
      candidates,
      needsChoice: true,
    }
  }
  const missing = raw.includes('签订合同后') || raw.includes('签署后') || raw.includes('签订后')
    ? '缺少合同签订日期'
    : raw.includes('期满前') || raw.includes('到期前') || raw.includes('合同期满前')
      ? '缺少合同到期/期满日期'
      : raw.includes('生效后') || raw.includes('生效日起') || raw.includes('自生效')
        ? '缺少合同生效日期'
        : '缺少可计算的基准日期'
  return {
    display: `相对期限：${condition}`,
    hint: `${missing}，暂不自动计算。`,
    candidates,
    needsChoice: false,
  }
}
function resolveRelativeDate(condition, baseValue) {
  const amountMatch = String(condition || '').match(/(\d{1,3})/)
  if (!amountMatch) return ''
  const amount = Number(amountMatch[1])
  const sign = /前/.test(condition) ? -1 : 1
  const base = new Date(`${String(baseValue).slice(0, 10)}T00:00:00`)
  if (Number.isNaN(base.getTime())) return ''
  if (/(月|个月)/.test(condition)) {
    base.setMonth(base.getMonth() + sign * amount)
  } else if (/(年)/.test(condition)) {
    base.setFullYear(base.getFullYear() + sign * amount)
  } else {
    base.setDate(base.getDate() + sign * amount)
  }
  return formatYmd(base)
}
function formatYmd(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
function evidenceSnapshotLabel(item) {
  if (!item) return '未命中快照'
  const parts = [
    item.fileName || item.title || `文档#${item.documentId || ''}`,
    item.version != null ? `v${item.version}` : '',
    item.snippet || item.contentSnippet || item.contentHash || '',
  ].filter(Boolean)
  return parts.join(' · ')
}
function knowledgeScopeLabel(scope) {
  return { GLOBAL:'全部合同', SPECIFIC_CASES:'指定合同', DISABLED:'不用于合同' }[scope] || '不用于合同'
}
function scopeClass(scope) {
  return String(scope || 'DISABLED').toLowerCase().replace(/_/g, '-')
}
function timelineSourceLabel(node) {
  const source = node.source || node.sourceType || ''
  return {
    RULE_EXTRACTED: '文档解析',
    RULE_CANDIDATE: '规则候选',
    LLM_ENRICHED: '规则提取 · Agent 复核',
    CASE_FIELD: '案件字段',
    PIPELINE_TIMELINE: '文档解析',
    OBLIGATION: '履约义务',
    AGENT_OBLIGATION: 'Agent 提取',
  }[source] || source || '时间节点'
}
function timelineTypeLabel(type) {
  return {
    CONTRACT_START: '合同开始', CONTRACT_END: '合同到期',
    SERVICE_START: '服务开始', SERVICE_END: '服务结束',
    PAYMENT: '付款/开票节点', DELIVERY: '交付/服务节点',
    ACCEPTANCE: '验收节点', NOTICE: '通知节点',
    RENEWAL: '续签节点', TERMINATION: '解除/终止节点',
    PENALTY: '违约处理节点', OTHER: '合同时间节点',
  }[type] || '合同时间节点'
}
function timelinePartyLabel(party) {
  return { OUR_ENTITY:'我方负责', COUNTERPARTY:'对方负责', BOTH:'双方协同', UNKNOWN:'责任方待确认' }[party] || party
}
function confidenceLabel(value) {
  const confidence = Number(value)
  return Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : '待确认'
}
function timelineStatusClass(node) {
  const status = node.status || ''
  if (status === 'OVERDUE') return 'danger'
  if (status === 'DUE_SOON') return 'warn'
  if (status === 'COMPLETED') return 'done'
  if (!timelineDateValue(node) && timelineCondition(node)) return 'condition'
  if (!timelineDateValue(node)) return 'pending'
  return ''
}
function timelineEmptyText() {
  const parsing = c.value.status === 'INTAKE_PARSING'
    || c.value.documents?.some(d => ['PENDING', 'PARSING'].includes(d.parseStatus))
  return parsing ? '合同文档仍在解析，时间节点会在解析完成后自动出现。' : '暂未识别到明确的生效、到期、付款、交付、验收、续签或通知时间节点。'
}

function statusClass(s) {
  return { DRAFT:'draft', INTAKE_PARSING:'review', INTAKE_CONFIRMING:'review', MATERIAL_PENDING:'warn', READY_FOR_REVIEW:'review', REVIEWING:'review', NEEDS_REVISION:'warn', PENDING_APPROVAL:'pending', APPROVED:'ok', READY_TO_SIGN:'ok', SIGNED:'ok', IN_FULFILLMENT:'active', EXPIRED:'warn', TERMINATED:'warn' }[s] || ''
}
function statusLabel(s) {
  return { DRAFT:'草稿', INTAKE_PARSING:'录入解析中', INTAKE_CONFIRMING:'待确认录入', MATERIAL_PENDING:'缺材料', READY_FOR_REVIEW:'待审查', REVIEWING:'审查中', NEEDS_REVISION:'需修改', PENDING_APPROVAL:'待审批', APPROVED:'已批准', READY_TO_SIGN:'待签署', SIGNED:'已签署', IN_FULFILLMENT:'履约中', EXPIRED:'已到期', TERMINATED:'已终止' }[s] || s
}
function typeLabel(t) { return { SERVICE_PROCUREMENT:'服务采购', GOODS_PURCHASE:'货物采购', NDA:'保密协议' }[t] || t }
function partyRoleLabel(r) { return { OUR_ENTITY:'我方', COUNTERPARTY:'对方', GUARANTOR:'担保方' }[r] || r }
function docTypeLabel(t) { return { MAIN:'主合同', ATTACHMENT:'附件', PRICING:'报价', CERTIFICATE:'资质', FULFILLMENT_EVIDENCE:'履约证据' }[t] || t }
function runStatusClass(s) { return { COMPLETED:'ok', FAILED:'error' }[s] || '' }
function runStatusLabel(s) { return { CREATED:'排队', CONTEXT_BUILDING:'分析中', ANALYZING:'审查中', VERIFYING:'验证中', COMPLETED:'完成', FAILED:'失败' }[s] || s }
function runTypeLabel(t) { return { CONTRACT_REVIEW:'合同审查', CONTRACT_INTAKE:'合同发起', APPROVAL_DECISION:'审批决策', VERSION_REVIEW:'版本复核', OBLIGATION_EXTRACTION:'义务提取', FULFILLMENT_CHECK:'履约核验' }[t] || t }
function taskQuestion(t) { return { CONTRACT_REVIEW:'审查当前合同版本', CONTRACT_INTAKE:'发起合同材料准备', APPROVAL_DECISION:'生成合同审批意见', VERSION_REVIEW:'复核合同版本变化', OBLIGATION_EXTRACTION:'提取合同履约义务', FULFILLMENT_CHECK:'核验合同时间节点履约证据' }[t] || '执行合同任务' }
function findingStatusLabel(s) { return { OPEN:'未处理', REMEDIATED:'已修改', ACCEPTED_EXCEPTION:'已接受例外', DISMISSED:'已驳回' }[s] || s }
function obligationStatusLabel(s) { return { PLANNED:'计划中', DUE_SOON:'即将到期', COMPLETED:'已完成', OVERDUE:'已逾期', ESCALATED:'已升级', WAIVED:'已豁免' }[s] || s }
function severityLabel(s) { return { HIGH:'高危', MEDIUM:'中危', LOW:'低危' }[s] || s || '中危' }
function riskStatusLabel(s) { return { LOW_RISK:'低风险', MEDIUM_RISK:'中风险', HIGH_RISK:'高风险' }[s] || s || '未评分' }
function clauseTypeLabel(t) { return { LIABILITY:'责任违约', PAYMENT:'商务付款', CONFIDENTIALITY:'保密合规', ACCEPTANCE:'验收交付', TERMINATION:'终止续签', IP:'知识产权', DATA_PROTECTION:'数据保护', OTHER:'其他' }[t] || t || '其他' }
function suggestedActionLabel(a) { return { CREATE_NEGOTIATION_TASK:'创建协商任务', REQUEST_MATERIAL:'补充材料', REQUEST_LEGAL_REVIEW:'法务复核', SCHEDULE_REMINDER:'设置提醒' }[a] || a }
function citationLabel(citation) {
  if (!citation || typeof citation !== 'object') return '暂无合同引用'
  const loc = citation.clause || citation.clauseNumber || (citation.page ? `第 ${citation.page} 页` : '')
  return [loc, citation.snippet].filter(Boolean).join(' · ') || '暂无合同引用'
}
function policyLabel(citation, ruleKey) {
  if (!citation || typeof citation !== 'object') return ruleKey || '暂无制度引用'
  return [citation.ruleKey || ruleKey, citation.ruleTitle, citation.snippet].filter(Boolean).join(' · ') || '暂无制度引用'
}
function formatDate(v) { return v ? String(v).replace('T',' ').slice(0,16) : '' }
function formatBytes(size) {
  const bytes = Number(size || 0)
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
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
.case-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.task-menu{display:flex;align-items:center;gap:6px}
.task-menu select{min-height:38px;padding:0 8px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-text);font-size:12px;font-weight:700}
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

.timeline-panel{margin-bottom:24px;padding:18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.timeline-panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:14px}
.timeline-panel-head span{display:block;margin-bottom:3px;color:var(--atlas-subtle);font-size:10px;font-weight:900;text-transform:uppercase}
.timeline-panel-head h3{margin:0;font-family:var(--atlas-font-display);font-size:17px;color:var(--atlas-text)}
.timeline-panel-head strong{padding:3px 8px;border:1px solid var(--atlas-border);border-radius:3px;background:var(--atlas-bg);color:var(--atlas-muted);font-size:11px}
.detail-timeline{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.detail-timeline-node{display:grid;grid-template-columns:14px 1fr;gap:10px;min-width:0;padding:12px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.detail-timeline-node i{width:9px;height:9px;margin-top:5px;border-radius:50%;background:var(--atlas-primary)}
.timeline-node-main{min-width:0}
.timeline-node-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.timeline-node-top strong{display:block;min-width:0;color:var(--atlas-text);font-size:13px;line-height:1.45;word-break:break-word}
.timeline-date-badge{flex:0 0 auto;max-width:46%;padding:2px 6px;border:1px solid rgba(66,111,166,.18);border-radius:3px;background:rgba(66,111,166,.06);color:var(--atlas-primary);font-size:11px;font-weight:900;line-height:1.45;word-break:break-word}
.timeline-meaning{margin:8px 0 0;color:var(--atlas-muted);font-size:12px;line-height:1.6}
.timeline-node-meta{margin-top:7px;color:var(--atlas-subtle);font-size:10px;line-height:1.55}
.timeline-node-meta small{font-size:10px}
.timeline-evidence{margin-top:9px;padding-top:8px;border-top:1px dashed var(--atlas-border)}
.timeline-evidence summary{cursor:pointer;color:var(--atlas-primary);font-size:11px;font-weight:800}
.timeline-evidence blockquote{margin:8px 0 0;padding:8px 10px;background:var(--atlas-surface);border-left:3px solid var(--atlas-primary);color:var(--atlas-muted);font-size:11px;line-height:1.6}
.timeline-evidence p{margin:7px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.55}
.timeline-condition{font-weight:700}
.timeline-review-note{color:var(--atlas-subtle)}
.timeline-date-resolution,
.timeline-consequence,
.knowledge-row{margin-top:8px;padding:8px 10px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.timeline-date-resolution strong,
.timeline-consequence span,
.knowledge-row span{display:block;margin-bottom:4px;color:var(--atlas-primary);font-size:10px;font-weight:900}
.timeline-date-resolution small,
.timeline-consequence p,
.knowledge-row small{display:block;color:var(--atlas-muted);font-size:11px;line-height:1.5}
.timeline-date-resolution select{margin-top:6px;min-height:30px;padding:0 8px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-bg);font-size:11px}
.timeline-consequence{display:grid;gap:8px}
.timeline-consequence p{margin:0}
.evidence-snapshot{background:rgba(66,111,166,.05);border-color:rgba(66,111,166,.14)}
.knowledge-row strong{display:block;color:var(--atlas-text);font-size:12px;line-height:1.5}
.knowledge-row small{margin-top:2px}
.knowledge-scope{display:inline-flex;width:fit-content;padding:2px 6px;border-radius:3px;font-size:9px;font-weight:900;margin-bottom:5px}
.knowledge-scope.global{color:#166534;background:#dcfce7}
.knowledge-scope.specific-cases{color:#1d4ed8;background:#dbeafe}
.knowledge-scope.disabled{color:#64748b;background:#f1f5f9}
.detail-timeline-node.warn i{background:var(--atlas-warning)}
.detail-timeline-node.danger i{background:#b35c56}
.detail-timeline-node.done i{background:#3f7f5d}
.detail-timeline-node.condition i{background:var(--atlas-muted)}
.timeline-empty{padding:14px;background:var(--atlas-bg);border:1px dashed var(--atlas-border);border-radius:4px;color:var(--atlas-muted);font-size:12px}
.fulfillment-box{margin-top:10px;padding:10px;background:var(--atlas-surface);border:1px solid rgba(63,127,93,.2);border-left:3px solid #3f7f5d;border-radius:4px}
.fulfillment-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.fulfillment-head span{display:block;margin-bottom:3px;color:#3f7f5d;font-size:10px;font-weight:900}
.fulfillment-head strong{display:block;color:var(--atlas-text);font-size:13px;line-height:1.35}
.fulfillment-box .quiet-button.tiny{margin-left:0;flex:0 0 auto}
.fulfillment-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.fulfillment-result{margin-top:8px}
.fulfillment-result>p{margin:0;color:var(--atlas-muted);font-size:12px;line-height:1.6}
.fulfillment-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.fulfillment-tags span{padding:2px 6px;background:rgba(66,111,166,.06);border:1px solid rgba(66,111,166,.14);border-radius:3px;color:var(--atlas-primary);font-size:10px;font-weight:800}
.fulfillment-requirements{margin-top:9px;padding:8px;background:rgba(63,127,93,.06);border:1px solid rgba(63,127,93,.16);border-radius:4px}
.fulfillment-requirements>small{display:block;margin-bottom:6px;color:#3f7f5d;font-size:10px;font-weight:900}
.fulfillment-requirements article{position:relative;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:7px;padding:8px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.fulfillment-requirements article:first-of-type{margin-top:0}
.fulfillment-requirements article div span{display:block;margin-bottom:3px;color:var(--atlas-subtle);font-size:9px;font-weight:900}
.fulfillment-requirements article div p{margin:0;color:var(--atlas-text);font-size:11px;line-height:1.55;word-break:break-word}
.fulfillment-requirements article em{position:absolute;right:7px;top:6px;color:var(--atlas-primary);font-size:9px;font-style:normal;font-weight:900}
.fulfillment-list{margin-top:9px;padding:8px;background:rgba(179,92,86,.06);border:1px solid rgba(179,92,86,.14);border-radius:4px}
.fulfillment-list small{display:block;margin-bottom:4px;color:#b35c56;font-size:10px;font-weight:900}
.fulfillment-list ul{margin:0;padding-left:16px;color:var(--atlas-text);font-size:11px;line-height:1.6}
.fulfillment-history{margin-top:8px;padding-top:8px;border-top:1px dashed var(--atlas-border)}
.fulfillment-history summary{cursor:pointer;color:var(--atlas-primary);font-size:11px;font-weight:800}
.fulfillment-history article{margin-top:8px;padding:8px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.fulfillment-history article strong{display:block;color:var(--atlas-text);font-size:12px}
.fulfillment-history article p{margin:5px 0;color:var(--atlas-muted);font-size:11px;line-height:1.55}
.fulfillment-history article small{display:block;color:var(--atlas-subtle);font-size:10px}
.fulfillment-confirm{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.fulfillment-empty{margin:8px 0 0;color:var(--atlas-subtle);font-size:11px;line-height:1.55}

.review-panel{display:grid;grid-template-columns:180px 1fr;gap:18px;margin-bottom:20px;padding:18px;background:linear-gradient(90deg,rgba(66,111,166,.08),rgba(63,127,93,.07));border:1px solid var(--atlas-border);border-radius:6px}
.review-score{display:flex;flex-direction:column;gap:4px;padding-right:18px;border-right:1px solid var(--atlas-border)}
.review-score span{font-size:12px;font-weight:900;color:var(--atlas-primary)}
.review-score strong{font-family:var(--atlas-font-display);font-size:46px;line-height:1;color:var(--atlas-text)}
.review-score small{font-size:11px;color:var(--atlas-muted)}
.review-main h3{margin:0 0 6px;font-family:var(--atlas-font-display);font-size:18px;color:var(--atlas-text)}
.review-main p{margin:0;color:var(--atlas-muted);font-size:13px;line-height:1.6}
.dimension-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:14px}
.dimension-strip div{padding:8px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.dimension-strip span{display:block;font-size:10px;color:var(--atlas-subtle);font-weight:800}
.dimension-strip strong{display:block;margin-top:3px;font-size:18px;color:var(--atlas-text)}

.side-section{margin-bottom:20px;padding:18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.side-section h3{margin:0 0 12px;font-family:var(--atlas-font-display);font-size:16px;color:var(--atlas-text)}
.party-row,.doc-row,.run-row,.finding-row,.obligation-row{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--atlas-border);font-size:12px}
.party-row span,.doc-row span,.run-row span,.finding-row span,.obligation-row span{padding:2px 6px;border-radius:2px;font-size:9px;font-weight:800}
.party-row strong,.doc-row strong,.run-row strong,.finding-row strong,.obligation-row strong{flex:1;color:var(--atlas-text)}
.doc-row small,.run-row small,.finding-row small,.obligation-row small{color:var(--atlas-subtle);font-size:10px;white-space:nowrap}
.finding-sev.sev-high{color:#b35c56;background:rgba(179,92,86,.08)}
.finding-sev.sev-medium{color:var(--atlas-warning);background:rgba(167,121,61,.08)}
.finding-sev.sev-low{color:#7d9a87;background:rgba(125,154,135,.08)}
.finding-card{padding:14px 0;border-top:1px solid var(--atlas-border)}
.finding-card:first-of-type{border-top:0;padding-top:2px}
.finding-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.finding-head small{margin-left:auto;color:var(--atlas-subtle);font-size:10px}
.clause-pill{padding:2px 6px;border:1px solid var(--atlas-border);border-radius:3px;color:var(--atlas-muted);font-size:9px;font-weight:800;background:var(--atlas-bg)}
.finding-card>strong{display:block;margin-bottom:6px;color:var(--atlas-text);font-size:14px}
.finding-card p{margin:0 0 8px;color:var(--atlas-muted);font-size:12px;line-height:1.65}
.impact-text{color:#8b5e34!important}
.advice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.advice-grid div{padding:10px;background:#fff;border:1px solid var(--atlas-border);border-radius:4px}
.advice-grid span,.verification-list>span{display:block;margin-bottom:5px;color:var(--atlas-subtle);font-size:10px;font-weight:900}
.advice-grid p{margin:0;color:var(--atlas-text);font-size:12px;line-height:1.65}
.verification-list{margin-top:8px;padding:10px;background:rgba(63,127,93,.06);border:1px solid rgba(63,127,93,.16);border-radius:4px}
.verification-list ul{margin:0;padding-left:16px;color:var(--atlas-text);font-size:12px;line-height:1.7}
.verification-list li+li{margin-top:3px}
.citation-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:10px}
.citation-grid div{padding:10px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.citation-grid span,.finding-action-line span{display:block;margin-bottom:4px;color:var(--atlas-subtle);font-size:10px;font-weight:900}
.citation-grid small{display:block;color:var(--atlas-text);font-size:11px;line-height:1.5;white-space:normal}
.finding-action-line{display:flex;align-items:center;gap:10px;margin-top:8px;padding:9px 10px;background:rgba(66,111,166,.06);border-left:3px solid var(--atlas-primary)}
.finding-action-line span{margin:0;white-space:nowrap}
.finding-action-line strong{font-size:12px;color:var(--atlas-text)}
.finding-buttons{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.run-row span.ok{color:#3f7f5d}.run-row span.error{color:#b35c56}
.section-header{display:flex;justify-content:space-between;align-items:center;gap:10px}
.section-header h3{margin:0!important}
.upload-form{margin:12px 0;padding:14px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.upload-file-mode{display:flex;flex-direction:column;gap:8px}
.upload-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.upload-row select,.upload-row input{min-height:34px;padding:4px 8px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-text);font-size:12px}
.upload-row input{flex:1;min-width:150px}
.path-row input{min-width:100%}
.file-picker{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 12px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-primary);font-size:12px;font-weight:800;cursor:pointer}
.file-picker input{display:none}
.file-picker:hover{border-color:var(--atlas-primary);background:rgba(66,111,166,.06)}
.upload-hint{display:block;margin-top:8px;color:var(--atlas-subtle);font-size:10px}
.upload-tabs{display:flex;gap:0;margin-bottom:12px;border-bottom:2px solid var(--atlas-border)}
.tab-btn{padding:8px 16px;border:0;background:0;color:var(--atlas-muted);font-size:12px;font-weight:700;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s}
.tab-btn.active{color:var(--atlas-primary);border-bottom-color:var(--atlas-primary)}
.tab-btn:hover:not(.active){color:var(--atlas-text)}
.upload-text-mode{display:flex;flex-direction:column;gap:10px}
.upload-textarea{width:100%;padding:12px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-text);font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;line-height:1.6;resize:vertical;min-height:280px}
.upload-textarea:focus{outline:0;border-color:var(--atlas-primary);box-shadow:0 0 0 2px rgba(66,111,166,.12)}
.upload-text-actions{display:flex;justify-content:space-between;align-items:center}
.upload-text-actions small{color:var(--atlas-muted);font-size:11px}
.primary-button.small{min-height:32px;padding:0 12px;font-size:11px}
.quiet-button.tiny{padding:1px 8px;font-size:10px;min-height:22px;margin-left:auto}

/* Text preview modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;display:flex;align-items:center;justify-content:center}
.modal-content{background:var(--atlas-surface);border-radius:8px;max-width:900px;width:90vw;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.25)}
.text-preview .modal-head{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--atlas-border)}
.text-preview .modal-head h3{margin:0;font-size:16px;color:var(--atlas-text)}
.contract-text-body{flex:1;overflow:auto;padding:20px;margin:0;font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;line-height:1.8;color:var(--atlas-text);white-space:pre-wrap;word-break:break-word;background:var(--atlas-bg)}
.modal-foot{padding:10px 20px;border-top:1px solid var(--atlas-border)}
.modal-foot small{color:var(--atlas-subtle);font-size:10px}
.evidence-link-modal .modal-head{display:flex;justify-content:space-between;align-items:flex-start;padding:16px 20px;border-bottom:1px solid var(--atlas-border)}
.evidence-link-modal .modal-head h3{margin:0;font-size:16px;color:var(--atlas-text)}
.evidence-link-modal .modal-head small{display:block;margin-top:3px;color:var(--atlas-subtle);font-size:11px;line-height:1.5}
.evidence-link-body{padding:16px 20px;overflow:auto}
.evidence-link-body>p{margin:0 0 12px;color:var(--atlas-muted);font-size:12px;line-height:1.6}
.evidence-link-row{display:grid;grid-template-columns:20px auto 1fr auto;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid var(--atlas-border);font-size:12px;cursor:pointer}
.evidence-link-row input{width:14px;height:14px}
.evidence-link-row span{padding:2px 6px;border-radius:3px;background:rgba(66,111,166,.06);color:var(--atlas-primary);font-size:9px;font-weight:900}
.evidence-link-row strong{min-width:0;color:var(--atlas-text);word-break:break-word}
.evidence-link-row small{color:var(--atlas-subtle);font-size:10px;white-space:nowrap}

/* Intake confirmation modal */
.intake-confirm{max-width:680px;width:95vw}
.intake-body{padding:20px;overflow:auto;max-height:60vh}
.intake-hint{color:var(--atlas-muted);font-size:13px;line-height:1.6;margin:0 0 16px}
.intake-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.intake-field{display:flex;flex-direction:column;gap:4px}
.intake-field label{font-size:11px;font-weight:700;color:var(--atlas-subtle);text-transform:uppercase}
.intake-field input,.intake-field select{min-height:36px;padding:4px 10px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-text);font-size:13px}
.intake-field input:focus,.intake-field select:focus{outline:0;border-color:var(--atlas-primary)}
.our-side-select,.our-side-single{margin-top:16px;padding:14px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.our-side-select>label,.our-side-single>label{display:block;font-size:12px;font-weight:800;color:var(--atlas-text);margin-bottom:8px}
.side-options{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.side-card{display:flex;align-items:center;gap:8px;padding:12px;border:2px solid var(--atlas-border);border-radius:6px;cursor:pointer;transition:border-color .15s}
.side-card.active{border-color:var(--atlas-primary);background:rgba(66,111,166,.04)}
.side-card input[type=radio]{accent-color:var(--atlas-primary)}
.side-card strong{font-size:14px;color:var(--atlas-text)}
.side-card span{font-size:11px;color:var(--atlas-subtle)}
.our-side-single input{width:100%;min-height:36px;padding:4px 10px;border:1px solid var(--atlas-border);border-radius:4px;font-size:13px}
.intake-actions{display:flex;justify-content:flex-end;gap:10px;padding:14px 20px}
.blank-state{padding:16px 0 4px;color:var(--atlas-muted);font-size:12px}
.loading-block{display:flex;align-items:center;justify-content:center;gap:9px;min-height:50vh;color:var(--atlas-muted)}
.loader{width:20px;height:20px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:700px){.case-header{align-items:flex-start;flex-direction:column}.case-actions{justify-content:flex-start}.review-panel{grid-template-columns:1fr}.review-score{border-right:0;border-bottom:1px solid var(--atlas-border);padding:0 0 12px}.dimension-strip{grid-template-columns:repeat(2,1fr)}.citation-grid,.advice-grid,.detail-timeline{grid-template-columns:1fr}.meta-grid{grid-template-columns:repeat(2,1fr)}.meta-grid div:nth-child(2n){border-right:0}.meta-grid div:nth-child(3n){border-right:1px solid var(--atlas-border)}}
</style>
