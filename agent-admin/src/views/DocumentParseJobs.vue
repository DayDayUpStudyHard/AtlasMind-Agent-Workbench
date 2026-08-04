<template>
  <div class="page">
    <div class="page-head">
      <div><h1>文件解析任务</h1><p>合同文档上传后的解析、OCR、分块和索引状态</p></div>
    </div>

    <div v-if="!docs.length" class="blank-state">
      <p>暂无上传的文件。在合同工作台上传合同正文或附件后，解析任务会出现在这里。</p>
      <a href="http://localhost:15174/contracts" target="_blank">打开合同工作台 →</a>
    </div>

    <el-table v-else :data="docs" stripe v-loading="loading">
      <el-table-column prop="caseKey" label="案件编号" width="120" />
      <el-table-column prop="fileName" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column label="类型" width="100">
        <template #default="{row}">{{ docType(row.documentType) }}</template>
      </el-table-column>
      <el-table-column label="解析状态" width="110">
        <template #default="{row}">
          <el-tag :type="parseTag(row.parseStatus)" size="small">{{ parseLabel(row.parseStatus) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="version" label="版本" width="70" />
      <el-table-column prop="pageCount" label="页数" width="70" />
      <el-table-column label="上传时间" width="160">
        <template #default="{row}">{{ (row.createTime||'').replace('T',' ')?.slice(0,16) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{row}">
          <el-button
            v-if="row.parseStatus === 'PENDING' || row.parseStatus === 'PARSING'"
            size="small" type="warning" @click="stopDoc(row)"
          >停止</el-button>
          <el-popconfirm title="确定删除此文件？" @confirm="delDoc(row)">
            <template #reference>
              <el-button size="small" type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api/index.js'

const docs = ref([])
const loading = ref(true)

onMounted(fetchDocs)

async function fetchDocs() {
  loading.value = true
  try {
    const r = await api.get('/api/admin/contracts/documents')
    docs.value = r.data.data || []
  } catch {} finally { loading.value = false }
}

async function stopDoc(row) {
  try {
    await api.put(`/api/admin/contracts/documents/${row.id}/cancel`)
    ElMessage.success('已停止解析')
    fetchDocs()
  } catch { ElMessage.error('操作失败') }
}

async function delDoc(row) {
  try {
    await api.delete(`/api/admin/contracts/documents/${row.id}`)
    ElMessage.success('已删除文件')
    fetchDocs()
  } catch { ElMessage.error('删除失败') }
}

function docType(t) { return { MAIN:'主合同', ATTACHMENT:'附件', PRICING:'报价单', CERTIFICATE:'资质', FULFILLMENT_EVIDENCE:'履约证据' }[t] || t }
function parseTag(s) { return { READY:'success', PARSING:'warning', FAILED:'danger', PENDING:'info' }[s] || '' }
function parseLabel(s) { return { READY:'就绪', PARSING:'解析中', FAILED:'失败', PENDING:'待处理' }[s] || s }
</script>

<style scoped>
.page{padding:0}
.page-head{margin-bottom:20px}
.page-head h1{margin:0;font-size:24px;color:#1f2d3d}
.page-head p{margin:6px 0 0;color:#8b9aaa;font-size:13px}
.blank-state{padding:60px 0;text-align:center;color:#8b9aaa}
.blank-state a{display:inline-block;margin-top:12px;color:#426fa6;font-weight:700}
</style>
