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
            {{ r.runtimeEngine }}
          </el-tag>
          <strong>{{ r.datasetName }} v{{ r.datasetVersion }}</strong>
          <div class="trend-metrics">
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
          <el-table-column prop="contractType" label="类型" width="130" />
          <el-table-column prop="caseCount" label="用例数" width="80" align="center" />
          <el-table-column label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="plain" size="small">
                {{ row.status }}
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
            <el-form-item label="类型">
              <el-select v-model="newDataset.contractType" style="width: 100%">
                <el-option label="服务采购" value="SERVICE_PROCUREMENT" />
                <el-option label="货物采购" value="GOODS_PURCHASE" />
                <el-option label="保密协议" value="NDA" />
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

        <!-- Cases sub-panel -->
        <div v-if="selectedDataset" class="cases-panel">
          <div class="cases-head">
            <h3>{{ selectedDataset.name }} · 用例列表</h3>
            <el-button type="primary" size="small" @click="showAddCase = true">+ 添加用例</el-button>
          </div>
          <el-table :data="cases" stripe v-if="cases.length">
            <el-table-column prop="caseKey" label="Key" width="120" />
            <el-table-column prop="title" label="标题" min-width="180" />
            <el-table-column prop="contractType" label="类型" width="120" />
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
          <el-table-column label="数据集" min-width="160">
            <template #default="{ row }">{{ row.datasetName }} v{{ row.datasetVersion }}</template>
          </el-table-column>
          <el-table-column label="Runtime" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="row.runtimeEngine === 'langgraph' ? 'primary' : 'info'" effect="plain" size="small">
                {{ row.runtimeEngine }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" align="center" />
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
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${r.runtimeEngine} · #${r.id}`" :value="r.id" />
          </el-select>
          <span class="vs">vs</span>
          <el-select v-model="compareId2" placeholder="选择 Run 2" style="width: 200px">
            <el-option v-for="r in runs" :key="r.id" :label="`${r.datasetName} · ${r.runtimeEngine} · #${r.id}`" :value="r.id" />
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
              <td>{{ d.mode1 }}</td>
              <td>{{ d.mode2 }}</td>
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

const newDataset = ref({ name: '', version: 'v1', contractType: 'SERVICE_PROCUREMENT', description: '' })

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
    newDataset.value = { name: '', version: 'v1', contractType: 'SERVICE_PROCUREMENT', description: '' }
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

async function viewCases(ds) {
  selectedDataset.value = ds
  try { cases.value = (await api.get(`/api/admin/eval/datasets/${ds.id}/cases`)).data.data || [] } catch {}
}

async function startRun(ds) {
  try {
    await api.post('/api/admin/eval/runs', { datasetId: ds.id, runtime: 'legacy' })
    ElMessage.success('评测已发起')
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
