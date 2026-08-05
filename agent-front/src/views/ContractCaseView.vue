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
      <div><span>结束方式</span><strong>{{ c.expiryDate || (primaryLifecycleCondition ? '满足约定条件后结束' : '待填写') }}</strong></div>
    </section>

    <section v-if="analysisWorkflow.id" class="analysis-workflow-panel">
      <div class="analysis-workflow-head">
        <div>
          <span class="section-kicker">合同分析流程</span>
          <h3>解析、确认与风险审查</h3>
          <p>风险审查会复用已经解析并确认的合同证据，不会重复 OCR 或重新切分全文。</p>
        </div>
        <strong :class="'workflow-status ' + workflowStatusClass(analysisWorkflow.status)">
          {{ workflowStatusLabel(analysisWorkflow.status) }}
        </strong>
      </div>
      <div class="analysis-workflow-stages">
        <div v-for="stage in analysisStages" :key="stage.key" class="analysis-workflow-stage" :class="stage.state">
          <span class="workflow-stage-mark">{{ stage.state === 'done' ? '✓' : stage.index }}</span>
          <div>
            <strong>{{ stage.label }}</strong>
            <small>{{ stage.description }}</small>
          </div>
        </div>
      </div>
      <div class="analysis-workflow-foot">
        <small v-if="analysisWorkflow.evidenceSnapshotHash">
          证据快照 v{{ analysisWorkflow.documentVersion || 1 }} · {{ String(analysisWorkflow.evidenceSnapshotHash).slice(0, 12) }}…
        </small>
        <button v-if="analysisWorkflow.status === 'WAITING_CONFIRMATION'" class="quiet-button small" @click="openIntakeConfirmation">
          打开识别确认
        </button>
        <button v-else-if="analysisWorkflow.status === 'READY_FOR_REVIEW'" class="primary-button small" :disabled="running" @click="startRun('CONTRACT_REVIEW')">
          开始风险审查
        </button>
      </div>
    </section>

    <section v-if="documentPipelineActive" class="document-progress-panel">
      <div class="document-progress-copy">
        <span class="section-kicker">合同文件处理</span>
        <h3>{{ documentPipelineActive.fileName }}</h3>
        <p>{{ documentPipelineAction(documentPipelineActive) }}。你可以返回合同工作台，任务会在后台继续。</p>
      </div>
      <div class="document-progress-value">
        <strong>{{ documentPipelineProgress }}%</strong>
        <span>当前进度</span>
      </div>
      <div class="document-progress-track"><i :style="{ width: `${documentPipelineProgress}%` }"></i></div>
    </section>

    <section v-if="primaryLifecycleCondition" class="contract-diagnostics">
      <div v-if="primaryLifecycleCondition" class="contract-end-condition">
        <div class="diagnostic-mark">结束条件</div>
        <div>
          <strong>{{ primaryLifecycleCondition.summary }}</strong>
          <ol v-if="lifecycleEvents(primaryLifecycleCondition).length">
            <li v-for="event in lifecycleEvents(primaryLifecycleCondition)" :key="event.sequence || event.event">
              <span>{{ primaryLifecycleCondition.logicOperator === 'ALL' ? '必须满足' : '条件' }}</span>
              {{ event.event }}
            </li>
          </ol>
          <small>来源：{{ lifecycleSourceLabel(primaryLifecycleCondition) }} · 最终结束状态需人工确认</small>
        </div>
      </div>
    </section>

    <section class="timeline-panel">
      <div class="timeline-panel-head">
        <div>
          <span>履约日程</span>
          <h3>关键时间与待办</h3>
        </div>
        <strong>{{ caseTimelineNodes.length }} 个节点</strong>
      </div>
      <div v-if="caseTimelineNodes.length" class="detail-timeline">
        <article
          v-for="node in caseTimelineNodes"
          :key="timelineKey(node)"
          class="detail-timeline-node"
          :class="timelineStatusClass(node)"
          role="button"
          tabindex="0"
          @click="openTimelineDetail(node)"
          @keydown.enter="openTimelineDetail(node)"
        >
          <div class="timeline-date-column">
            <strong>{{ timelineDateLabel(node) }}</strong>
            <span v-if="timelineNeedsRecognition(node)" class="recognition-warning">日期/文字可能有误</span>
            <span v-else-if="relativeDateResult(node).baseUncertain" class="basis-warning">基准日期待确认</span>
            <small v-else>{{ timelineDateKind(node) }}</small>
          </div>
          <div class="timeline-node-main">
            <span v-if="timelineTypeLabel(node.nodeType) !== (node.label || timelineTypeLabel(node.nodeType))" class="timeline-type">{{ timelineTypeLabel(node.nodeType) }}</span>
            <h4>{{ node.label || timelineTypeLabel(node.nodeType) }}</h4>
            <p class="timeline-action">{{ timelineAction(node) }}</p>
            <p v-if="timelineQualityNote(node)" class="timeline-quality-note">{{ timelineQualityNote(node) }}</p>
            <div class="timeline-node-meta">
              <small>{{ timelineSourceLabel(node) }}</small>
              <small>{{ timelinePartyLabel(node.responsibleParty) }}</small>
              <small v-if="node.confidence != null">可信度 {{ confidenceLabel(node.confidence) }}</small>
              <small v-if="timelineNeedsRecognition(node)">需要人工核对</small>
            </div>
          </div>
          <div class="timeline-row-actions" @click.stop>
            <button v-if="canFulfillmentCheck(node)" class="evidence-button" @click="openTimelineDetail(node, true)">上传证明</button>
            <button class="detail-button" @click="openTimelineDetail(node)">查看详情 <span aria-hidden="true">→</span></button>
          </div>
        </article>
      </div>
      <div v-else class="timeline-empty">{{ timelineEmptyText() }}</div>
    </section>

    <div v-if="selectedTimelineNode" class="modal-overlay" @click.self="closeTimelineDetail">
      <section class="timeline-detail-modal" role="dialog" aria-modal="true" aria-labelledby="timeline-detail-title">
        <header class="timeline-detail-header">
          <div>
            <span>{{ timelineTypeLabel(selectedTimelineNode.nodeType) }}</span>
            <h3 id="timeline-detail-title">{{ selectedTimelineNode.label || timelineTypeLabel(selectedTimelineNode.nodeType) }}</h3>
            <p>{{ timelineAction(selectedTimelineNode) }}</p>
            <small v-if="timelineQualityNote(selectedTimelineNode)" class="detail-quality-note">{{ timelineQualityNote(selectedTimelineNode) }}</small>
          </div>
          <button class="modal-close" aria-label="关闭时间节点详情" @click="closeTimelineDetail">×</button>
        </header>

        <div class="timeline-detail-body">
          <section class="detail-date-band">
            <div>
              <span>预计时间</span>
              <strong>{{ timelineDateLabel(selectedTimelineNode) }}</strong>
              <small v-if="timelineNeedsRecognition(selectedTimelineNode)" class="recognition-warning">当前识别的日期/数字可能有误，请核对合同原页</small>
              <small v-if="relativeDateResult(selectedTimelineNode).baseUncertain">基准日期不确定，当前结果为推定日期</small>
              <small v-else>{{ timelineDateKind(selectedTimelineNode) }}</small>
            </div>
            <label v-if="timelineCondition(selectedTimelineNode)" class="base-date-editor">
              <span>计算基准日期</span>
              <input
                type="date"
                :value="relativeDateResult(selectedTimelineNode).baseDate"
                @input="setTimelineBaseDate(selectedTimelineNode, $event.target.value)"
              />
              <small>{{ relativeDateResult(selectedTimelineNode).hint }}</small>
              <div v-if="timelineBaseSelection[timelineKey(selectedTimelineNode)]" class="base-date-actions">
                <button
                  v-if="timelineBaseField(selectedTimelineNode)"
                  type="button"
                  class="base-date-save"
                  :disabled="timelineBaseSaving"
                  @click="saveTimelineBaseDate(selectedTimelineNode)"
                >{{ timelineBaseSaving ? '保存中...' : `保存为${timelineBaseField(selectedTimelineNode).label}` }}</button>
                <button type="button" :disabled="timelineBaseSaving" @click="resetTimelineBaseDate(selectedTimelineNode)">恢复系统推定</button>
              </div>
              <small v-if="timelineBaseSelection[timelineKey(selectedTimelineNode)] && !timelineBaseField(selectedTimelineNode)" class="base-date-trial-note">事件触发日期仅用于本页试算，不会改写合同基本信息。</small>
            </label>
          </section>

          <section class="detail-section">
            <div class="detail-section-title"><span>01</span><h4>本节点要完成什么</h4></div>
            <div v-if="timelineContractRequirements(selectedTimelineNode).length" class="requirement-list">
              <div v-for="item in timelineContractRequirements(selectedTimelineNode)" :key="item">
                <span class="source-contract">来自合同</span><p>{{ item }}</p>
              </div>
            </div>
            <div v-if="timelineAiSuggestions(selectedTimelineNode).length" class="requirement-list ai-list">
              <div v-for="item in timelineAiSuggestions(selectedTimelineNode)" :key="item">
                <span class="source-ai">AI 建议</span><p>{{ item }}</p>
              </div>
            </div>
            <p v-if="!timelineContractRequirements(selectedTimelineNode).length && !timelineAiSuggestions(selectedTimelineNode).length" class="detail-empty">
              合同未明确列出交付材料，需由 Agent 结合完整条款补充建议。
            </p>
          </section>

          <section class="detail-section">
            <div class="detail-section-title"><span>02</span><h4>原文依据</h4></div>
            <p class="evidence-location">{{ selectedTimelineNode.sourceTitle || '合同正文' }} · {{ timelineSourceLabel(selectedTimelineNode) }}</p>
            <blockquote class="full-contract-quote">{{ timelineFullQuote(selectedTimelineNode) || timelineQuote(selectedTimelineNode) }}</blockquote>
            <p v-if="timelineCondition(selectedTimelineNode)" class="timeline-condition">合同期限：{{ timelineConditionDisplay(selectedTimelineNode) }}</p>
          </section>

          <section v-if="timelineConsequence(selectedTimelineNode).explicit || timelineConsequence(selectedTimelineNode).ai" class="detail-section">
            <div class="detail-section-title"><span>03</span><h4>未完成可能产生什么后果</h4></div>
            <div class="consequence-split">
              <div v-if="timelineConsequence(selectedTimelineNode).explicit">
                <span>合同明确约定</span><p>{{ timelineConsequence(selectedTimelineNode).explicit }}</p>
              </div>
              <div v-if="timelineConsequence(selectedTimelineNode).ai" class="ai-consequence">
                <span>AI 推断，仅供参考，不代表合同约定</span><p>{{ stripAiRiskPrefix(timelineConsequence(selectedTimelineNode).ai) }}</p>
              </div>
            </div>
          </section>

          <section v-if="canFulfillmentCheck(selectedTimelineNode)" ref="evidenceSection" class="detail-section fulfillment-workspace">
            <div class="detail-section-title"><span>04</span><h4>上传证明并进行履约核验</h4></div>
            <div class="evidence-upload-zone">
              <label>
                <input type="file" accept=".doc,.docx,.pdf,.txt,.md,.markdown" @change="chooseTimelineEvidenceFile" />
                <strong>{{ timelineEvidenceUpload.file?.name || '选择履约证明文件' }}</strong>
                <small>支持 PDF、DOC、DOCX、TXT；图片证据请先转为 PDF，或由人工配合复核</small>
              </label>
              <button :disabled="!timelineEvidenceUpload.file || timelineEvidenceUpload.uploading" @click="uploadTimelineEvidence(selectedTimelineNode)">
                {{ timelineEvidenceUpload.uploading ? '上传并解析中' : '上传并绑定当前节点' }}
              </button>
            </div>
            <div class="fulfillment-actions detail-actions">
              <button class="quiet-button" @click="openEvidenceLinks(selectedTimelineNode)">管理已绑定证据</button>
              <button class="primary-button" :disabled="running || fulfillmentCheckRunning(selectedTimelineNode)" @click="startTimelineFulfillmentCheck(selectedTimelineNode)">
                {{ fulfillmentCheckRunning(selectedTimelineNode) ? 'Agent 核验中' : '让 Agent 核验履约情况' }}
              </button>
            </div>

            <div v-if="latestFulfillmentCheck(selectedTimelineNode)" class="fulfillment-result detail-result">
              <div class="fulfillment-summary-row">
                <strong>{{ fulfillmentConclusionLabel(latestFulfillmentCheck(selectedTimelineNode).conclusion) }}</strong>
                <div class="fulfillment-tags">
                  <span>风险 {{ levelLabel(latestFulfillmentCheck(selectedTimelineNode).riskLevel) }}</span>
                  <span>可信度 {{ levelLabel(latestFulfillmentCheck(selectedTimelineNode).confidenceLevel) }}</span>
                  <span v-if="latestFulfillmentCheck(selectedTimelineNode).needsRecheck">新证据待重新核验</span>
                </div>
              </div>
              <p>{{ latestFulfillmentCheck(selectedTimelineNode).summary || '等待核验结果生成。' }}</p>
              <div v-if="requirementRows(latestFulfillmentCheck(selectedTimelineNode)).length" class="fulfillment-requirements">
                <small>合同要求 · 证据 · 判断 · 缺口</small>
                <article v-for="(row, index) in requirementRows(latestFulfillmentCheck(selectedTimelineNode))" :key="index">
                  <div><span>合同要求</span><p>{{ row.requirement || '待人工复核合同要求' }}</p></div>
                  <div><span>证据</span><p>{{ row.evidence || '暂无充分证据' }}</p></div>
                  <div><span>判断</span><p>{{ row.judgement || row.judgment || '需人工复核' }}</p></div>
                  <div><span>缺口</span><p>{{ row.gap || '暂无明确缺口' }}</p></div>
                  <em>{{ row.required === false ? '辅助项' : '必需项' }}</em>
                </article>
              </div>
              <div v-if="arrayField(latestFulfillmentCheck(selectedTimelineNode).missingEvidenceJson).length" class="fulfillment-list">
                <small>还需补充</small>
                <ul><li v-for="item in arrayField(latestFulfillmentCheck(selectedTimelineNode).missingEvidenceJson)" :key="item">{{ item }}</li></ul>
              </div>
              <details class="fulfillment-history">
                <summary>查看 {{ fulfillmentHistory(selectedTimelineNode).length }} 次核验历史</summary>
                <article v-for="check in fulfillmentHistory(selectedTimelineNode)" :key="check.id">
                  <strong>#{{ check.id }} · {{ fulfillmentConclusionLabel(check.conclusion) }}</strong>
                  <p>{{ check.summary || check.runCurrentStep || '等待 Agent 生成结果' }}</p>
                  <small>{{ formatDate(check.createTime) }} · {{ check.runStatus || check.status }}</small>
                </article>
              </details>
              <div class="fulfillment-confirm">
                <button class="quiet-button" @click="confirmFulfillmentCheck(latestFulfillmentCheck(selectedTimelineNode), 'COMPLETED')">人工确认完成</button>
                <button class="quiet-button" @click="confirmFulfillmentCheck(latestFulfillmentCheck(selectedTimelineNode), 'FAILED')">人工确认失败</button>
                <button class="quiet-button" @click="confirmFulfillmentCheck(latestFulfillmentCheck(selectedTimelineNode), 'NEEDS_MORE_EVIDENCE')">继续补证</button>
              </div>
            </div>
            <p v-else class="fulfillment-empty">先上传证明材料，再让 Agent 按合同要求逐项核验；最终结果仍由人工确认。</p>
          </section>
        </div>
      </section>
    </div>

    <section class="side-section" v-if="availableKnowledge.length">
      <h3>本合同可用知识 · {{ availableKnowledge.length }} 份</h3>
      <div v-for="doc in availableKnowledge" :key="doc.id" class="knowledge-row">
        <span :class="'knowledge-scope ' + scopeClass(doc.contractUsageScope)">{{ knowledgeScopeLabel(doc.contractUsageScope) }}</span>
        <strong>{{ doc.title }}</strong>
        <small>{{ knowledgeChangeSummary(doc) }}</small>
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
          <small v-if="documentPipelineStatusActive(d)" class="doc-pipeline-action">{{ documentPipelineAction(d) }} · {{ d.pipelineProgress || 0 }}%</small>
          <div v-if="documentPipelineStatusActive(d)" class="doc-pipeline-track"><i :style="{ width: `${d.pipelineProgress || 0}%` }"></i></div>
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
        <header class="intake-review-hero">
          <div>
            <span>合同识别核对</span>
            <h3>确认合同识别结果</h3>
            <p>请优先确认我方主体和关键日期，确认后将覆盖合同详情中的基础信息。</p>
          </div>
          <button class="intake-close-button" @click="showIntakeModal = false" aria-label="关闭合同识别结果">关闭</button>
        </header>

        <div class="intake-review-strip">
          <div>
            <span>识别单</span>
            <strong>#{{ intakeFields.intakeId }}</strong>
          </div>
          <div>
            <span>需重点核对</span>
            <strong>{{ intakeAttentionCount }} 项</strong>
          </div>
          <div>
            <span>我方主体</span>
            <strong>{{ intakeOurSideLabel }}</strong>
          </div>
        </div>

        <div class="intake-body intake-review-body">
          <section class="intake-review-main">
            <div class="intake-section-title">
              <span>01</span>
              <div>
                <strong>基础合同事实</strong>
                <small>来自 AI 抽取，可在这里直接修正</small>
              </div>
            </div>

            <div class="intake-grid">
              <div class="intake-field title-wide" :class="intakeFieldTone('contractTitle')">
                <label>合同标题</label>
                <input v-model="intakeFields.title" placeholder="合同标题" />
                <small>{{ intakeFieldStateText('contractTitle') }}</small>
              </div>
              <div class="intake-field" :class="intakeFieldTone('contractType')">
                <label>合同类型</label>
                <select v-model="intakeFields.contractType">
                  <option value="SERVICE_PROCUREMENT">服务采购</option>
                  <option value="GOODS_PURCHASE">货物采购</option>
                  <option value="NDA">保密协议</option>
                  <option value="OTHER">其他</option>
                </select>
                <small>{{ intakeFieldStateText('contractType') }}</small>
              </div>
              <div class="intake-field" :class="intakeFieldTone('amount')">
                <label>合同金额</label>
                <input v-model.number="intakeFields.amount" type="number" placeholder="0" />
                <small>{{ intakeFieldStateText('amount') }}</small>
              </div>
              <div class="intake-field" :class="intakeFieldTone('currency')">
                <label>币种</label>
                <input v-model="intakeFields.currency" placeholder="CNY" />
                <small>{{ intakeFieldStateText('currency') }}</small>
              </div>
            </div>
          </section>

          <aside class="intake-side-panel">
            <div class="intake-section-title">
              <span>02</span>
              <div>
                <strong>确认我方主体</strong>
                <small>风险审查和履约核验都按这个角色分析</small>
              </div>
            </div>

            <div class="our-side-select" v-if="intakeFields.partyA && intakeFields.partyB">
              <div class="side-options">
                <label :class="['side-card', { active: intakeFields.ourSide === 'partyA' }]">
                  <input type="radio" v-model="intakeFields.ourSide" value="partyA" />
                  <span>甲方</span>
                  <strong>{{ intakeFields.partyA }}</strong>
                </label>
                <label :class="['side-card', { active: intakeFields.ourSide === 'partyB' }]">
                  <input type="radio" v-model="intakeFields.ourSide" value="partyB" />
                  <span>乙方</span>
                  <strong>{{ intakeFields.partyB }}</strong>
                </label>
              </div>
            </div>
            <div v-else-if="intakeFields.partyA || intakeFields.partyB" class="our-side-single">
              <label>我方主体</label>
              <input v-model="intakeFields.ourEntity" placeholder="请输入我方公司全称" />
              <label>相对方</label>
              <input v-model="intakeFields.counterparty" placeholder="请输入对方公司全称" />
            </div>
            <p class="intake-role-note">这里不是权限控制，而是合同视角。系统会据此判断我方义务、对方义务和履约风险。</p>
          </aside>

          <section class="intake-review-dates">
            <div class="intake-section-title">
              <span>03</span>
              <div>
                <strong>关键日期</strong>
                <small>影响相对期限、履约提醒和后续核验</small>
              </div>
            </div>
            <div class="intake-grid date-grid">
              <div class="intake-field" :class="intakeFieldTone('signedDate')">
                <label>签订日期</label>
                <input v-model="intakeFields.signedDate" type="date" />
                <small>{{ intakeFieldStateText('signedDate') }}</small>
              </div>
              <div class="intake-field" :class="intakeFieldTone('effectiveDate')">
                <label>生效日期</label>
                <input v-model="intakeFields.effectiveDate" type="date" />
                <small>{{ intakeFieldStateText('effectiveDate') }}</small>
              </div>
              <div class="intake-field" :class="intakeFieldTone('expiryDate')">
                <label>到期日期</label>
                <input v-model="intakeFields.expiryDate" type="date" />
                <small>{{ intakeFieldStateText('expiryDate') }}</small>
              </div>
            </div>
          </section>

          <section class="intake-review-business">
            <div class="intake-section-title">
              <span>04</span>
              <div>
                <strong>业务归属</strong>
                <small>可留空，后续也可以在合同详情中补充</small>
              </div>
            </div>
            <div class="intake-field">
              <label>所属部门</label>
              <input v-model="intakeFields.department" placeholder="如：采购部" />
            </div>
          </section>
        </div>

        <div class="modal-foot intake-actions">
          <button class="quiet-button" @click="showIntakeModal = false">暂不处理</button>
          <button class="primary-button" @click="doConfirmIntake" :disabled="confirming">
            {{ confirming ? '正在更新' : '确认无误，更新合同信息' }}
          </button>
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
          <button class="quiet-button" @click="closeEvidenceLinks">取消</button>
          <button class="primary-button" :disabled="evidenceDialog.saving" @click="saveEvidenceLinks">
            {{ evidenceDialog.saving ? '正在保存' : '保存绑定' }}
          </button>
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
    <section class="risk-workbench" data-section="findings" v-if="c.findings?.length">
      <header class="risk-workbench-head">
        <div>
          <span class="section-kicker">风险研判</span>
          <h3>审查发现</h3>
          <p>先处理高风险和关键动作，展开后查看完整论证、双重依据与谈判建议。</p>
        </div>
        <div class="risk-counts" aria-label="风险数量汇总">
          <span class="high"><strong>{{ findingCountBySeverity('HIGH') }}</strong> 高风险</span>
          <span class="medium"><strong>{{ findingCountBySeverity('MEDIUM') }}</strong> 中风险</span>
          <span class="low"><strong>{{ findingCountBySeverity('LOW') }}</strong> 低风险</span>
        </div>
      </header>

      <section v-for="group in findingGroups" :key="group.key" class="risk-domain-group">
        <div class="risk-domain-head">
          <div>
            <span>{{ group.items.length }} 项发现</span>
            <h4>{{ group.name }}</h4>
          </div>
          <small v-if="group.highCount">{{ group.highCount }} 项需优先处理</small>
        </div>

        <article v-for="f in group.items" :key="f.id" class="finding-card" :class="'finding-' + (f.severity || 'MEDIUM').toLowerCase()">
          <div class="finding-summary-row">
            <div class="finding-rank">
              <span class="finding-sev" :class="'sev-'+ (f.severity||'MEDIUM').toLowerCase()">{{ severityLabel(f.severity) }}</span>
              <small>{{ findingStatusLabel(f.status) }}</small>
            </div>
            <div class="finding-summary-main">
              <div class="finding-title-line">
                <h5>{{ findingHeadline(f) }}</h5>
                <span class="clause-pill">{{ findingDomainName(f) }}</span>
              </div>
              <p class="finding-one-line">{{ findingOneLine(f) }}</p>
              <div class="finding-key-action">
                <span>首要处理</span>
                <strong>{{ findingKeyPoint(f) }}</strong>
              </div>
              <div class="finding-source-strip">
                <span :class="{ active: findingHasContractBasis(f) }">合同原文{{ findingHasContractBasis(f) ? '已引用' : '待补充' }}</span>
                <span :class="{ active: findingHasPolicyBasis(f) }">知识依据{{ findingHasPolicyBasis(f) ? '已引用' : '待补充' }}</span>
                <span>可信度 {{ levelLabel(findingDetail(f).confidenceLevel) }}</span>
                <span v-if="f.suggestedAction">{{ suggestedActionLabel(f.suggestedAction) }}</span>
              </div>
            </div>
            <button
              type="button"
              class="finding-expand"
              :aria-expanded="isFindingExpanded(f)"
              :aria-controls="`finding-detail-${f.id}`"
              @click="toggleFinding(f)"
            >{{ isFindingExpanded(f) ? '收起详情' : '查看详情' }}</button>
          </div>

          <div v-if="isFindingExpanded(f)" :id="`finding-detail-${f.id}`" class="finding-detail">
            <section v-if="findingExplanation(f)">
              <span>风险解释</span>
              <p>{{ findingExplanation(f) }}</p>
            </section>
            <section v-if="findingBusinessImpact(f)">
              <span>可能影响</span>
              <p>{{ findingBusinessImpact(f) }}</p>
            </section>

            <div class="finding-evidence-grid">
              <section>
                <span>合同依据</span>
                <p>{{ findingContractBasis(f) }}</p>
                <blockquote v-if="f.contractCitation?.snippet">{{ f.contractCitation.snippet }}</blockquote>
              </section>
              <section>
                <span>知识库 / 标准条款依据</span>
                <p>{{ findingKnowledgeBasis(f) }}</p>
                <blockquote v-if="f.policyCitation?.snippet">{{ f.policyCitation.snippet }}</blockquote>
              </section>
            </div>

            <div v-if="findingDetail(f).explicitConsequence || findingDetail(f).inferredConsequence" class="finding-consequence-grid">
              <section v-if="findingDetail(f).explicitConsequence">
                <span>合同明确后果</span>
                <p>{{ findingDetail(f).explicitConsequence }}</p>
              </section>
              <section v-if="findingDetail(f).inferredConsequence" class="ai-inference">
                <span>AI 推断，仅供参考，不代表合同约定</span>
                <p>{{ findingDetail(f).inferredConsequence }}</p>
              </section>
            </div>

            <div class="advice-grid" v-if="findingRevisionAdvice(f) || f.negotiationAdvice">
              <section v-if="findingRevisionAdvice(f)">
                <span>条款修改建议</span>
                <p>{{ findingRevisionAdvice(f) }}</p>
              </section>
              <section v-if="f.negotiationAdvice">
                <span>谈判口径</span>
                <p>{{ f.negotiationAdvice }}</p>
              </section>
            </div>

            <section v-if="findingReviewQuestions(f).length" class="verification-list">
              <span>人工复核问题</span>
              <ul><li v-for="point in findingReviewQuestions(f)" :key="point">{{ point }}</li></ul>
            </section>
            <div class="finding-buttons" v-if="f.status === 'OPEN'">
              <button class="quiet-button tiny" @click="updateFinding(f.id, 'REMEDIATED')">标记已修改</button>
              <button class="quiet-button tiny" @click="updateFinding(f.id, 'ACCEPTED_EXCEPTION')">接受例外</button>
              <button class="quiet-button tiny" @click="updateFinding(f.id, 'DISMISSED')">驳回</button>
            </div>
          </div>
        </article>
      </section>
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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api/index.js'
import {
  deriveTimelineAction,
  resolveTimelineDate,
  sanitizeTimelineMeaning,
} from '../utils/contractTimeline.js'

const route = useRoute(); const router = useRouter(); const message = useMessage()
const c = ref({}); const loading = ref(true); const running = ref(false)
const expandedFindings = reactive(new Set())
const showUpload = ref(false)
const uploading = ref(false)
const upload = ref({ mode: 'file', docType: 'MAIN', fileName: '', filePath: '', contentText: '', file: null })
const viewTextDoc = ref(null)
const showIntakeModal = ref(false)
const intakeFields = ref(null)
const confirming = ref(false)
const selectedTask = ref('VERSION_REVIEW')
const timelineBaseSelection = reactive({})
const timelineBaseSaving = ref(false)
const selectedTimelineNode = ref(null)
const evidenceSection = ref(null)
const timelineEvidenceUpload = reactive({ file: null, uploading: false })
const evidenceDialog = reactive({
  visible: false,
  loading: false,
  saving: false,
  node: null,
  available: [],
  selectedIds: [],
})
let caseRefreshTimer = null
let caseRefreshInFlight = false
const caseTimelineNodes = computed(() => Array.isArray(c.value.timelineNodes) ? c.value.timelineNodes : [])
const availableKnowledge = computed(() => Array.isArray(c.value.availableKnowledge) ? c.value.availableKnowledge : [])
const analysisWorkflow = computed(() => c.value.analysisWorkflow || {})
const analysisStages = computed(() => {
  const workflow = analysisWorkflow.value
  const status = String(workflow.status || '').toUpperCase()
  const current = String(workflow.currentStage || '').toUpperCase()
  const parseDone = ['WAITING_CONFIRMATION', 'READY_FOR_REVIEW', 'REVIEWING', 'COMPLETED'].includes(status)
    || ['HUMAN_CONFIRMATION', 'RISK_REVIEW', 'REPORT_READY'].includes(current)
  const confirmDone = ['READY_FOR_REVIEW', 'REVIEWING', 'COMPLETED'].includes(status)
    || ['RISK_REVIEW', 'REPORT_READY'].includes(current)
  const reviewDone = status === 'COMPLETED' || current === 'REPORT_READY'
  const failedStage = status === 'FAILED' ? current : ''
  return [
    { index: '01', key: 'DOCUMENT_PARSE', label: '文档解析', description: '读取正文并建立条款证据', state: failedStage === 'DOCUMENT_PARSE' ? 'error' : parseDone ? 'done' : status === 'PARSING' ? 'active' : 'pending' },
    { index: '02', key: 'HUMAN_CONFIRMATION', label: '人工确认', description: '核对主体、日期和关键字段', state: failedStage === 'HUMAN_CONFIRMATION' ? 'error' : confirmDone ? 'done' : status === 'WAITING_CONFIRMATION' ? 'active' : 'pending' },
    { index: '03', key: 'RISK_REVIEW', label: '风险审查', description: '检索证据并分析适用风险', state: failedStage === 'RISK_REVIEW' ? 'error' : reviewDone ? 'done' : status === 'READY_FOR_REVIEW' || status === 'REVIEWING' ? 'active' : 'pending' },
    { index: '04', key: 'REPORT_READY', label: '报告生成', description: '保存报告、发现和处理建议', state: reviewDone ? 'done' : 'pending' },
  ]
})
const primaryLifecycleCondition = computed(() => {
  const values = Array.isArray(c.value.lifecycleConditions) ? c.value.lifecycleConditions : []
  return values.find(item => item.manualOverride) || values[0] || null
})
const documentPipelineActive = computed(() => {
  const documents = Array.isArray(c.value.documents) ? c.value.documents : []
  return documents.find(document => {
    const status = String(document.pipelineStatus || document.parseStatus || '').toUpperCase()
    return ['UPLOADED', 'PROCESSING', 'PENDING', 'PARSING'].includes(status)
  }) || null
})
const documentPipelineProgress = computed(() => {
  const value = Number(documentPipelineActive.value?.pipelineProgress)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
})
const findingGroups = computed(() => {
  const groups = new Map()
  const severityOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
  for (const finding of Array.isArray(c.value.findings) ? c.value.findings : []) {
    const detail = findingDetail(finding)
    const key = detail.domainKey || finding.clauseType || 'OTHER'
    if (!groups.has(key)) groups.set(key, { key, name: findingDomainName(finding), items: [], highCount: 0 })
    const group = groups.get(key)
    group.items.push(finding)
    if (finding.severity === 'HIGH') group.highCount += 1
  }
  return Array.from(groups.values())
    .map(group => ({
      ...group,
      items: group.items.sort((a, b) => (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9)),
    }))
    .sort((a, b) => b.highCount - a.highCount || a.name.localeCompare(b.name, 'zh-CN'))
})
const intakeAttentionCount = computed(() => {
  const keys = ['contractTitle', 'contractType', 'amount', 'currency', 'signedDate', 'effectiveDate', 'expiryDate']
  return keys.filter(key => intakeFieldTone(key) !== 'ok').length + (intakeFields.value?.ourSide ? 0 : 1)
})
const intakeOurSideLabel = computed(() => {
  if (intakeFields.value?.ourSide === 'partyA') return '甲方'
  if (intakeFields.value?.ourSide === 'partyB') return '乙方'
  return '待确认'
})

const primaryAction = computed(() => {
  const status = c.value.status
  const hasRunning = c.value.runs?.some(r => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(r.status))
  if (analysisWorkflow.value.status === 'WAITING_CONFIRMATION' || status === 'INTAKE_CONFIRMING') {
    return { label: '确认识别结果', taskType: null, disabled: false, openIntake: true }
  }
  if (analysisWorkflow.value.status === 'PARSING' || status === 'INTAKE_PARSING') {
    return { label: '等待文档处理', taskType: null, disabled: true }
  }
  if (hasRunning || status === 'REVIEWING') return { label: '查看审查进度', taskType: null, disabled: false, scrollTo: 'runs' }
  if (c.value.findings?.some(f => f.status === 'OPEN')) return { label: '处理审查发现', taskType: null, disabled: false, scrollTo: 'findings' }
  if (status === 'PENDING_APPROVAL') return { label: '生成审批意见', taskType: 'APPROVAL_DECISION', disabled: false }
  if (['SIGNED', 'IN_FULFILLMENT'].includes(status)) return { label: '提取履约义务', taskType: 'OBLIGATION_EXTRACTION', disabled: false }
  if (!c.value.documents?.length) return { label: '先上传合同', taskType: null, disabled: true }
  return { label: '开始合同审查', taskType: 'CONTRACT_REVIEW', disabled: false }
})

onMounted(() => {
  loadCase()
  caseRefreshTimer = window.setInterval(() => {
    if (documentPipelineActive.value && !caseRefreshInFlight) refreshCase().catch(() => {})
  }, 3500)
})
onBeforeUnmount(() => {
  if (caseRefreshTimer) window.clearInterval(caseRefreshTimer)
})

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
  caseRefreshInFlight = true
  try {
    const r = await api.get(`/api/workspace/contracts/${route.params.id}`)
    c.value = r.data.data
    if (selectedTimelineNode.value) {
      selectedTimelineNode.value = caseTimelineNodes.value.find(node =>
        String(node.sourceId || node.id) === String(selectedTimelineNode.value.sourceId || selectedTimelineNode.value.id)
      ) || selectedTimelineNode.value
    }
    checkPendingIntake()
  } finally {
    caseRefreshInFlight = false
  }
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
    fieldMeta: fields,
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

function intakeFieldMeta(key) {
  return intakeFields.value?.fieldMeta?.[key] || null
}

function intakeFieldCurrentValue(key) {
  const f = intakeFields.value || {}
  const fieldMap = {
    contractTitle: 'title',
    contractType: 'contractType',
    amount: 'amount',
    currency: 'currency',
    signedDate: 'signedDate',
    effectiveDate: 'effectiveDate',
    expiryDate: 'expiryDate',
  }
  return f[fieldMap[key]]
}

function intakeFieldTone(key) {
  const value = intakeFieldCurrentValue(key)
  if (value === null || value === undefined || value === '') return 'missing'
  const confidence = Number(intakeFieldMeta(key)?.confidence || 0)
  return confidence >= 0.85 ? 'ok' : 'check'
}

function intakeFieldStateText(key) {
  const tone = intakeFieldTone(key)
  if (tone === 'missing') return '待补充'
  if (tone === 'check') return '建议人工核对'
  return 'AI 已识别'
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

function documentPipelineAction(document) {
  if (document?.pipelineAction) return document.pipelineAction
  const labels = {
    UPLOADED: '正在准备合同文件',
    DOCUMENT_START: '正在读取合同文件',
    TEXT_PARSING: '正在读取合同文字',
    PDF_PARSING: '正在读取合同文字',
    PDF_RECOGNITION_OPTIMIZATION: '正在优化文字识别',
    DOC_CONVERSION: '正在整理 Word 文档',
    DOCX_PARSING: '正在读取 Word 文档',
    CLAUSE_SPLITTING: '正在识别合同条款',
    CLAUSE_PERSISTING: '正在保存条款证据',
    TIMELINE_EXTRACTING: '正在提取合同时间节点',
    LIFECYCLE_EXTRACTING: '正在识别合同结束条件',
    EMBEDDING: '正在建立合同语义检索',
    INDEXING: '正在整理合同检索索引',
  }
  const stage = String(document?.pipelineStage || '').toUpperCase()
  return labels[stage] || (String(document?.pipelineStatus || '').toUpperCase() === 'FAILED' ? '合同解析失败' : '正在处理合同文件')
}
function documentPipelineStatusActive(document) {
  return ['UPLOADED', 'PROCESSING', 'PENDING', 'PARSING'].includes(
    String(document?.pipelineStatus || document?.parseStatus || '').toUpperCase()
  )
}

async function startRun(taskType) {
  running.value = true
  try {
    await api.post(`/api/workspace/contracts/${route.params.id}/runs`, { taskType, triggerType: 'MANUAL', question: taskQuestion(taskType) })
    message.success('Agent 任务已创建')
    setTimeout(refreshCase, 2000)
  } catch (e) { message.error(e.response?.data?.message || e.message || '启动失败') }
  finally { running.value = false }
}

function handlePrimaryAction() {
  const action = primaryAction.value
  if (action.openIntake) {
    openIntakeConfirmation()
    return
  }
  if (action.scrollTo) {
    document.querySelector(`[data-section="${action.scrollTo}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  if (action.taskType) startRun(action.taskType)
}

function openIntakeConfirmation() {
  if (!intakeFields.value) checkPendingIntake()
  if (intakeFields.value) showIntakeModal.value = true
  else message.info('识别结果还未准备好，请等待文档解析完成')
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
  return (node.sourceType || node.source) === 'PIPELINE_TIMELINE'
    && Number(node.sourceId || 0) > 0
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
async function openTimelineDetail(node, focusEvidence = false) {
  selectedTimelineNode.value = node
  if (focusEvidence) {
    await nextTick()
    evidenceSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
function closeTimelineDetail() {
  selectedTimelineNode.value = null
  timelineEvidenceUpload.file = null
}
function chooseTimelineEvidenceFile(event) {
  timelineEvidenceUpload.file = event.target.files?.[0] || null
}
async function uploadTimelineEvidence(node) {
  const file = timelineEvidenceUpload.file
  if (!file || timelineEvidenceUpload.uploading || !canFulfillmentCheck(node)) return
  timelineEvidenceUpload.uploading = true
  try {
    const form = new FormData()
    form.append('file', file)
    const stored = await api.post('/api/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
    const filePath = stored.data.data?.url || ''
    if (!filePath) throw new Error('文件存储未返回可用路径')
    const uploaded = await api.post(`/api/workspace/contracts/${route.params.id}/fulfillment-evidence`, {
      fileName: file.name,
      filePath,
      fileSize: file.size,
    })
    const documentId = Number(uploaded.data.data?.uploadedDocumentId || 0)
    const links = await api.get(`/api/workspace/contracts/${route.params.id}/timeline/${node.sourceId}/evidence-links`)
    const linkedIds = Array.isArray(links.data.data?.linkedDocumentIds)
      ? links.data.data.linkedDocumentIds.map(Number).filter(Boolean)
      : []
    if (documentId && !linkedIds.includes(documentId)) linkedIds.push(documentId)
    await api.put(`/api/workspace/contracts/${route.params.id}/timeline/${node.sourceId}/evidence-links`, {
      documentIds: linkedIds,
    })
    timelineEvidenceUpload.file = null
    message.success('证明文件已上传并绑定当前节点，解析完成后可发起 Agent 核验')
    await refreshCase()
  } catch (e) {
    message.error(uploadErrorMessage(e, '履约证明上传失败'))
  } finally {
    timelineEvidenceUpload.uploading = false
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
function timelineNeedsRecognition(node) {
  const citation = timelineCitation(node)
  return ['NEEDS_RECOGNITION', 'NEEDS_REVIEW'].includes(String(node?.status || '').toUpperCase())
    && Boolean(citation?.textQuality?.requiresReview || citation?.textQuality?.level === 'LOW' || node?.status === 'NEEDS_RECOGNITION')
}
function timelineDateLabel(node) {
  const result = relativeDateResult(node)
  if (result.resolvedDate) return result.resolvedDate
  if (timelineDateValue(node)) return timelineDateValue(node)
  return timelineConditionDisplay(node) || '待确认'
}
function timelineMeaning(node) {
  const meaning = sanitizeTimelineMeaning(node.businessMeaning || node.description || '')
  if (meaning && !isGenericTimelineMeaning(meaning)) return meaning
  return timelineAction(node)
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
function timelineFullQuote(node) {
  const citation = timelineCitation(node)
  return citation?.fullQuote || citation?.clauseContent || timelineQuote(node)
}
function timelineAction(node) {
  const enrichment = timelineCitation(node)?.timelineEnrichment || {}
  const enriched = sanitizeTimelineMeaning(enrichment.businessMeaning || '')
  if (enriched && !isGenericTimelineMeaning(enriched)) return enriched
  const sourceText = timelineCondition(node)
    ? (timelineFullQuote(node) || timelineQuote(node))
    : (timelineQuote(node) || timelineFullQuote(node))
  const action = deriveTimelineAction(sourceText, timelineConditionDisplay(node))
  if (action && !isGenericTimelineMeaning(action)) return action
  return enriched || sanitizeTimelineMeaning(node.businessMeaning || '')
}
function timelineQualityNote(node) {
  return timelineNeedsRecognition(node)
    ? '当前节点已保留供参考，但识别文字可能有误；请核对合同原页后再用于履约判断。'
    : ''
}
function isGenericTimelineMeaning(value) {
  const text = sanitizeTimelineMeaning(value)
  return !text
    || /^(?:需要跟踪|需要关注|来自合同正文|来自合同或案件字段|合同时间节点|请关注[“"]?合同期限)/.test(text)
    || /来源\s*=|原文片段/.test(text)
}
function timelineConditionDisplay(node) {
  const raw = String(timelineCondition(node) || '').replace(/\s+/g, ' ').trim()
  if (!raw) return ''
  let text = raw
    .replace(/^[^:：]{0,16}[:：]\s*(?=(?:两台|合同|乙方|甲方|对方|我方|收到|不可抗力|期满|验收|交付|付款|书面通知))/i, '')
    .replace(/^["'`]?f?l?\\?\d{0,2}\s*(?=方)/i, '一')
    .replace(/[:：]\s*[\\|Il]{0,3}\s*0\s*(?=(?:天|日|个月|月|年))/gi, '：数字待核对')
  return text || raw
}
function lifecycleEvents(condition) {
  const value = condition?.conditions
  if (Array.isArray(value)) return value
  if (value && Array.isArray(value.events)) return value.events
  return []
}
function lifecycleSourceLabel(condition) {
  return condition?.source === 'LLM_ENRICHED' ? '合同原文 · Agent 复核' : '合同原文 · 待复核'
}
function timelineContractRequirements(node) {
  const values = timelineCitation(node)?.timelineEnrichment?.contractRequirements
  if (Array.isArray(values) && values.length) return values.map(String).filter(Boolean)
  const action = timelineAction(node)
  if (!action || /需要关注|来自合同|时间节点/.test(action)) return []
  return [action]
}
function timelineAiSuggestions(node) {
  const values = timelineCitation(node)?.timelineEnrichment?.aiSuggestions
  return Array.isArray(values) ? values.map(String).filter(Boolean) : []
}
function timelineEnrichmentReason(node) {
  const citation = timelineCitation(node)
  return citation?.timelineEnrichment?.reason || ''
}
function timelineConsequence(node) {
  const check = latestFulfillmentCheck(node) || {}
  const enrichment = timelineCitation(node)?.timelineEnrichment || {}
  return {
    explicit: check.explicitConsequence || enrichment.explicitConsequence || '',
    ai: check.aiRisk || enrichment.aiRisk || '',
  }
}
function relativeDateResult(node) {
  return resolveTimelineDate({
    condition: timelineCondition(node),
    contract: c.value,
    manualBaseDate: timelineBaseSelection[timelineKey(node)] || '',
  })
}
function setTimelineBaseDate(node, value) {
  timelineBaseSelection[timelineKey(node)] = value
}
function resetTimelineBaseDate(node) {
  delete timelineBaseSelection[timelineKey(node)]
}
function timelineBaseField(node) {
  const condition = String(timelineCondition(node) || '').replace(/\s+/g, '')
  if (/签订合同后|签署后|签订后/.test(condition)) return { key: 'signedDate', label: '合同签订日期' }
  if (/生效后|生效日起|自生效/.test(condition)) return { key: 'effectiveDate', label: '合同生效日期' }
  if (/期满前|到期前|合同期满前/.test(condition)) return { key: 'expiryDate', label: '合同到期日期' }
  return null
}
async function saveTimelineBaseDate(node) {
  const field = timelineBaseField(node)
  const value = timelineBaseSelection[timelineKey(node)]
  if (!field || !value || timelineBaseSaving.value) return
  timelineBaseSaving.value = true
  try {
    const response = await api.put(`/api/workspace/contracts/${route.params.id}`, { [field.key]: value })
    c.value = response.data.data
    delete timelineBaseSelection[timelineKey(node)]
    message.success(`${field.label}已保存，相关时间节点已重新计算`)
  } catch (e) {
    message.error(e.response?.data?.message || `${field.label}保存失败`)
  } finally {
    timelineBaseSaving.value = false
  }
}
function timelineDateKind(node) {
  if (timelineCondition(node)) {
    return relativeDateResult(node).resolvedDate ? '按合同相对期限计算' : '条件触发，日期待补充'
  }
  return timelineDateValue(node) ? '合同明确日期' : '日期待确认'
}
function evidenceSnapshotLabel(item) {
  if (!item) return '未命中快照'
  const parts = [
    item.fileName || item.title || `文档#${item.documentId || ''}`,
    item.version != null ? `v${item.version}` : '',
    item.contentHash ? `hash ${String(item.contentHash).slice(0, 10)}` : '',
    item.matchReason || '',
    item.snippet || item.contentSnippet || item.contentHash || '',
  ].filter(Boolean)
  return parts.join(' · ')
}
function stripAiRiskPrefix(value) {
  return String(value || '').replace(/^AI 推断，仅供参考[:：]\s*/, '')
}
function knowledgeScopeLabel(scope) {
  return { GLOBAL:'全部合同', SPECIFIC_CASES:'指定合同', DISABLED:'不用于合同' }[scope] || '不用于合同'
}
function scopeClass(scope) {
  return String(scope || 'DISABLED').toLowerCase().replace(/_/g, '-')
}
function knowledgeChangeSummary(doc) {
  const summary = doc.contractUsageSummary || '用于合同风险审查与履约核验'
  const updated = formatDate(doc.contractUsageUpdatedAt)
  const space = doc.spaceName ? ` · ${doc.spaceName}` : ''
  return `${summary}${space}${updated ? ' · 最近变更 ' + updated : ''}`
}
function timelineSourceLabel(node) {
  const source = node.source || node.sourceType || ''
  return {
    RULE_EXTRACTED: '合同原文',
    RULE_CANDIDATE: '合同原文',
    LLM_ENRICHED: '合同原文 · AI 整理',
    CASE_FIELD: '案件信息',
    PIPELINE_TIMELINE: '合同原文',
    OBLIGATION: '合同义务',
    AGENT_OBLIGATION: '合同义务 · AI 整理',
  }[source] || (source ? '合同原文' : '时间节点')
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
function runStatusLabel(s) { return { CREATED:'排队', CONTEXT_BUILDING:'分析中', PLANNING:'规划中', ANALYZING:'审查中', VERIFYING:'验证中', WAITING_HUMAN:'等待人工确认', COMPLETED:'完成', FAILED:'失败', CANCELLED:'已取消' }[s] || s }
function runTypeLabel(t) { return { CONTRACT_REVIEW:'合同审查', CONTRACT_INTAKE:'合同发起', APPROVAL_DECISION:'审批决策', VERSION_REVIEW:'版本复核', OBLIGATION_EXTRACTION:'义务提取', FULFILLMENT_CHECK:'履约核验' }[t] || t }
function taskQuestion(t) { return { CONTRACT_REVIEW:'审查当前合同版本', CONTRACT_INTAKE:'发起合同材料准备', APPROVAL_DECISION:'生成合同审批意见', VERSION_REVIEW:'复核合同版本变化', OBLIGATION_EXTRACTION:'提取合同履约义务', FULFILLMENT_CHECK:'核验合同时间节点履约证据' }[t] || '执行合同任务' }
function workflowStatusLabel(s) { return { PARSING:'文档处理中', WAITING_CONFIRMATION:'待人工确认', READY_FOR_REVIEW:'待风险审查', REVIEWING:'风险审查中', COMPLETED:'分析完成', FAILED:'需要处理' }[s] || '分析流程' }
function workflowStatusClass(s) { return { PARSING:'active', WAITING_CONFIRMATION:'attention', READY_FOR_REVIEW:'ready', REVIEWING:'active', COMPLETED:'done', FAILED:'error' }[s] || '' }
function findingStatusLabel(s) { return { OPEN:'未处理', REMEDIATED:'已修改', ACCEPTED_EXCEPTION:'已接受例外', DISMISSED:'已驳回' }[s] || s }
function obligationStatusLabel(s) { return { PLANNED:'计划中', DUE_SOON:'即将到期', COMPLETED:'已完成', OVERDUE:'已逾期', ESCALATED:'已升级', WAIVED:'已豁免' }[s] || s }
function severityLabel(s) { return { HIGH:'高危', MEDIUM:'中危', LOW:'低危' }[s] || s || '中危' }
function riskStatusLabel(s) { return { LOW_RISK:'低风险', MEDIUM_RISK:'中风险', HIGH_RISK:'高风险' }[s] || s || '未评分' }
function clauseTypeLabel(t) { return { LIABILITY:'责任违约', PAYMENT:'商务付款', CONFIDENTIALITY:'保密合规', ACCEPTANCE:'验收交付', TERMINATION:'终止续签', IP:'知识产权', DATA_PROTECTION:'数据保护', OTHER:'其他' }[t] || t || '其他' }
function suggestedActionLabel(a) { return { CREATE_NEGOTIATION_TASK:'创建协商任务', REQUEST_MATERIAL:'补充材料', REQUEST_LEGAL_REVIEW:'法务复核', SCHEDULE_REMINDER:'设置提醒' }[a] || a }
function findingDetail(finding) {
  const value = finding?.detailJson
  if (!value) return {}
  if (typeof value === 'object') return value
  try { return JSON.parse(value) || {} } catch { return {} }
}
function findingDomainName(finding) {
  return findingDetail(finding).domainName || clauseTypeLabel(finding?.clauseType)
}
function findingHeadline(finding) {
  return findingDetail(finding).frontendDisplay?.headline || finding?.title || '合同风险待复核'
}
function findingOneLine(finding) {
  const detail = findingDetail(finding)
  return detail.frontendDisplay?.summary || detail.oneLineSummary || finding?.description || '请展开查看风险依据与处理建议。'
}
function findingKeyPoint(finding) {
  const detail = findingDetail(finding)
  return detail.frontendDisplay?.primaryAction || detail.keyPoint || findingRevisionAdvice(finding) || suggestedActionLabel(finding?.suggestedAction) || '人工复核合同条款与适用规则'
}
function findingExplanation(finding) {
  const detail = findingDetail(finding)
  return detail.riskExplanation || finding?.description || ''
}
function findingBusinessImpact(finding) {
  const detail = findingDetail(finding)
  return detail.businessImpact || finding?.impact || ''
}
function findingRevisionAdvice(finding) {
  const detail = findingDetail(finding)
  return detail.revisionAdvice || finding?.remediationAdvice || ''
}
function findingContractBasis(finding) {
  return findingDetail(finding).contractBasis?.summary || citationLabel(finding?.contractCitation)
}
function findingKnowledgeBasis(finding) {
  return findingDetail(finding).knowledgeBasis?.summary || policyLabel(finding?.policyCitation, finding?.ruleKey)
}
function findingHasContractBasis(finding) {
  const detail = findingDetail(finding)
  return Boolean(finding?.contractCitation || detail.contractBasis?.citations?.length || detail.contractCitationIds?.length)
}
function findingHasPolicyBasis(finding) {
  const detail = findingDetail(finding)
  return Boolean(finding?.policyCitation || detail.knowledgeBasis?.citations?.length || detail.policyCitationIds?.length)
}
function findingReviewQuestions(finding) {
  const detail = findingDetail(finding)
  const values = [
    ...(Array.isArray(detail.reviewQuestions) ? detail.reviewQuestions : []),
    ...(Array.isArray(finding?.verificationPoints) ? finding.verificationPoints : []),
  ].map(String).filter(Boolean)
  return [...new Set(values)]
}
function findingCountBySeverity(severity) {
  return (c.value.findings || []).filter(finding => finding.severity === severity).length
}
function findingExpansionKey(finding) { return String(finding?.id || finding?.title || '') }
function isFindingExpanded(finding) { return expandedFindings.has(findingExpansionKey(finding)) }
function toggleFinding(finding) {
  const key = findingExpansionKey(finding)
  if (expandedFindings.has(key)) expandedFindings.delete(key)
  else expandedFindings.add(key)
}
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
.analysis-workflow-panel{margin:-8px 0 24px;padding:17px 18px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-left:4px solid var(--atlas-primary);border-radius:4px}
.analysis-workflow-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.analysis-workflow-head .section-kicker{display:block;margin-bottom:4px;color:var(--atlas-subtle);font-size:10px;font-weight:900;letter-spacing:.06em;text-transform:uppercase}
.analysis-workflow-head h3{margin:0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:17px}
.analysis-workflow-head p{margin:5px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.55}
.workflow-status{flex:0 0 auto;padding:5px 8px;border-radius:3px;font-size:10px;font-weight:900}
.workflow-status.active{color:#315d8b;background:#edf4fa}.workflow-status.attention{color:#8a5b14;background:#fff4db}.workflow-status.ready{color:#246744;background:#eaf6ef}.workflow-status.done{color:#246744;background:#dceee3}.workflow-status.error{color:#a33f39;background:#fff0ee}
.analysis-workflow-stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:15px}
.analysis-workflow-stage{display:flex;align-items:flex-start;gap:8px;min-width:0;padding:10px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:3px}
.workflow-stage-mark{display:inline-flex;align-items:center;justify-content:center;flex:0 0 22px;width:22px;height:22px;border-radius:3px;background:#e9edf0;color:var(--atlas-subtle);font-size:10px;font-weight:900}
.analysis-workflow-stage strong{display:block;color:var(--atlas-text);font-size:11px;line-height:1.4}.analysis-workflow-stage small{display:block;margin-top:3px;color:var(--atlas-subtle);font-size:10px;line-height:1.45}
.analysis-workflow-stage.done{border-color:#b9d8c5;background:#f4faf6}.analysis-workflow-stage.done .workflow-stage-mark{color:#fff;background:#347254}.analysis-workflow-stage.active{border-color:#b7cde0;background:#f5f9fc}.analysis-workflow-stage.active .workflow-stage-mark{color:#fff;background:var(--atlas-primary)}.analysis-workflow-stage.error{border-color:#e4b2ad;background:#fff7f6}.analysis-workflow-stage.error .workflow-stage-mark{color:#fff;background:#b35c56}
.analysis-workflow-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px}.analysis-workflow-foot small{color:var(--atlas-subtle);font-size:10px;word-break:break-all}.analysis-workflow-foot .small{min-height:32px;padding:0 10px;font-size:11px}
.document-progress-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 18px;align-items:center;margin:-8px 0 24px;padding:16px 18px;border:1px solid #b7cde0;border-left:4px solid var(--atlas-primary);background:#f5f9fc}
.document-progress-copy{min-width:0}.document-progress-copy h3{margin:3px 0 4px;color:var(--atlas-text);font-size:14px;line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.document-progress-copy p{margin:0;color:var(--atlas-muted);font-size:11px;line-height:1.55}.document-progress-value{display:flex;flex-direction:column;align-items:flex-end;gap:2px}.document-progress-value strong{color:var(--atlas-primary);font-size:20px;font-variant-numeric:tabular-nums}.document-progress-value span{color:var(--atlas-subtle);font-size:10px}.document-progress-track{grid-column:1 / -1;height:4px;overflow:hidden;background:#dbe6f0}.document-progress-track i{display:block;height:100%;background:var(--atlas-primary);transition:width .35s ease}
.contract-diagnostics{display:grid;gap:10px;margin:-8px 0 24px}
.contract-end-condition{display:grid;grid-template-columns:88px minmax(0,1fr);gap:16px;align-items:start;padding:15px 17px;border:1px solid var(--atlas-border);background:var(--atlas-surface)}
.contract-end-condition{border-left:4px solid #347254;background:#f3f8f5}
.diagnostic-mark{color:var(--atlas-subtle);font-size:10px;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
.contract-end-condition strong{display:block;color:var(--atlas-text);font-size:13px;line-height:1.5}
.contract-end-condition ol{display:grid;gap:5px;margin:9px 0 7px;padding:0;list-style:none;counter-reset:end-condition}
.contract-end-condition li{color:var(--atlas-text);font-size:12px;line-height:1.55;counter-increment:end-condition}
.contract-end-condition li:before{content:counter(end-condition);display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-right:6px;color:#347254;background:#dceee3;border-radius:3px;font-size:10px;font-weight:900}
.contract-end-condition li span{margin-right:5px;color:#347254;font-size:10px;font-weight:900}
.contract-end-condition small{color:var(--atlas-subtle);font-size:10px;line-height:1.5}

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
.history-grid{display:grid;gap:6px;margin-top:8px}
.history-grid div{padding:7px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.history-grid span,.history-snapshots span{display:block;margin-bottom:4px;color:var(--atlas-primary);font-size:9px;font-weight:900}
.history-grid p{margin:3px 0!important;color:var(--atlas-text)!important}
.history-snapshots{margin-top:8px;padding:7px;background:rgba(66,111,166,.05);border:1px solid rgba(66,111,166,.14);border-radius:4px}
.history-snapshots.warn{background:rgba(179,92,86,.06);border-color:rgba(179,92,86,.14)}
.history-snapshots.warn span{color:#b35c56}
.history-snapshots small{margin-top:3px;line-height:1.45}
.history-consequence{margin-top:8px;padding:7px;background:var(--atlas-surface);border-left:3px solid var(--atlas-warning)}
.history-consequence p{margin:3px 0!important;color:var(--atlas-text)!important}
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
.doc-row{flex-wrap:wrap}.doc-pipeline-action{flex:1 0 100%;margin-left:78px;color:var(--atlas-primary)!important}.doc-pipeline-track{flex:1 0 100%;height:3px;margin-left:78px;overflow:hidden;background:var(--atlas-border)}.doc-pipeline-track i{display:block;height:100%;background:var(--atlas-primary);transition:width .35s ease}
.risk-workbench{margin:28px 0 22px;padding:0;border-top:2px solid var(--atlas-text);border-bottom:1px solid var(--atlas-border)}
.risk-workbench-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:18px 0 16px}
.risk-workbench-head h3{margin:3px 0 5px;font-family:var(--atlas-font-display);font-size:22px;color:var(--atlas-text)}
.risk-workbench-head p{max-width:650px;margin:0;color:var(--atlas-muted);font-size:12px;line-height:1.6}
.section-kicker{color:var(--atlas-primary);font-size:10px;font-weight:900}
.risk-counts{display:flex;align-items:stretch;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface)}
.risk-counts>span{display:flex;align-items:baseline;gap:5px;min-width:82px;padding:9px 11px;border-left:1px solid var(--atlas-border);color:var(--atlas-muted);font-size:10px;font-weight:800;white-space:nowrap}
.risk-counts>span:first-child{border-left:0}
.risk-counts strong{font-size:19px;line-height:1;color:var(--atlas-text)}
.risk-counts .high strong{color:#9f3f3a}.risk-counts .medium strong{color:#8b642d}.risk-counts .low strong{color:#387052}
.risk-domain-group{padding:14px 0 18px;border-top:1px solid var(--atlas-border)}
.risk-domain-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:9px}
.risk-domain-head div{display:flex;align-items:baseline;gap:9px}
.risk-domain-head span{color:var(--atlas-subtle);font-size:10px;font-weight:800}
.risk-domain-head h4{margin:0;color:var(--atlas-text);font-size:14px}
.risk-domain-head small{color:#9f3f3a;font-size:10px;font-weight:800}
.finding-sev{display:inline-flex;align-items:center;justify-content:center;min-width:54px;padding:4px 7px;border-radius:3px;font-size:10px;font-weight:900}
.finding-sev.sev-high{color:#903933;background:#f8e7e5;border:1px solid #e7bbb7}
.finding-sev.sev-medium{color:#7b591f;background:#fbf2df;border:1px solid #ead4a2}
.finding-sev.sev-low{color:#2f694b;background:#e8f3ec;border:1px solid #bfd8c8}
.finding-card{position:relative;margin-top:8px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-left:4px solid #8290a0;border-radius:4px;overflow:hidden}
.finding-card.finding-high{border-left-color:#a84640}.finding-card.finding-medium{border-left-color:#a67834}.finding-card.finding-low{border-left-color:#477b5d}
.finding-summary-row{display:grid;grid-template-columns:68px minmax(0,1fr) auto;gap:14px;align-items:start;padding:15px 16px}
.finding-rank{display:flex;flex-direction:column;align-items:flex-start;gap:7px}
.finding-rank small{color:var(--atlas-subtle);font-size:9px;font-weight:700}
.finding-summary-main{min-width:0}
.finding-title-line{display:flex;align-items:flex-start;gap:9px;flex-wrap:wrap}
.finding-title-line h5{min-width:0;margin:0;color:var(--atlas-text);font-size:15px;line-height:1.45}
.clause-pill{padding:2px 6px;border:1px solid var(--atlas-border);border-radius:3px;color:var(--atlas-muted);font-size:9px;font-weight:800;background:var(--atlas-bg)}
.finding-one-line{margin:6px 0 0;color:var(--atlas-muted);font-size:12px;line-height:1.65}
.finding-key-action{display:flex;align-items:flex-start;gap:9px;margin-top:9px;padding:8px 10px;background:#f2f6f9;border-left:3px solid var(--atlas-primary)}
.finding-key-action span{flex:0 0 auto;color:var(--atlas-primary);font-size:9px;font-weight:900}
.finding-key-action strong{color:var(--atlas-text);font-size:11px;line-height:1.5}
.finding-source-strip{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.finding-source-strip span{padding:3px 6px;border:1px solid var(--atlas-border);border-radius:3px;color:var(--atlas-subtle);background:var(--atlas-bg);font-size:9px;font-weight:800}
.finding-source-strip span.active{color:#31634a;background:#edf6f0;border-color:#c6dccd}
.finding-expand{min-width:78px;min-height:36px;padding:0 10px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-primary);font-size:11px;font-weight:900;cursor:pointer;transition:border-color .18s ease,background .18s ease}
.finding-expand:hover{border-color:var(--atlas-primary);background:#f3f7fa}.finding-expand:focus-visible{outline:2px solid var(--atlas-primary);outline-offset:2px}
.finding-detail{padding:16px 16px 17px 98px;background:#f8fafc;border-top:1px solid var(--atlas-border)}
.finding-detail>section{margin-top:13px}.finding-detail>section:first-child{margin-top:0}
.finding-detail span,.finding-evidence-grid span,.finding-consequence-grid span,.advice-grid span,.verification-list>span{display:block;margin-bottom:5px;color:var(--atlas-subtle);font-size:10px;font-weight:900}
.finding-detail p{margin:0;color:var(--atlas-text);font-size:12px;line-height:1.75;white-space:pre-wrap}
.finding-evidence-grid,.finding-consequence-grid,.advice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:13px}
.finding-evidence-grid section,.finding-consequence-grid section,.advice-grid section{padding:11px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.finding-evidence-grid section:first-child{border-top:3px solid #416f9b}.finding-evidence-grid section:last-child{border-top:3px solid #477b5d}
.finding-evidence-grid blockquote{margin:8px 0 0;padding:8px 9px;background:var(--atlas-bg);border-left:2px solid var(--atlas-border);color:var(--atlas-muted);font-size:11px;line-height:1.6}
.finding-consequence-grid section{border-left:3px solid #a84640}.finding-consequence-grid .ai-inference{border-left-color:#a67834;background:#fffaf0}
.verification-list{margin-top:13px;padding:11px;background:#edf6f0;border:1px solid #c6dccd;border-radius:4px}
.verification-list ul{margin:0;padding-left:16px;color:var(--atlas-text);font-size:12px;line-height:1.7}
.verification-list li+li{margin-top:3px}
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
.intake-confirm{width:min(920px,calc(100vw - 32px));max-width:920px;overflow:hidden;border-radius:8px;border:1px solid #c8d3df;background:#fbfcfe;box-shadow:0 24px 80px rgba(30,45,60,.28)}
.intake-review-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:22px 26px 20px;background:linear-gradient(135deg,#eef4fa 0%,#f8fbfd 62%,#f8f3ea 100%);border-bottom:1px solid var(--atlas-border)}
.intake-review-hero span{display:block;color:var(--atlas-primary);font-size:10px;font-weight:900;letter-spacing:.04em}
.intake-review-hero h3{margin:5px 0 7px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:28px;line-height:1.2}
.intake-review-hero p{max-width:560px;margin:0;color:var(--atlas-muted);font-size:13px;line-height:1.65}
.intake-close-button{min-height:36px;padding:0 13px;border:1px solid var(--atlas-border);border-radius:4px;background:rgba(255,255,255,.72);color:var(--atlas-muted);font-size:12px;font-weight:900;cursor:pointer}
.intake-close-button:hover{border-color:var(--atlas-primary);color:var(--atlas-primary)}
.intake-review-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-bottom:1px solid var(--atlas-border);background:#fff}
.intake-review-strip div{padding:13px 20px;border-right:1px solid var(--atlas-border)}
.intake-review-strip div:last-child{border-right:0}
.intake-review-strip span{display:block;margin-bottom:4px;color:var(--atlas-subtle);font-size:10px;font-weight:900}
.intake-review-strip strong{display:block;color:var(--atlas-text);font-size:15px}
.intake-body.intake-review-body{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(280px,.9fr);gap:0;max-height:62vh;padding:0;overflow:auto;background:#f6f8fb}
.intake-review-main,.intake-side-panel,.intake-review-dates,.intake-review-business{padding:20px 22px;border-bottom:1px solid var(--atlas-border)}
.intake-review-main{background:#fbfcfe;border-right:1px solid var(--atlas-border)}
.intake-side-panel{background:#f7fafc}
.intake-review-dates{grid-column:1/-1;background:#fff}
.intake-review-business{grid-column:1/-1;background:#f7fafc;border-bottom:0}
.intake-section-title{display:flex;align-items:flex-start;gap:10px;margin-bottom:14px}
.intake-section-title>span{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border:1px solid #c8d9e8;border-radius:4px;background:#eef5fb;color:var(--atlas-primary);font-size:10px;font-weight:900}
.intake-section-title strong{display:block;color:var(--atlas-text);font-size:14px}
.intake-section-title small{display:block;margin-top:3px;color:var(--atlas-muted);font-size:11px;line-height:1.45}
.intake-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.intake-grid.date-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.intake-field{display:flex;min-width:0;flex-direction:column;gap:6px;padding:11px 12px;border:1px solid var(--atlas-border);border-left-width:3px;border-radius:6px;background:#fff}
.intake-field.title-wide{grid-column:1/-1}
.intake-field.ok{border-left-color:#3f7f5d}
.intake-field.check{border-left-color:#b98536;background:#fffaf2}
.intake-field.missing{border-left-color:#b35c56;background:#fff7f7}
.intake-field label{font-size:11px;font-weight:900;color:var(--atlas-subtle)}
.intake-field input,.intake-field select{width:100%;min-height:38px;box-sizing:border-box;padding:4px 8px;border:1px solid #cbd7e3;border-radius:4px;background:#fbfcfe;color:var(--atlas-text);font-size:13px}
.intake-field input:focus,.intake-field select:focus{outline:2px solid rgba(66,111,166,.16);border-color:var(--atlas-primary)}
.intake-field small{color:var(--atlas-muted);font-size:10px;font-weight:800}
.intake-confirm .our-side-select,.intake-confirm .our-side-single{margin:0;padding:0;background:transparent;border:0}
.intake-confirm .side-options{display:grid;grid-template-columns:1fr;gap:10px}
.intake-confirm .side-card{position:relative;display:grid;grid-template-columns:18px 44px minmax(0,1fr);gap:10px;align-items:center;min-height:68px;padding:13px;border:1px solid #cbd7e3;border-radius:6px;background:#fff;cursor:pointer;transition:background-color .18s ease,border-color .18s ease,box-shadow .18s ease}
.intake-confirm .side-card:hover{border-color:var(--atlas-primary);background:#f7fbff}
.intake-confirm .side-card.active{border-color:var(--atlas-primary);background:#eef5fb;box-shadow:inset 0 0 0 1px var(--atlas-primary)}
.intake-confirm .side-card input[type=radio]{width:16px;height:16px;accent-color:var(--atlas-primary)}
.intake-confirm .side-card span{display:inline-flex;align-items:center;justify-content:center;height:24px;border-radius:4px;background:#edf2f7;color:var(--atlas-primary);font-size:11px;font-weight:900}
.intake-confirm .side-card strong{min-width:0;color:var(--atlas-text);font-size:14px;line-height:1.45;word-break:break-word}
.intake-confirm .our-side-single{display:grid;gap:8px}
.intake-confirm .our-side-single label{color:var(--atlas-subtle);font-size:11px;font-weight:900}
.intake-confirm .our-side-single input{width:100%;min-height:38px;padding:4px 10px;border:1px solid var(--atlas-border);border-radius:4px;background:#fff;font-size:13px}
.intake-role-note{margin:13px 0 0;padding:10px 12px;border-left:3px solid var(--atlas-primary);background:#fff;color:var(--atlas-muted);font-size:12px;line-height:1.65}
.intake-actions{display:flex;justify-content:flex-end;gap:10px;padding:15px 22px;background:#fff;border-top:1px solid var(--atlas-border)}
.blank-state{padding:16px 0 4px;color:var(--atlas-muted);font-size:12px}
.loading-block{display:flex;align-items:center;justify-content:center;gap:9px;min-height:50vh;color:var(--atlas-muted)}
.loader{width:20px;height:20px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* Fulfillment timeline workbench */
.timeline-panel{padding:0;overflow:hidden}
.timeline-panel-head{margin:0;padding:18px 20px;border-bottom:1px solid var(--atlas-border)}
.detail-timeline{display:block}
.detail-timeline-node{display:grid;grid-template-columns:152px minmax(0,1fr) 142px;gap:18px;align-items:center;padding:16px 20px;background:var(--atlas-surface);border:0;border-bottom:1px solid var(--atlas-border);border-radius:0;cursor:pointer;transition:background-color .18s ease,box-shadow .18s ease}
.detail-timeline-node:last-child{border-bottom:0}
.detail-timeline-node:hover,.detail-timeline-node:focus-visible{background:#f7fafc;box-shadow:inset 3px 0 0 var(--atlas-primary);outline:0}
.timeline-date-column{align-self:stretch;display:flex;flex-direction:column;justify-content:center;padding-right:16px;border-right:1px solid var(--atlas-border)}
.timeline-date-column strong{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:18px;line-height:1.25;font-variant-numeric:tabular-nums;word-break:break-word}
.timeline-date-column small{margin-top:5px;color:var(--atlas-subtle);font-size:10px;font-weight:700}
.basis-warning{display:inline-flex;width:fit-content;margin-top:6px;padding:3px 6px;color:#8a5b14;background:#fff8e6;border:1px solid #e7c878;border-radius:3px;font-size:10px;font-weight:900}
.recognition-warning{display:inline-flex;width:fit-content;margin-top:6px;padding:3px 6px;color:#984e2a;background:#fff0e8;border:1px solid #e5b397;border-radius:3px;font-size:10px;font-weight:900}
.timeline-type{display:block;margin-bottom:4px;color:var(--atlas-primary);font-size:10px;font-weight:900}
.timeline-node-main h4{margin:0;color:var(--atlas-text);font-size:15px;line-height:1.4}
.timeline-action{margin:6px 0 0;color:var(--atlas-muted);font-size:13px;line-height:1.65;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.timeline-quality-note,.detail-quality-note{display:block;margin:6px 0 0;color:#984e2a;font-size:10px;line-height:1.5}.detail-quality-note{max-width:680px}
.timeline-node-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
.timeline-node-meta small{color:var(--atlas-subtle);font-size:10px}
.timeline-row-actions{display:flex;flex-direction:column;gap:7px}
.timeline-row-actions button,.modal-close,.evidence-upload-zone button{min-height:44px;border-radius:4px;font-size:12px;font-weight:900;cursor:pointer;transition:background-color .18s ease,border-color .18s ease,color .18s ease}
.evidence-button{color:#fff;background:#347254;border:1px solid #347254}
.evidence-button:hover{background:#285c42}
.detail-button{color:var(--atlas-primary);background:transparent;border:1px solid var(--atlas-border)}
.detail-button:hover{border-color:var(--atlas-primary);background:#f4f8fc}

.timeline-detail-modal{width:min(920px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:hidden;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:6px;box-shadow:0 24px 80px rgba(30,45,60,.28)}
.timeline-detail-header{display:flex;justify-content:space-between;gap:20px;padding:22px 26px;border-bottom:1px solid var(--atlas-border);background:#f7fafc}
.timeline-detail-header>div{min-width:0}
.timeline-detail-header span{color:var(--atlas-primary);font-size:10px;font-weight:900}
.timeline-detail-header h3{margin:4px 0 5px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:23px;line-height:1.35}
.timeline-detail-header p{max-width:720px;margin:0;color:var(--atlas-muted);font-size:13px;line-height:1.6}
.modal-close{flex:0 0 44px;width:44px;padding:0;color:var(--atlas-muted);background:var(--atlas-surface);border:1px solid var(--atlas-border);font-size:23px;font-weight:400}
.modal-close:hover{color:var(--atlas-text);border-color:var(--atlas-primary)}
.timeline-detail-body{max-height:calc(100vh - 160px);overflow:auto;padding:0 26px 28px}
.detail-date-band{display:grid;grid-template-columns:minmax(180px,.7fr) minmax(280px,1.3fr);gap:22px;margin:0 -26px;padding:18px 26px;background:#edf5f1;border-bottom:1px solid #cfe1d7}
.detail-date-band>div{display:flex;flex-direction:column;justify-content:center}
.detail-date-band span,.base-date-editor>span{color:#347254;font-size:10px;font-weight:900}
.detail-date-band strong{margin-top:3px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:27px;font-variant-numeric:tabular-nums}
.detail-date-band small{margin-top:4px;color:var(--atlas-muted);font-size:11px;line-height:1.5}
.base-date-editor{display:grid;grid-template-columns:1fr;gap:5px;align-items:center;padding-left:22px;border-left:1px solid #c4d9cd}
.base-date-editor>span,.base-date-editor>small{grid-column:1/-1}
.base-date-editor input{min-height:40px;padding:0 10px;color:var(--atlas-text);background:var(--atlas-surface);border:1px solid #aac8b8;border-radius:4px;font:inherit;font-size:13px}
.base-date-editor button{min-height:40px;padding:0 10px;color:#347254;background:transparent;border:1px solid #aac8b8;border-radius:4px;font-size:11px;font-weight:800;cursor:pointer}
.base-date-editor button:disabled{cursor:wait;opacity:.6}
.base-date-actions{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:8px}
.base-date-editor .base-date-save{color:#fff;background:#347254;border-color:#347254}
.base-date-editor .base-date-save:hover:not(:disabled){background:#285c42}
.base-date-editor .base-date-trial-note{color:#8a5b14}
.detail-section{padding:22px 0;border-bottom:1px solid var(--atlas-border)}
.detail-section:last-child{border-bottom:0}
.detail-section-title{display:flex;align-items:center;gap:10px;margin-bottom:13px}
.detail-section-title>span{display:inline-flex;align-items:center;justify-content:center;width:27px;height:27px;color:var(--atlas-primary);background:#edf4fa;border:1px solid #c9dae9;border-radius:3px;font-size:10px;font-weight:900}
.detail-section-title h4{margin:0;color:var(--atlas-text);font-size:15px}
.requirement-list{display:grid;gap:8px}
.requirement-list>div{display:grid;grid-template-columns:76px 1fr;gap:10px;align-items:start;padding:10px 0;border-top:1px solid var(--atlas-border)}
.requirement-list>div:first-child{border-top:0}
.requirement-list span{display:inline-flex;justify-content:center;padding:3px 6px;border-radius:3px;font-size:10px;font-weight:900}
.source-contract{color:#246744;background:#eaf6ef}
.source-ai{color:#355c88;background:#eaf2fa}
.requirement-list p{margin:0;color:var(--atlas-text);font-size:13px;line-height:1.65}
.ai-list{margin-top:8px;padding-top:8px;border-top:1px dashed var(--atlas-border)}
.detail-empty{margin:0;color:var(--atlas-subtle);font-size:12px}
.evidence-location{margin:0 0 8px;color:var(--atlas-subtle);font-size:11px;font-weight:800}
.full-contract-quote{max-height:260px;overflow:auto;margin:0;padding:15px 17px;color:#354452;background:#f7f9fb;border:1px solid var(--atlas-border);border-left:3px solid var(--atlas-primary);font-size:13px;line-height:1.85;white-space:pre-wrap;word-break:break-word}
.timeline-condition{margin:9px 0 0;color:var(--atlas-muted);font-size:12px;font-weight:700}
.consequence-split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.consequence-split>div{padding:12px 14px;background:#fff8f2;border-left:3px solid #b76d36}
.consequence-split .ai-consequence{background:#f3f7fb;border-left-color:#527aa3}
.consequence-split span{display:block;margin-bottom:5px;color:#8e4e22;font-size:10px;font-weight:900}
.consequence-split .ai-consequence span{color:#42678c}
.consequence-split p{margin:0;color:var(--atlas-text);font-size:12px;line-height:1.65}
.evidence-upload-zone{display:grid;grid-template-columns:minmax(0,1fr) 190px;gap:10px;padding:14px;background:#f4f8f6;border:1px dashed #8eb5a0;border-radius:4px}
.evidence-upload-zone label{display:flex;flex-direction:column;justify-content:center;min-height:64px;padding:0 14px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer}
.evidence-upload-zone label:focus-within{outline:2px solid var(--atlas-primary);outline-offset:2px}
.evidence-upload-zone input{position:absolute;width:1px;height:1px;opacity:0}
.evidence-upload-zone strong{color:var(--atlas-text);font-size:13px;word-break:break-word}
.evidence-upload-zone small{margin-top:4px;color:var(--atlas-subtle);font-size:10px;line-height:1.5}
.evidence-upload-zone button{padding:0 14px;color:#fff;background:#347254;border:1px solid #347254}
.evidence-upload-zone button:disabled{opacity:.5;cursor:not-allowed}
.detail-actions{justify-content:flex-start;margin-top:10px}
.detail-actions .quiet-button,.detail-actions .primary-button{min-height:42px}
.detail-result{margin-top:18px;padding-top:18px;border-top:1px solid var(--atlas-border)}
.fulfillment-summary-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.fulfillment-summary-row>strong{color:var(--atlas-text);font-size:17px}

@media(max-width:700px){
  .case-page{padding:20px 14px 48px}.case-header{align-items:flex-start;flex-direction:column}.case-actions{justify-content:flex-start}.review-panel{grid-template-columns:1fr}.review-score{border-right:0;border-bottom:1px solid var(--atlas-border);padding:0 0 12px}.dimension-strip{grid-template-columns:repeat(2,1fr)}.citation-grid,.advice-grid{grid-template-columns:1fr}.meta-grid{grid-template-columns:repeat(2,1fr)}.meta-grid div:nth-child(2n){border-right:0}.meta-grid div:nth-child(3n){border-right:1px solid var(--atlas-border)}.analysis-workflow-head{flex-direction:column}.analysis-workflow-stages{grid-template-columns:1fr 1fr}.analysis-workflow-foot{align-items:flex-start;flex-direction:column}.analysis-workflow-foot button{width:100%;justify-content:center}.document-progress-panel{grid-template-columns:1fr}.document-progress-value{align-items:flex-start;flex-direction:row}.document-progress-track{grid-column:auto}
  .risk-workbench-head{align-items:flex-start;flex-direction:column}.risk-workbench-head p,.finding-one-line,.finding-detail p{font-size:13px}.risk-counts{width:100%}.risk-counts>span{flex:1;min-width:0;justify-content:center}.finding-summary-row{grid-template-columns:1fr;padding:14px}.finding-rank{flex-direction:row;align-items:center}.finding-expand{width:100%;min-height:44px}.finding-detail{padding:15px 14px}.finding-evidence-grid,.finding-consequence-grid{grid-template-columns:1fr}.risk-domain-head{align-items:flex-start}.risk-domain-head div{align-items:flex-start;flex-direction:column;gap:2px}.finding-buttons .quiet-button.tiny{min-height:44px;padding:0 12px;margin-left:0}
  .intake-confirm{width:100vw;max-height:100vh;height:100vh;border:0;border-radius:0}.intake-review-hero{padding:18px;align-items:flex-start}.intake-review-hero h3{font-size:23px}.intake-review-hero p{font-size:12px}.intake-review-strip{grid-template-columns:1fr 1fr}.intake-review-strip div{padding:11px 14px}.intake-review-strip div:nth-child(2){border-right:0}.intake-review-strip div:last-child{grid-column:1/-1;border-top:1px solid var(--atlas-border)}.intake-body.intake-review-body{grid-template-columns:1fr;max-height:calc(100vh - 230px)}.intake-review-main{border-right:0}.intake-grid,.intake-grid.date-grid{grid-template-columns:1fr}.intake-review-main,.intake-side-panel,.intake-review-dates,.intake-review-business{padding:17px}.intake-actions{padding:12px 14px}.intake-actions .quiet-button,.intake-actions .primary-button{min-height:44px}
  .detail-timeline-node{grid-template-columns:1fr;gap:11px;padding:15px}.timeline-date-column{padding:0 0 10px;border-right:0;border-bottom:1px solid var(--atlas-border)}.timeline-row-actions{display:grid;grid-template-columns:1fr 1fr}.timeline-detail-modal{width:100vw;max-height:100vh;height:100vh;border:0;border-radius:0}.timeline-detail-header{padding:18px}.timeline-detail-header h3{font-size:19px}.timeline-detail-body{max-height:calc(100vh - 122px);padding:0 18px 24px}.detail-date-band{grid-template-columns:1fr;margin:0 -18px;padding:16px 18px}.base-date-editor{padding:14px 0 0;border-left:0;border-top:1px solid #c4d9cd}.consequence-split{grid-template-columns:1fr}.evidence-upload-zone{grid-template-columns:1fr}.fulfillment-summary-row{align-items:flex-start;flex-direction:column}
}
@media(prefers-reduced-motion:reduce){.finding-expand{transition:none}}
</style>
