<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Connectors</span>
        <h2>连接器配置</h2>
        <p>统一管理企业数据源入口。当前 GitHub 具备只读证据同步能力，其他连接器先保留配置位。</p>
      </div>
    </section>

    <section class="connector-grid">
      <article v-for="connector in connectors" :key="connector.name" class="connector-card">
        <div>
          <span class="connector-kind">{{ connector.kind }}</span>
          <h3>{{ connector.name }}</h3>
          <p>{{ connector.description }}</p>
        </div>
        <el-tag :type="connector.ready ? 'success' : 'info'" effect="plain">
          {{ connector.ready ? '已接入' : '预留接口' }}
        </el-tag>
      </article>
    </section>
  </div>
</template>

<script setup>
const connectors = [
  { name: 'GitHub Repository', kind: 'Code', ready: true, description: '读取 README、文件树、Issue、PR、Commit，用作项目健康分析证据。' },
  { name: 'Local Project Scanner', kind: 'Code', ready: false, description: '预留本地目录读取、依赖识别、技术文档抽取和项目结构分析接口。' },
  { name: 'Jira / 禅道', kind: 'Delivery', ready: false, description: '预留需求、缺陷、迭代、负责人、状态流转和延期风险同步接口。' },
  { name: 'CI/CD', kind: 'Quality', ready: false, description: '预留构建结果、测试通过率、发布记录和失败日志同步接口。' }
]
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head, .connector-card { background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.page-head { padding: 22px; }
.eyebrow, .connector-kind { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p, .connector-card p { margin: 0; color: #607184; line-height: 1.7; }
.connector-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.connector-card { display: flex; justify-content: space-between; gap: 18px; min-width: 0; padding: 18px; }
.connector-card h3 { margin: 8px 0; color: #1f2d3d; font-size: 18px; }
@media (max-width: 780px) { .connector-grid { grid-template-columns: 1fr; } .connector-card { align-items: flex-start; flex-direction: column; } }
</style>
