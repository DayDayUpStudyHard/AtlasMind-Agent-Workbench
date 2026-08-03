<template>
  <div class="page">
    <div class="page-head">
      <div><h1>标准条款库</h1><p>管理企业标准合同条款：编辑、语义要素、谈判底线、版本管理</p></div>
      <el-button type="primary" @click="openCreate">+ 新增条款</el-button>
    </div>

    <el-table :data="clauses" stripe v-loading="loading" @row-click="row => selected = row" highlight-current-row>
      <el-table-column prop="clauseType" label="条款类型" width="110" />
      <el-table-column prop="title" label="条款名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="content" label="条款内容" min-width="300" show-overflow-tooltip>
        <template #default="{row}">{{ row.content?.slice(0, 100) }}...</template>
      </el-table-column>
      <el-table-column label="强制" width="60"><template #default="{row}">{{ row.isMandatory ? '是' : '否' }}</template></el-table-column>
      <el-table-column label="版本" width="60"><template #default="{row}">v{{ row.version }}</template></el-table-column>
      <el-table-column label="状态" width="70">
        <template #default="{row}"><el-tag :type="row.isActive?'success':'info'" size="small">{{ row.isActive ? '启用' : '停用' }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{row}">
          <el-button size="small" @click.stop="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click.stop="doDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Selected clause detail -->
    <div v-if="selected" class="clause-detail">
      <h3>{{ selected.title }} <el-tag size="small">{{ selected.clauseType }}</el-tag></h3>
      <p class="clause-body">{{ selected.content }}</p>
      <div class="clause-meta-grid">
        <div><span>语义要素</span><code>{{ selected.semanticElements || '未设置' }}</code></div>
        <div><span>谈判底线</span><p>{{ selected.negotiationBottomLine || '未设置' }}</p></div>
        <div><span>强制条款</span><strong>{{ selected.isMandatory ? '是 - 不可协商' : '否 - 可协商' }}</strong></div>
      </div>
    </div>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑条款' : '新增条款'" width="700px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="条款类型"><el-select v-model="form.clauseType"><el-option v-for="t in types" :key="t" :label="t" :value="t" /></el-select></el-form-item>
        <el-form-item label="条款名称"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="条款内容"><el-input v-model="form.content" type="textarea" rows="6" /></el-form-item>
        <el-form-item label="语义要素"><el-input v-model="form.semanticElements" type="textarea" rows="2" placeholder='{"liabilityCapPct":100,"indirectDamages":"excluded"}' /></el-form-item>
        <el-form-item label="谈判底线"><el-input v-model="form.negotiationBottomLine" type="textarea" rows="2" placeholder="最低接受责任上限为合同金额的50%" /></el-form-item>
        <el-form-item label="强制条款"><el-switch v-model="form.isMandatory" /></el-form-item>
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

const clauses = ref([]); const loading = ref(true); const saving = ref(false); const selected = ref(null)
const dialog = reactive({ visible: false, isEdit: false })
const types = ['LIABILITY','PAYMENT','ACCEPTANCE','CONFIDENTIALITY','TERMINATION','IP','DATA_PROTECTION','OTHER']
const form = reactive({ clauseType:'LIABILITY', title:'', content:'', semanticElements:'', negotiationBottomLine:'', isMandatory:false, isActive:true })

onMounted(loadClauses)
async function loadClauses() { try { clauses.value = (await api.get('/api/admin/contracts/clauses')).data.data } catch {} finally { loading.value = false } }
function openCreate() { Object.assign(form, { clauseType:'LIABILITY', title:'', content:'', semanticElements:'', negotiationBottomLine:'', isMandatory:false, isActive:true }); dialog.isEdit = false; dialog.visible = true }
function openEdit(r) { Object.assign(form, r); dialog.isEdit = true; dialog.visible = true }
async function doSave() {
  saving.value = true
  try {
    if (dialog.isEdit) await api.put(`/api/admin/contracts/clauses/${form.id}`, form)
    else await api.post('/api/admin/contracts/clauses', form)
    ElMessage.success(dialog.isEdit ? '已更新' : '已创建')
    dialog.visible = false; loadClauses()
  } catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}
async function doDelete(id) {
  try { await ElMessageBox.confirm('确定删除？', '确认', { type: 'warning' }) } catch { return }
  await api.delete(`/api/admin/contracts/clauses/${id}`)
  ElMessage.success('已删除'); loadClauses()
}
</script>

<style scoped>
.page{padding:0}
.page-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}
.page-head h1{margin:0;font-size:24px;color:#1f2d3d}
.page-head p{margin:6px 0 0;color:#8b9aaa;font-size:13px}
.clause-detail{margin-top:24px;padding:20px;background:#fbfcfe;border:1px solid #dce4ee;border-radius:4px}
.clause-detail h3{margin:0 0 12px;font-size:18px;color:#1f2d3d;display:flex;align-items:center;gap:8px}
.clause-body{margin:0 0 16px;padding:14px;background:#fff;border:1px solid #dce4ee;border-radius:4px;color:#607184;font-size:13px;line-height:1.7;white-space:pre-wrap}
.clause-meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.clause-meta-grid div{padding:10px;background:#fff;border:1px solid #dce4ee;border-radius:4px}
.clause-meta-grid span{display:block;color:#8b9aaa;font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:4px}
.clause-meta-grid code{color:#426fa6;font-size:12px;word-break:break-all}
.clause-meta-grid p{color:#607184;font-size:12px;line-height:1.5;margin:0}
.clause-meta-grid strong{color:#1f2d3d;font-size:13px}
</style>
