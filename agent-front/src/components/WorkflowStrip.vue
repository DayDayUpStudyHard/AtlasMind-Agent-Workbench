<template>
  <div class="workflow-strip" role="list" aria-label="合同工作流阶段">
    <div
      v-for="(stage, index) in stages"
      :key="stage.key"
      class="workflow-stage"
      :class="[stage.state.toLowerCase(), { current: stage.key === currentKey }]"
      role="listitem"
      :title="stageTitle(stage)"
    >
      <span class="workflow-stage-index">
        <template v-if="stage.state === 'DONE'">✓</template>
        <template v-else>{{ index + 1 }}</template>
      </span>
      <div class="workflow-stage-body">
        <strong>{{ stage.label }}</strong>
        <small>{{ stateLabel(stage.state) }}</small>
        <em v-if="stage.ownerRole">{{ stage.ownerRole }}</em>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  stages: { type: Array, default: () => [] },
  currentKey: { type: String, default: '' },
})

function stateLabel(state) {
  return {
    DONE: '已完成',
    ACTIVE: '进行中',
    WAITING_HUMAN: '待人处理',
    BLOCKED: '已卡住',
    PENDING: '未开始',
  }[state] || ''
}

function stageTitle(stage) {
  return [`${stage.label}：${stateLabel(stage.state)}`, stage.ownerRole ? `责任人：${stage.ownerRole}` : '']
    .filter(Boolean).join(' · ')
}
</script>

<style scoped>
.workflow-strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}
.workflow-stage {
  display: flex;
  flex: 1 0 92px;
  min-width: 92px;
  align-items: flex-start;
  gap: 7px;
  padding: 9px 10px;
  background: var(--atlas-bg, #f7f8fa);
  border: 1px solid var(--atlas-border, #e3e6ea);
  border-radius: 3px;
}
.workflow-stage.current { box-shadow: inset 0 -2px 0 var(--atlas-primary, #2f6feb); }
.workflow-stage.done { border-color: #b9d8c5; background: #f4faf6; }
.workflow-stage.active { border-color: #b7cde0; background: #f5f9fc; }
.workflow-stage.waiting_human { border-color: #e8cfa4; background: #fffaf0; }
.workflow-stage.blocked { border-color: #e4b2ad; background: #fff7f6; }
.workflow-stage.pending { opacity: .72; }

.workflow-stage-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  border-radius: 2px;
  background: var(--atlas-border, #e3e6ea);
  color: var(--atlas-muted, #5b6470);
  font-size: 10px;
  font-weight: 800;
}
.workflow-stage.done .workflow-stage-index { color: #fff; background: #347254; }
.workflow-stage.active .workflow-stage-index { color: #fff; background: var(--atlas-primary, #2f6feb); }
.workflow-stage.waiting_human .workflow-stage-index { color: #fff; background: #b7791f; }
.workflow-stage.blocked .workflow-stage-index { color: #fff; background: #b35c56; }

.workflow-stage-body { min-width: 0; }
.workflow-stage-body strong { display: block; color: var(--atlas-text, #1f2530); font-size: 11px; line-height: 1.35; }
.workflow-stage-body small { display: block; margin-top: 2px; color: var(--atlas-subtle, #7a848f); font-size: 10px; line-height: 1.35; }
.workflow-stage-body em { display: block; margin-top: 2px; color: var(--atlas-muted, #5b6470); font-size: 9px; font-style: normal; }

@media (max-width: 1280px) {
  .workflow-stage { flex: 0 0 104px; }
}
</style>
