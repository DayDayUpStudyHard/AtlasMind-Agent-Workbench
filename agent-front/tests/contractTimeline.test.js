import test from 'node:test'
import assert from 'node:assert/strict'

import {
  deriveTimelineAction,
  resolveTimelineDate,
  sanitizeTimelineMeaning,
} from '../src/utils/contractTimeline.js'

test('uses effective date as an uncertain fallback when signed date is missing', () => {
  const result = resolveTimelineDate({
    condition: '签订合同后30天内',
    contract: {
      signedDate: null,
      effectiveDate: '2025-08-15',
      expiryDate: '2026-12-31',
    },
  })

  assert.equal(result.resolvedDate, '2025-09-14')
  assert.equal(result.baseDate, '2025-08-15')
  assert.equal(result.baseUncertain, true)
  assert.match(result.hint, /推定/)
})

test('ignores list numbering when calculating a relative deadline', () => {
  const result = resolveTimelineDate({
    condition: '（1）签订合同后30天内',
    contract: { effectiveDate: '2025-08-15' },
  })

  assert.equal(result.resolvedDate, '2025-09-14')
})

test('does not invent a date for an event-triggered duration without a trigger date', () => {
  const result = resolveTimelineDate({
    condition: '不可抗力持续10日以上',
    contract: { effectiveDate: '2025-08-15' },
  })

  assert.equal(result.resolvedDate, '')
  assert.equal(result.needsManualBase, true)
})

test('manual base date overrides the inferred date immediately', () => {
  const result = resolveTimelineDate({
    condition: '签订合同后30天内',
    contract: { effectiveDate: '2025-08-15' },
    manualBaseDate: '2025-08-01',
  })

  assert.equal(result.resolvedDate, '2025-08-31')
  assert.equal(result.baseDate, '2025-08-01')
  assert.equal(result.baseUncertain, false)
  assert.equal(result.baseSource, 'MANUAL')
})

test('clamps month-based deadlines to the final day of the target month', () => {
  const beforeExpiry = resolveTimelineDate({
    condition: '合同期满前1个月',
    contract: { expiryDate: '2026-12-31' },
  })
  const afterSigning = resolveTimelineDate({
    condition: '签订合同后1个月',
    contract: { signedDate: '2025-01-31' },
  })

  assert.equal(beforeExpiry.resolvedDate, '2026-11-30')
  assert.equal(afterSigning.resolvedDate, '2025-02-28')
})

test('removes parser implementation labels from legacy timeline descriptions', () => {
  const value = sanitizeTimelineMeaning(
    '需要跟踪服务或交付物完成时限；来源=DURATION_TERM；原文片段：3．技术服务进度：签订合同后30天内提供实施方案。'
  )

  assert.equal(value, '需要跟踪服务或交付物完成时限')
  assert.doesNotMatch(value, /DURATION_TERM|TEXT_DATE|原文片段/)
})

test('extracts the concrete delivery action instead of a generic template', () => {
  const action = deriveTimelineAction(
    '（1）签订合同后30天内，提供项目具体实施方案；（2）签订合同后180天内，完成第一阶段研究内容。',
    '签订合同后30天内'
  )

  assert.equal(action, '提供项目具体实施方案')
})

test('extracts the correct numbered milestone from a full clause', () => {
  const action = deriveTimelineAction(
    '3．技术服务进度：（1）签订合同后30天内，提供具体实施方案；（2）签订合同后180天内，完成第一条中技术服务目标的（1）-（2）项研究内容；（3）签订合同后360天内，完成目标（3）-（4）项研究内容。',
    '（2）签订合同后180天内'
  )

  assert.equal(action, '完成第一条中技术服务目标的（1）-（2）项研究内容')
})
