function ymd(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dateValue(value) {
  const raw = String(value || '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return ''
  const parsed = new Date(`${raw}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? '' : raw
}

function addWorkingDays(date, amount) {
  const direction = amount < 0 ? -1 : 1
  let remaining = Math.abs(amount)
  while (remaining > 0) {
    date.setDate(date.getDate() + direction)
    const weekday = date.getDay()
    if (weekday !== 0 && weekday !== 6) remaining -= 1
  }
}

function addCalendarMonths(date, amount) {
  const day = date.getDate()
  date.setDate(1)
  date.setMonth(date.getMonth() + amount)
  const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
  date.setDate(Math.min(day, lastDay))
}

function addCalendarYears(date, amount) {
  const month = date.getMonth()
  const day = date.getDate()
  date.setDate(1)
  date.setFullYear(date.getFullYear() + amount)
  date.setMonth(month)
  const lastDay = new Date(date.getFullYear(), month + 1, 0).getDate()
  date.setDate(Math.min(day, lastDay))
}

export function calculateRelativeDate(condition, baseValue) {
  const amountMatch = String(condition || '').match(/(\d{1,3})\s*(?:个)?\s*(?:工作日|自然日|日|天|个月|月|年)/)
  const baseDate = dateValue(baseValue)
  if (!amountMatch || !baseDate) return ''
  const amount = Number(amountMatch[1])
  const sign = /前/.test(condition) ? -1 : 1
  const date = new Date(`${baseDate}T00:00:00`)
  if (/工作日/.test(condition)) {
    addWorkingDays(date, sign * amount)
  } else if (/(个月|月)/.test(condition)) {
    addCalendarMonths(date, sign * amount)
  } else if (/年/.test(condition)) {
    addCalendarYears(date, sign * amount)
  } else {
    date.setDate(date.getDate() + sign * amount)
  }
  return ymd(date)
}

function concreteTimelineDates(contract) {
  return (Array.isArray(contract?.timelineNodes) ? contract.timelineNodes : [])
    .map(node => dateValue(node?.nodeDate || node?.date))
    .filter(Boolean)
    .sort()
}

export function resolveTimelineDate({ condition, contract = {}, manualBaseDate = '' }) {
  const raw = String(condition || '').replace(/\s+/g, '')
  if (!raw) return { resolvedDate: '', baseDate: '', candidates: [], baseUncertain: false, hint: '' }

  const manual = dateValue(manualBaseDate)
  const signedDate = dateValue(contract.signedDate)
  const effectiveDate = dateValue(contract.effectiveDate)
  const expiryDate = dateValue(contract.expiryDate)
  const timelineDates = concreteTimelineDates(contract)
  const candidates = []
  const add = (value, label, source, uncertain = false) => {
    const date = dateValue(value)
    if (!date || candidates.some(item => item.value === date)) return
    candidates.push({ value: date, label, source, uncertain })
  }

  if (/期满前|到期前|合同期满前/.test(raw)) {
    add(expiryDate, '合同到期/期满日', 'EXPIRY_DATE')
    add(timelineDates.at(-1), '时间线最晚日期（推定）', 'TIMELINE_INFERRED', true)
  } else if (/生效后|生效日起|自生效/.test(raw)) {
    add(effectiveDate, '合同生效日', 'EFFECTIVE_DATE')
    add(signedDate, '合同签订日（推定）', 'SIGNED_DATE_INFERRED', true)
    add(timelineDates[0], '时间线最早日期（推定）', 'TIMELINE_INFERRED', true)
  } else if (/签订合同后|签署后|签订后/.test(raw)) {
    add(signedDate, '合同签订日', 'SIGNED_DATE')
    add(effectiveDate, '合同生效日（暂代签订日）', 'EFFECTIVE_DATE_INFERRED', true)
    add(timelineDates[0], '时间线最早日期（推定）', 'TIMELINE_INFERRED', true)
  }

  const selected = manual
    ? { value: manual, label: '手工指定日期', source: 'MANUAL', uncertain: false }
    : candidates[0]
  const resolvedDate = selected ? calculateRelativeDate(raw, selected.value) : ''
  const expectedBase = /签订合同后|签署后|签订后/.test(raw) ? '合同签订日期'
    : /期满前|到期前|合同期满前/.test(raw) ? '合同到期日期'
      : /生效后|生效日起|自生效/.test(raw) ? '合同生效日期' : '触发日期'

  return {
    resolvedDate,
    baseDate: selected?.value || '',
    baseLabel: selected?.label || expectedBase,
    baseSource: selected?.source || '',
    baseUncertain: Boolean(resolvedDate && selected?.uncertain),
    candidates,
    needsManualBase: !selected,
    hint: selected?.uncertain
      ? `缺少${expectedBase}，当前按${selected.label}推定；请核对或修改。`
      : selected
        ? `按${selected.label}计算。`
        : `缺少可确认的${expectedBase}，请填写实际触发日期后计算。`,
  }
}

export function sanitizeTimelineMeaning(value) {
  let text = String(value || '').replace(/\s+/g, ' ').trim()
  text = text.replace(/[；;]\s*来源\s*=\s*[A-Z0-9_]+\s*/gi, '')
  text = text.replace(/[；;]\s*原文片段\s*[:：].*$/i, '')
  text = text.replace(/来源\s*=\s*(?:DURATION_TERM|TEXT_DATE(?:_INFERRED_YEAR)?|RELATIVE_TERM)(?:_RESOLVED)?/gi, '')
  return text.replace(/[；;，,\s]+$/g, '').trim()
}

export function deriveTimelineAction(quote, condition = '') {
  const text = String(quote || '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  const compactCondition = String(condition || '').replace(/\s+/g, '')
  const clauses = text.split(/[；;。\n]/).map(item => item.trim()).filter(Boolean)
  const conditionWithoutIndex = compactCondition.replace(/^（?\d+）?[、.．]?/, '')
  const matched = clauses.find(item => {
    const compactItem = item.replace(/\s+/g, '')
    return (compactCondition && compactItem.includes(compactCondition))
      || (conditionWithoutIndex && compactItem.includes(conditionWithoutIndex))
  }) || clauses[0]
  let action = matched
    .replace(/^（?\d+）?\s*[、.．]?\s*/, '')
  let conditionRemoved = false
  if (compactCondition || conditionWithoutIndex) {
    const compactAction = action.replace(/\s+/g, '')
    const needle = compactAction.includes(compactCondition) ? compactCondition : conditionWithoutIndex
    const conditionIndex = compactAction.indexOf(needle)
    if (conditionIndex >= 0) {
      action = compactAction.slice(conditionIndex + needle.length)
      conditionRemoved = true
    }
  }
  if (!conditionRemoved) {
    action = action.replace(/^.*?(?:后|前|内|起|届满|以上)\s*[，,]?\s*/, '')
  }
  return action
    .replace(/^[，,：:\s]+/, '')
    .replace(/[；;。]+$/g, '')
    .trim()
}
