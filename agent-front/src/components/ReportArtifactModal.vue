<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="visible" class="artifact-modal-backdrop" @click.self="close" @keydown.escape="close">
        <div class="artifact-modal" role="dialog" aria-modal="true" :aria-labelledby="modalTitleId">
          <header class="artifact-modal-header">
            <div>
              <p class="section-kicker">{{ typeLabel }}</p>
              <h2 :id="modalTitleId">{{ report?.title || typeLabel }}</h2>
            </div>
            <button type="button" class="artifact-modal-close" aria-label="关闭" @click="close">&times;</button>
          </header>

          <div class="artifact-modal-meta" v-if="report">
            <span v-if="report.scoringVersion">{{ report.scoringVersion }}</span>
            <span v-if="report.analysisMode">{{ report.analysisMode }}</span>
            <span v-if="report.healthScore != null">{{ report.healthScore }}/100</span>
            <span>{{ formatDate(report.createTime) }}</span>
          </div>

          <div class="artifact-modal-body">
            <!-- ── Health: score + dimensions + risks ── -->
            <template v-if="isHealth">
              <div v-if="report?.healthScore != null" class="modal-score-hero">
                <strong>{{ report.healthScore }}<small>/100</small></strong>
                <span>{{ healthLabel(report.healthStatus) }}</span>
              </div>
              <div v-if="modalDimensions.length" class="modal-dim-grid">
                <div v-for="d in modalDimensions" :key="d.name" class="modal-dim-row">
                  <div class="modal-dim-head"><span>{{ d.name }}</span><strong>{{ d.score }}</strong></div>
                  <div class="modal-dim-bar"><i :style="{ width: `${d.score}%` }"></i></div>
                  <p v-if="d.note">{{ d.note }}</p>
                </div>
              </div>
              <div v-if="modalRisks.length" class="modal-section">
                <p class="modal-section-label">风险清单 · {{ modalRisks.length }} 项</p>
                <div v-for="r in modalRisks" :key="r.id" class="modal-risk-row">
                  <span class="risk-sev" :class="sevClass(r.severity)">{{ sevLabel(r.severity) }}</span>
                  <strong>{{ r.title }}</strong>
                  <p>{{ r.description }}</p>
                </div>
              </div>
            </template>

            <!-- ── Onboarding: role + sections + risks ── -->
            <template v-if="isOnboarding">
              <div v-if="modalContent.taskInput" class="modal-role-tag">
                <span>目标角色</span>
                <strong>{{ modalContent.taskInput.audience || '后端研发' }}</strong>
                <small v-if="modalContent.taskInput.experienceLevel">{{ levelLabel(modalContent.taskInput.experienceLevel) }}</small>
              </div>
              <div v-if="modalContent.sections?.length" class="modal-section">
                <p class="modal-section-label">模块导航 · {{ modalContent.sections.length }} 章</p>
                <div v-for="(sec, si) in modalContent.sections" :key="si" class="modal-onboard-section">
                  <h4>{{ si + 1 }}. {{ sec.title }}</h4>
                  <div v-for="(item, ii) in (sec.items || [])" :key="ii" class="modal-onboard-item">
                    <strong>{{ item.title }}</strong>
                    <p>{{ item.description }}</p>
                  </div>
                </div>
              </div>
              <div v-if="modalRisks.length" class="modal-section">
                <p class="modal-section-label">上手风险 · {{ modalRisks.length }} 项</p>
                <div v-for="r in modalRisks" :key="r.id" class="modal-risk-row">
                  <span class="risk-sev" :class="sevClass(r.severity)">{{ sevLabel(r.severity) }}</span>
                  <strong>{{ r.title }}</strong>
                  <p>{{ r.description }}</p>
                </div>
              </div>
            </template>

            <!-- ── Decision: recommendation + options matrix + criteria ── -->
            <template v-if="isDecision">
              <div v-if="modalContent.recommendation" class="modal-recommendation">
                <span class="rec-badge" :class="confClass(modalContent.confidence)">{{ confLabel(modalContent.confidence) }}</span>
                <p>{{ modalContent.recommendation }}</p>
              </div>
              <div v-if="modalContent.options?.length" class="modal-section">
                <p class="modal-section-label">方案对比 · {{ modalContent.options.length }} 个方案</p>
                <div class="modal-options-table">
                  <div v-for="(opt, oi) in modalContent.options" :key="oi" class="modal-option-card" :class="{ pick: oi === 0 }">
                    <div class="opt-header">
                      <strong>{{ opt.name }}</strong>
                      <span v-if="oi === 0" class="opt-pick-badge">推荐</span>
                    </div>
                    <p class="opt-verdict">{{ opt.verdict }}</p>
                    <div v-if="opt.migrationCost" class="opt-dims">
                      <span>迁移成本 <em>{{ opt.migrationCost }}</em></span>
                      <span>安全风险 <em>{{ opt.safetyRisk }}</em></span>
                      <span>兼容性 <em>{{ opt.compatibility }}</em></span>
                      <span>团队熟悉度 <em>{{ opt.teamFamiliarity }}</em></span>
                    </div>
                    <div v-if="opt.benefits?.length" class="opt-list pro">
                      <p>优势</p><ul><li v-for="(b, bi) in opt.benefits.slice(0, 3)" :key="bi">{{ b }}</li></ul>
                    </div>
                    <div v-if="opt.risks?.length" class="opt-list con">
                      <p>风险</p><ul><li v-for="(r, ri) in opt.risks.slice(0, 3)" :key="ri">{{ r }}</li></ul>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="modalContent.criteria?.length" class="modal-section">
                <p class="modal-section-label">决策标准</p>
                <div class="modal-criteria-chips">
                  <span v-for="(c, ci) in modalContent.criteria" :key="ci" class="modal-criteria-chip" :class="impClass(c.importance)">{{ c.name }} · {{ impLabel(c.importance) }}</span>
                </div>
              </div>
            </template>

            <!-- ── Common: risks + plan ── -->
            <div v-if="modalRisks.length && (isOnboarding || isDecision)" class="modal-section" />

            <div v-if="modalPlan.length" class="modal-section">
              <p class="modal-section-label">执行计划 · {{ modalPlan.length }} 步</p>
              <div v-for="p in modalPlan" :key="p.id" class="modal-plan-row">
                <span>{{ p.id }}</span>
                <strong>{{ p.title }}</strong>
                <small>{{ p.ownerRole }}</small>
                <p v-if="p.acceptance">{{ p.acceptance }}</p>
              </div>
            </div>

            <!-- ── Markdown body ── -->
            <div v-if="report?.reportMarkdown" class="markdown-body" v-html="renderMarkdown(report.reportMarkdown)"></div>
            <div v-else-if="report?.summary && !isHealth && !isOnboarding && !isDecision" class="artifact-fallback">
              <p>{{ report.summary }}</p>
            </div>
            <div v-else-if="!hasStructuredContent" class="blank-state">该报告暂无详细内容。</div>
          </div>

          <footer class="artifact-modal-footer">
            <button type="button" class="quiet-button" @click="close">关闭</button>
            <button type="button" class="primary-button" @click="downloadArtifact" :disabled="!report?.reportMarkdown">
              导出 Markdown
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  visible: { type: Boolean, default: false },
  report: { type: Object, default: null },
  taskType: { type: String, default: 'HEALTH_ANALYSIS' }
})

const emit = defineEmits(['close'])

const typeLabel = computed(() => {
  return {
    HEALTH_ANALYSIS: '项目健康分析', HEALTH_REPORT: '项目健康分析',
    PROJECT_ONBOARDING: '项目接手手册', ONBOARDING_GUIDE: '项目接手手册',
    ENGINEERING_DECISION: '研发决策备忘录', DECISION_MEMO: '研发决策备忘录'
  }[props.taskType] || '任务产物'
})

const isHealth = computed(() => ['HEALTH_ANALYSIS', 'HEALTH_REPORT'].includes(props.taskType))
const isOnboarding = computed(() => ['PROJECT_ONBOARDING', 'ONBOARDING_GUIDE'].includes(props.taskType))
const isDecision = computed(() => ['ENGINEERING_DECISION', 'DECISION_MEMO'].includes(props.taskType))

const modalContent = computed(() => {
  const raw = props.report?.contentJson
  if (!raw) return {}
  try { return typeof raw === 'string' ? JSON.parse(raw) : raw } catch { return {} }
})

const modalDimensions = computed(() => {
  const raw = props.report?.dimensionsJson
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
})

const modalRisks = computed(() => {
  const raw = props.report?.risksJson
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
})

const modalPlan = computed(() => {
  const raw = props.report?.planJson
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
})

const hasStructuredContent = computed(() =>
  (props.report?.healthScore != null) || modalDimensions.value.length ||
  modalContent.value.sections?.length || modalContent.value.recommendation ||
  modalContent.value.options?.length || modalRisks.value.length ||
  modalPlan.value.length || !!props.report?.reportMarkdown
)

const modalTitleId = 'artifact-modal-title'

function close() { emit('close') }
function renderMarkdown(value) { return marked.parse(value || '', { breaks: true }) }
function formatDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }

function healthLabel(s) {
  return { HEALTHY: '稳定', WATCH: '关注', AT_RISK: '有风险', UNKNOWN: '未分析' }[s] || s || ''
}
function sevClass(s) { return { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' }[s] || 'medium' }
function sevLabel(s) { return { HIGH: '高', MEDIUM: '中', LOW: '低' }[s] || s || '' }
function confClass(s) { return { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' }[s] || '' }
function confLabel(s) { return { HIGH: '高置信度', MEDIUM: '中等置信度', LOW: '低置信度' }[s] || s || '' }
function impClass(s) { return { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' }[s] || '' }
function impLabel(s) { return { HIGH: '高', MEDIUM: '中', LOW: '低' }[s] || s || '' }
function levelLabel(v) {
  return { NEW_TO_STACK: '不熟悉技术栈', FAMILIAR_WITH_STACK: '熟悉技术栈', HANDOVER_OWNER: '项目接手负责人' }[v] || v || ''
}

function downloadArtifact() {
  const markdown = props.report?.reportMarkdown
  if (!markdown) return
  const typeSuffix = {
    HEALTH_ANALYSIS: '健康分析报告', HEALTH_REPORT: '健康分析报告',
    PROJECT_ONBOARDING: '项目接手手册', ONBOARDING_GUIDE: '项目接手手册',
    ENGINEERING_DECISION: '研发决策备忘录', DECISION_MEMO: '研发决策备忘录'
  }[props.taskType] || '任务产物'
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${typeSuffix}.md`
  link.click()
  URL.revokeObjectURL(link.href)
}

function onKeydown(event) { if (event.key === 'Escape' && props.visible) close() }

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  if (props.visible) document.body.style.overflow = 'hidden'
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
watch(() => props.visible, (value) => { document.body.style.overflow = value ? 'hidden' : '' })
</script>

<style scoped>
.artifact-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 500;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 48px 24px 60px;
  background: rgba(15, 23, 42, 0.48);
  overflow-y: auto;
}

.artifact-modal {
  width: min(820px, 100%);
  max-height: none;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-top: 4px solid var(--atlas-primary);
  border-radius: 4px;
  box-shadow: 0 22px 48px rgba(15, 23, 42, 0.22);
  display: flex;
  flex-direction: column;
}

.artifact-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px 0;
}

.artifact-modal-header h2 {
  margin: 4px 0 0;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 26px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.artifact-modal-close {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  background: var(--atlas-surface);
  color: var(--atlas-muted);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}

.artifact-modal-close:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.artifact-modal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--atlas-border);
}

.artifact-modal-meta span {
  padding: 4px 8px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 3px;
  font-size: 11px;
  font-weight: 800;
}

.artifact-modal-body {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
}

.artifact-modal-body .markdown-body {
  font-size: 15px;
  line-height: 1.85;
}

.artifact-fallback p {
  color: var(--atlas-muted);
  font-size: 14px;
  line-height: 1.7;
}

.artifact-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--atlas-border);
}

.quiet-button,
.primary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 4px;
  border: 1px solid var(--atlas-border);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  text-decoration: none;
  white-space: nowrap;
}

.quiet-button {
  color: var(--atlas-muted);
  background: var(--atlas-surface);
}

.quiet-button:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.primary-button {
  color: #fff;
  background: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.primary-button:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.blank-state {
  padding: 22px 0 5px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
}

/* ── Structured modal content ── */
.modal-score-hero {
  display: flex; align-items: baseline; gap: 12px; margin-bottom: 20px; padding: 16px;
  background: var(--atlas-bg); border: 1px solid var(--atlas-border); border-radius: 4px;
}
.modal-score-hero strong {
  color: var(--atlas-text); font-family: var(--atlas-font-display); font-size: 42px; line-height: 1;
}
.modal-score-hero strong small { font-size: 14px; color: var(--atlas-subtle); font-family: var(--atlas-font-body); }
.modal-score-hero > span { color: var(--atlas-primary); font-size: 13px; font-weight: 800; }

.modal-dim-grid { display: flex; flex-direction: column; gap: 10px; margin-bottom: 20px; }
.modal-dim-row { min-width: 0; }
.modal-dim-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 3px; }
.modal-dim-head span { color: var(--atlas-muted); font-size: 12px; }
.modal-dim-head strong { color: var(--atlas-primary); font-family: var(--atlas-font-display); font-size: 16px; }
.modal-dim-bar { height: 4px; background: var(--atlas-surface-soft); border-radius: 2px; }
.modal-dim-bar i { display: block; height: 100%; background: var(--atlas-primary); border-radius: 2px; }
.modal-dim-row p { margin: 4px 0 0; color: var(--atlas-muted); font-size: 12px; line-height: 1.5; }

.modal-section { margin-bottom: 18px; }
.modal-section-label { margin: 0 0 8px; color: var(--atlas-text); font-size: 12px; font-weight: 800; }

.modal-risk-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; padding: 8px 0; border-bottom: 1px solid var(--atlas-border); }
.modal-risk-row strong { color: var(--atlas-text); font-size: 12px; }
.modal-risk-row p { width: 100%; margin: 4px 0 0; color: var(--atlas-muted); font-size: 11px; line-height: 1.45; }
.risk-sev { padding: 1px 6px; border-radius: 2px; font-size: 9px; font-weight: 800; }
.risk-sev.high { color: #b35c56; background: rgba(179,92,86,.08); }
.risk-sev.medium { color: var(--atlas-warning); background: rgba(167,121,61,.08); }
.risk-sev.low { color: #7d9a87; background: rgba(125,154,135,.08); }

.modal-role-tag { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; padding: 10px 14px; background: var(--atlas-bg); border: 1px solid var(--atlas-border); border-radius: 4px; }
.modal-role-tag span { color: var(--atlas-subtle); font-size: 10px; font-weight: 800; text-transform: uppercase; }
.modal-role-tag strong { color: var(--atlas-text); font-size: 13px; }
.modal-role-tag small { color: var(--atlas-primary); font-size: 11px; font-weight: 700; }

.modal-onboard-section { margin-bottom: 14px; }
.modal-onboard-section h4 { margin: 0 0 6px; color: var(--atlas-text); font-size: 14px; }
.modal-onboard-item { padding: 8px 0; border-bottom: 1px solid var(--atlas-border); }
.modal-onboard-item:last-child { border-bottom: 0; }
.modal-onboard-item strong { color: var(--atlas-text); font-size: 12px; }
.modal-onboard-item p { margin: 3px 0 0; color: var(--atlas-muted); font-size: 11px; line-height: 1.5; }

.modal-recommendation { margin-bottom: 18px; padding: 14px; background: var(--atlas-bg); border: 1px solid var(--atlas-border); border-left: 3px solid var(--atlas-primary); border-radius: 4px; }
.modal-recommendation p { margin: 8px 0 0; color: var(--atlas-text); font-size: 13px; line-height: 1.65; }
.rec-badge { display: inline-block; padding: 2px 8px; border-radius: 2px; font-size: 10px; font-weight: 800; }
.rec-badge.high { color: #3f7f5d; background: rgba(63,127,93,.08); }
.rec-badge.medium { color: var(--atlas-warning); background: rgba(167,121,61,.08); }
.rec-badge.low { color: #b35c56; background: rgba(179,92,86,.08); }

.modal-options-table { display: flex; flex-direction: column; gap: 10px; }
.modal-option-card { padding: 14px; border: 1px solid var(--atlas-border); border-radius: 4px; background: var(--atlas-bg); }
.modal-option-card.pick { border-color: var(--atlas-primary); box-shadow: inset 0 0 0 1px var(--atlas-primary); }
.opt-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.opt-header strong { color: var(--atlas-text); font-size: 13px; }
.opt-pick-badge { padding: 1px 6px; border-radius: 2px; color: var(--atlas-primary); background: rgba(66,111,166,.08); font-size: 9px; font-weight: 800; }
.opt-verdict { margin: 0; color: var(--atlas-primary); font-size: 11px; font-weight: 700; }
.opt-dims { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.opt-dims span { padding: 2px 7px; border: 1px solid var(--atlas-border); border-radius: 3px; font-size: 9px; color: var(--atlas-muted); }
.opt-dims em { font-style: normal; font-weight: 800; color: var(--atlas-text); margin-left: 2px; }
.opt-list { margin-top: 8px; }
.opt-list p { margin: 0; font-size: 10px; font-weight: 800; }
.opt-list.pro p { color: #3f7f5d; }
.opt-list.con p { color: #b35c56; }
.opt-list ul { margin: 3px 0 0; padding-left: 16px; }
.opt-list li { color: var(--atlas-muted); font-size: 11px; line-height: 1.5; }

.modal-criteria-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.modal-criteria-chip { padding: 4px 10px; border: 1px solid var(--atlas-border); border-radius: 3px; font-size: 10px; font-weight: 700; color: var(--atlas-muted); }
.modal-criteria-chip.high { border-color: var(--atlas-primary); color: var(--atlas-primary); }

.modal-plan-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--atlas-border); }
.modal-plan-row span { width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; color: var(--atlas-primary); background: var(--atlas-surface-soft); font-size: 9px; font-weight: 800; flex: 0 0 auto; }
.modal-plan-row strong { color: var(--atlas-text); font-size: 12px; }
.modal-plan-row small { color: var(--atlas-subtle); font-size: 10px; }
.modal-plan-row p { width: 100%; margin: 4px 0 0; color: var(--atlas-muted); font-size: 11px; line-height: 1.45; }

/* Transition */
.modal-enter-active {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-leave-active {
  transition: all 0.15s ease;
}

.modal-enter-from {
  opacity: 0;
}

.modal-enter-from .artifact-modal {
  transform: translateY(24px) scale(0.97);
  opacity: 0;
}

.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .artifact-modal {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-leave-active .artifact-modal {
  transition: all 0.15s ease;
}

@media (max-width: 620px) {
  .artifact-modal-backdrop {
    padding: 16px 8px 40px;
  }

  .artifact-modal-header h2 {
    font-size: 21px;
  }

  .artifact-modal-body {
    padding: 16px;
  }
}
</style>
