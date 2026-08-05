import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 10000
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('atlasmind-token')
  if (token) config.headers['atlasmind-token'] = token
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401 && window.location.pathname !== `${import.meta.env.BASE_URL}login`) {
      localStorage.removeItem('atlasmind-token')
      window.location.href = `${import.meta.env.BASE_URL}login`
    }
    return Promise.reject(error)
  }
)

export function login(data) {
  return api.post('/api/auth/login', data)
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
