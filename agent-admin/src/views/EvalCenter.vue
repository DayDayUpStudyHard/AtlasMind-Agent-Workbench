<template>
  <div class="eval-center">
    <header class="page-head">
      <h2>评测中心</h2>
      <p>管理合同 Agent 评测数据集、运行评测、对比新旧 Runtime 准确率</p>
    </header>

    <!-- Metrics trend -->
    <section class="trend-strip" v-if="trend.length">
      <h3>最近评测趋势</h3>
      <div class="trend-grid">
        <div v-for="r in trend.slice(0, 6)" :key="r.id" class="trend-card">
          <span :class="'trend-badge ' + r.runtimeEngine">{{ r.runtimeEngine }}</span>
          <strong>{{ r.datasetName }} v{{ r.datasetVersion }}</strong>
          <div class="trend-metrics">
            <small>召回 {{ (r.highRiskRecall * 100).toFixed(0) }}%</small>
            <small>引用 {{ (r.dualCitationRate * 100).toFixed(0) }}%</small>
            <small>误报 {{ (r.falsePositiveRate * 100).toFixed(0) }}%</small>
          </div>
        </div>
      </div>
    </section>

    <!-- Tabs: Datasets | Runs | Compare -->
    <nav class="eval-tabs">
      <button :class="{ active: tab === 'datasets' }" @click="tab = 'datasets'">数据集</button>
      <button :class="{ active: tab === 'runs' }" @click="tab = 'runs'">评测记录</button>
      <button :class="{ active: tab === 'compare' }" @click="tab = 'compare'">版本对比</button>
    </nav>

    <!-- Datasets tab -->
    <section v-if="tab === 'datasets'">
      <div class="section-actions">
        <button class="btn-primary" @click="showCreateDataset = true">+ 新建数据集</button>
      </div>
      <table class="data-table" v-if="datasets.length">
        <thead><tr><th>名称</th><th>版本</th><th>类型</th><th>用例数</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="ds in datasets" :key="ds.id">
            <td><strong>{{ ds.name }}</strong></td>
            <td>{{ ds.version }}</td>
            <td>{{ ds.contractType }}</td>
            <td>{{ ds.caseCount }}</td>
            <td><span :class="'status-' + ds.status.toLowerCase()">{{ ds.status }}</span></td>
            <td>
              <button class="btn-sm" @click="viewCases(ds)">用例</button>
              <button class="btn-sm" @click="startRun(ds)">评测</button>
              <button class="btn-sm danger" @click="deleteDataset(ds.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无评测数据集</p>

      <!-- Create dataset modal -->
      <div v-if="showCreateDataset" class="modal-overlay" @click.self="showCreateDataset = false">
        <div class="modal-content">
          <h3>新建评测数据集</h3>
          <input v-model="newDataset.name" placeholder="数据集名称" />
          <input v-model="newDataset.version" placeholder="版本 (如 v1)" />
          <select v-model="newDataset.contractType">
            <option value="SERVICE_PROCUREMENT">服务采购</option>
            <option value="GOODS_PURCHASE">货物采购</option>
            <option value="NDA">保密协议</option>
          </select>
          <textarea v-model="newDataset.description" placeholder="描述" rows="3"></textarea>
          <div class="modal-actions">
            <button class="btn-primary" @click="createDataset">创建</button>
            <button @click="showCreateDataset = false">取消</button>
          </div>
        </div>
      </div>

      <!-- Cases view -->
      <div v-if="selectedDataset" class="cases-panel">
        <h3>{{ selectedDataset.name }} · 用例列表</h3>
        <button class="btn-primary" @click="showAddCase = true">+ 添加用例</button>
        <table class="data-table" v-if="cases.length">
          <thead><tr><th>Key</th><th>标题</th><th>类型</th><th>预期发现</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="c in cases" :key="c.id">
              <td>{{ c.caseKey }}</td>
              <td>{{ c.title }}</td>
              <td>{{ c.contractType }}</td>
              <td>{{ c.expectedFindingCount }}</td>
              <td><button class="btn-sm danger" @click="deleteCase(c.id)">删除</button></td>
            </tr>
          </tbody>
        </table>
        <button class="btn-back" @click="selectedDataset = null; cases = []">← 返回数据集列表</button>
      </div>
    </section>

    <!-- Runs tab -->
    <section v-if="tab === 'runs'">
      <table class="data-table" v-if="runs.length">
        <thead><tr><th>数据集</th><th>Runtime</th><th>状态</th><th>风险召回</th><th>引用率</th><th>误报率</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>{{ r.datasetName }} v{{ r.datasetVersion }}</td>
            <td><span :class="'runtime-' + r.runtimeEngine">{{ r.runtimeEngine }}</span></td>
            <td>{{ r.status }}</td>
            <td>{{ (r.highRiskRecall * 100).toFixed(0) }}%</td>
            <td>{{ (r.dualCitationRate * 100).toFixed(0) }}%</td>
            <td>{{ (r.falsePositiveRate * 100).toFixed(0) }}%</td>
            <td>{{ formatDate(r.startedAt) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty">暂无评测记录</p>
    </section>

    <!-- Compare tab -->
    <section v-if="tab === 'compare'">
      <div class="compare-controls">
        <select v-model="compareId1"><option v-for="r in runs" :key="r.id" :value="r.id">{{ r.datasetName }} · {{ r.runtimeEngine }} · #{{ r.id }}</option></select>
        <span>vs</span>
        <select v-model="compareId2"><option v-for="r in runs" :key="r.id" :value="r.id">{{ r.datasetName }} · {{ r.runtimeEngine }} · #{{ r.id }}</option></select>
        <button class="btn-primary" @click="doCompare">对比</button>
      </div>
      <table class="data-table" v-if="compareDiffs.length">
        <thead><tr><th>用例</th><th>召回1</th><th>召回2</th><th>引用1</th><th>引用2</th><th>模式1</th><th>模式2</th></tr></thead>
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
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
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
  try { datasets.value = (await api.get('/api/admin/eval/datasets')).data.data || [] } catch (e) {}
  try { runs.value = (await api.get('/api/admin/eval/runs')).data.data || [] } catch (e) {}
  try { trend.value = (await api.get('/api/admin/eval/metrics/trend')).data.data || [] } catch (e) {}
}

async function createDataset() {
  await api.post('/api/admin/eval/datasets', newDataset.value)
  showCreateDataset.value = false
  newDataset.value = { name: '', version: 'v1', contractType: 'SERVICE_PROCUREMENT', description: '' }
  loadAll()
}

async function deleteDataset(id) {
  if (!confirm('删除数据集将同时删除所有用例，确定？')) return
  await api.delete(`/api/admin/eval/datasets/${id}`)
  loadAll()
}

async function viewCases(ds) {
  selectedDataset.value = ds
  try { cases.value = (await api.get(`/api/admin/eval/datasets/${ds.id}/cases`)).data.data || [] } catch (e) {}
}

async function startRun(ds) {
  await api.post('/api/admin/eval/runs', { datasetId: ds.id, runtime: 'legacy' })
  loadAll()
}

async function deleteCase(id) {
  await api.delete(`/api/admin/eval/cases/${id}`)
  viewCases(selectedDataset.value)
}

async function doCompare() {
  if (!compareId1.value || !compareId2.value) return
  try {
    const r = await api.get(`/api/admin/eval/runs/compare?runId1=${compareId1.value}&runId2=${compareId2.value}`)
    compareDiffs.value = r.data.data?.diffs || []
  } catch (e) {}
}

function formatDate(v) { return v ? String(v).replace('T', ' ').slice(0, 16) : '' }
</script>

<style scoped>
.eval-center{max-width:1200px;margin:0 auto;padding:24px}
.page-head{margin-bottom:24px}
.page-head h2{font-size:24px;color:#1e293b;margin:0}
.page-head p{color:#64748b;font-size:13px;margin:4px 0 0}

.trend-strip{margin-bottom:24px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px}
.trend-strip h3{font-size:14px;color:#334155;margin:0 0 12px}
.trend-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.trend-card{padding:12px;background:#fff;border:1px solid #e2e8f0;border-radius:6px}
.trend-badge{display:inline-block;padding:2px 6px;border-radius:3px;font-size:9px;font-weight:800}
.trend-badge.legacy{color:#64748b;background:#f1f5f9}
.trend-badge.langgraph{color:#1d4ed8;background:#dbeafe}
.trend-card strong{display:block;margin-top:6px;color:#1e293b;font-size:13px}
.trend-metrics{display:flex;gap:12px;margin-top:8px}
.trend-metrics small{color:#64748b;font-size:11px}

.eval-tabs{display:flex;gap:0;margin-bottom:20px;border-bottom:2px solid #e2e8f0}
.eval-tabs button{padding:10px 20px;border:0;background:none;color:#64748b;font-size:13px;font-weight:700;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px}
.eval-tabs button.active{color:#1d4ed8;border-bottom-color:#1d4ed8}

.section-actions{margin-bottom:12px}
.btn-primary{padding:8px 16px;background:#1d4ed8;color:#fff;border:0;border-radius:4px;font-size:12px;font-weight:700;cursor:pointer}
.btn-sm{padding:4px 10px;background:#f1f5f9;color:#334155;border:1px solid #e2e8f0;border-radius:3px;font-size:11px;cursor:pointer;margin-right:4px}
.btn-sm.danger{color:#dc2626}
.btn-sm.danger:hover{background:#fef2f2}
.btn-back{display:block;margin-top:12px;background:none;border:0;color:#1d4ed8;cursor:pointer;font-size:12px}

.data-table{width:100%;border-collapse:collapse;font-size:12px}
.data-table th{text-align:left;padding:10px 12px;color:#64748b;font-weight:700;border-bottom:2px solid #e2e8f0}
.data-table td{padding:10px 12px;border-bottom:1px solid #f1f5f9;color:#334155}
.data-table tr.has-diff{background:#fffbeb}

.compare-controls{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.compare-controls select{min-height:36px;padding:4px 8px;border:1px solid #e2e8f0;border-radius:4px;font-size:12px;min-width:200px}
.compare-controls span{color:#94a3b8;font-size:14px;font-weight:700}

.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:100}
.modal-content{background:#fff;padding:24px;border-radius:8px;min-width:400px;display:flex;flex-direction:column;gap:12px}
.modal-content input,.modal-content select,.modal-content textarea{padding:8px;border:1px solid #e2e8f0;border-radius:4px;font-size:13px}
.modal-actions{display:flex;gap:8px;justify-content:flex-end}

.cases-panel{margin-top:20px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px}
.cases-panel h3{font-size:15px;margin:0 0 12px}

.status-active{color:#16a34a}.status-draft{color:#94a3b8}
.runtime-legacy{color:#64748b;background:#f1f5f9;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:800}
.runtime-langgraph{color:#1d4ed8;background:#dbeafe;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:800}
.empty{color:#94a3b8;font-size:13px;padding:20px 0}
</style>
