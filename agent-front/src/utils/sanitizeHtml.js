/**
 * Minimal, dependency-free sanitizer for HTML produced by `marked`.
 *
 * Model output and report Markdown are untrusted input, so the rendered HTML
 * must not be injected into `v-html` verbatim. Instead of pulling in a runtime
 * dependency (the CI installs with `npm ci`, which requires a matching
 * lockfile), the string is parsed into an inert document, disallowed elements
 * are removed and only a small set of formatting tags/attributes survives.
 */

const ALLOWED_TAGS = new Set([
  'p', 'br', 'strong', 'em', 'b', 'i', 'code', 'pre', 'ul', 'ol', 'li',
  'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'blockquote', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'del', 'span'
])

const ALLOWED_ATTRS = new Set(['href', 'title', 'class'])

// Elements whose entire subtree must be dropped (not just the tag).
const DROP_WITH_CONTENT = new Set([
  'script', 'style', 'iframe', 'object', 'embed', 'template', 'noscript',
  'svg', 'math', 'form', 'input', 'button', 'textarea', 'select', 'option'
])

function isSafeHref(value) {
  const normalized = String(value || '').trim().toLowerCase()
  // Block javascript:, vbscript:, data: and control-character obfuscation.
  return !/^(javascript|vbscript|data|file):/.test(normalized.replace(/[\u0000-\u0020]/g, ''))
}

function scrubElement(el) {
  for (const attr of Array.from(el.attributes || [])) {
    const name = attr.name.toLowerCase()
    if (!ALLOWED_ATTRS.has(name)) {
      el.removeAttribute(attr.name)
      continue
    }
    if (name === 'href' && !isSafeHref(attr.value)) {
      el.removeAttribute(attr.name)
    }
    if (name === 'class') {
      // Only keep syntax-highlighting classes emitted by highlight.js.
      const kept = String(attr.value || '')
        .split(/\s+/)
        .filter(token => /^(hljs|language-|lang-)[\w-]*$/.test(token))
        .join(' ')
      if (kept) el.setAttribute('class', kept)
      else el.removeAttribute('class')
    }
  }
}

function sanitizeNode(node) {
  for (const child of Array.from(node.childNodes || [])) {
    if (child.nodeType !== 1) continue // text nodes are inert
    const tag = child.tagName.toLowerCase()
    if (DROP_WITH_CONTENT.has(tag)) {
      child.remove()
      continue
    }
    if (!ALLOWED_TAGS.has(tag)) {
      // Unwrap unknown-but-harmless wrappers instead of discarding their text.
      sanitizeNode(child)
      while (child.firstChild) child.parentNode.insertBefore(child.firstChild, child)
      child.remove()
      continue
    }
    scrubElement(child)
    sanitizeNode(child)
  }
}

/**
 * Sanitize an HTML string for safe use with `v-html`.
 * @param {string} html
 * @returns {string}
 */
export function sanitizeHtml(html) {
  const source = String(html || '')
  if (!source) return ''
  if (typeof window === 'undefined' || typeof window.DOMParser === 'undefined') {
    // Non-browser environment: fall back to conservative escaping.
    return source
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }
  const doc = new window.DOMParser().parseFromString(source, 'text/html')
  if (!doc.body) return ''
  sanitizeNode(doc.body)
  return doc.body.innerHTML
}

export default sanitizeHtml
