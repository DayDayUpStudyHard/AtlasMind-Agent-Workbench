function cleanText(value) {
  if (value == null) return ''
  return String(value).replace(/\s+/g, ' ').trim()
}

function primitiveText(value) {
  if (value == null || value === '') return ''
  if (typeof value === 'object') return structuredValueSummary(value)
  return cleanText(value)
}

function joinParts(parts, separator = ' · ') {
  return parts.map(cleanText).filter(Boolean).slice(0, 5).join(separator)
}

function amountText(value, currency) {
  if (value == null || value === '') return ''
  const unit = cleanText(currency)
  return `${cleanText(value)}${unit ? ` ${unit}` : ''}`
}

function pickValue(value, keys) {
  for (const key of keys) {
    const text = primitiveText(value?.[key])
    if (text) return text
  }
  return ''
}

function structuredBusinessSummary(value) {
  const type = primitiveText(value.type || value.kind || value.category)
  const condition = primitiveText(value.condition || value.trigger || value.requirement)
  const timing = primitiveText(value.timing || value.deadline || value.timeLimit || value.period)
  const note = primitiveText(value.note || value.remark || value.comment)
  const cap = primitiveText(value.cap || value.limit)
  const action = primitiveText(value.action || value.obligation || value.task)
  const party = primitiveText(value.party || value.obligor || value.responsibleParty)
  const amount = amountText(value.amount, value.currency)
  if (amount && !(condition || timing || action || note || cap)) return amount

  if (condition || timing || action || note || cap) {
    const lead = type ? `${type}：` : ''
    const first = joinParts([party, action || condition, amount], '，')
    const tail = joinParts([
      timing ? `时限：${timing}` : '',
      cap ? `上限：${cap}` : '',
      note ? `备注：${note}` : '',
    ], '；')
    return `${lead}${joinParts([first, tail], '；')}`.trim()
  }

  const materials = Array.isArray(value.materials) ? value.materials.map(primitiveText).filter(Boolean) : []
  if (materials.length) return `应提交材料：${materials.slice(0, 5).join('、')}`

  const details = Array.isArray(value.breachDetails) ? value.breachDetails.map(primitiveText).filter(Boolean) : []
  if (details.length) return `违约责任：${details.slice(0, 3).join('；')}`

  return ''
}

export function structuredValueDetails(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  const details = [
    ['类型', pickValue(value, ['type', 'kind', 'category'])],
    ['责任方', pickValue(value, ['party', 'obligor', 'responsibleParty'])],
    ['触发条件', pickValue(value, ['condition', 'trigger', 'requirement'])],
    ['应做事项', pickValue(value, ['action', 'obligation', 'task'])],
    ['金额/比例', amountText(value.amount, value.currency) || pickValue(value, ['ratio', 'percentage'])],
    ['时限', pickValue(value, ['timing', 'deadline', 'timeLimit', 'period'])],
    ['上限/保留', pickValue(value, ['cap', 'limit'])],
    ['备注', pickValue(value, ['note', 'remark', 'comment'])],
    ['生效条件', pickValue(value, ['effectiveCondition'])],
    ['结束条件', pickValue(value, ['terminationCondition'])],
  ].filter(([, text]) => text)

  const materials = Array.isArray(value.materials) ? value.materials.map(primitiveText).filter(Boolean) : []
  if (materials.length) details.push(['应提交材料', materials.slice(0, 6).join('、')])
  const rows = Array.isArray(value.rows) ? value.rows : Array.isArray(value.items) ? value.items : []
  if (rows.length && details.length === 0) details.push(['明细', `${rows.length} 项`])
  return details
}

export function elementPresentation(element) {
  const normalized = element?.normalizedValue
  const raw = element?.rawValue
  const value = normalized && typeof normalized === 'object'
    ? normalized
    : raw && typeof raw === 'object'
      ? raw
      : null
  const key = cleanText(element?.elementKey).toLowerCase()
  const category = cleanText(element?.category || element?.groupKey).toLowerCase()
  const label = cleanText(element?.displayLabel || element?.label || element?.title || element?.elementKey || '合同要素')
  const summary = elementDisplayValue(element)
  const details = value ? structuredValueDetails(value) : []
  const type = value ? pickValue(value, ['type', 'kind', 'category']) : ''
  const headline = type && !label.includes(type) ? `${label} · ${type}` : label

  let displayMode = cleanText(element?.displayMode || value?.displayMode).toUpperCase()
  if (!displayMode) {
    if (key.includes('payment') || key.includes('settlement') || category.includes('financial')) displayMode = 'PAYMENT'
    else if (key.includes('notice') || key.includes('claim') || summary.includes('索赔') || summary.includes('通知')) displayMode = 'PROCESS'
    else if (key.includes('liability') || key.includes('breach') || summary.includes('违约')) displayMode = 'LIABILITY'
    else if (key.includes('termination') || summary.includes('终止') || summary.includes('失效')) displayMode = 'TERMINATION'
    else displayMode = 'FACT'
  }

  const chips = [
    type,
    value ? pickValue(value, ['timing', 'deadline', 'timeLimit', 'period']) : '',
    value ? amountText(value.amount, value.currency) : '',
  ].filter(Boolean).slice(0, 3)

  return {
    displayMode,
    headline,
    summary,
    details,
    chips,
    structured: Boolean(value),
  }
}

export function structuredValueSummary(value) {
  if (!value || typeof value !== 'object') return ''
  if (Array.isArray(value)) {
    return value
      .map(item => (item && typeof item === 'object' ? structuredValueSummary(item) : cleanText(item)))
      .filter(Boolean)
      .slice(0, 3)
      .join('；')
  }

  const preferredKeys = ['displayValue', 'summary', 'value', 'name', 'fullName', 'title']
  const preferred = joinParts(preferredKeys.map(key => primitiveText(value[key])))
  if (preferred) return preferred

  const business = structuredBusinessSummary(value)
  if (business) return business

  const keys = [
    'role', 'address', 'contact', 'phone', 'tel', 'mobile', 'bank', 'account',
    'date', 'startDate', 'endDate', 'effectiveCondition', 'terminationCondition',
  ]
  const parts = keys.map(key => primitiveText(value[key])).filter(Boolean)
  if (parts.length) return parts.slice(0, 4).join(' · ')
  if (Array.isArray(value.rows) && value.rows.length) return `${value.rows.length} 行`
  if (Array.isArray(value.items) && value.items.length) return `${value.items.length} 项`
  if (Array.isArray(value.schedule) && value.schedule.length) return `${value.schedule.length} 个节点`
  return ''
}

export function elementDisplayValue(element) {
  const normalized = element?.normalizedValue
  if (normalized && typeof normalized === 'object') {
    const structured = structuredValueSummary(normalized)
    if (structured) return structured
  }
  const raw = element?.rawValue
  if (raw && typeof raw === 'object') {
    const structured = structuredValueSummary(raw)
    if (structured) return structured
    return '结构化信息，查看完整证据'
  }
  return raw || '待确认'
}

export function compactElementValue(element, limit = 100) {
  const value = cleanText(elementDisplayValue(element))
  if (!value) return '待确认'
  return value.length > limit ? `${value.slice(0, limit).trim()}…` : value
}

export function compactAmountValue(element) {
  const normalized = element?.normalizedValue
  if (normalized && typeof normalized === 'object') {
    const amount = normalized.amount ?? normalized.value
    const currency = normalized.currency
    if (amount != null && cleanText(amount)) return amountText(amount, currency)
  }
  const raw = String(element?.rawValue || '')
  const match = raw.match(/(?:人民币|￥|¥)?\s*([\d,]+(?:\.\d+)?)\s*元?(?:\s*人民币)?/)
  return match ? `${match[1]} 元人民币` : compactElementValue(element, 44)
}
