<template>
  <div class="page">
    <div class="page-head">
      <div><h1>审查规则管理</h1><p>管理合同审查的确定性规则：新增、编辑、启用/停用、配置检查逻辑</p></div>
      <el-button type="primary" @click="openCreate">+ 新增规则</el-button>
    </div>

    <el-table :data="rules" stripe v-loading="loading">
      <el-table-column prop="ruleKey" label="规则编号" width="180" />
      <el-table-column prop="title" label="规则名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="clauseType" label="条款类型" width="100" />
      <el-table-column label="检查方式" width="100">
        <template #default="{row}">{{ checkLabel(row.checkType) }}</template>
      </el-table-column>
      <el-table-column label="严重度" width="80">
        <template #default="{row}"><el-tag :type="row.severity==='HIGH'?'danger':row.severity==='MEDIUM'?'warning':'info'" size="small">{{ row.severity }}</el-tag></template>
      </el-table-column>
      <el-table-column label="分值" width="60"><template #default="{row}">{{ row.weight }}</template></el-table-column>
      <el-table-column label="一票否决" width="80"><template #default="{row}">{{ row.isVeto ? '是' : '否' }}</template></el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{row}"><el-tag :type="row.isActive?'success':'info'" size="small">{{ row.isActive ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{row}">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="doDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create/Edit Dialog -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑规则' : '新增规则'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="规则编号"><el-input v-model="form.ruleKey" placeholder="PROC-PAY-001" /></el-form-item>
        <el-form-item label="规则集"><el-input v-model="form.ruleSet" placeholder="SERVICE_PROCUREMENT_V1" /></el-form-item>
        <el-form-item label="条款类型"><el-select v-model="form.clauseType"><el-option v-for="t in clauseTypes" :key="t" :label="t" :value="t" /></el-select></el-form-item>
        <el-form-item label="规则名称"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" rows="2" /></el-form-item>
        <el-form-item label="检查方式"><el-select v-model="form.checkType"><el-option label="缺失检查 MISSING" value="MISSING" /><el-option label="关键词 CONTAINS" value="CONTAINS" /><el-option label="阈值 THRESHOLD" value="THRESHOLD" /><el-option label="语义 SEMANTIC" value="SEMANTIC" /></el-select></el-form-item>
        <el-form-item label="检查配置"><el-input v-model="form.checkConfig" type="textarea" rows="2" placeholder='{"keywords":["验收","交付"]} 或 {"field":"advancePaymentPct","operator":"lte","value":30}' /></el-form-item>
        <el-form-item label="严重度"><el-select v-model="form.severity"><el-option label="高 HIGH" value="HIGH" /><el-option label="中 MEDIUM" value="MEDIUM" /><el-option label="低 LOW" value="LOW" /></el-select></el-form-item>
        <el-form-item label="扣分权重"><el-input-number v-model="form.weight" :min="1" :max="50" /></el-form-item>
        <el-form-item label="一票否决"><el-switch v-model="form.isVeto" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.isActive" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="doSave" :loading="saving">{{ dialog.isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index.js'

const rules = ref([]); const loading = ref(true); const saving = ref(false)
const dialog = reactive({ visible: false, isEdit: false })
const clauseTypes = ['LIABILITY','PAYMENT','ACCEPTANCE','CONFIDENTIALITY','TERMINATION','IP','DATA_PROTECTION','OTHER']
const form = reactive({ ruleKey:'', ruleSet:'SERVICE_PROCUREMENT_V1', clauseType:'PAYMENT', title:'', description:'', checkType:'MISSING', checkConfig:'', severity:'MEDIUM', weight:10, isVeto:false, isActive:true })

onMounted(loadRules)
async function loadRules() { try { rules.value = (await api.get('/api/admin/contracts/rules')).data.data } catch {} finally { loading.value = false } }

function openCreate() { Object.assign(form, { ruleKey:'', ruleSet:'SERVICE_PROCUREMENT_V1', clauseType:'PAYMENT', title:'', description:'', checkType:'MISSING', checkConfig:'', severity:'MEDIUM', weight:10, isVeto:false, isActive:true }); dialog.isEdit = false; dialog.visible = true }
function openEdit(r) { Object.assign(form, r); form.isVeto = !!r.isVeto; form.isActive = !!r.isActive; dialog.isEdit = true; dialog.visible = true }

async function doSave() {
  saving.value = true
  try {
    if (dialog.isEdit) await api.put(`/api/admin/contracts/rules/${form.id}`, form)
    else await api.post('/api/admin/contracts/rules', form)
    ElMessage.success(dialog.isEdit ? '已更新' : '已创建')
    dialog.visible = false; loadRules()
  } catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

async function doDelete(id) {
  try { await ElMessageBox.confirm('确定删除此规则？', '确认', { type: 'warning' }) } catch { return }
  await api.delete(`/api/admin/contracts/rules/${id}`)
  ElMessage.success('已删除'); loadRules()
}

function checkLabel(t) { return { MISSING:'缺失检查', CONTAINS:'关键词', THRESHOLD:'阈值', SEMANTIC:'语义', PATTERN:'模式' }[t] || t }
</script>

<style scoped>
.page{padding:0}
.page-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}
.page-head h1{margin:0;font-size:24px;color:#1f2d3d}
.page-head p{margin:6px 0 0;color:#8b9aaa;font-size:13px}
</style>
