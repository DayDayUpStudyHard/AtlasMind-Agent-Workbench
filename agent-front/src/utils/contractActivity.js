const TERMINAL_PIPELINE_STATUSES = new Set(['READY', 'COMPLETED', 'FAILED', 'CANCELLED'])
// LIMITED is a terminal status too — the run delivered a scoped report, it
// is not still executing.
const TERMINAL_RUN_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'LIMITED'])

function numericProgress(value) {
  const progress = Number(value)
  if (!Number.isFinite(progress)) return 0
  return Math.max(0, Math.min(100, progress))
}

function timestampOf(item) {
  const value = item?.updateTime || item?.createTime || item?.finishedAt || item?.startedAt
  const timestamp = value ? Date.parse(value) : NaN
  return Number.isFinite(timestamp) ? timestamp : 0
}

function isPipelineActive(pipeline) {
  return !TERMINAL_PIPELINE_STATUSES.has(String(pipeline?.status || '').toUpperCase())
}

function isRunActive(run) {
  return !TERMINAL_RUN_STATUSES.has(String(run?.status || '').toUpperCase())
}

function isContractRun(run) {
  return String(run?.subjectType || '').toUpperCase() === 'CONTRACT_CASE'
}

function keepLatest(map, key, value) {
  const previous = map.get(key)
  if (!previous || timestampOf(value) >= timestampOf(previous)) {
    map.set(key, value)
  }
}

function statusFor(pipeline, run) {
  if (pipeline && isPipelineActive(pipeline)) return 'PROCESSING'
  if (run && isRunActive(run)) return String(run.status || 'RUNNING').toUpperCase()
  if (pipeline && ['FAILED', 'CANCELLED'].includes(String(pipeline.status || '').toUpperCase())) return 'FAILED'
  if (run && ['FAILED', 'CANCELLED'].includes(String(run.status || '').toUpperCase())) return 'FAILED'
  if (run && String(run.status || '').toUpperCase() === 'LIMITED') return 'LIMITED'
  return 'COMPLETED'
}

/**
 * Combine two backend feeds into one business-level contract activity.
 *
 * A file pipeline and the Agent run it enables belong to the same contract
 * workflow. The UI can therefore show both stages without rendering them as
 * two independent notifications.
 */
export function mergeContractActivities(pipelines = [], runs = [], limit = 8) {
  const pipelineByKey = new Map()
  const runByKey = new Map()

  for (const pipeline of Array.isArray(pipelines) ? pipelines : []) {
    const caseId = pipeline?.caseId
    const key = caseId != null ? `case:${caseId}` : `document:${pipeline?.documentId || pipeline?.jobId}`
    keepLatest(pipelineByKey, key, pipeline)
  }

  for (const run of Array.isArray(runs) ? runs : []) {
    const key = isContractRun(run) && run?.subjectId != null
      ? `case:${run.subjectId}`
      : `run:${run?.id}`
    keepLatest(runByKey, key, run)
  }

  const keys = new Set([...pipelineByKey.keys(), ...runByKey.keys()])
  const activities = Array.from(keys, key => {
    const pipeline = pipelineByKey.get(key) || null
    const run = runByKey.get(key) || null
    const caseId = pipeline?.caseId ?? (isContractRun(run) ? run?.subjectId : null)
    const caseTitle = pipeline?.caseTitle
      || run?.projectName
      || (caseId != null ? `合同 #${caseId}` : `Agent 任务 #${run?.id || pipeline?.jobId || ''}`)

    return {
      id: key,
      kind: caseId != null ? 'CONTRACT_WORKFLOW' : 'AGENT_TASK',
      caseId,
      caseTitle,
      fileName: pipeline?.fileName || '',
      status: statusFor(pipeline, run),
      updatedAt: Math.max(timestampOf(pipeline), timestampOf(run)),
      pipeline,
      run,
    }
  })

  return activities
    .sort((left, right) => right.updatedAt - left.updatedAt)
    .slice(0, limit)
}

export function isActivityActive(activity) {
  return ['PROCESSING', 'CREATED', 'CONTEXT_BUILDING', 'PLANNING', 'ANALYZING', 'VERIFYING', 'WAITING_HUMAN', 'WAITING_APPROVAL']
    .includes(String(activity?.status || '').toUpperCase())
}

export function activityProgress(activity) {
  if (activity?.pipeline && isPipelineActive(activity.pipeline)) {
    return numericProgress(activity.pipeline.progress)
  }
  return numericProgress(activity?.run?.progress)
}
