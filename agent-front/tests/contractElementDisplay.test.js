import test from 'node:test'
import assert from 'node:assert/strict'

import {
  elementDisplayValue,
  structuredValueSummary,
} from '../src/utils/contractElementDisplay.js'

test('summarizes structured payment terms instead of leaking JSON', () => {
  const value = {
    type: '结算款',
    condition: '根据发包人确认的工程结算报告,承包人向发包人申请支付工程结算款',
    amount: null,
    currency: null,
    timing: '收到申请后30天内',
    note: '除质量保证金(最终合同价款的5%)以外的结算款',
  }

  const summary = structuredValueSummary(value)

  assert.match(summary, /结算款/)
  assert.match(summary, /工程结算报告/)
  assert.match(summary, /30天内/)
  assert.match(summary, /质量保证金/)
  assert.doesNotMatch(summary, /^\s*\{/)
  assert.doesNotMatch(summary, /"condition"|normalizedValue/)
})

test('element display uses structured normalized values as business copy', () => {
  const text = elementDisplayValue({
    normalizedValue: {
      type: '进度款',
      condition: '承包人按月报送已完工工程统计报表和进度款支付申请',
      timing: '30日内',
      cap: '累计支付到合同约定建筑安装费的75%为止',
    },
    rawValue: '{"type":"进度款"}',
  })

  assert.equal(
    text,
    '进度款：承包人按月报送已完工工程统计报表和进度款支付申请；时限：30日内；上限：累计支付到合同约定建筑安装费的75%为止',
  )
})
