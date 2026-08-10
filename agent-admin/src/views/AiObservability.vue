<template>
  <div class="observability-page">
    <div class="page-head">
      <div>
        <span class="eyebrow">AI Observability</span>
        <h2>AI 可观测性</h2>
        <p>查看聊天检索链路，以及每次 Agent Run 的业务任务、规划、工具调用、反思和产物。</p>
      </div>
      <el-button @click="refreshActive">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab" class="observe-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="Agent Run 链路" name="agent">
        <section class="toolbar">
          <el-input
            v-model="agentKeyword"
            placeholder="搜索合同、项目、问题、步骤"
            clearable
            @keyup.enter="fetchAgentRuns"
            @clear="fetchAgentRuns"
          />
          <el-select v-model="agentSubjectType" clearable placeholder="业务对象" @change="fetchAgentRuns">
            <el-option label="合同案件" value="CONTRACT_CASE" />
            <el-option label="研发项目" value="PROJECT" />
          </el-select>
          <el-select v-model="agentRunType" clearable placeholder="任务类型" @change="fetchAgentRuns">
          <el-option v-for="item in runTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="agentStatus" clearable placeholder="运行状态" @change="fetchAgentRuns">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-button type="primary" @click="fetchAgentRuns">搜索</el-button>
        </section>

        <el-table
          v-loading="agentLoading"
          :data="agentRecords"
          class="trace-table clickable-table"
          border
          @row-click="row => openAgentRun(row.runId)"
        >
          <el-table-column prop="runId" label="Run" width="82" />
          <el-table-column label="干什么工作" min-width="230">
            <template #default="{ row }">
              <button class="question-link" @click="openAgentRun(row.runId)">
                {{ runTypeLabel(row.runType) }}
              </button>
              <div class="muted">{{ subjectLabel(row) }}</div>
              <div v-if="row.question" class="muted ellipsis">{{ row.question }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag :type="statusTag(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="progress" label="进度" width="150">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.progress) || 0" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="工具 / 路径" width="170">
            <template #default="{ row }">
              <div class="metrics-line">
                <span>{{ row.toolCallCount || 0 }} 工具</span>
                <span>{{ row.traceCount || 0 }} 步骤</span>
              </div>
              <div v-if="row.failedToolCallCount" class="error-text">{{ row.failedToolCallCount }} 个工具失败</div>
            </template>
          </el-table-column>
          <el-table-column label="产物 / 动作" width="140">
            <template #default="{ row }">
              <div class="metrics-line">
                <span>{{ row.reportCount || 0 }} 报告</span>
                <span>{{ row.actionCount || 0 }} 动作</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="currentStep" label="当前步骤" min-width="220" show-overflow-tooltip />
          <el-table-column prop="createTime" label="创建时间" width="170">
            <template #default="{ row }">{{ formatDate(row.createTime) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click.stop="openAgentRun(row.runId)">查看详情</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="agentPage"
            :page-size="agentSize"
            :total="agentTotal"
            layout="prev, pager, next, total"
            @current-change="fetchAgentRuns"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="Document Pipeline 文档处理" name="pipeline">
        <section class="toolbar pipeline-toolbar">
          <el-input
            v-model="pipelineKeyword"
            placeholder="搜索案件、合同标题、文件名、阶段"
            clearable
            @keyup.enter="fetchDocumentPipelines"
            @clear="fetchDocumentPipelines"
          />
          <el-select v-model="pipelineStatus" clearable placeholder="流水线状态" @change="fetchDocumentPipelines">
            <el-option v-for="item in pipelineStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-button type="primary" @click="fetchDocumentPipelines">搜索</el-button>
        </section>

        <el-table
          v-loading="pipelineLoading"
          :data="pipelineRecords"
          class="trace-table clickable-table"
          border
          @row-click="row => openDocumentPipeline(row.jobId)"
        >
          <el-table-column prop="jobId" label="Job" width="86" />
          <el-table-column label="合同与文件" min-width="260">
            <template #default="{ row }">
              <button class="question-link" @click.stop="openDocumentPipeline(row.jobId)">
                {{ row.fileName || `Document #${row.documentId}` }}
              </button>
              <div class="muted">{{ row.caseKey || `#${row.caseId}` }} · {{ row.caseTitle || '未命名合同' }}</div>
              <div class="muted">{{ row.documentType || '-' }} · Document {{ row.documentId }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag :type="pipelineStatusTag(row.status)" effect="plain">{{ pipelineStatusLabel(row.status) }}</el-tag>
              <div class="muted">{{ pipelineStageLabel(row.stage) }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="progress" label="进度" width="150">
            <template #default="{ row }">
              <el-progress :percentage="Number(row.progress) || 0" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="解析产物" width="190">
            <template #default="{ row }">
              <div class="metrics-line">
                <span>{{ row.clauseCount || 0 }} 条款</span>
                <span>{{ row.chunkCount || 0 }} 切片</span>
              </div>
              <div class="metrics-line">
                <span>{{ row.timelineNodeCount || 0 }} 时间点</span>
                <span>{{ row.traceCount || 0 }} 步骤</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="索引" width="150">
            <template #default="{ row }">
              <div class="metrics-line">
                <span>{{ row.embeddedChunkCount || 0 }} embedding</span>
              </div>
              <div class="metrics-line">
                <span>{{ row.indexedChunkCount || 0 }} ES</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="updateTime" label="更新时间" width="170">
            <template #default="{ row }">{{ formatDate(row.updateTime || row.createTime) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click.stop="openDocumentPipeline(row.jobId)">查看详情</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="pipelinePage"
            :page-size="pipelineSize"
            :total="pipelineTotal"
            layout="prev, pager, next, total"
            @current-change="fetchDocumentPipelines"
          />
        </div>
      </el-tab-pane>

      <el-tab-pane label="Chat Trace 检索" name="chat">
        <section class="toolbar">
          <el-input
            v-model="chatKeyword"
            placeholder="搜索问题或回答"
            clearable
            @keyup.enter="fetchChatTraces"
            @clear="fetchChatTraces"
          />
          <el-button type="primary" @click="fetchChatTraces">搜索</el-button>
        </section>

        <el-table v-loading="chatLoading" :data="chatRecords" class="trace-table" border>
          <el-table-column prop="traceId" label="Trace" width="86" />
          <el-table-column label="问题" min-width="260">
            <template #default="{ row }">
              <button class="question-link" @click="openChatTrace(row.traceId)">
                {{ row.question }}
              </button>
              <div class="muted">Session {{ row.sessionId }} · {{ formatDate(row.createTime) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="检索" width="170">
            <template #default="{ row }">
              <el-tag :type="retrievalTag(row.retrievalType)" effect="plain">
                {{ row.retrievalType || 'NONE' }}
              </el-tag>
              <div v-if="row.fallbackReason" class="muted ellipsis">{{ row.fallbackReason }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="hitCount" label="命中" width="80" />
          <el-table-column label="耗时" width="160">
            <template #default="{ row }">
              <span>{{ row.retrievalLatencyMs || 0 }}ms</span>
              <span class="muted"> / {{ row.llmLatencyMs || 0 }}ms</span>
            </template>
          </el-table-column>
          <el-table-column label="回答" min-width="220">
            <template #default="{ row }">
              <span class="answer-preview">{{ row.answer || 'No answer recorded' }}</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="chatPage"
            :page-size="chatSize"
            :total="chatTotal"
            layout="prev, pager, next, total"
            @current-change="fetchChatTraces"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="agentDrawerOpen" title="Agent Run 详细路径" size="78%">
      <div v-if="activeAgentRun" class="trace-detail">
        <section class="run-hero">
          <div>
            <span class="eyebrow">{{ runTypeLabel(activeAgentRun.runType) }}</span>
            <h3>{{ subjectLabel(activeAgentRun) }}</h3>
            <p>{{ activeAgentRun.question || taskFallback(activeAgentRun.runType) }}</p>
          </div>
          <div class="run-status-block">
            <el-tag :type="statusTag(activeAgentRun.status)" effect="dark">
              {{ statusLabel(activeAgentRun.status) }}
            </el-tag>
            <strong>{{ Number(activeAgentRun.progress) || 0 }}%</strong>
            <small>{{ formatDate(activeAgentRun.createTime) }}</small>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">为什么调用 Agent</div>
          <div class="fact-grid">
            <div><span>业务对象</span><strong>{{ activeAgentRun.subjectType || '-' }}</strong></div>
            <div><span>对象 ID</span><strong>{{ activeAgentRun.subjectId || '-' }}</strong></div>
            <div><span>触发方式</span><strong>{{ activeAgentRun.triggerType || '-' }}</strong></div>
            <div><span>当前步骤</span><strong>{{ activeAgentRun.currentStep || '-' }}</strong></div>
            <div><span>Runtime</span><strong>{{ activeAgentRun.runtimeEngine || 'legacy' }}</strong></div>
            <div><span>Graph</span><strong>{{ activeAgentRun.graphName || '-' }} · {{ activeAgentRun.graphVersion || '-' }}</strong></div>
            <div><span>模型</span><strong>{{ activeAgentRun.model || '-' }}</strong></div>
            <div><span>Prompt 版本</span><strong>{{ activeAgentRun.promptVersion || '-' }}</strong></div>
          </div>
          <pre v-if="activeAgentRun.inputJson" class="json-box">{{ prettyJson(activeAgentRun.inputJson) }}</pre>
          <p v-if="activeAgentRun.errorMessage" class="error-text">{{ activeAgentRun.errorMessage }}</p>
        </section>

        <section class="detail-section">
          <div class="section-title">执行概览</div>
          <div class="stat-grid">
            <div><span>运行步骤</span><strong>{{ activeAgentRun.traces?.length || 0 }}</strong></div>
            <div><span>工具调用</span><strong>{{ activeAgentRun.toolCalls?.length || 0 }}</strong></div>
            <div><span>图节点</span><strong>{{ activeAgentRun.nodeExecutions?.length || 0 }}</strong></div>
            <div><span>失败工具</span><strong>{{ failedToolCount(activeAgentRun) }}</strong></div>
            <div><span>反思节点</span><strong>{{ eventCount(activeAgentRun, 'REFLECTION') }}</strong></div>
            <div><span>报告产物</span><strong>{{ activeAgentRun.reports?.length || 0 }}</strong></div>
            <div><span>审查发现</span><strong>{{ activeAgentRun.findings?.length || 0 }}</strong></div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">Graph 节点执行</div>
          <div v-if="activeAgentRun.nodeExecutions?.length" class="loop-list">
            <article v-for="node in activeAgentRun.nodeExecutions" :key="node.id || `${node.runId}-${node.sequenceNo}`" class="loop-step">
              <div class="loop-index">#{{ node.sequenceNo }}</div>
              <div class="loop-body">
                <div class="tool-row">
                  <strong>{{ node.nodeName }}</strong>
                  <el-tag size="small" :type="node.status === 'FAILED' ? 'danger' : 'success'" effect="plain">{{ node.status }}</el-tag>
                  <span class="muted">{{ node.latencyMs || 0 }}ms · {{ formatDate(node.finishedAt || node.createTime) }}</span>
                </div>
                <div class="io-grid">
                  <div><span>节点输入摘要</span><pre class="json-box compact">{{ prettyJson(node.inputSummary) }}</pre></div>
                  <div><span>节点输出摘要</span><pre class="json-box compact">{{ prettyJson(node.outputSummary) }}</pre></div>
                  <div v-if="node.errorMessage"><span>错误</span><p class="error-text">{{ node.errorMessage }}</p></div>
                </div>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无节点执行记录，可能是旧运行或运行尚未写入检查点" />
        </section>

        <section class="detail-section">
          <div class="section-title">Agent 循环与运行路径</div>
          <div v-if="activeAgentRun.traces?.length" class="loop-list">
            <article v-for="trace in activeAgentRun.traces" :key="trace.id" class="loop-step">
              <div class="loop-index">#{{ trace.sequenceNo }}</div>
              <div class="loop-body">
                <div class="tool-row">
                  <strong>{{ eventLabel(trace.eventType) }}</strong>
                  <el-tag size="small" :type="traceType(trace.eventType)" effect="plain">{{ trace.eventType }}</el-tag>
                  <span class="muted">{{ formatDate(trace.createTime) }}</span>
                </div>
                <p>{{ trace.summary }}</p>
                <pre v-if="trace.payloadJson && trace.payloadJson !== '{}'" class="json-box compact">{{ prettyJson(trace.payloadJson) }}</pre>
              </div>
            </article>
          </div>
          <el-empty v-if="!activeAgentRun.traces?.length" description="暂无运行路径" />
        </section>

        <section class="detail-section">
          <div class="section-title">工具调用</div>
          <el-timeline>
            <el-timeline-item
              v-for="tool in activeAgentRun.toolCalls || []"
              :key="tool.id"
              :type="tool.status === 'DONE' ? 'success' : tool.status === 'FAILED' ? 'danger' : 'info'"
              :timestamp="`${tool.latencyMs || 0}ms · ${formatDate(tool.createTime)}`"
            >
              <div class="tool-row">
                <strong>{{ tool.toolName }}</strong>
                <el-tag size="small" effect="plain">{{ tool.status }}</el-tag>
                <span class="muted">step {{ tool.planStepId || '-' }}</span>
              </div>
              <div class="io-grid">
                <div>
                  <span>Input</span>
                  <pre class="json-box compact">{{ prettyJson(tool.inputJson) }}</pre>
                </div>
                <div>
                  <span>Output</span>
                  <pre class="json-box compact">{{ prettyJson(tool.outputJson) }}</pre>
                </div>
              </div>
              <p v-if="tool.errorMessage" class="error-text">{{ tool.errorMessage }}</p>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-if="!activeAgentRun.toolCalls?.length" description="暂无工具调用" />
        </section>

        <section class="detail-section" v-if="activeAgentRun.reports?.length">
          <div class="section-title">生成产物</div>
          <div v-for="report in activeAgentRun.reports" :key="report.id" class="report-card">
            <div class="artifact-row">
              <div>
                <strong>{{ report.title || report.reportType }}</strong>
                <p>{{ report.summary || '暂无摘要' }}</p>
              </div>
              <div class="artifact-meta">
                <el-tag effect="plain">{{ report.reportType }}</el-tag>
                <span v-if="report.healthScore != null">{{ report.healthScore }} 分</span>
                <span>{{ report.analysisMode || report.status }}</span>
              </div>
            </div>
            <el-collapse class="inner-collapse">
              <el-collapse-item title="报告正文 / Markdown" name="markdown" v-if="report.reportMarkdown">
                <pre class="markdown-box">{{ report.reportMarkdown }}</pre>
              </el-collapse-item>
              <el-collapse-item title="结构化 JSON 产物" name="content" v-if="report.contentJson">
                <pre class="json-box">{{ prettyJson(report.contentJson) }}</pre>
              </el-collapse-item>
              <el-collapse-item title="评分依据 / 引用 / 计划" name="meta">
                <div class="io-grid">
                  <div><span>Scoring Rationale</span><pre class="json-box compact">{{ prettyJson(report.scoringRationaleJson) }}</pre></div>
                  <div><span>Citations</span><pre class="json-box compact">{{ prettyJson(report.citationsJson) }}</pre></div>
                  <div><span>Risks</span><pre class="json-box compact">{{ prettyJson(report.risksJson) }}</pre></div>
                  <div><span>Plan</span><pre class="json-box compact">{{ prettyJson(report.planJson) }}</pre></div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </section>

        <section class="detail-section" v-if="activeAgentRun.findings?.length">
          <div class="section-title">审查发现</div>
          <div v-for="finding in activeAgentRun.findings" :key="finding.id" class="finding-card">
            <div class="tool-row">
              <strong>{{ finding.title }}</strong>
              <el-tag size="small" :type="severityTag(finding.severity)" effect="plain">{{ finding.severity }}</el-tag>
              <el-tag size="small" effect="plain">{{ finding.status }}</el-tag>
              <span class="muted">{{ finding.ruleKey || finding.clauseType }}</span>
            </div>
            <p v-if="finding.description"><b>问题描述：</b>{{ finding.description }}</p>
            <p v-if="finding.impact"><b>业务影响：</b>{{ finding.impact }}</p>
            <p v-if="finding.remediationAdvice"><b>整改建议：</b>{{ finding.remediationAdvice }}</p>
            <p v-if="finding.negotiationAdvice"><b>谈判建议：</b>{{ finding.negotiationAdvice }}</p>
            <div class="io-grid">
              <div v-if="finding.contractCitation"><span>合同引用</span><pre class="json-box compact">{{ prettyJson(finding.contractCitation) }}</pre></div>
              <div v-if="finding.policyCitation"><span>规则引用</span><pre class="json-box compact">{{ prettyJson(finding.policyCitation) }}</pre></div>
              <div v-if="finding.verificationPoints"><span>复核点</span><pre class="json-box compact">{{ prettyJson(finding.verificationPoints) }}</pre></div>
            </div>
          </div>
        </section>

        <section class="detail-section" v-if="activeAgentRun.actions?.length">
          <div class="section-title">动作建议</div>
          <div v-for="action in activeAgentRun.actions" :key="action.id" class="artifact-row">
            <div>
              <strong>{{ action.title || action.actionType }}</strong>
              <pre v-if="action.payloadJson" class="json-box compact">{{ prettyJson(action.payloadJson) }}</pre>
              <p v-if="action.errorMessage" class="error-text">{{ action.errorMessage }}</p>
            </div>
            <div class="artifact-meta">
              <el-tag effect="plain">{{ action.actionType }}</el-tag>
              <span>{{ action.status }}</span>
            </div>
          </div>
        </section>
      </div>
    </el-drawer>

    <el-drawer v-model="pipelineDrawerOpen" title="Document Pipeline 详细路径" size="72%">
      <div v-if="activePipeline" class="trace-detail">
        <section class="run-hero">
          <div>
            <span class="eyebrow">Contract Document Pipeline</span>
            <h3>{{ activePipeline.fileName || `Document #${activePipeline.documentId}` }}</h3>
            <p>{{ activePipeline.caseKey || `#${activePipeline.caseId}` }} · {{ activePipeline.caseTitle || '未命名合同' }}</p>
          </div>
          <div class="run-status-block">
            <el-tag :type="pipelineStatusTag(activePipeline.status)" effect="dark">
              {{ pipelineStatusLabel(activePipeline.status) }}
            </el-tag>
            <strong>{{ Number(activePipeline.progress) || 0 }}%</strong>
            <small>{{ pipelineStageLabel(activePipeline.stage) }}</small>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">为什么触发文档流水线</div>
          <div class="fact-grid">
            <div><span>合同案件</span><strong>{{ activePipeline.caseKey || activePipeline.caseId }}</strong></div>
            <div><span>文档 ID</span><strong>{{ activePipeline.documentId || '-' }}</strong></div>
            <div><span>文档类型</span><strong>{{ activePipeline.documentType || '-' }}</strong></div>
            <div><span>Parse Status</span><strong>{{ activePipeline.parseStatus || '-' }}</strong></div>
          </div>
          <p v-if="activePipeline.errorMessage || activePipeline.parseError" class="error-text">
            {{ activePipeline.errorMessage || activePipeline.parseError }}
          </p>
        </section>

        <section class="detail-section">
          <div class="section-title">处理结果</div>
          <div class="stat-grid pipeline-stat-grid">
            <div><span>Trace 步骤</span><strong>{{ activePipeline.traces?.length || 0 }}</strong></div>
            <div><span>条款</span><strong>{{ activePipeline.clauseCount || 0 }}</strong></div>
            <div><span>切片</span><strong>{{ activePipeline.chunkCount || 0 }}</strong></div>
            <div><span>Embedding</span><strong>{{ activePipeline.embeddedChunkCount || 0 }}</strong></div>
            <div><span>ES 索引</span><strong>{{ activePipeline.indexedChunkCount || 0 }}</strong></div>
            <div><span>时间节点</span><strong>{{ activePipeline.timelineNodeCount || 0 }}</strong></div>
          </div>
          <div v-if="activePipeline.latestRunId" class="link-row">
            <span>关联最近 Agent Run</span>
            <el-button size="small" text type="primary" @click="openAgentRun(activePipeline.latestRunId)">Run #{{ activePipeline.latestRunId }}</el-button>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-title">流水线阶段与输入输出</div>
          <div v-if="activePipeline.traces?.length" class="loop-list">
            <article v-for="trace in activePipeline.traces" :key="trace.id" class="loop-step">
              <div class="loop-index">#{{ trace.sequenceNo }}</div>
              <div class="loop-body">
                <div class="tool-row">
                  <strong>{{ pipelineStageLabel(trace.stage) }}</strong>
                  <el-tag size="small" :type="pipelineTraceType(trace)" effect="plain">{{ trace.stage }}</el-tag>
                  <span class="muted">{{ formatDate(trace.createTime) }}</span>
                </div>
                <p>{{ trace.summary }}</p>
                <div class="io-grid">
                  <div v-if="trace.inputJson && trace.inputJson !== '{}'">
                    <span>Input</span>
                    <pre class="json-box compact">{{ prettyJson(trace.inputJson) }}</pre>
                  </div>
                  <div v-if="trace.outputJson && trace.outputJson !== '{}'">
                    <span>Output</span>
                    <pre class="json-box compact">{{ prettyJson(trace.outputJson) }}</pre>
                  </div>
                </div>
                <p v-if="trace.errorMessage" class="error-text">{{ trace.errorMessage }}</p>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无文档处理路径" />
        </section>
      </div>
    </el-drawer>

    <el-drawer v-model="chatDrawerOpen" title="Answer Trace" size="54%">
      <div v-if="activeChatTrace" class="trace-detail">
        <section class="detail-section">
          <div class="section-title">User Question</div>
          <p class="question-text">{{ activeChatTrace.question }}</p>
          <div class="meta-row">
            <el-tag :type="retrievalTag(activeChatTrace.retrievalType)" effect="plain">
              {{ activeChatTrace.retrievalType || 'NONE' }}
            </el-tag>
            <span>topK {{ activeChatTrace.topK }}</span>
            <span>retrieval {{ activeChatTrace.retrievalLatencyMs || 0 }}ms</span>
            <span>LLM {{ activeChatTrace.llmLatencyMs || 0 }}ms</span>
          </div>
          <p v-if="activeChatTrace.fallbackReason" class="fallback">
            Fallback: {{ activeChatTrace.fallbackReason }}
          </p>
        </section>

        <section class="detail-section">
          <div class="section-title">Tool Calls</div>
          <el-timeline>
            <el-timeline-item
              v-for="tool in activeChatTrace.toolCalls || []"
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
          <el-empty v-if="!activeChatTrace.toolCalls?.length" description="No tool calls recorded" />
        </section>

        <section class="detail-section">
          <div class="section-title">Citations</div>
          <div v-if="activeChatTrace.hits?.length" class="hit-list">
            <div v-for="hit in activeChatTrace.hits" :key="hit.id" class="hit-row">
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
          <div class="answer-box">{{ activeChatTrace.answer || 'No answer recorded' }}</div>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAiObservabilityAgentRun,
  getAiObservabilityAgentRuns,
  getAiObservabilityDocumentPipeline,
  getAiObservabilityDocumentPipelines,
  getAiObservabilityTrace,
  getAiObservabilityTraces,
} from '../api/index.js'

const activeTab = ref('agent')

const agentLoading = ref(false)
const agentRecords = ref([])
const agentKeyword = ref('')
const agentSubjectType = ref('')
const agentRunType = ref('')
const agentStatus = ref('')
const agentPage = ref(1)
const agentSize = 10
const agentTotal = ref(0)
const agentDrawerOpen = ref(false)
const activeAgentRun = ref(null)

const pipelineLoading = ref(false)
const pipelineRecords = ref([])
const pipelineKeyword = ref('')
const pipelineStatus = ref('')
const pipelinePage = ref(1)
const pipelineSize = 10
const pipelineTotal = ref(0)
const pipelineDrawerOpen = ref(false)
const activePipeline = ref(null)

const chatLoading = ref(false)
const chatRecords = ref([])
const chatKeyword = ref('')
const chatPage = ref(1)
const chatSize = 10
const chatTotal = ref(0)
const chatDrawerOpen = ref(false)
const activeChatTrace = ref(null)

const runTypeOptions = [
  { value: 'CONTRACT_REVIEW', label: '合同审查' },
  { value: 'CONTRACT_INTAKE', label: '合同发起' },
  { value: 'APPROVAL_DECISION', label: '审批决策' },
  { value: 'VERSION_REVIEW', label: '版本复核' },
  { value: 'OBLIGATION_EXTRACTION', label: '义务提取' },
  { value: 'CONTRACT_ELEMENT_EXTRACTION', label: '合同要素提取' },
  { value: 'HEALTH_ANALYSIS', label: '健康分析' },
  { value: 'PROJECT_ONBOARDING', label: '项目接手' },
  { value: 'ENGINEERING_DECISION', label: '研发决策' },
]

const statusOptions = [
  { value: 'CREATED', label: '排队' },
  { value: 'CONTEXT_BUILDING', label: '构建上下文' },
  { value: 'PLANNING', label: '规划中' },
  { value: 'ANALYZING', label: '执行中' },
  { value: 'VERIFYING', label: '反思验证' },
  { value: 'COMPLETED', label: '完成' },
  { value: 'FAILED', label: '失败' },
  { value: 'CANCELLED', label: '已取消' },
]

const pipelineStatusOptions = [
  { value: 'UPLOADED', label: '已上传' },
  { value: 'PROCESSING', label: '处理中' },
  { value: 'READY', label: '可审查' },
  { value: 'FAILED', label: '失败' },
]

onMounted(fetchAgentRuns)

function handleTabChange() {
  if (activeTab.value === 'agent') fetchAgentRuns()
  else if (activeTab.value === 'pipeline') fetchDocumentPipelines()
  else fetchChatTraces()
}

function refreshActive() {
  if (activeTab.value === 'agent') fetchAgentRuns()
  else if (activeTab.value === 'pipeline') fetchDocumentPipelines()
  else fetchChatTraces()
}

async function fetchAgentRuns() {
  agentLoading.value = true
  try {
    const response = await getAiObservabilityAgentRuns({
      page: agentPage.value,
      size: agentSize,
      keyword: agentKeyword.value || undefined,
      subjectType: agentSubjectType.value || undefined,
      runType: agentRunType.value || undefined,
      status: agentStatus.value || undefined,
    })
    agentRecords.value = response.data.data?.records || []
    agentTotal.value = Number(response.data.data?.total || 0)
  } finally {
    agentLoading.value = false
  }
}

async function openAgentRun(id) {
  try {
    const response = await getAiObservabilityAgentRun(id)
    activeAgentRun.value = response.data.data
    agentDrawerOpen.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.message || 'Agent Run 加载失败')
  }
}

async function fetchDocumentPipelines() {
  pipelineLoading.value = true
  try {
    const response = await getAiObservabilityDocumentPipelines({
      page: pipelinePage.value,
      size: pipelineSize,
      keyword: pipelineKeyword.value || undefined,
      status: pipelineStatus.value || undefined,
    })
    pipelineRecords.value = response.data.data?.records || []
    pipelineTotal.value = Number(response.data.data?.total || 0)
  } finally {
    pipelineLoading.value = false
  }
}

async function openDocumentPipeline(id) {
  try {
    const response = await getAiObservabilityDocumentPipeline(id)
    activePipeline.value = response.data.data
    pipelineDrawerOpen.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.message || '文档流水线加载失败')
  }
}

async function fetchChatTraces() {
  chatLoading.value = true
  try {
    const response = await getAiObservabilityTraces({
      page: chatPage.value,
      size: chatSize,
      keyword: chatKeyword.value || undefined,
    })
    chatRecords.value = response.data.data?.records || []
    chatTotal.value = Number(response.data.data?.total || 0)
  } finally {
    chatLoading.value = false
  }
}

async function openChatTrace(id) {
  try {
    const response = await getAiObservabilityTrace(id)
    activeChatTrace.value = response.data.data
    chatDrawerOpen.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.message || 'Trace 加载失败')
  }
}

function runTypeLabel(type) {
  return {
    HEALTH_ANALYSIS: '项目健康分析',
    PROJECT_ONBOARDING: '项目接手与入职',
    ENGINEERING_DECISION: '研发决策',
    CONTRACT_REVIEW: '合同审查',
    TIMELINE_EXTRACTION: '正式履约日程',
    CONTRACT_INTAKE: '合同发起',
    APPROVAL_DECISION: '审批决策',
    VERSION_REVIEW: '版本复核',
    OBLIGATION_EXTRACTION: '义务提取',
    CONTRACT_ELEMENT_EXTRACTION: '合同要素提取',
    FULFILLMENT_CHECK: '履约检查',
  }[type] || type || 'Agent 任务'
}

function statusLabel(status) {
  return {
    CREATED: '排队',
    CONTEXT_BUILDING: '构建上下文',
    PLANNING: '规划中',
    ANALYZING: '执行中',
    VERIFYING: '反思验证',
    COMPLETED: '完成',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[status] || status || '-'
}

function statusTag(status) {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'warning'
  if (['CREATED', 'CONTEXT_BUILDING', 'PLANNING', 'ANALYZING', 'VERIFYING'].includes(status)) return 'primary'
  return 'info'
}

function pipelineStatusLabel(status) {
  return {
    UPLOADED: '已上传',
    PROCESSING: '处理中',
    READY: '可审查',
    FAILED: '失败',
  }[status] || status || '-'
}

function pipelineStatusTag(status) {
  if (status === 'READY') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'PROCESSING') return 'primary'
  if (status === 'UPLOADED') return 'warning'
  return 'info'
}

function pipelineStageLabel(stage) {
  return {
    UPLOADED: '上传登记',
    DOCX_PARSING: 'DOCX 原生解析',
    PDF_PARSING: 'PDF 文本解析',
    TEXT_PARSING: '正文读取',
    CLAUSE_SPLITTING: '条款切分',
    CLAUSE_PERSISTING: '条款入库',
    CHUNKING: '证据切片',
    EMBEDDING: '向量化',
    INDEXING: '索引写入',
    TIMELINE_EXTRACTING: '时间节点提取',
    TIMELINE_EXTRACTION: '时间节点提取',
    READY: '处理完成',
    DISPATCH_FAILED: '调度失败',
    FAILED: '处理失败',
  }[stage] || stage || '-'
}

function pipelineTraceType(trace) {
  if (trace.errorMessage || trace.stage === 'FAILED' || trace.stage === 'DISPATCH_FAILED') return 'danger'
  if (trace.stage === 'READY') return 'success'
  if (['TEXT_PARSING', 'CLAUSE_SPLITTING', 'CLAUSE_PERSISTING'].includes(trace.stage)) return 'primary'
  return 'info'
}

function subjectLabel(row) {
  const prefix = row.subjectType === 'CONTRACT_CASE' ? '合同案件' : '研发项目'
  const key = row.subjectKey || `#${row.subjectId || row.projectId || '-'}`
  const title = row.subjectTitle || '未命名对象'
  return `${prefix} ${key} · ${title}`
}

function taskFallback(type) {
  return {
    CONTRACT_REVIEW: '审查当前合同版本',
    CONTRACT_INTAKE: '识别合同材料并准备发起',
    APPROVAL_DECISION: '生成合同审批意见',
    VERSION_REVIEW: '复核合同版本变化',
    OBLIGATION_EXTRACTION: '提取合同履约义务',
    CONTRACT_ELEMENT_EXTRACTION: '提取合同主体、金额、日期、义务和风险条款要素',
  }[type] || '执行 Agent 任务'
}

function traceType(type) {
  if (String(type || '').includes('FAILED')) return 'danger'
  if (String(type || '').includes('PASSED') || String(type || '').includes('COMPLETED')) return 'success'
  if (String(type || '').includes('TOOL')) return 'primary'
  if (String(type || '').includes('REFLECTION')) return 'warning'
  return 'info'
}

function eventLabel(type) {
  const value = String(type || '')
  if (value.includes('PLAN')) return '规划器'
  if (value.includes('TOOL')) return '工具调用'
  if (value.includes('REFLECTION')) return '反思验证'
  if (value.includes('MEMORY')) return '记忆读写'
  if (value.includes('ARTIFACT')) return '产物生成'
  if (value.includes('CONCURRENT')) return '并发执行'
  if (value.includes('FAILED')) return '异常'
  return '执行事件'
}

function failedToolCount(run) {
  return (run.toolCalls || []).filter(tool => tool.status === 'FAILED').length
}

function eventCount(run, keyword) {
  return (run.traces || []).filter(trace => String(trace.eventType || '').includes(keyword)).length
}

function severityTag(severity) {
  if (severity === 'HIGH') return 'danger'
  if (severity === 'MEDIUM') return 'warning'
  if (severity === 'LOW') return 'info'
  return ''
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

function prettyJson(value) {
  if (!value) return '{}'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style scoped>
.observability-page { display: flex; flex-direction: column; gap: 16px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; padding: 22px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { margin: 0; color: #607184; line-height: 1.7; }
.observe-tabs { padding: 18px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) 150px 170px 140px auto; gap: 8px; margin-bottom: 14px; }
.pipeline-toolbar { grid-template-columns: minmax(260px, 1fr) 160px auto; }
.trace-table { border: 1px solid #dce4ee; border-radius: 4px; }
.clickable-table :deep(.el-table__row) { cursor: pointer; }
.question-link { padding: 0; border: 0; background: transparent; color: #1f2d3d; cursor: pointer; font: inherit; font-weight: 700; text-align: left; }
.question-link:hover { color: #426fa6; }
.muted { margin-top: 4px; color: #8b9aaa; font-size: 12px; line-height: 1.5; }
.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metrics-line { display: flex; gap: 8px; color: #607184; font-size: 12px; }
.answer-preview { display: -webkit-box; overflow: hidden; color: #607184; line-height: 1.5; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.trace-detail { display: flex; flex-direction: column; gap: 18px; }
.run-hero { display: flex; justify-content: space-between; gap: 18px; padding: 18px; background: #f7f9fc; border: 1px solid #dce4ee; border-radius: 4px; }
.run-hero h3 { margin: 5px 0 8px; color: #1f2d3d; font-size: 20px; }
.run-hero p { margin: 0; color: #607184; line-height: 1.7; }
.run-status-block { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; min-width: 110px; }
.run-status-block strong { color: #1f2d3d; font-size: 28px; }
.run-status-block small { color: #8b9aaa; }
.detail-section { border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; }
.section-title { margin-bottom: 10px; color: #1f2d3d; font-weight: 800; }
.fact-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.fact-grid div { padding: 10px; background: #fbfcfe; border: 1px solid #dce4ee; border-radius: 4px; }
.fact-grid span, .io-grid span { display: block; margin-bottom: 4px; color: #8b9aaa; font-size: 11px; font-weight: 800; }
.fact-grid strong { color: #1f2d3d; font-size: 13px; }
.stat-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
.pipeline-stat-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.stat-grid div { padding: 12px; background: #fbfcfe; border: 1px solid #dce4ee; border-radius: 4px; }
.stat-grid span { display: block; color: #8b9aaa; font-size: 11px; font-weight: 800; }
.stat-grid strong { display: block; margin-top: 4px; color: #1f2d3d; font-size: 22px; }
.loop-list { display: flex; flex-direction: column; gap: 8px; }
.loop-step { display: grid; grid-template-columns: 54px 1fr; gap: 10px; padding: 12px; background: #fbfcfe; border: 1px solid #dce4ee; border-radius: 4px; }
.loop-index { color: #426fa6; font-family: monospace; font-weight: 900; }
.loop-body p { margin: 6px 0 0; color: #607184; line-height: 1.6; }
.question-text { margin: 0 0 10px; color: #1f2d3d; line-height: 1.7; }
.meta-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; color: #607184; font-size: 12px; }
.fallback { margin: 10px 0 0; color: #a7793d; font-size: 13px; }
.link-row { display: flex; align-items: center; gap: 8px; margin-top: 12px; color: #607184; font-size: 13px; }
.tool-row { display: flex; align-items: center; gap: 8px; }
.error-text { margin: 4px 0 0; color: #f56c6c; font-size: 12px; }
.io-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }
.json-box { max-height: 260px; overflow: auto; margin: 10px 0 0; padding: 10px; white-space: pre-wrap; word-break: break-word; background: #f3f6fa; border: 1px solid #d4dde8; border-radius: 4px; color: #1f2d3d; font-size: 12px; line-height: 1.55; }
.json-box.compact { max-height: 180px; margin-top: 4px; }
.markdown-box { max-height: 340px; overflow: auto; margin: 0; padding: 12px; white-space: pre-wrap; word-break: break-word; background: #f3f6fa; border: 1px solid #d4dde8; border-radius: 4px; color: #1f2d3d; line-height: 1.65; }
.report-card, .finding-card { padding: 12px; border: 1px solid #dce4ee; border-radius: 4px; background: #fbfcfe; margin-bottom: 10px; }
.finding-card p { margin: 8px 0 0; color: #607184; line-height: 1.7; }
.finding-card b { color: #1f2d3d; }
.inner-collapse { margin-top: 8px; border-top: 1px solid #e5e7eb; }
.artifact-row { display: flex; justify-content: space-between; gap: 14px; padding: 12px 0; border-top: 1px solid #e5e7eb; }
.artifact-row:first-of-type { border-top: 0; }
.artifact-row strong { color: #1f2d3d; }
.artifact-row p { margin: 5px 0 0; color: #607184; line-height: 1.6; }
.artifact-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; color: #607184; font-size: 12px; min-width: 130px; }
.hit-list { display: flex; flex-direction: column; gap: 10px; }
.hit-row { border: 1px solid #d4dde8; border-radius: 4px; padding: 12px; background: #fbfcfe; }
.hit-main { display: flex; flex-direction: column; gap: 3px; }
.hit-main strong { color: #1f2d3d; }
.hit-main span { color: #8b9aaa; font-size: 12px; }
.hit-score { float: right; color: #426fa6; font-family: monospace; font-size: 12px; }
.hit-row p { margin: 8px 0 0; color: #607184; line-height: 1.6; }
.answer-box { white-space: pre-wrap; color: #1f2d3d; background: #f3f6fa; border: 1px solid #d4dde8; border-radius: 4px; padding: 14px; line-height: 1.7; }
@media (max-width: 980px) { .toolbar { grid-template-columns: 1fr 1fr; } .fact-grid, .io-grid, .stat-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 720px) { .page-head, .run-hero, .artifact-row { align-items: flex-start; flex-direction: column; } .toolbar { grid-template-columns: 1fr; } .run-status-block, .artifact-meta { align-items: flex-start; } }
</style>
