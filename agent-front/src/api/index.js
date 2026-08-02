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

export function getProjectOverview() {
  return api.get('/api/workspace/projects/overview')
}

export function getProject(id) {
  return api.get(`/api/workspace/projects/${id}`)
}

export function createProject(data) {
  return api.post('/api/workspace/projects', data)
}

export function syncProjectEvidence(projectId) {
  return api.post(`/api/workspace/projects/${projectId}/sync`, null, { timeout: 120000 })
}

export function getProjectEvidence(projectId, params = {}) {
  return api.get(`/api/workspace/projects/${projectId}/evidence`, { params })
}

export function getProjectSyncJobs(projectId) {
  return api.get(`/api/workspace/projects/${projectId}/sync-jobs`)
}

export function startProjectRun(projectId, data = {}) {
  return api.post(`/api/workspace/projects/${projectId}/runs`, data, { timeout: 120000 })
}

export function getProjectRun(runId) {
  return api.get(`/api/workspace/projects/runs/${runId}`)
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

export function getContractPortfolio() { return api.get('/api/workspace/contracts/portfolio') }
export function listContracts(params) { return api.get('/api/workspace/contracts', { params }) }
export function getContractCase(id) { return api.get(`/api/workspace/contracts/${id}`) }
export function createContractCase(data) { return api.post('/api/workspace/contracts', data) }
export function startContractRun(caseId, data) { return api.post(`/api/workspace/contracts/${caseId}/runs`, data) }
export function getContractRun(runId) { return api.get(`/api/workspace/contracts/runs/${runId}`) }
export function approveContractAction(runId, actionId, data) { return api.post(`/api/workspace/contracts/runs/${runId}/actions/${actionId}/approval`, data) }

export function approveProjectAction(runId, actionId, data = {}) {
  return api.post(`/api/workspace/projects/runs/${runId}/actions/${actionId}/approval`, data)
}

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
