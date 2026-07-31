<template>
  <div class="overview-page">
    <section class="overview-hero">
      <div>
        <p class="eyebrow"><span class="eyebrow-mark"></span> AtlasMind / R&D control plane</p>
        <h1>把项目状态变成<br><em>可行动的交付判断</em></h1>
        <p class="hero-copy">
          连接项目事实、Agent 参考库和 Agent Run。先看全局风险，再进入一个项目核验证据、生成计划并提交经过审批的执行动作。
        </p>
      </div>
      <div class="hero-aside">
        <div class="hero-aside-label">本次工作区信号</div>
        <strong>{{ overview.projectCount || 0 }} 个项目</strong>
        <span>{{ overview.activeRuns || 0 }} 个运行中的 Agent Run</span>
        <span>{{ overview.pendingApprovals || 0 }} 个待审批动作</span>
      </div>
    </section>

    <section class="signal-strip" aria-label="workspace signals">
      <div class="signal-cell"><span>项目总数</span><strong>{{ overview.projectCount || 0 }}</strong><small>当前组织工作区</small></div>
      <div class="signal-cell"><span>风险项目</span><strong class="risk-number">{{ overview.riskProjects || 0 }}</strong><small>需要负责人关注</small></div>
      <div class="signal-cell"><span>运行中</span><strong>{{ overview.activeRuns || 0 }}</strong><small>异步 Agent Run</small></div>
      <div class="signal-cell"><span>待审批</span><strong>{{ overview.pendingApprovals || 0 }}</strong><small>外部写操作已拦截</small></div>
    </section>

    <section class="section-head">
      <div><p class="section-kicker">项目组合视图</p><h2>项目总览</h2><p>从项目健康状态进入具体证据、风险和交付计划。</p></div>
      <button type="button" class="quiet-button" @click="loadOverview" :disabled="loading"><span aria-hidden="true">↻</span> {{ loading ? '同步中' : '刷新状态' }}</button>
    </section>

    <section v-if="loading && !projects.length" class="empty-panel"><span class="loader"></span><strong>正在装载项目上下文</strong><p>读取项目事实、历史 Agent Run 和审批状态。</p></section>
    <section v-else class="project-grid">
      <router-link v-for="project in visibleProjects" :key="project.id" :to="`/projects/${project.id}`" class="project-card">
        <div class="project-card-top"><span class="project-key">{{ project.projectKey }}</span><span class="health-chip" :class="healthClass(project.healthStatus)">{{ healthLabel(project.healthStatus) }}</span></div>
        <h3>{{ project.name }}</h3>
        <p class="project-description">{{ project.description || '尚未补充项目描述。' }}</p>
        <div class="score-line"><strong>{{ project.healthScore || '—' }}</strong><span>/ 100 健康信号</span><div class="score-bar"><i :style="{ width: `${project.healthScore || 0}%` }"></i></div></div>
        <div class="project-meta">
          <span>{{ sourceTypeLabel(project.repositoryType) }}</span>
          <span>{{ project.evidenceCount || 0 }} 条证据</span>
          <span>{{ syncLabel(project.syncStatus) }}</span>
          <span>{{ project.runCount || 0 }} 次运行</span>
          <span>{{ project.openRisks || 0 }} 个审批</span>
        </div>
        <div class="project-card-footer"><span>{{ project.currentMilestone || '待设置里程碑' }}</span><span class="arrow" aria-hidden="true">↗</span></div>
      </router-link>
      <button type="button" class="new-project-card" @click="showCreate = true">
        <span class="new-project-icon" aria-hidden="true">＋</span><strong>接入一个项目</strong><span>绑定 GitHub 仓库，开始第一条健康分析闭环。</span>
      </button>
    </section>

    <section class="lower-grid">
      <div class="lower-panel">
        <div class="panel-heading"><div><p class="section-kicker">运行模型</p><h2>一条可审计的工作链</h2></div><router-link to="/knowledge" class="text-link">查看 Agent 参考库 ↗</router-link></div>
        <div class="workflow-line">
          <div v-for="(item, index) in workflow" :key="item.title" class="workflow-step"><span class="step-index">0{{ index + 1 }}</span><strong>{{ item.title }}</strong><p>{{ item.description }}</p></div>
        </div>
      </div>
      <div class="lower-panel boundary-panel">
        <p class="section-kicker">执行边界</p><h2>先判断，再执行</h2>
        <p>分析、引用和计划可以自动运行；创建 GitHub Issue 之前，必须经过人工审批。代码修改、合并 PR 和部署暂不自动化。</p>
        <div class="boundary-tags"><span>RAG</span><span>Tool Calling</span><span>Evidence Review</span><span>Approval Gate</span></div>
      </div>
    </section>

    <div v-if="showCreate" class="modal-backdrop" @click.self="showCreate = false">
      <form class="create-modal" @submit.prevent="createProjectNow">
        <button type="button" class="modal-close" aria-label="关闭" @click="showCreate = false">×</button>
        <p class="section-kicker">项目接入</p><h2>接入研发项目</h2><p class="modal-copy">先录入少量业务事实，再让 Agent 读取 GitHub 和技术文档。</p>
        <label>项目名称<input v-model="form.name" required placeholder="例如：支付服务重构" /></label>
        <label>GitHub 仓库<input v-model="form.repositoryUrl" placeholder="https://github.com/org/repository" /></label>
        <label>当前里程碑<input v-model="form.currentMilestone" placeholder="例如：MVP 验收" /></label>
        <label>项目目标<textarea v-model="form.businessScope" rows="3" placeholder="用一句话描述业务目标和范围"></textarea></label>
        <div class="modal-actions"><button type="button" class="quiet-button" @click="showCreate = false">取消</button><button type="submit" class="primary-button" :disabled="creating">{{ creating ? '创建中' : '创建项目' }}</button></div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { createProject, getProjectOverview } from '../api/index.js'

const message = useMessage()
const route = useRoute()
const loading = ref(false)
const creating = ref(false)
const showCreate = ref(false)
const projects = ref([])
const overview = ref({})
const form = ref({ name: '', repositoryUrl: '', currentMilestone: '', businessScope: '' })
const visibleProjects = computed(() => {
  const keyword = String(route.query.keyword || '').trim().toLowerCase()
  if (!keyword) return projects.value
  return projects.value.filter(project => [
    project.name,
    project.projectKey,
    project.description,
    project.repositoryUrl,
    project.currentMilestone,
    project.techStack
  ].filter(Boolean).some(value => String(value).toLowerCase().includes(keyword)))
})
const workflow = [
  { title: '装载上下文', description: '项目事实、知识源、历史记忆' },
  { title: '检索证据', description: 'RAG + GitHub connector' },
  { title: '核验结论', description: 'Reviewer 拦截无依据判断' },
  { title: '审批动作', description: '人确认后才写入外部系统' }
]

onMounted(loadOverview)

async function loadOverview() {
  loading.value = true
  try {
    const response = await getProjectOverview()
    overview.value = response.data.data || {}
    projects.value = overview.value.projects || []
  } catch (error) {
    message.error(error.response?.data?.message || '项目总览加载失败')
  } finally {
    loading.value = false
  }
}

async function createProjectNow() {
  creating.value = true
  try {
    const response = await createProject(form.value)
    const project = response.data.data
    showCreate.value = false
    form.value = { name: '', repositoryUrl: '', currentMilestone: '', businessScope: '' }
    await loadOverview()
    message.success('项目已接入')
    if (project?.id) window.location.href = `${import.meta.env.BASE_URL}projects/${project.id}`
  } catch (error) {
    message.error(error.response?.data?.message || '项目创建失败')
  } finally {
    creating.value = false
  }
}

function healthClass(status) { return String(status || 'UNKNOWN').toLowerCase() }
function healthLabel(status) { return { HEALTHY: '稳定', WATCH: '关注', AT_RISK: '有风险', UNKNOWN: '未分析' }[status] || '未分析' }
function syncLabel(status) { return { READY: '已同步', SYNCING: '同步中', FAILED: '同步失败', PENDING: '待同步' }[status] || '待同步' }
function sourceTypeLabel(type) { return { GITHUB: 'GitHub 仓库', LOCAL: '本地项目', JIRA: 'Jira', ZENTAO: '禅道', CI: 'CI/CD' }[type] || '证据源' }
</script>

<style scoped>
/* Hallmark | macrostructure: Portfolio Desk | tone: calm operational engineering | anchor hue: ink blue */
.overview-page{display:flex;flex-direction:column;gap:34px}.overview-hero{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:42px;padding:28px 0 4px}.eyebrow,.section-kicker{margin:0;color:var(--atlas-primary);font-size:12px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}.eyebrow{display:flex;align-items:center;gap:8px}.eyebrow-mark{width:10px;height:10px;border:2px solid var(--atlas-primary);border-radius:2px}.overview-hero h1{max-width:680px;margin:16px 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:clamp(38px,5vw,64px);line-height:1.05;overflow-wrap:anywhere}.overview-hero h1 em{color:var(--atlas-primary);font-style:normal}.hero-copy{max-width:630px;margin:0;color:var(--atlas-muted);font-size:16px;line-height:1.8}.hero-aside{align-self:end;display:flex;flex-direction:column;gap:8px;padding:18px 0 4px 20px;border-left:2px solid var(--atlas-primary)}.hero-aside-label{color:var(--atlas-subtle);font-size:12px;font-weight:700}.hero-aside strong{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:28px}.hero-aside span{color:var(--atlas-muted);font-size:13px}.signal-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--atlas-border);border-bottom:1px solid var(--atlas-border)}.signal-cell{display:flex;flex-direction:column;gap:4px;min-width:0;padding:18px 20px 16px 0;border-right:1px solid var(--atlas-border)}.signal-cell:not(:first-child){padding-left:20px}.signal-cell:last-child{border-right:0}.signal-cell span{color:var(--atlas-muted);font-size:12px;font-weight:700}.signal-cell strong{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:29px;line-height:1.1}.signal-cell strong.risk-number{color:var(--atlas-warning)}.signal-cell small{color:var(--atlas-subtle);font-size:12px}.section-head,.panel-heading{display:flex;align-items:end;justify-content:space-between;gap:20px}.section-head h2,.panel-heading h2,.create-modal h2{margin:7px 0 4px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:30px;line-height:1.2}.section-head>div>p:last-child,.panel-heading p:last-child{margin:0;color:var(--atlas-muted);font-size:14px;line-height:1.6}.quiet-button,.primary-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:0 14px;border-radius:4px;border:1px solid var(--atlas-border);font-size:13px;font-weight:800;cursor:pointer}.quiet-button{color:var(--atlas-muted);background:var(--atlas-surface)}.quiet-button:hover:not(:disabled){color:var(--atlas-primary);border-color:var(--atlas-primary)}.primary-button{color:#fff;background:var(--atlas-primary);border-color:var(--atlas-primary)}.primary-button:hover:not(:disabled){background:var(--atlas-primary-dark)}button:disabled{cursor:not-allowed;opacity:.55}.project-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.project-card,.new-project-card{min-width:0;min-height:282px;padding:18px;text-decoration:none}.project-card{display:flex;flex-direction:column;color:inherit;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;transition:border-color .18s,transform .18s}.project-card:hover{border-color:var(--atlas-primary);transform:translateY(-2px)}.project-card-top,.project-card-footer,.project-meta,.score-line{display:flex;align-items:center}.project-card-top,.project-card-footer{justify-content:space-between;gap:12px}.project-key{color:var(--atlas-primary);font-size:12px;font-weight:800;letter-spacing:.05em}.health-chip{padding:4px 7px;border:1px solid currentColor;border-radius:3px;font-size:11px;font-weight:800}.health-chip.healthy{color:#3f7f5d;background:rgba(63,127,93,.06)}.health-chip.watch{color:var(--atlas-warning);background:rgba(167,121,61,.06)}.health-chip.at_risk{color:#b35c56;background:rgba(179,92,86,.06)}.health-chip.unknown{color:var(--atlas-subtle);background:var(--atlas-bg)}.project-card h3{margin:24px 0 8px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:23px;line-height:1.2;overflow-wrap:anywhere}.project-description{display:-webkit-box;min-height:42px;margin:0;overflow:hidden;color:var(--atlas-muted);font-size:13px;line-height:1.6;-webkit-line-clamp:2;-webkit-box-orient:vertical}.score-line{position:relative;flex-wrap:wrap;gap:5px;margin-top:auto;padding-top:20px}.score-line strong{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:34px}.score-line span{color:var(--atlas-subtle);font-size:11px}.score-bar{flex-basis:100%;height:4px;margin-top:7px;background:var(--atlas-surface-soft)}.score-bar i{display:block;height:100%;background:var(--atlas-primary)}.project-meta{flex-wrap:wrap;gap:8px 14px;margin-top:15px;color:var(--atlas-subtle);font-size:11px}.project-card-footer{margin-top:18px;padding-top:13px;color:var(--atlas-muted);border-top:1px solid var(--atlas-border);font-size:12px}.arrow{color:var(--atlas-primary);font-size:18px}.new-project-card{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;color:var(--atlas-muted);background:transparent;border:1px dashed var(--atlas-border-strong);border-radius:4px;text-align:left;cursor:pointer}.new-project-card:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}.new-project-icon{margin-bottom:15px;color:var(--atlas-primary);font-size:28px;line-height:1}.new-project-card strong{color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:21px}.new-project-card span:last-child{max-width:210px;margin-top:8px;color:var(--atlas-muted);font-size:13px;line-height:1.6}.lower-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr);gap:14px}.lower-panel{min-width:0;padding:20px;border-top:2px solid var(--atlas-primary);background:var(--atlas-surface);border-bottom:1px solid var(--atlas-border)}.workflow-line{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:28px}.workflow-step{min-width:0;padding-top:12px;border-top:1px solid var(--atlas-border)}.step-index{color:var(--atlas-primary);font-family:var(--atlas-font-display);font-size:20px}.workflow-step strong{display:block;margin-top:13px;color:var(--atlas-text);font-size:14px}.workflow-step p{margin:6px 0 0;color:var(--atlas-muted);font-size:12px;line-height:1.6}.text-link{color:var(--atlas-primary);font-size:12px;font-weight:800;text-decoration:none}.boundary-panel h2{margin-top:12px}.boundary-panel>p:not(.section-kicker){color:var(--atlas-muted);font-size:14px;line-height:1.75}.boundary-tags{display:flex;flex-wrap:wrap;gap:7px;margin-top:22px}.boundary-tags span{padding:5px 7px;color:var(--atlas-primary);background:var(--atlas-surface-soft);border:1px solid var(--atlas-border);border-radius:3px;font-size:11px;font-weight:700}.empty-panel{display:flex;flex-direction:column;align-items:center;gap:8px;padding:58px 20px;border:1px dashed var(--atlas-border-strong);color:var(--atlas-muted);text-align:center}.empty-panel strong{color:var(--atlas-text)}.empty-panel p{margin:0;font-size:13px}.loader{width:26px;height:26px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}.modal-backdrop{position:fixed;inset:0;z-index:200;display:grid;place-items:center;padding:20px;background:rgba(15,23,42,.36)}.create-modal{position:relative;width:min(500px,100%);padding:28px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;box-shadow:0 20px 60px rgba(15,23,42,.18)}.modal-close{position:absolute;top:14px;right:15px;color:var(--atlas-muted);background:transparent;border:0;font-size:24px;cursor:pointer}.modal-copy{margin:0 0 22px;color:var(--atlas-muted);font-size:13px;line-height:1.6}.create-modal label{display:flex;flex-direction:column;gap:6px;margin-top:14px;color:var(--atlas-text);font-size:12px;font-weight:800}.create-modal input,.create-modal textarea{width:100%;padding:10px 11px;color:var(--atlas-text);background:var(--atlas-bg);border:1px solid var(--atlas-border);border-radius:3px;outline:0;font:inherit;font-weight:400;resize:vertical}.create-modal input:focus,.create-modal textarea:focus{border-color:var(--atlas-primary);box-shadow:0 0 0 3px rgba(66,111,166,.12)}.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:24px}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:920px){.project-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.lower-grid{grid-template-columns:1fr}}@media(max-width:680px){.overview-hero{grid-template-columns:1fr;gap:22px}.hero-aside{align-self:start;padding:15px 0 0;border-top:2px solid var(--atlas-primary);border-left:0}.signal-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.signal-cell:nth-child(2){border-right:0}.signal-cell:nth-child(3),.signal-cell:nth-child(4){border-top:1px solid var(--atlas-border)}.signal-cell:nth-child(3){padding-left:0}.project-grid,.workflow-line{grid-template-columns:1fr}.section-head,.panel-heading{align-items:flex-start;flex-direction:column}.overview-page{gap:27px}}@media(max-width:420px){.overview-hero h1{font-size:37px}.signal-cell{padding-right:12px}.signal-cell:not(:first-child){padding-left:12px}.create-modal{padding:22px 18px}}
</style>
