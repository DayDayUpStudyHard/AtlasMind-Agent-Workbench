import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 10000,
  withCredentials: true
})

const authApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 10000,
  withCredentials: true
})

// ── Memory-only access token (never localStorage) ──────────────
let accessToken = null

export function setAccessToken(token) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function clearAccessToken() {
  accessToken = null
}

api.interceptors.request.use(config => {
  if (accessToken) {
    config.headers['atlasmind-token'] = accessToken
  }
  return config
})

// ── Shared refresh logic (used by both 401 interceptor AND router guard) ──
let isRefreshing = false
let refreshQueue = []

function resolveQueue(token) {
  refreshQueue.forEach(([resolve]) => resolve(token))
  refreshQueue = []
}

function rejectQueue(error) {
  refreshQueue.forEach(([, reject]) => reject(error))
  refreshQueue = []
}

/**
 * Attempt to refresh the access token via httpOnly cookie.
 * Guards against concurrent calls — only one refresh request flies at a time.
 * Returns the new access token on success, or null on failure.
 */
export async function refreshAccessToken() {
  if (isRefreshing) {
    // Queue: wait for the in-flight refresh to finish
    return new Promise((resolve, reject) => {
      refreshQueue.push([resolve, reject])
    })
  }

  isRefreshing = true
  try {
    console.log('[auth] refresh: sending request...')
    const res = await authApi.post('/api/auth/refresh')
    const token = res.data?.data?.token
    if (token) {
      console.log('[auth] refresh: success, got token')
      accessToken = token
      resolveQueue(token)
      return token
    }
    console.warn('[auth] refresh: no token in response body', res.data)
    rejectQueue(new Error('No token in refresh response'))
    return null
  } catch (err) {
    if (err.response) {
      console.warn('[auth] refresh: backend returned error', err.response.status, err.response.data)
    } else {
      console.warn('[auth] refresh: network error', err.message)
    }
    rejectQueue(err)
    accessToken = null
    return null
  } finally {
    isRefreshing = false
  }
}

api.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      const token = await refreshAccessToken()
      if (token) {
        originalRequest._retry = true
        originalRequest.headers['atlasmind-token'] = token
        return api(originalRequest)
      }
      // Refresh failed → redirect to login
      accessToken = null
      if (window.location.pathname !== `${import.meta.env.BASE_URL || '/'}login`) {
        window.location.href = `${import.meta.env.BASE_URL || '/'}login`
      }
      return Promise.reject(error)
    }
    return Promise.reject(error)
  }
)

export function login(data) {
  return api.post('/api/auth/login', data)
}

export function logout() {
  return api.post('/api/auth/logout', {}, { withCredentials: true })
}

export function getUserInfo() {
  return api.get('/api/auth/info')
}

export function getSiteInfo() {
  return api.get('/api/site/info')
}

export function getRuntimeConfig() {
  return api.get('/api/site/runtime-config')
}

export function getKbSpaces() {
  return api.get('/api/kb/spaces')
}

export function getKbDocuments(params) {
  return api.get('/api/kb/documents', { params })
}

export function getKbDocument(id) {
  return api.get(`/api/kb/documents/${id}`)
}

export function getKbDocumentChunks(id) {
  return api.get(`/api/kb/documents/${id}/chunks`)
}

export function getWorkspaceNotifications(params = {}) {
  return api.get('/api/workspace/notifications', { params })
}

export function getWorkspaceUnreadCount() {
  return api.get('/api/workspace/notifications/unread-count')
}

export function readWorkspaceNotification(id) {
  return api.put(`/api/workspace/notifications/${id}/read`)
}

export function readAllWorkspaceNotifications() {
  return api.put('/api/workspace/notifications/read-all')
}

export function getWorkspaceAiStatus() {
  return api.get('/api/workspace/ai-status', { timeout: 15000 })
}

export function getRecentWorkspaceRuns() {
  return api.get('/api/workspace/runs/recent')
}

export function getRecentContractDocumentPipelines() {
  return api.get('/api/workspace/contracts/document-pipelines/recent')
}

export function getContractPortfolio() { return api.get('/api/workspace/contracts/portfolio') }
export function getContractWorkQueueSummary() { return api.get('/api/workspace/contracts/work-queues/summary') }
export function getContractWorkQueue(type) { return api.get('/api/workspace/contracts/work-queues', { params: { type } }) }
export function listContracts(params) { return api.get('/api/workspace/contracts', { params }) }
export function getContractCase(id) { return api.get(`/api/workspace/contracts/${id}`) }
export function createContractCase(data) { return api.post('/api/workspace/contracts', data) }
export function startContractRun(caseId, data) { return api.post(`/api/workspace/contracts/${caseId}/runs`, data) }
export function getContractRun(runId) { return api.get(`/api/workspace/contracts/runs/${runId}`) }
export function updateContractFinding(findingId, data) { return api.patch(`/api/workspace/contracts/findings/${findingId}`, data) }
export function approveContractAction(runId, actionId, data) { return api.post(`/api/workspace/contracts/runs/${runId}/actions/${actionId}/approval`, data) }

// ── Contract file download ──────────────────────────────────────
export function downloadContractDocument(documentId) {
  return api.get(`/api/workspace/contracts/documents/${documentId}/download`, { responseType: 'blob' })
}

// ── Contract members ────────────────────────────────────────────
export function getContractMembers(caseId) { return api.get(`/api/workspace/contracts/${caseId}/members`) }
export function inviteContractMember(caseId, data) { return api.post(`/api/workspace/contracts/${caseId}/members/invite`, data) }
export function updateContractMemberRole(caseId, userId, data) { return api.patch(`/api/workspace/contracts/${caseId}/members/${userId}`, data) }
export function removeContractMember(caseId, userId) { return api.delete(`/api/workspace/contracts/${caseId}/members/${userId}`) }
export function transferContractOwnership(caseId, data) { return api.post(`/api/workspace/contracts/${caseId}/owner/transfer`, data) }

// ── Contract status transitions ─────────────────────────────────
export function submitContractReview(caseId) { return api.post(`/api/workspace/contracts/${caseId}/submit-review`) }
export function approveContract(caseId) { return api.post(`/api/workspace/contracts/${caseId}/approve`) }
export function requestContractRevision(caseId, data) { return api.post(`/api/workspace/contracts/${caseId}/request-revision`, data) }

export function createAiSession(data = {}) {
  return api.post('/api/ai/sessions', data)
}

export function getAiSessionMessages(sessionId, ownerToken) {
  return api.get(`/api/ai/sessions/${sessionId}/messages`, {
    headers: ownerToken ? { 'X-AI-Session-Token': ownerToken } : undefined
  })
}

export function appendAiMessage(sessionId, data, ownerToken) {
  return api.post(`/api/ai/sessions/${sessionId}/messages`, data, {
    headers: ownerToken ? { 'X-AI-Session-Token': ownerToken } : undefined
  })
}

export default api
