<template>
  <div class="workbench-page">
    <div v-if="loading" class="loading-block">
      <span class="loader"></span>
      正在读取项目上下文
    </div>

    <template v-else-if="project">
      <header class="project-header">
        <div>
          <router-link to="/" class="back-link">返回项目总览</router-link>
          <div class="project-title-row">
            <span class="project-key">{{ project.projectKey }}</span>
            <span class="health-chip" :class="healthClass(project.healthStatus)">
              {{ healthLabel(project.healthStatus) }}
            </span>
          </div>
          <h1>{{ project.name }}</h1>
          <p>{{ project.description || '这个项目还没有补充说明。' }}</p>
        </div>
        <div class="project-header-actions">
          <a v-if="project.repositoryUrl" :href="project.repositoryUrl" target="_blank" rel="noreferrer" class="quiet-button">
            查看仓库
          </a>
          <button class="quiet-button" type="button" :disabled="syncing" @click="syncEvidence">
            {{ syncing ? '同步中' : '同步 GitHub 证据' }}
          </button>
          <button class="primary-button" type="button" :disabled="running" @click="openTaskLauncher('HEALTH_ANALYSIS')">
            {{ running ? 'Agent 运行中' : '新建 Agent 任务' }}
          </button>
        </div>
      </header>

      <section class="context-row">
        <div><span>当前里程碑</span><strong>{{ project.currentMilestone || '待设置' }}</strong></div>
        <div><span>目标版本</span><strong>{{ project.releaseTarget || '待设置' }}</strong></div>
        <div><span>团队规模</span><strong>{{ project.teamSize || '—' }} 人</strong></div>
        <div><span>技术栈</span><strong>{{ project.techStack || '待补充' }}</strong></div>
      </section>

      <section class="source-sync-panel">
        <div class="source-copy">
          <p class="section-kicker">证据来源</p>
          <h2>GitHub 只读证据同步</h2>
          <p>
            Agent Run 会优先读取这里沉淀的仓库、README、配置文件、Issue、PR 和 Commit 证据；
            没有证据时才回退到知识库检索和项目录入事实。
          </p>
        </div>
        <div class="source-status-grid">
          <div><span>同步状态</span><strong :class="sourceStatusClass(sourceStatus)">{{ sourceStatusLabel(sourceStatus) }}</strong></div>
          <div><span>证据条目</span><strong>{{ evidence.length }}</strong></div>
          <div><span>最近同步</span><strong>{{ latestSyncJob ? formatDate(latestSyncJob.finishedAt || latestSyncJob.createTime) : '尚未同步' }}</strong></div>
          <div><span>默认分支</span><strong>{{ project.defaultBranch || 'main' }}</strong></div>
        </div>
        <div v-if="latestSyncJob?.errorMessage" class="sync-error">{{ latestSyncJob.errorMessage }}</div>
      </section>

      <!-- ====== 三张任务卡片（纵向排列） ====== -->
      <section class="task-cards-section">

        <!-- Card 1: 项目健康分析 -->
        <article class="task-card health-card">
          <div class="task-card-topline">
            <span class="task-card-eyebrow">健康与交付</span>
            <small v-if="latestHealthRun?.status && !isTerminal(latestHealthRun.status)">运行中 {{ latestHealthRun.progress || 0 }}%</small>
            <small v-else-if="latestHealthReport">{{ latestHealthReport.healthScore || '—' }}/100 {{ healthLabel(latestHealthReport.healthStatus) }}</small>
            <small v-else>尚未运行</small>
          </div>
          <h3>项目健康分析</h3>
          <p>用确定性规则计算健康分，由 DeepSeek 解释风险并生成交付计划。</p>

          <template v-if="latestHealthReport">
            <div class="card-health-grid">
              <div class="card-health-left">
                <span class="card-metric-label">健康分</span>
                <strong class="card-metric-score">{{ latestHealthReport.healthScore || '—' }}<small>/100</small></strong>
                <span class="card-metric-status">{{ healthLabel(latestHealthReport.healthStatus) }}</span>
                <small class="card-metric-time">{{ formatDate(latestHealthReport.createTime) }}</small>
              </div>
              <div class="card-health-right">
                <div v-for="item in dimensions" :key="item.name" class="card-dim-row">
                  <div class="card-dim-head"><span>{{ item.name }}</span><strong>{{ item.score }}</strong></div>
                  <div class="card-dim-bar"><i :style="{ width: `${item.score}%` }"></i></div>
                </div>
              </div>
            </div>

            <div class="card-actions-row">
              <div class="tooltip-wrap">
                <button type="button" class="card-btn" @mouseenter="tooltipOpen='scoring'" @mouseleave="tooltipOpen=''" @click="tooltipOpen = tooltipOpen==='scoring' ? '' : 'scoring'">评分依据</button>
                <transition name="tip"><div v-if="tooltipOpen==='scoring'" class="card-tooltip scoring-tooltip" @mouseenter="tooltipOpen='scoring'" @mouseleave="tooltipOpen=''">
                  <div class="score-explain-grid">
                    <div><span>版本</span><strong>{{ latestHealthReport.scoringVersion || 'legacy' }}</strong></div>
                    <div><span>模式</span><strong>{{ latestHealthReport.analysisMode || '历史报告' }}</strong></div>
                    <div><span>快照</span><strong>{{ shortHash(latestHealthReport.evidenceHash) }}</strong></div>
                  </div>
                  <div v-if="missingScoringSignals.length" class="score-rationale-list">
                    <div v-for="s in missingScoringSignals" :key="`${s.dimension}-${s.title}`" class="score-rationale-item missing">
                      <span>{{ s.dimension }}</span><strong>{{ s.title }}</strong><em>{{ s.impact }}</em>
                      <p>{{ s.note }}</p>
                    </div>
                  </div>
                  <div v-else class="blank-state compact-blank">未识别到扣分项。</div>
                </div></transition>
              </div>

              <div class="tooltip-wrap">
                <button type="button" class="card-btn" @mouseenter="tooltipOpen='risks'" @mouseleave="tooltipOpen=''" @click="tooltipOpen = tooltipOpen==='risks' ? '' : 'risks'">证据与风险</button>
                <transition name="tip"><div v-if="tooltipOpen==='risks'" class="card-tooltip risks-tooltip" @mouseenter="tooltipOpen='risks'" @mouseleave="tooltipOpen=''">
                  <div v-if="risks.length" class="risk-list">
                    <div v-for="risk in risks" :key="risk.id" class="risk-row">
                      <div class="risk-marker" :class="severityClass(risk.severity)"></div>
                      <div class="risk-body">
                        <div class="risk-top"><strong>{{ risk.title }}</strong><span>{{ severityLabel(risk.severity) }}</span></div>
                        <p>{{ risk.description }}</p>
                      </div>
                    </div>
                  </div>
                  <div v-else class="blank-state compact-blank">运行分析后显示带引用的风险清单。</div>
                </div></transition>
              </div>

              <button type="button" class="card-btn report-btn" @click="latestHealthReport?.reportMarkdown && openArtifactModal(latestHealthReport)">完整报告</button>
              <button type="button" class="card-btn" :disabled="running" @click="openTaskLauncher('HEALTH_ANALYSIS')">重新运行</button>
            </div>

            <div class="card-bottom-grid" v-if="plan.length || citations.length">
              <div v-if="plan.length" class="card-bottom-panel">
                <p class="section-kicker">交付计划</p>
                <div v-for="task in plan.slice(0, 3)" :key="task.id" class="card-plan-row">
                  <span>{{ task.id }}</span><strong>{{ task.title }}</strong><small>{{ task.ownerRole }}</small>
                </div>
              </div>
              <div v-if="citations.length" class="card-bottom-panel">
                <p class="section-kicker">引用来源 · {{ citations.length }} 条</p>
                <div v-for="c in citations.slice(0, 3)" :key="`${c.sourceType}-${c.sourceId}`" class="card-cite-row">
                  <span>{{ objectLabel(c.objectType || c.sourceType) }}</span><strong>{{ c.title }}</strong>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="card-empty">
            <p>尚未运行项目健康分析。同步 GitHub 证据后启动一次 Agent Run，生成确定性健康评分和带引用的交付报告。</p>
            <button type="button" class="primary-button" :disabled="running" @click="openTaskLauncher('HEALTH_ANALYSIS')">运行健康分析</button>
          </div>
        </article>

        <!-- Card 2: 项目接手手册 -->
        <article class="task-card">
          <div class="task-card-topline">
            <span class="task-card-eyebrow">接手与入职</span>
            <small v-if="latestOnboardingRun?.status && !isTerminal(latestOnboardingRun.status)">运行中 {{ latestOnboardingRun.progress || 0 }}%</small>
            <small v-else-if="latestOnboardingReport">{{ formatDate(latestOnboardingReport.createTime) }}</small>
            <small v-else>尚未运行</small>
          </div>
          <h3>生成项目接手手册</h3>
          <p>面向具体角色梳理项目定位、模块入口、启动方式、工程规范和信息缺口。</p>

          <div v-if="reportLoading.onboard" class="card-loading">
            <span class="loader"></span> 正在加载报告内容...
          </div>
          <template v-else-if="latestOnboardingReport">
            <!-- 目标角色 -->
            <div v-if="onboardingRoles.audience" class="card-role-badge">
              <span>目标角色</span>
              <strong>{{ onboardingRoles.audience }}</strong>
              <small v-if="onboardingRoles.level">{{ onboardingRoles.level }}</small>
              <em v-if="onboardingRoles.focusAreas">关注：{{ onboardingRoles.focusAreas }}</em>
            </div>

            <!-- 模块导航 -->
            <div v-if="onboardingSections.length" class="card-module-strip">
              <div
                v-for="(sec, si) in onboardingSections"
                :key="si"
                class="module-chip"
                @mouseenter="onboardingHover = si"
                @mouseleave="onboardingHover = -1"
              >{{ sec.title }}</div>
            </div>
            <transition name="tip">
              <div v-if="onboardingHover >= 0 && onboardingSections[onboardingHover]?.items?.length" class="card-module-tooltip">
                <div v-for="(item, ii) in onboardingSections[onboardingHover].items.slice(0, 4)" :key="ii" class="module-item-row">
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.description }}</p>
                </div>
              </div>
            </transition>

            <!-- 上手风险 -->
            <div v-if="onboardingRisks.length" class="card-inline-section">
              <p class="card-inline-label">上手风险 · {{ onboardingRisks.length }} 项</p>
              <div class="card-inline-risks">
                <div v-for="risk in onboardingRisks.slice(0, 3)" :key="risk.id" class="card-inline-risk">
                  <span class="risk-sev-dot" :class="severityClass(risk.severity)"></span>
                  <strong>{{ risk.title }}</strong>
                  <small>{{ severityLabel(risk.severity) }}</small>
                </div>
              </div>
            </div>

            <!-- 首周计划 -->
            <div v-if="onboardingPlan.length" class="card-inline-section">
              <p class="card-inline-label">首周计划 · {{ onboardingPlan.length }} 步</p>
              <div class="card-inline-plan">
                <div v-for="task in onboardingPlan.slice(0, 3)" :key="task.id" class="card-inline-plan-row">
                  <span>{{ task.id }}</span>
                  <strong>{{ task.title }}</strong>
                  <small>{{ task.ownerRole }}</small>
                </div>
              </div>
            </div>

            <div class="card-actions-row">
              <button type="button" class="card-btn report-btn" @click="openArtifactModal(latestOnboardingReport)">查看报告</button>
              <button type="button" class="card-btn" :disabled="running" @click="openTaskLauncher('PROJECT_ONBOARDING')">重新运行</button>
              <span v-if="onboardingCitations.length" class="card-cite-badge">引用 {{ onboardingCitations.length }} 条</span>
            </div>
          </template>
          <div v-else class="card-empty">
            <p>生成面向具体角色的项目接手手册，帮助新成员在一周内理解项目并完成第一个低风险交付。</p>
            <button type="button" class="primary-button" :disabled="running" @click="openTaskLauncher('PROJECT_ONBOARDING')">创建接手任务</button>
          </div>
        </article>

        <!-- Card 3: 研发决策助手 -->
        <article class="task-card">
          <div class="task-card-topline">
            <span class="task-card-eyebrow">方案与权衡</span>
            <small v-if="latestDecisionRun?.status && !isTerminal(latestDecisionRun.status)">运行中 {{ latestDecisionRun.progress || 0 }}%</small>
            <small v-else-if="latestDecisionReport">{{ formatDate(latestDecisionReport.createTime) }}</small>
            <small v-else>尚未运行</small>
          </div>
          <h3>研发决策助手</h3>
          <p>比较候选方案、显式列出假设与代价，并设计可回滚的验证步骤。</p>

          <div v-if="reportLoading.decision" class="card-loading">
            <span class="loader"></span> 正在加载报告内容...
          </div>
          <template v-else-if="latestDecisionReport">
            <!-- 建议结论 -->
            <div v-if="decisionRec" class="card-recommendation">
              <div class="rec-head">
                <span class="section-kicker">建议结论</span>
                <strong class="rec-confidence" :class="confidenceClass(decisionConfidence)">{{ confidenceLabel(decisionConfidence) }}</strong>
              </div>
              <p class="rec-text">{{ decisionRec }}</p>
            </div>

            <!-- 方案比较 -->
            <div v-if="decisionOptions.length" class="card-options-grid">
              <div v-for="(opt, oi) in decisionOptions" :key="oi" class="card-option-chip" :class="{ recommended: oi === 0 }">
                <strong class="opt-name">{{ opt.name }}</strong>
                <span class="opt-verdict">{{ opt.verdict }}</span>
                <div class="opt-counts">
                  <small class="opt-pro">利 {{ opt.benefits?.length || 0 }}</small>
                  <small class="opt-con">弊 {{ opt.costs?.length || 0 }}</small>
                  <small class="opt-risk">险 {{ opt.risks?.length || 0 }}</small>
                </div>
                <div v-if="opt.benefits?.[0]" class="opt-snippet">{{ opt.benefits[0] }}</div>
                <div v-if="opt.risks?.[0]" class="opt-snippet risk-snippet">{{ opt.risks[0] }}</div>
              </div>
            </div>

            <!-- 决策标准 -->
            <div v-if="decisionCriteria.length" class="card-inline-section">
              <p class="card-inline-label">决策标准</p>
              <div class="criteria-chips">
                <span v-for="(c, ci) in decisionCriteria" :key="ci" class="criteria-chip" :class="importanceClass(c.importance)">
                  {{ c.name }} <em>{{ importanceLabel(c.importance) }}</em>
                </span>
              </div>
            </div>

            <!-- 关键风险 -->
            <div v-if="decisionRisks.length" class="card-inline-section">
              <p class="card-inline-label">关键风险 · {{ decisionRisks.length }} 项</p>
              <div class="card-inline-risks">
                <div v-for="risk in decisionRisks.slice(0, 3)" :key="risk.id" class="card-inline-risk">
                  <span class="risk-sev-dot" :class="severityClass(risk.severity)"></span>
                  <strong>{{ risk.title }}</strong>
                  <small>{{ severityLabel(risk.severity) }}</small>
                </div>
              </div>
            </div>

            <!-- 验证计划 -->
            <div v-if="decisionPlan.length" class="card-inline-section">
              <p class="card-inline-label">验证计划 · {{ decisionPlan.length }} 步</p>
              <div class="card-inline-plan">
                <div v-for="task in decisionPlan.slice(0, 3)" :key="task.id" class="card-inline-plan-row">
                  <span>{{ task.id }}</span>
                  <strong>{{ task.title }}</strong>
                  <small>{{ task.ownerRole }}</small>
                </div>
              </div>
            </div>

            <div class="card-actions-row">
              <button type="button" class="card-btn report-btn" @click="openArtifactModal(latestDecisionReport)">查看报告</button>
              <button type="button" class="card-btn" :disabled="running" @click="openTaskLauncher('ENGINEERING_DECISION')">重新运行</button>
              <span class="card-cite-badge">引用 {{ decisionCitations.length }} 条</span>
            </div>
          </template>
          <div v-else class="card-empty">
            <p>选择方案，Agent 提供证据支持和验证计划，最终决定仍由人工审批。</p>
            <button type="button" class="primary-button" :disabled="running" @click="openTaskLauncher('ENGINEERING_DECISION')">发起决策分析</button>
          </div>
        </article>

      </section>

      <!-- ====== 侧栏 ====== -->
      <section class="sidebar-row">
        <div class="sidebar-grid">
          <article class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">审批闸门</p><h2>待审批动作</h2></div></div>
            <div v-if="pendingActions.length" class="action-list">
              <div v-for="action in pendingActions" :key="action.id" class="action-card">
                <span class="action-label">{{ actionTypeLabel(action.actionType) }}</span>
                <strong>{{ action.title }}</strong>
                <p>Agent 已生成草稿，确认后才会调用 GitHub 写接口。</p>
                <div class="action-buttons">
                  <button v-if="action.status === 'PENDING_APPROVAL'" type="button" class="primary-button small" @click="approveAction(action)">批准</button>
                  <button v-if="action.status === 'PENDING_APPROVAL'" type="button" class="quiet-button small" @click="rejectAction(action)">驳回</button>
                </div>
                <small v-if="action.errorMessage" class="action-error">{{ action.errorMessage }}</small>
              </div>
            </div>
            <div v-else class="blank-state">当前没有待审批外部动作。</div>
          </article>
          <article class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">证据库存</p><h2>证据库存</h2></div></div>
            <div v-if="evidenceSummary.length" class="inventory-list">
              <div v-for="item in evidenceSummary" :key="item.objectType" class="inventory-row"><span>{{ objectLabel(item.objectType) }}</span><strong>{{ item.count }}</strong></div>
            </div>
            <div v-if="evidence.length" class="evidence-list">
              <a v-for="item in evidence.slice(0, 8)" :key="item.id" :href="item.sourceUrl || undefined" target="_blank" rel="noreferrer" class="evidence-row">
                <span>{{ objectLabel(item.objectType) }}</span><strong>{{ item.title }}</strong><small>{{ item.sourceRef || item.sourceUrl }}</small>
              </a>
            </div>
            <div v-else class="blank-state">同步 GitHub 后会展示可引用证据。</div>
          </article>
          <article class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">项目上下文</p><h2>长期记忆</h2></div></div>
            <div v-if="project.memories?.length" class="memory-list">
              <div v-for="memory in project.memories" :key="memory.id" class="memory-row">
                <span>{{ memoryTypeLabel(memory.memoryType) }}</span><strong>{{ memory.title }}</strong><p>{{ memory.content }}</p>
              </div>
            </div>
            <div v-else class="blank-state">项目事实和决策确认后会沉淀在这里。</div>
          </article>
        </div>
      </section>

      <!-- ====== Run Observability Panel ====== -->
      <section v-if="selectedRun" class="run-observability-panel">
        <div class="panel-heading">
          <div><p class="section-kicker">运行观测</p><h2>运行详情 #{{ selectedRun.id }}</h2></div>
          <div class="panel-heading-actions">
            <span v-if="!isTerminal(selectedRun.status)" class="run-live-dot" title="运行中"></span>
            <button type="button" class="quiet-button small" @click="selectRun(selectedRun.id)">刷新</button>
          </div>
        </div>
        <div class="run-meta-row">
          <span>状态 <strong :class="runStatusClass(selectedRun.status)">{{ runStatusLabel(selectedRun.status) }}</strong></span>
          <span>类型 <strong>{{ runTypeLabel(selectedRun.runType) }}</strong></span>
          <span>进度 <strong>{{ selectedRun.progress || 0 }}%</strong></span>
          <span>步骤 <strong>{{ selectedRun.currentStep || '—' }}</strong></span>
        </div>
        <div v-if="selectedRun.errorMessage" class="run-error">{{ selectedRun.errorMessage }}</div>

        <!-- Harness 执行过程 -->
        <div class="run-harness-body">
          <template v-if="selectedRun.traces?.length">
            <p class="harness-section-label">Agent 执行轨迹</p>
            <div class="trace-timeline">
              <div v-for="(t, i) in selectedRun.traces" :key="i" class="trace-step" :class="traceStepClass(t.eventType)">
                <div class="trace-dot"></div>
                <div class="trace-content">
                  <div class="trace-head">
                    <strong>{{ traceEventLabel(t.eventType) }}</strong>
                    <small>#{{ t.sequenceNo }}</small>
                  </div>
                  <p v-if="t.summary">{{ t.summary }}</p>
                  <small class="trace-time">{{ formatDate(t.createTime) }}</small>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedRun.toolCalls?.length">
            <p class="harness-section-label">工具调用 · {{ selectedRun.toolCalls.length }} 次</p>
            <div class="tool-calls-grid">
              <div v-for="tc in selectedRun.toolCalls" :key="tc.id" class="tool-call-chip" :class="toolCallClass(tc.status)">
                <span class="tc-name">{{ tc.toolName }}</span>
                <span class="tc-status">{{ tc.status }}</span>
                <span class="tc-latency">{{ tc.latencyMs }}ms</span>
                <small v-if="tc.errorMessage" class="tc-error">{{ tc.errorMessage }}</small>
              </div>
            </div>
          </template>

          <div v-if="!selectedRun.traces?.length && !selectedRun.toolCalls?.length" class="blank-state">
            暂无执行轨迹。运行中的任务会逐步记录 Planner → Tool Calling → Reflection 过程。
          </div>
        </div>
      </section>
    </template>

    <div v-else class="blank-state page-blank">没有找到这个项目。</div>

    <!-- ====== Report Artifact Modal ====== -->
    <ReportArtifactModal
      :visible="artifactModal.visible"
      :report="artifactModal.report"
      :task-type="artifactModal.taskType"
      @close="artifactModal.visible = false"
    />

    <!-- ====== Task Launcher Modal ====== -->
    <div v-if="taskModalOpen" class="task-modal-backdrop" @click.self="closeTaskLauncher">
      <div class="task-modal" role="dialog" aria-modal="true">
        <button type="button" class="task-modal-close" aria-label="关闭" @click="closeTaskLauncher">&times;</button>
        <p class="section-kicker">{{ modalDef.eyebrow }}</p>
        <h2>{{ modalDef.title }}</h2>
        <p class="task-modal-intro">{{ modalDef.formIntro }}</p>
        <form @submit.prevent="submitTask">
          <label>任务目标</label>
          <textarea v-model.trim="taskForm.question" rows="4" :placeholder="modalDef.placeholder" required></textarea>

          <template v-if="taskForm.runType==='PROJECT_ONBOARDING'">
            <div class="task-form-grid">
              <div><label>接手角色</label><select v-model="taskForm.audience"><option>后端研发</option><option>前端研发</option><option>测试研发</option><option>技术负责人</option><option>全栈研发</option></select></div>
              <div><label>熟悉程度</label><select v-model="taskForm.experienceLevel"><option value="NEW_TO_STACK">不熟悉技术栈</option><option value="FAMILIAR_WITH_STACK">熟悉技术栈</option><option value="HANDOVER_OWNER">项目接手负责人</option></select></div>
            </div>
            <label>重点关注</label><input v-model.trim="taskForm.focusAreas" placeholder="例如：本地启动、核心模块、发布流程" />
          </template>
          <template v-if="taskForm.runType==='ENGINEERING_DECISION'">
            <label>已知备选方案</label><input v-model.trim="taskForm.options" placeholder="例如：继续单体、模块化重构、拆分微服务" />
            <label>约束条件</label><textarea v-model.trim="taskForm.constraints" rows="2" placeholder="例如：两周内完成、不能停机"></textarea>
          </template>
          <p v-if="taskFormError" class="task-form-error" role="alert">{{ taskFormError }}</p>
          <div class="task-modal-actions">
            <button type="button" class="quiet-button" @click="closeTaskLauncher">取消</button>
            <button type="submit" class="primary-button" :disabled="running">{{ modalDef.submitLabel }}</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { useMessage } from 'naive-ui'
import { useRoute } from 'vue-router'
import { approveProjectAction, getProject, getProjectEvidence, getProjectRun, startProjectRun, syncProjectEvidence } from '../api/index.js'
import ReportArtifactModal from '../components/ReportArtifactModal.vue'

const route = useRoute()
const message = useMessage()
const loading = ref(true)
const running = ref(false)
const syncing = ref(false)
const project = ref(null)
const evidence = ref([])
const selectedRun = ref(null)
const taskModalOpen = ref(false)
const taskFormError = ref('')
const tooltipOpen = ref('')
const onboardingHover = ref(-1)
const artifactModal = ref({ visible: false, report: null, taskType: 'HEALTH_ANALYSIS' })
const taskForm = ref({ runType:'HEALTH_ANALYSIS', question:'', audience:'后端研发', experienceLevel:'FAMILIAR_WITH_STACK', focusAreas:'', options:'', constraints:'' })
const reportLoading = ref({ health: false, onboard: false, decision: false })

const taskDefs = [
  { type:'HEALTH_ANALYSIS', eyebrow:'健康与交付', title:'项目健康分析', formIntro:'补充本次分析目标。健康分由规则引擎计算。', placeholder:'分析项目健康状态、关键风险和下一阶段交付计划', submitLabel:'开始健康分析' },
  { type:'PROJECT_ONBOARDING', eyebrow:'接手与入职', title:'生成项目接手手册', formIntro:'告诉 Agent 谁要接手、重点理解什么。', placeholder:'帮助新成员在一周内理解项目并完成第一个低风险交付', submitLabel:'生成接手手册' },
  { type:'ENGINEERING_DECISION', eyebrow:'方案与权衡', title:'研发决策助手', formIntro:'描述要做的选择。Agent 提供证据支持和验证计划。', placeholder:'例如：当前项目是否应该从单体架构拆分微服务？', submitLabel:'生成决策备忘录' }
]

const reportsByType = computed(() => {
  const m = {}
  for (const r of (project.value?.reports || [])) { const t = r.reportType || 'HEALTH_REPORT'; if (!m[t]) m[t] = r }
  return m
})
const latestHealthReport = computed(() => reportsByType.value['HEALTH_REPORT'] || null)
const latestOnboardingReport = computed(() => reportsByType.value['ONBOARDING_GUIDE'] || null)
const latestDecisionReport = computed(() => reportsByType.value['DECISION_MEMO'] || null)
const runs = computed(() => project.value?.runs || [])
const latestHealthRun = computed(() => runs.value.find(r => (r.runType||'HEALTH_ANALYSIS')==='HEALTH_ANALYSIS') || null)
const latestOnboardingRun = computed(() => runs.value.find(r => r.runType==='PROJECT_ONBOARDING') || null)
const latestDecisionRun = computed(() => runs.value.find(r => r.runType==='ENGINEERING_DECISION') || null)
const latestSyncJob = computed(() => project.value?.syncJobs?.[0] || null)
const evidenceSummary = computed(() => project.value?.evidenceSummary || [])
const dimensions = computed(() => parseJson(latestHealthReport.value?.dimensionsJson))
const risks = computed(() => parseJson(latestHealthReport.value?.risksJson))
const plan = computed(() => parseJson(latestHealthReport.value?.planJson))
const citations = computed(() => parseJson(latestHealthReport.value?.citationsJson))
const scoringRationale = computed(() => parseJson(latestHealthReport.value?.scoringRationaleJson))
const missingScoringSignals = computed(() => scoringRationale.value.filter(item => item.type==='MISSING'))
const sourceStatus = computed(() => project.value?.sources?.[0]?.status || 'PENDING')
const pendingActions = computed(() => selectedRun.value?.actions?.filter(a => ['PENDING_APPROVAL','APPROVED','BLOCKED'].includes(a.status)) || [])
const modalDef = computed(() => taskDefs.find(d => d.type===taskForm.value.runType) || taskDefs[0])

/* ── 接手手册 ── */
const onboardingContent = computed(() => parseJsonObject(latestOnboardingReport.value?.contentJson))
const onboardingSections = computed(() => onboardingContent.value?.sections || [])
const onboardingRisks = computed(() => parseJson(latestOnboardingReport.value?.risksJson))
const onboardingPlan = computed(() => parseJson(latestOnboardingReport.value?.planJson))
const onboardingCitations = computed(() => parseJson(latestOnboardingReport.value?.citationsJson))
const onboardingRoles = computed(() => {
  const taskInput = onboardingContent.value?.taskInput || {}
  const audience = taskInput.audience || '后端研发'
  const level = { NEW_TO_STACK:'不熟悉技术栈', FAMILIAR_WITH_STACK:'熟悉技术栈', HANDOVER_OWNER:'项目接手负责人' }[taskInput.experienceLevel] || ''
  return { audience, level, focusAreas: taskInput.focusAreas || '' }
})

/* ── 研发决策 ── */
const decisionContent = computed(() => parseJsonObject(latestDecisionReport.value?.contentJson))
const decisionRec = computed(() => decisionContent.value?.recommendation || '')
const decisionConfidence = computed(() => decisionContent.value?.confidence || '')
const decisionCriteria = computed(() => decisionContent.value?.criteria || [])
const decisionOptions = computed(() => decisionContent.value?.options || [])
const decisionRisks = computed(() => parseJson(latestDecisionReport.value?.risksJson))
const decisionPlan = computed(() => parseJson(latestDecisionReport.value?.planJson))
const decisionCitations = computed(() => parseJson(latestDecisionReport.value?.citationsJson))

function isTerminal(s) { return ['COMPLETED','FAILED','WAITING_APPROVAL'].includes(s) }

onMounted(loadProject)

async function loadProject() {
  loading.value = true
  try {
    const res = await getProject(route.params.id); project.value = res.data.data
    await loadEvidence()
    if (project.value?.runs?.[0]) await selectRun(project.value.runs[0].id)
    // Lazy-fetch full report content for structured card rendering
    fetchFullReports()
  } catch (e) { message.error(e.response?.data?.message || '项目加载失败') }
  finally { loading.value = false }
}

/** Fetch full report (with contentJson) for each card and merge into project.reports. */
async function fetchFullReports() {
  if (!project.value?.runs) return
  const reportTypeToRunType = { HEALTH_REPORT: 'HEALTH_ANALYSIS', ONBOARDING_GUIDE: 'PROJECT_ONBOARDING', DECISION_MEMO: 'ENGINEERING_DECISION' }
  const promises = []
  for (const run of project.value.runs) {
    const reportType = run.runType === 'HEALTH_ANALYSIS' ? 'HEALTH_REPORT'
      : run.runType === 'PROJECT_ONBOARDING' ? 'ONBOARDING_GUIDE'
      : run.runType === 'ENGINEERING_DECISION' ? 'DECISION_MEMO' : null
    if (!reportType) continue
    const existing = project.value.reports?.find(r => (r.reportType || 'HEALTH_REPORT') === reportType)
    if (existing?.contentJson) continue // already has full data
    const loadingKey = reportType === 'HEALTH_REPORT' ? 'health' : reportType === 'ONBOARDING_GUIDE' ? 'onboard' : 'decision'
    reportLoading.value[loadingKey] = true
    promises.push(
      getProjectRun(run.id).then(res => {
        const fullRun = res.data.data
        const fullReport = fullRun.report
        if (fullReport && project.value) {
          // Merge full report into project.reports
          const idx = project.value.reports.findIndex(r => (r.reportType || 'HEALTH_REPORT') === reportType)
          if (idx >= 0) {
            project.value.reports[idx] = { ...project.value.reports[idx], ...fullReport }
          } else if (fullReport.id) {
            project.value.reports.push(fullReport)
          }
        }
      }).catch(() => {}).finally(() => { reportLoading.value[loadingKey] = false })
    )
  }
  await Promise.all(promises)
}
async function loadEvidence() { const r = await getProjectEvidence(route.params.id, { limit: 50 }); evidence.value = r.data.data || [] }
async function syncEvidence() {
  syncing.value = true
  try { const r = await syncProjectEvidence(route.params.id); if (r.data.data?.status==='FAILED') message.error(r.data.data.errorMessage||'同步失败'); else message.success('GitHub 证据已同步'); await loadProject() }
  catch (e) { message.error(e.response?.data?.message || '同步失败') }
  finally { syncing.value = false }
}

function openTaskLauncher(runType) {
  const d = taskDefs.find(x => x.type===runType) || taskDefs[0]
  taskForm.value = { runType:d.type, question:d.placeholder, audience:'后端研发', experienceLevel:'FAMILIAR_WITH_STACK', focusAreas:'', options:'', constraints:'' }
  taskFormError.value = ''; taskModalOpen.value = true
}
function closeTaskLauncher() { if (!running.value) { taskModalOpen.value = false; taskFormError.value = '' } }

async function submitTask() {
  if (taskForm.value.question.trim().length < 6) { taskFormError.value = '请至少用一句完整的话说明任务目标。'; return }
  taskFormError.value = ''; running.value = true
  try {
    if (project.value?.repositoryUrl && !evidence.value.length) { message.info('首次运行前先同步 GitHub 项目证据'); syncing.value = true; await syncProjectEvidence(route.params.id); syncing.value = false; await loadProject() }
    const r = await startProjectRun(route.params.id, { triggerType:'MANUAL', ...taskForm.value })
    selectedRun.value = r.data.data; taskModalOpen.value = false
    message.success(`${modalDef.value.title}任务已创建，后台运行中`)
    await pollRun(selectedRun.value.id)
  } catch (e) { taskFormError.value = e.response?.data?.message || '无法启动任务'; message.error(taskFormError.value) }
  finally { running.value = false }
}

async function pollRun(runId) {
  for (let i = 0; i < 120; i += 1) { await new Promise(r => setTimeout(r, 2000)); try { const res = await getProjectRun(runId); selectedRun.value = res.data.data; if (['WAITING_APPROVAL','COMPLETED','FAILED'].includes(selectedRun.value.status)) break } catch { break } }
  await loadProject()
  if (selectedRun.value?.status==='COMPLETED') message.success('Agent 任务已完成')
  else if (selectedRun.value?.status==='FAILED') message.error(`任务失败：${selectedRun.value.errorMessage||'未知错误'}`)
}

async function selectRun(id) { const r = await getProjectRun(id); selectedRun.value = r.data.data }

function openArtifactModal(report) {
  const m = { HEALTH_REPORT:'HEALTH_ANALYSIS', ONBOARDING_GUIDE:'PROJECT_ONBOARDING', DECISION_MEMO:'ENGINEERING_DECISION' }
  artifactModal.value = { visible:true, report, taskType: m[report.reportType||'HEALTH_REPORT'] || 'HEALTH_ANALYSIS' }
}

async function approveAction(a) { try { const r = await approveProjectAction(selectedRun.value.id, a.id, { approved:true }); selectedRun.value = r.data.data; message.success('已批准') } catch (e) { message.error(e.response?.data?.message||'审批失败') } }
async function rejectAction(a) { try { const r = await approveProjectAction(selectedRun.value.id, a.id, { approved:false }); selectedRun.value = r.data.data; message.info('已驳回') } catch (e) { message.error(e.response?.data?.message||'审批失败') } }

function parseJson(v) { if (!v) return []; try { return JSON.parse(v) } catch { return [] } }
function parseJsonObject(v) { if (!v) return {}; try { return JSON.parse(v) } catch { return {} } }
function formatDate(v) { return v ? String(v).replace('T',' ').slice(0,16) : '' }
function shortHash(v) { return v ? String(v).slice(0,10) : '暂无快照' }
function healthClass(s) { return String(s||'UNKNOWN').toLowerCase() }
function healthLabel(s) { return { HEALTHY:'稳定', WATCH:'关注', AT_RISK:'有风险', UNKNOWN:'未分析' }[s] || '未分析' }
function sourceStatusClass(s) { return String(s||'PENDING').toLowerCase() }
function sourceStatusLabel(s) { return { READY:'已就绪', SYNCING:'同步中', FAILED:'失败', PENDING:'待同步' }[s] || '待同步' }
function runStatusLabel(s) { return { CREATED:'已创建', CONTEXT_BUILDING:'构建上下文', ANALYZING:'分析中', VERIFYING:'复核中', PLANNING:'规划中', WAITING_APPROVAL:'等待审批', COMPLETED:'已完成', FAILED:'失败' }[s] || s || '未知' }
function runTypeLabel(t) { return { HEALTH_ANALYSIS:'健康分析', PROJECT_ONBOARDING:'项目接手', ENGINEERING_DECISION:'研发决策' }[t] || t || '' }
function severityClass(s) { return { 高:'high',中:'medium',低:'low',HIGH:'high',MEDIUM:'medium',LOW:'low' }[s] || 'medium' }
function severityLabel(s) { return { HIGH:'高', MEDIUM:'中', LOW:'低' }[s] || s || '待确认' }
function actionTypeLabel(t) { return { CREATE_GITHUB_ISSUE:'创建 GitHub Issue' }[t] || t || '外部动作' }
function memoryTypeLabel(t) { return { FACT:'事实', DECISION:'决策', RISK:'风险', PREFERENCE:'偏好', PROJECT_CONTEXT:'项目上下文' }[t] || t || '记忆' }
function objectLabel(t) { return { GITHUB:'GitHub', REPO:'仓库', README:'README', FILE_TREE:'目录', FILE:'文件', ISSUE:'Issue', PR:'PR', COMMIT:'Commit', PROJECT_CONTEXT:'项目事实' }[t] || t }
function runStatusClass(s) { const m = { COMPLETED:'ok', FAILED:'error' }; return m[s]||'' }
function traceEventLabel(t) { return { PLAN_START:'规划开始', PLAN_DONE:'规划完成', TOOL_START:'工具调用开始', TOOL_DONE:'工具调用完成', REFLECT_START:'反思开始', REFLECT_DONE:'反思完成', REPLAN_REQUESTED:'请求重规划', REPLAN_DONE:'重规划完成', ARTIFACT_PERSISTED:'产物持久化', PLAN_SUMMARY:'规划摘要' }[t] || t }
function traceStepClass(t) { if (/START|REQUESTED/.test(t)) return 'active'; if (/DONE|PERSISTED/.test(t)) return 'done'; if (/FAIL/.test(t)) return 'failed'; return '' }
function toolCallClass(s) { return { DONE:'done', FAILED:'failed', RUNNING:'running' }[s] || '' }
function confidenceLabel(s) { return { HIGH:'高置信度', MEDIUM:'中等置信度', LOW:'低置信度' }[s] || s || '未评估' }
function confidenceClass(s) { return { HIGH:'high', MEDIUM:'medium', LOW:'low' }[s] || '' }
function importanceLabel(s) { return { HIGH:'高', MEDIUM:'中', LOW:'低' }[s] || s || '' }
function importanceClass(s) { return { HIGH:'high', MEDIUM:'medium', LOW:'low' }[s] || '' }
</script>

<style scoped>
/* ═══ Base ═══ */
.workbench-page{display:flex;flex-direction:column;gap:26px;min-width:0;overflow-x:clip}
.project-header{display:flex;justify-content:space-between;align-items:end;gap:30px;padding:10px 0 4px}
.back-link{color:var(--atlas-primary);font-size:12px;font-weight:800;text-decoration:none}
.project-title-row{display:flex;align-items:center;gap:10px;margin-top:24px}
.project-key{color:var(--atlas-primary);font-size:12px;font-weight:800;letter-spacing:.06em}
.health-chip{padding:4px 7px;border:1px solid currentColor;border-radius:3px;font-size:11px;font-weight:800}
.health-chip.healthy{color:#3f7f5d;background:rgba(63,127,93,.06)}
.health-chip.watch{color:var(--atlas-warning);background:rgba(167,121,61,.06)}
.health-chip.at_risk{color:#b35c56;background:rgba(179,92,86,.06)}
.health-chip.unknown{color:var(--atlas-subtle);background:var(--atlas-bg)}
.project-header h1{margin:10px 0 7px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:clamp(36px,5vw,52px);line-height:1.06;overflow-wrap:anywhere}
.project-header p{max-width:640px;margin:0;color:var(--atlas-muted);line-height:1.7}
.project-header-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px}
.quiet-button,.primary-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:0 14px;border-radius:4px;border:1px solid var(--atlas-border);font-size:13px;font-weight:800;cursor:pointer;text-decoration:none;white-space:nowrap}
.quiet-button{color:var(--atlas-muted);background:var(--atlas-surface)}
.quiet-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}
.primary-button{color:#fff;background:var(--atlas-primary);border-color:var(--atlas-primary)}
.primary-button:hover:not(:disabled){background:var(--atlas-primary-dark)}
.primary-button.small,.quiet-button.small{min-height:34px;padding:0 10px;font-size:12px}
button:disabled{cursor:not-allowed;opacity:.55}
.context-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--atlas-border);border-bottom:1px solid var(--atlas-border)}
.context-row div{display:flex;flex-direction:column;gap:5px;min-width:0;padding:15px 17px 14px 0;border-right:1px solid var(--atlas-border)}
.context-row div:not(:first-child){padding-left:17px}
.context-row div:last-child{border-right:0}
.context-row span,.source-status-grid span{color:var(--atlas-subtle);font-size:11px;font-weight:800;text-transform:uppercase}
.context-row strong,.source-status-grid strong{overflow-wrap:anywhere;color:var(--atlas-text);font-size:13px;line-height:1.4}
.source-sync-panel{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.55fr);gap:20px;min-width:0;padding:19px 0;border-top:2px solid var(--atlas-primary);border-bottom:1px solid var(--atlas-border)}
.source-copy{min-width:0}
.section-kicker{margin:0;color:var(--atlas-primary);font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
.source-copy h2{margin:6px 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:28px;overflow-wrap:anywhere}
.source-copy p:not(.section-kicker){max-width:720px;margin:0;color:var(--atlas-muted);font-size:13px;line-height:1.7}
.source-status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.source-status-grid div{min-width:0;padding:10px 12px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.source-status-grid strong.ready{color:#3f7f5d}.source-status-grid strong.failed{color:#b35c56}.source-status-grid strong.syncing{color:var(--atlas-warning)}
.sync-error{grid-column:1/-1;padding:10px 12px;color:#8f3f3b;background:rgba(179,92,86,.08);border:1px solid rgba(179,92,86,.18);font-size:12px;line-height:1.5}

/* ═══ Task Cards ═══ */
.task-cards-section{display:flex;flex-direction:column;gap:16px}
.task-card{min-width:0;padding:22px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;border-left:3px solid var(--atlas-primary)}
.task-card-topline{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px}
.task-card-eyebrow{color:var(--atlas-primary);font-size:10px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
.task-card-topline small{color:var(--atlas-subtle);font-size:10px;font-weight:700;white-space:nowrap}
.task-card h3{margin:0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:22px;line-height:1.3}
.task-card>p{margin:6px 0 0;color:var(--atlas-muted);font-size:13px;line-height:1.55;max-width:680px}

/* Health card content */
.card-health-grid{display:grid;grid-template-columns:160px minmax(0,1fr);gap:20px;margin-top:18px;padding:16px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.card-health-left{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:10px 0}
.card-metric-label{color:var(--atlas-subtle);font-size:10px;font-weight:800;text-transform:uppercase}
.card-metric-score{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:48px;line-height:1}
.card-metric-score small{margin-left:2px;color:var(--atlas-subtle);font-size:13px;font-family:var(--atlas-font-body)}
.card-metric-status{color:var(--atlas-primary);font-size:12px;font-weight:800}
.card-metric-time{color:var(--atlas-subtle);font-size:10px}
.card-health-right{display:flex;flex-direction:column;gap:10px;justify-content:center}
.card-dim-row{min-width:0}
.card-dim-head{display:flex;justify-content:space-between;gap:8px;margin-bottom:3px}
.card-dim-head span{color:var(--atlas-muted);font-size:11px}
.card-dim-head strong{color:var(--atlas-primary);font-family:var(--atlas-font-display);font-size:15px}
.card-dim-bar{height:4px;background:var(--atlas-surface-soft);border-radius:2px}
.card-dim-bar i{display:block;height:100%;background:var(--atlas-primary);border-radius:2px}

/* Card buttons */
.card-actions-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.card-btn{display:inline-flex;align-items:center;min-height:32px;padding:0 11px;border:1px solid var(--atlas-border);border-radius:3px;background:var(--atlas-bg);color:var(--atlas-muted);font-size:11px;font-weight:700;cursor:pointer;transition:all .15s}
.card-btn:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}
.card-btn:disabled{cursor:not-allowed;opacity:.45}
.report-btn{color:var(--atlas-primary);border-color:var(--atlas-primary);background:var(--atlas-surface-soft)}
.report-btn:hover{color:#fff;background:var(--atlas-primary)}
.tooltip-wrap{position:relative}
.card-tooltip{position:absolute;bottom:calc(100% + 10px);left:0;z-index:30;width:440px;max-width:calc(100vw - 40px);padding:14px;background:var(--atlas-surface);border:1px solid var(--atlas-border-strong);border-radius:4px;box-shadow:0 16px 36px rgba(15,23,42,.2)}
.scoring-tooltip{width:380px}.risks-tooltip{width:460px}
.tip-enter-active{transition:all .15s ease}.tip-leave-active{transition:all .1s ease}
.tip-enter-from,.tip-leave-to{opacity:0;transform:translateY(4px)}

/* Bottom grid (plan + citations) */
.card-bottom-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px;padding-top:16px;border-top:1px solid var(--atlas-border)}
.card-bottom-panel{min-width:0}
.card-plan-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--atlas-border)}
.card-plan-row span{width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;color:var(--atlas-primary);background:var(--atlas-surface-soft);font-size:9px;font-weight:800;flex:0 0 auto}
.card-plan-row strong{color:var(--atlas-text);font-size:11px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-plan-row small{color:var(--atlas-subtle);font-size:9px;white-space:nowrap}
.card-cite-row{display:flex;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid var(--atlas-border)}
.card-cite-row span{padding:2px 5px;color:var(--atlas-primary);background:var(--atlas-surface-soft);font-size:9px;font-weight:800}
.card-cite-row strong{color:var(--atlas-text);font-size:11px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Card empty / preview / loading */
.card-empty{padding:20px 0 4px}.card-empty p{color:var(--atlas-muted);font-size:13px;line-height:1.6;margin:0 0 14px}
.card-loading{display:flex;align-items:center;gap:9px;padding:18px 0 10px;color:var(--atlas-muted);font-size:12px}
.card-loading .loader{width:16px;height:16px;border:2px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite;flex:0 0 auto}
.card-report-preview{padding-top:14px}.card-preview-summary{color:var(--atlas-muted);font-size:13px;line-height:1.7;margin:0}

/* ── Onboarding card ── */
.card-role-badge{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px;padding:10px 14px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:4px}
.card-role-badge span{color:var(--atlas-subtle);font-size:10px;font-weight:800;text-transform:uppercase}
.card-role-badge strong{color:var(--atlas-text);font-size:13px}
.card-role-badge small{color:var(--atlas-primary);font-size:11px;font-weight:700}
.card-role-badge em{color:var(--atlas-muted);font-size:11px;font-style:normal}

.card-module-strip{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px}
.module-chip{display:inline-flex;padding:5px 10px;border:1px solid var(--atlas-border);border-radius:3px;color:var(--atlas-muted);font-size:11px;font-weight:700;cursor:default;transition:all .15s}
.module-chip:hover{color:var(--atlas-primary);border-color:var(--atlas-primary);background:var(--atlas-bg)}
.card-module-tooltip{position:relative;z-index:5;margin-top:8px;padding:12px;background:var(--atlas-bg);border:1px solid var(--atlas-border-strong);border-radius:4px;box-shadow:0 8px 20px rgba(15,23,42,.1)}
.module-item-row{padding:6px 0;border-bottom:1px solid var(--atlas-border)}
.module-item-row:last-child{border-bottom:0}
.module-item-row strong{color:var(--atlas-text);font-size:11px}
.module-item-row p{margin:2px 0 0;color:var(--atlas-muted);font-size:10px;line-height:1.45}

/* ── Decision card ── */
.card-recommendation{margin-top:16px;padding:14px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-left:3px solid var(--atlas-primary);border-radius:4px}
.rec-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
.rec-confidence{padding:2px 8px;border-radius:2px;font-size:10px;font-weight:800}
.rec-confidence.high{color:#3f7f5d;background:rgba(63,127,93,.08)}
.rec-confidence.medium{color:var(--atlas-warning);background:rgba(167,121,61,.08)}
.rec-confidence.low{color:#b35c56;background:rgba(179,92,86,.08)}
.rec-text{color:var(--atlas-text);font-size:13px;line-height:1.65;margin:0}

.card-options-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin-top:16px}
.card-option-chip{min-width:0;padding:12px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-bg)}
.card-option-chip.recommended{border-color:var(--atlas-primary);box-shadow:inset 0 0 0 1px var(--atlas-primary)}
.opt-name{display:block;color:var(--atlas-text);font-size:12px;font-weight:800}
.opt-verdict{display:block;margin-top:3px;color:var(--atlas-primary);font-size:10px;font-weight:700}
.opt-counts{display:flex;gap:8px;margin-top:6px}
.opt-counts small{font-size:10px;font-weight:700}
.opt-pro{color:#3f7f5d}.opt-con{color:var(--atlas-warning)}.opt-risk{color:#b35c56}
.opt-snippet{margin-top:6px;padding-top:6px;color:var(--atlas-muted);font-size:10px;line-height:1.4;border-top:1px solid var(--atlas-border)}
.opt-snippet.risk-snippet{color:#b35c56}

.criteria-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.criteria-chip{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border:1px solid var(--atlas-border);border-radius:3px;font-size:10px;font-weight:700;color:var(--atlas-muted)}
.criteria-chip.high{border-color:var(--atlas-primary);color:var(--atlas-primary)}
.criteria-chip em{font-size:9px;font-style:normal;font-weight:800;opacity:.8}

/* ── Shared inline sections for onboarding & decision ── */
.card-inline-section{margin-top:16px}
.card-inline-label{margin:0 0 6px;color:var(--atlas-text);font-size:11px;font-weight:800}
.card-inline-risks{display:flex;flex-direction:column;gap:4px}
.card-inline-risk{display:flex;align-items:center;gap:8px;padding:5px 0}
.risk-sev-dot{width:6px;height:6px;flex:0 0 auto;border-radius:50%;background:var(--atlas-primary)}
.risk-sev-dot.high{background:#b35c56}.risk-sev-dot.medium{background:var(--atlas-warning)}.risk-sev-dot.low{background:#7d9a87}
.card-inline-risk strong{color:var(--atlas-text);font-size:11px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-inline-risk small{color:var(--atlas-subtle);font-size:9px;font-weight:800;white-space:nowrap}
.card-inline-plan{display:flex;flex-direction:column;gap:2px}
.card-inline-plan-row{display:flex;align-items:center;gap:8px;padding:4px 0}
.card-inline-plan-row span{width:18px;height:18px;display:inline-flex;align-items:center;justify-content:center;color:var(--atlas-primary);background:var(--atlas-surface-soft);font-size:9px;font-weight:800;flex:0 0 auto}
.card-inline-plan-row strong{color:var(--atlas-text);font-size:11px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-inline-plan-row small{color:var(--atlas-subtle);font-size:9px;white-space:nowrap}

.card-cite-badge{margin-left:auto;color:var(--atlas-subtle);font-size:10px;font-weight:700;white-space:nowrap}

/* Score explain inside tooltip */
.score-explain-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-bottom:10px}
.score-explain-grid div{min-width:0;padding:8px;background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:3px}
.score-explain-grid span{display:block;color:var(--atlas-subtle);font-size:9px;font-weight:800;text-transform:uppercase}
.score-explain-grid strong{display:block;margin-top:3px;color:var(--atlas-text);font-size:11px}
.score-rationale-list{display:flex;flex-direction:column;gap:6px}
.score-rationale-item{padding:8px 0;border-top:1px solid var(--atlas-border)}
.score-rationale-item span{color:var(--atlas-subtle);font-size:9px;font-weight:800}
.score-rationale-item strong{display:block;margin-top:2px;color:var(--atlas-text);font-size:11px}
.score-rationale-item em{color:#b35c56;font-size:10px;font-weight:800;font-style:normal}
.score-rationale-item p{margin:3px 0 0;color:var(--atlas-muted);font-size:10px;line-height:1.45}

/* Tooltip risk list */
.risk-list{display:flex;flex-direction:column;gap:8px}
.risk-row{display:grid;grid-template-columns:4px minmax(0,1fr);gap:10px}
.risk-marker{width:4px;background:var(--atlas-primary)}.risk-marker.high{background:#b35c56}.risk-marker.medium{background:var(--atlas-warning)}.risk-marker.low{background:#7d9a87}
.risk-body{min-width:0}.risk-top{display:flex;justify-content:space-between;gap:8px}.risk-top strong{color:var(--atlas-text);font-size:12px}.risk-top span{color:var(--atlas-warning);font-size:10px;font-weight:800}
.risk-body p{margin:4px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.5}

/* ═══ Sidebar ═══ */
.sidebar-row{padding:0;border-top:1px solid var(--atlas-border);border-bottom:1px solid var(--atlas-border)}
.sidebar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;padding:20px 0}
.side-panel{min-width:0;padding:16px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.panel-heading{display:flex;align-items:end;justify-content:space-between;gap:14px}.panel-heading h2{margin:4px 0 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:17px;line-height:1.2}
.action-list,.memory-list,.evidence-list,.inventory-list{display:flex;flex-direction:column;gap:8px;margin-top:14px}
.action-card{padding:10px;border:1px solid var(--atlas-border);border-left:3px solid var(--atlas-warning);background:var(--atlas-bg)}
.action-label{color:var(--atlas-warning);font-size:10px;font-weight:800}
.action-card strong{display:block;margin-top:6px;color:var(--atlas-text);font-size:12px;line-height:1.4}
.action-card p{margin:6px 0;color:var(--atlas-muted);font-size:11px;line-height:1.5}
.action-buttons{display:flex;flex-wrap:wrap;gap:6px}
.action-error{display:block;margin-top:6px;color:#8f3f3b;font-size:10px}
.inventory-row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid var(--atlas-border)}
.inventory-row span{color:var(--atlas-muted);font-size:12px}.inventory-row strong{color:var(--atlas-primary);font-family:var(--atlas-font-display)}
.evidence-row,.memory-row{display:block;min-width:0;padding:8px 0;color:inherit;text-decoration:none;border-bottom:1px solid var(--atlas-border)}
.evidence-row span,.memory-row span{color:var(--atlas-primary);font-size:10px;font-weight:800}
.evidence-row strong,.memory-row strong{display:block;margin-top:4px;overflow:hidden;color:var(--atlas-text);font-size:12px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
.evidence-row small{display:block;margin-top:3px;overflow:hidden;color:var(--atlas-subtle);font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.memory-row p{margin:3px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.5}

/* ═══ Run Observability ═══ */
.run-observability-panel{padding:20px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}
.panel-heading-actions{display:flex;align-items:center;gap:10px}
.run-live-dot{width:9px;height:9px;border-radius:50%;background:var(--atlas-primary);animation:live-pulse 1.4s ease infinite}
@keyframes live-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(66,111,166,.5)}50%{opacity:.5;box-shadow:0 0 0 6px rgba(66,111,166,0)}}
.run-meta-row{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px}
.run-meta-row span{color:var(--atlas-subtle);font-size:11px;font-weight:800;text-transform:uppercase}
.run-meta-row strong{color:var(--atlas-text);font-size:13px}
.run-meta-row strong.ok{color:#3f7f5d}.run-meta-row strong.error{color:#b35c56}
.run-error{margin-top:12px;padding:10px;color:#8f3f3b;background:rgba(179,92,86,.06);border:1px solid rgba(179,92,86,.18);font-size:12px}

/* Harness body */
.run-harness-body{margin-top:18px;padding-top:16px;border-top:1px solid var(--atlas-border)}
.harness-section-label{margin:0 0 10px;color:var(--atlas-text);font-size:12px;font-weight:800}

/* Trace timeline */
.trace-timeline{display:flex;flex-direction:column;gap:0;position:relative;padding-left:18px;border-left:2px solid var(--atlas-border)}
.trace-step{display:grid;grid-template-columns:auto minmax(0,1fr);gap:12px;padding:8px 0;position:relative}
.trace-step:not(:last-child){padding-bottom:12px}
.trace-dot{position:absolute;left:-23px;top:11px;width:9px;height:9px;border-radius:50%;background:var(--atlas-border);border:2px solid var(--atlas-surface);z-index:1}
.trace-step.active .trace-dot{background:var(--atlas-primary);box-shadow:0 0 0 3px rgba(66,111,166,.18)}
.trace-step.done .trace-dot{background:#3f7f5d;border-color:#3f7f5d}
.trace-step.failed .trace-dot{background:#b35c56;border-color:#b35c56}
.trace-content{min-width:0}
.trace-head{display:flex;align-items:center;gap:8px}
.trace-head strong{color:var(--atlas-text);font-size:12px}
.trace-head small{color:var(--atlas-subtle);font-size:10px;font-weight:700}
.trace-content>p{margin:3px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.45}
.trace-time{display:block;margin-top:3px;color:var(--atlas-subtle);font-size:9px}

/* Tool calls */
.tool-calls-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.tool-call-chip{min-width:0;padding:10px;border:1px solid var(--atlas-border);border-left:3px solid var(--atlas-border);border-radius:3px;background:var(--atlas-bg)}
.tool-call-chip.done{border-left-color:#3f7f5d}
.tool-call-chip.failed{border-left-color:#b35c56;background:rgba(179,92,86,.04)}
.tool-call-chip.running{border-left-color:var(--atlas-primary)}
.tc-name{display:block;color:var(--atlas-primary);font-size:10px;font-weight:800;font-family:monospace}
.tc-status{display:inline-block;margin-top:4px;padding:1px 6px;border-radius:2px;font-size:9px;font-weight:800}
.tool-call-chip.done .tc-status{color:#3f7f5d;background:rgba(63,127,93,.08)}
.tool-call-chip.failed .tc-status{color:#b35c56;background:rgba(179,92,86,.08)}
.tool-call-chip.running .tc-status{color:var(--atlas-primary);background:rgba(66,111,166,.08)}
.tc-latency{display:block;margin-top:6px;color:var(--atlas-subtle);font-size:10px}
.tc-error{display:block;margin-top:4px;color:#b35c56;font-size:9px;line-height:1.4;overflow-wrap:anywhere}

.blank-state{padding:16px 0 4px;color:var(--atlas-muted);font-size:12px}.compact-blank{padding:8px 0 2px;font-size:11px}
.loading-block{display:flex;align-items:center;justify-content:center;gap:9px;min-height:50vh;color:var(--atlas-muted)}
.loader{width:20px;height:20px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}.page-blank{padding:80px 0;text-align:center}
@keyframes spin{to{transform:rotate(360deg)}}

/* ═══ Task Modal ═══ */
.task-modal-backdrop{position:fixed;inset:0;z-index:500;display:flex;align-items:flex-start;justify-content:center;padding:60px 24px 80px;background:rgba(15,23,42,.48);overflow-y:auto}
.task-modal{position:relative;width:min(600px,100%);padding:24px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-top:4px solid var(--atlas-primary);border-radius:4px;box-shadow:0 22px 48px rgba(15,23,42,.22)}
.task-modal-close{position:absolute;top:16px;right:20px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-muted);font-size:20px;cursor:pointer}
.task-modal-close:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}
.task-modal h2{margin:4px 0 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:22px}
.task-modal-intro{margin:8px 0 16px;color:var(--atlas-muted);font-size:13px;line-height:1.6}
.task-modal label{display:block;margin:14px 0 4px;color:var(--atlas-text);font-size:12px;font-weight:800}
.task-modal textarea,.task-modal input,.task-modal select{width:100%;min-height:40px;padding:8px 10px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-bg);color:var(--atlas-text);font-family:inherit;font-size:13px;outline:none;resize:vertical}
.task-modal textarea:focus,.task-modal input:focus,.task-modal select:focus{border-color:var(--atlas-primary);box-shadow:0 0 0 3px rgba(66,111,166,.12)}
.task-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:8px}
.task-form-error{margin:12px 0 0;padding:10px;color:#8f3f3b;background:rgba(179,92,86,.06);border:1px solid rgba(179,92,86,.18);border-radius:4px;font-size:12px}
.task-modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}

/* ═══ Responsive ═══ */
@media(max-width:900px){.source-sync-panel{grid-template-columns:1fr}.sidebar-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card-health-grid{grid-template-columns:1fr}.card-bottom-grid{grid-template-columns:1fr}}
@media(max-width:650px){.project-header{align-items:flex-start;flex-direction:column}.project-header-actions{justify-content:stretch;width:100%}.context-row,.source-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.context-row div:nth-child(2){border-right:0}.context-row div:nth-child(3),.context-row div:nth-child(4){border-top:1px solid var(--atlas-border)}.context-row div:nth-child(3){padding-left:0}.sidebar-grid{grid-template-columns:1fr}}
@media(max-width:420px){.project-header h1{font-size:36px}.card-health-left{padding:6px 0}.card-metric-score{font-size:38px}.card-tooltip{left:-20px;width:calc(100vw - 32px)}}
</style>
