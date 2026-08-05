import test from 'node:test'
import assert from 'node:assert/strict'

import { mergeContractActivities } from '../src/utils/contractActivity.js'

test('merges document processing and Agent run into one contract activity', () => {
  const activities = mergeContractActivities(
    [
      {
        jobId: 17,
        caseId: 41,
        caseTitle: '信息化运维技术服务采购合同',
        fileName: 'contract.pdf',
        status: 'PROCESSING',
        stage: 'CLAUSE_SPLITTING',
        progress: 58,
        updateTime: '2026-08-05T10:02:00',
      },
    ],
    [
      {
        id: 12,
        subjectType: 'CONTRACT_CASE',
        subjectId: 41,
        runType: 'CONTRACT_REVIEW',
        status: 'ANALYZING',
        progress: 42,
        currentStep: '正在检索合同证据',
        createTime: '2026-08-05T10:01:00',
      },
    ],
  )

  assert.equal(activities.length, 1)
  assert.equal(activities[0].caseId, 41)
  assert.equal(activities[0].pipeline.jobId, 17)
  assert.equal(activities[0].run.id, 12)
  assert.equal(activities[0].status, 'PROCESSING')
  assert.equal(activities[0].pipeline.progress, 58)
  assert.equal(activities[0].run.progress, 42)
})
