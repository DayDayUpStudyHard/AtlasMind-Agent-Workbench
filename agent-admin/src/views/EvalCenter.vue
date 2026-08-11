<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Evaluation</span>
        <h2>评测中心</h2>
        <p>管理合同 Agent 评测数据集、运行评测、对比新旧 Runtime 准确率</p>
      </div>
    </section>

    <!-- Metrics trend -->
    <section class="trend-strip" v-if="trend.length">
      <h3>最近评测趋势</h3>
      <div class="trend-grid">
        <div v-for="r in trend.slice(0, 6)" :key="r.id" class="trend-card">
          <el-tag :type="r.runtimeEngine === 'langgraph' ? 'primary' : 'info'" size="small" effect="plain">
            {{ r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine) }}
          </el-tag>
          <strong>{{ r.datasetName }} v{{ r.datasetVersion }}</strong>
          <div class="trend-metrics">
            <small>目标 {{ r.datasetTypeLabel || formatDatasetType(r.contractType) }}</small>
            <small>召回 {{ (r.highRiskRecall * 100).toFixed(0) }}%</small>
            <small>引用 {{ (r.dualCitationRate * 100).toFixed(0) }}%</small>
            <small>误报 {{ (r.falsePositiveRate * 100).toFixed(0) }}%</small>
          </div>
        </div>
      </div>
    </section>

    <el-tabs v-model="tab">
      <!-- ═══ Datasets Tab ═══ -->
      <el-tab-pane label="数据集" name="datasets">
        <div class="section-actions">
          <el-button type="primary" @click="showCreateDataset = true">+ 新建数据集</el-button>
        </div>

        <el-table :data="datasets" stripe v-if="datasets.length">
          <el-table-column prop="name" label="名称" min-width="150">
            <template #default="{ row }"><strong>{{ row.name }}</strong></template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="80" />
          <el-table-column prop="contractTypeLabel" label="评测目标" width="140">
            <template #default="{ row }">
              {{ row.contractTypeLabel || formatDatasetType(row.contractType) }}
            </template>
          </el-table-column>
          <el-table-column prop="caseCount" label="用例数" width="80" align="center" />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="plain" size="small">
                {{ row.statusLabel || formatStatus(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button size="small" @click="viewCases(row)">用例</el-button>
              <el-button size="small" @click="startRun(row)">评测</el-button>
              <el-button size="small" type="danger" @click="deleteDataset(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无评测数据集" :image-size="64" />

        <!-- Create dataset dialog -->
        <el-dialog v-model="showCreateDataset" title="新建评测数据集" width="460px">
          <el-form :model="newDataset" label-width="80px">
            <el-form-item label="名称">
              <el-input v-model="newDataset.name" placeholder="数据集名称" />
            </el-form-item>
            <el-form-item label="版本">
              <el-input v-model="newDataset.version" placeholder="如 v1" />
            </el-form-item>
            <el-form-item label="评测目标">
              <el-select v-model="newDataset.contractType" style="width: 100%">
                <el-option label="风险审查" value="CONTRACT_REVIEW" />
                <el-option label="合同要素提取" value="INTAKE" />
                <el-option label="履约日程提取" value="FULFILLMENT_TIMELINE" />
                <el-option label="履约核验" value="FULFILLMENT_CHECK" />
                <el-option label="综合评测" value="COMPREHENSIVE" />
              </el-select>
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="newDataset.description" type="textarea" rows="3" placeholder="描述" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showCreateDataset = false">取消</el-button>
            <el-button type="primary" @click="createDataset">创建</el-button>
          </template>
        </el-dialog>

        <!-- Add case dialog -->
        <el-dialog v-model="showAddCase" title="添加评测用例" width="680px">
          <el-form :model="newCase" label-width="100px">
            <el-form-item label="用例Key">
              <el-input v-model="newCase.caseKey" placeholder="唯一标识，如 CASE-001" />
            </el-form-item>
            <el-form-item label="标题">
              <el-input v-model="newCase.title" placeholder="用例标题" />
            </el-form-item>
            <div style="color:#909399;line-height:1.6;margin-bottom:8px">
              用例会自动继承评测目标，不再强制选择合同类型。若需要做样本背景区分，后续再补高级标签。
            </div>
            <el-form-item label="合同全文">
              <el-input v-model="newCase.contractText" type="textarea" rows="10" placeholder="粘贴完整合同文本" />
            </el-form-item>
            <el-form-item label="预期发现">
              <el-input v-model="newCase.expectedFindingsJson" type="textarea" rows="5"
                        placeholder='[{"title":"...","severity":"HIGH","clauseType":"PAYMENT"}]' />
              <small style="color:#909399;display:block;margin-top:4px">JSON 数组，每项必须含 title、severity（HIGH/MEDIUM/LOW）、clauseType</small>
            </el-form-item>
            <el-form-item label="不应发现">
              <el-input v-model="newCase.shouldNotFindJson" type="textarea" rows="3"
                        placeholder='["不应被误报的风险点"]' />
              <small style="color:#909399;display:block;margin-top:4px">JSON 数组，列举不应被 Agent 识别为风险的内容</small>
            </el-form-item>
            <el-form-item label="预期引用数">
              <el-input-number v-model="newCase.expectedCitationCount" :min="0" />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showAddCase = false">取消</el-button>
            <el-button type="primary" @click="addCase">添加</el-button>
          </template>
        </el-dialog>

        <!-- Start run dialog -->
        <el-dialog v-model="showStartRun" title="发起评测" width="520px">
          <el-form label-width="90px">
            <el-form-item label="数据集">
              <strong>{{ startRunDs?.name }} v{{ startRunDs?.version }}</strong>
            </el-form-item>
            <el-form-item label="Runtime">
              <el-select v-model="startRunRuntime" style="width: 100%">
                <el-option label="Legacy (六阶段流水线)" value="legacy" />
                <el-option label="LangGraph (状态图)" value="langgraph" />
              </el-select>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">模型与提示词</el-divider>
            <el-form-item label="模型">
              <el-select v-model="startRunFeatures.model" style="width: 100%" clearable placeholder="使用全局默认">
                <el-option label="DeepSeek V3" value="deepseek-chat" />
                <el-option label="DeepSeek R1" value="deepseek-reasoner" />
                <el-option label="Claude Sonnet 5" value="claude-sonnet-5" />
                <el-option label="Claude Opus 5" value="claude-opus-5" />
                <el-option label="Qwen Max" value="qwen-max" />
              </el-select>
            </el-form-item>
            <el-form-item label="提示词版本">
              <el-select v-model="startRunFeatures.promptVersion" style="width: 100%" clearable placeholder="使用默认版本">
                <el-option label="contract-review-graph-v1 (当前)" value="contract-review-graph-v1" />
                <el-option label="contract-review-graph-v2" value="contract-review-graph-v2" />
              </el-select>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">功能组件</el-divider>
            <el-form-item label="Rerank">
              <el-switch v-model="startRunFeatures.rerank" active-text="LLM 重排序" inactive-text="关键词加分" />
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">
              检索参数
              <el-button size="small" text @click="showRetrievalOpts = !showRetrievalOpts" style="margin-left:8px">
                {{ showRetrievalOpts ? '收起' : '展开' }}
              </el-button>
            </el-divider>
            <template v-if="showRetrievalOpts">
              <el-form-item label="召回乘数">
                <el-input-number v-model="startRunFeatures.recallMultiplier" :min="2" :max="15" size="small" />
                <small style="color:#909399;margin-left:8px">top_k × 乘数 = 粗排候选数，默认 6</small>
              </el-form-item>
              <el-form-item label="召回下限">
                <el-input-number v-model="startRunFeatures.recallMin" :min="10" :max="100" size="small" />
                <small style="color:#909399;margin-left:8px">最少召回候选数，默认 30</small>
              </el-form-item>
              <el-form-item label="召回上限">
                <el-input-number v-model="startRunFeatures.recallMax" :min="20" :max="200" size="small" />
                <small style="color:#909399;margin-left:8px">最多召回候选数，默认 50</small>
              </el-form-item>
            </template>
            <el-divider content-position="left" style="margin:12px 0">P1 反思与控制</el-divider>
            <el-form-item label="定向检索重试">
              <el-select v-model="startRunFeatures.targetedRetrievalRetries" style="width: 120px">
                <el-option label="0 (跳过)" :value="0" />
                <el-option label="1 (默认)" :value="1" />
                <el-option label="2" :value="2" />
              </el-select>
              <small style="color:#909399;margin-left:8px">覆盖缺口后二次检索次数</small>
            </el-form-item>
            <el-form-item label="覆盖反思">
              <el-switch v-model="startRunFeatures.coverageReflection" active-text="启用" inactive-text="跳过" />
              <small style="color:#909399;margin-left:8px">关闭后直接 CONFIRMED，跳过反思阶段</small>
            </el-form-item>
            <el-divider content-position="left" style="margin:12px 0">P2 生成参数</el-divider>
            <el-form-item label="温度">
              <el-input-number v-model="startRunFeatures.temperature" :min="0" :max="2" :step="0.1" :precision="1" size="small" />
              <small style="color:#909399;margin-left:8px">LLM 采样温度，0 = 使用提示词默认值</small>
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="showStartRun = false">取消</el-button>
            <el-button type="primary" @click="doStartRun">开始评测</el-button>
          </template>
        </el-dialog>

        <!-- Cases sub-panel -->
        <div v-if="selectedDataset" class="cases-panel">
          <div class="cases-head">
            <h3>{{ selectedDataset.name }} · 用例列表</h3>
            <el-button type="primary" size="small" @click="showAddCase = true">+ 添加用例</el-button>
          </div>
          <el-table :data="cases" stripe v-if="cases.length">
            <el-table-column prop="caseKey" label="Key" width="120" />
            <el-table-column prop="title" label="标题" min-width="180" />
            <el-table-column prop="expectedFindingCount" label="预期发现" width="90" align="center" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" type="danger" @click="deleteCase(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无用例" :image-size="48" />
          <el-button class="back-btn" @click="selectedDataset = null; cases = []">← 返回数据集列表</el-button>
        </div>
      </el-tab-pane>

      <!-- ═══ Runs Tab ═══ -->
      <el-tab-pane label="评测记录" name="runs">
        <el-table :data="runs" stripe v-if="runs.length">
          <el-table-column label="数据集" min-width="180">
            <template #default="{ row }">
              <div style="display:flex;flex-direction:column;gap:4px">
                <strong>{{ row.datasetName }} v{{ row.datasetVersion }}</strong>
                <small style="color:#909399">{{ row.datasetTypeLabel || formatDatasetType(row.contractType) }}</small>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="Runtime" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="row.runtimeEngine === 'langgraph' ? 'primary' : 'info'" effect="plain" size="small">
                {{ row.runtimeEngineLabel || formatRuntimeEngine(row.runtimeEngine) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="功能组件" width="200" align="center">
            <template #default="{ row }">
              <div style="display:flex;flex-wrap:wrap;gap:3px;justify-content:center">
                <el-tag v-if="parseFeatures(row.featuresJson).model" type="warning" effect="plain" size="small">{{ parseFeatures(row.featuresJson).model }}</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).promptVersion" type="" effect="plain" size="small">{{ parseFeatures(row.featuresJson).promptVersion }}</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).rerank !== false" type="success" effect="plain" size="small">重排序</el-tag>
                <el-tag v-else type="info" effect="plain" size="small">无重排序</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).targetedRetrievalRetries > 0" type="primary" effect="plain" size="small">定向检索×{{ parseFeatures(row.featuresJson).targetedRetrievalRetries }}</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).coverageReflection === false" type="danger" effect="plain" size="small">无覆盖反思</el-tag>
                <el-tag v-if="parseFeatures(row.featuresJson).temperature > 0" type="warning" effect="plain" size="small">T={{ parseFeatures(row.featuresJson).temperature }}</el-tag>
                <el-tag v-if="!parseFeatures(row.featuresJson).model && !parseFeatures(row.featuresJson).promptVersion && parseFeatures(row.featuresJson).rerank !== false && !(parseFeatures(row.featuresJson).targetedRetrievalRetries > 0) && parseFeatures(row.featuresJson).coverageReflection !== false && !(parseFeatures(row.featuresJson).temperature > 0)" type="info" effect="plain" size="small">默认配置</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="statusLabel" label="状态" width="90" align="center">
            <template #default="{ row }">{{ row.statusLabel || formatStatus(row.status) }}</template>
          </el-table-column>
          <el-table-column label="风险召回" width="100" align="center">
            <template #default="{ row }">{{ (row.highRiskRecall * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column label="引用率" width="90" align="center">
            <template #default="{ row }">{{ (row.dualCitationRate * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column label="误报率" width="90" align="center">
            <template #default="{ row }">{{ (row.falsePositiveRate * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column label="时间" width="140">
            <template #default="{ row }">{{ formatDate(row.startedAt) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无评测记录" :image-size="64" />
      </el-tab-pane>

      <!-- ═══ Compare Tab ═══ -->
      <el-tab-pane label="版本对比" name="compare">
        <div class="compare-controls">
          <el-select v-model="compareId1" placeholder="选择 Run 1" style="width: 200px">
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${(r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine))} · #${r.id}`" :value="r.id" />
          </el-select>
          <span class="vs">vs</span>
          <el-select v-model="compareId2" placeholder="选择 Run 2" style="width: 200px">
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${(r.runtimeEngineLabel || formatRuntimeEngine(r.runtimeEngine))} · #${r.id}`" :value="r.id" />
          </el-select>
          <el-button type="primary" @click="doCompare">对比</el-button>
        </div>

        <table v-if="compareDiffs.length" class="compare-table">
          <thead>
            <tr>
              <th>用例</th>
              <th>召回1</th>
              <th>召回2</th>
              <th>引用1</th>
              <th>引用2</th>
              <th>模式1</th>
              <th>模式2</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in compareDiffs" :key="d.caseId" :class="{ 'has-diff': d.recall1 !== d.recall2 || d.mode1 !== d.mode2 }">
              <td>{{ d.caseTitle }}</td>
              <td>{{ (d.recall1 * 100).toFixed(0) }}%</td>
              <td>{{ (d.recall2 * 100).toFixed(0) }}%</td>
              <td>{{ (d.dualCite1 * 100).toFixed(0) }}%</td>
              <td>{{ (d.dualCite2 * 100).toFixed(0) }}%</td>
              <td>{{ d.mode1Label || formatAnalysisMode(d.mode1) }}</td>
              <td>{{ d.mode2Label || formatAnalysisMode(d.mode2) }}</td>
            </tr>
          </tbody>
        </table>
        <el-empty v-else description="选择两个 Run 进行对比" :image-size="64" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index.js'

const tab = ref('datasets')
const datasets = ref([])
const runs = ref([])
const trend = ref([])
const cases = ref([])
const selectedDataset = ref(null)
const showCreateDataset = ref(false)
const showAddCase = ref(false)
const compareId1 = ref(null)
const compareId2 = ref(null)
const compareDiffs = ref([])

const newDataset = ref({ name: '', version: 'v1', contractType: 'CONTRACT_REVIEW', description: '' })
const newCase = ref({ caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0 })
const showStartRun = ref(false)
const startRunDs = ref(null)
const startRunRuntime = ref('legacy')
const startRunFeatures = ref({ rerank: true, model: '', promptVersion: '', recallMultiplier: 0, recallMin: 0, recallMax: 0, targetedRetrievalRetries: 1, coverageReflection: true, temperature: 0 })
const showRetrievalOpts = ref(false)

onMounted(() => { loadAll() })

async function loadAll() {
  try { datasets.value = (await api.get('/api/admin/eval/datasets')).data.data || [] } catch {}
  try { runs.value = (await api.get('/api/admin/eval/runs')).data.data || [] } catch {}
  try { trend.value = (await api.get('/api/admin/eval/metrics/trend')).data.data || [] } catch {}
}

async function createDataset() {
  try {
    await api.post('/api/admin/eval/datasets', newDataset.value)
    ElMessage.success('数据集已创建')
    showCreateDataset.value = false
    newDataset.value = { name: '', version: 'v1', contractType: 'CONTRACT_REVIEW', description: '' }
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '创建失败')
  }
}

async function deleteDataset(id) {
  try {
    await ElMessageBox.confirm('删除数据集将同时删除所有用例，确定？', '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/api/admin/eval/datasets/${id}`)
    ElMessage.success('数据集已删除')
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

async function addCase() {
  if (!newCase.value.caseKey || !newCase.value.title || !newCase.value.contractText) {
    ElMessage.warning('用例Key、标题和合同全文为必填')
    return
  }
  try {
    await api.post(`/api/admin/eval/datasets/${selectedDataset.value.id}/cases`, {
      caseKey: newCase.value.caseKey,
      title: newCase.value.title,
      contractText: newCase.value.contractText,
      expectedFindingsJson: newCase.value.expectedFindingsJson,
      shouldNotFindJson: newCase.value.shouldNotFindJson,
      expectedCitationCount: newCase.value.expectedCitationCount,
    })
    ElMessage.success('用例已添加')
    showAddCase.value = false
    newCase.value = { caseKey: '', title: '', contractText: '', expectedFindingsJson: '[]', shouldNotFindJson: '[]', expectedCitationCount: 0 }
    viewCases(selectedDataset.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '添加失败')
  }
}

async function viewCases(ds) {
  selectedDataset.value = ds
  try { cases.value = (await api.get(`/api/admin/eval/datasets/${ds.id}/cases`)).data.data || [] } catch {}
}

async function startRun(ds) {
  startRunDs.value = ds
  startRunRuntime.value = 'legacy'
  startRunFeatures.value = { rerank: true, model: '', promptVersion: '', recallMultiplier: 0, recallMin: 0, recallMax: 0, targetedRetrievalRetries: 1, coverageReflection: true, temperature: 0 }
  showRetrievalOpts.value = false
  showStartRun.value = true
}

async function doStartRun() {
  try {
    await api.post('/api/admin/eval/runs', {
      datasetId: startRunDs.value.id,
      runtime: startRunRuntime.value,
      features: JSON.stringify(startRunFeatures.value),
    })
    ElMessage.success('评测已发起')
    showStartRun.value = false
    loadAll()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '发起失败')
  }
}

async function deleteCase(id) {
  try {
    await ElMessageBox.confirm('确定删除此用例？', '确认', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/api/admin/eval/cases/${id}`)
    ElMessage.success('用例已删除')
    viewCases(selectedDataset.value)
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

async function doCompare() {
  if (!compareId1.value || !compareId2.value) return
  try {
    const r = await api.get(`/api/admin/eval/runs/compare?runId1=${compareId1.value}&runId2=${compareId2.value}`)
    compareDiffs.value = r.data.data?.diffs || []
  } catch {
    ElMessage.error('对比请求失败')
  }
}

function formatDate(v) { return v ? String(v).replace('T', ' ').slice(0, 16) : '' }
function parseFeatures(v) { try { return JSON.parse(v) || {} } catch { return {} } }
function formatDatasetType(v) {
  return {
    CONTRACT_REVIEW: '风险审查',
    RISK_REVIEW: '风险审查',
    INTAKE: '合同要素提取',
    ELEMENT_EXTRACTION: '合同要素提取',
    FULFILLMENT_TIMELINE: '履约日程提取',
    TIMELINE_EXTRACTION: '履约日程提取',
    FULFILLMENT_CHECK: '履约核验',
    FULFILLMENT_VERIFICATION: '履约核验',
    COMPREHENSIVE: '综合评测',
  }[v] || v || '-'
}
function formatRuntimeEngine(v) {
  return {
    legacy: '传统流水线',
    langgraph: 'LangGraph',
  }[v] || v || '-'
}
function formatStatus(v) {
  return {
    ACTIVE: '启用',
    DRAFT: '草稿',
    RUNNING: '运行中',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[v] || v || '-'
}
function formatAnalysisMode(v) {
  return {
    FULL: '完整分析',
    LIMITED: '范围受限',
    RULE_ONLY: '规则兜底',
  }[v] || v || '-'
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }

/* Trend strip */
.trend-strip { padding: 18px; background: #f8fafc; border: 1px solid #dce4ee; border-radius: 4px; }
.trend-strip h3 { font-size: 14px; color: #1f2d3d; margin: 0 0 14px; }
.trend-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.trend-card { padding: 14px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.trend-card strong { display: block; margin-top: 8px; color: #1f2d3d; font-size: 14px; }
.trend-metrics { display: flex; gap: 14px; margin-top: 10px; }
.trend-metrics small { color: #607184; font-size: 12px; }

/* Section actions */
.section-actions { margin-bottom: 14px; }

/* Cases panel */
.cases-panel { margin-top: 24px; padding: 18px; background: #fbfcfe; border: 1px solid #dce4ee; border-radius: 4px; }
.cases-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.cases-head h3 { margin: 0; color: #1f2d3d; font-size: 15px; }
.back-btn { margin-top: 14px; }

/* Compare */
.compare-controls { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.compare-controls .vs { color: #909399; font-size: 15px; font-weight: 700; }

.compare-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.compare-table th { text-align: left; padding: 10px 12px; background: #f3f6fa; color: #607184; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; border-bottom: 2px solid #dce4ee; }
.compare-table td { padding: 10px 12px; border-bottom: 1px solid #eef1f5; color: #1f2d3d; }
.compare-table tr.has-diff { background: #fffbeb; }

@media (max-width: 860px) {
  .trend-grid { grid-template-columns: 1fr; }
}
</style>
