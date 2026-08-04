import axios from 'axios'

const api = axios.create({
  // 开发环境: http://localhost:18080，生产环境: / (nginx 反向代理)
  baseURL: import.meta.env.VITE_API_BASE || '/',
  timeout: 10000
})

const KB_UPLOAD_TIMEOUT = 10 * 60 * 1000

api.interceptors.request.use(config => {
  const token = localStorage.getItem('atlasmind-token')
  if (token) config.headers['atlasmind-token'] = token
  return config
})

api.interceptors.response.use(
  res => res,
  err => {
    if (err.response && err.response.status === 401) {
      localStorage.removeItem('atlasmind-token')
      // 使用 BASE_URL 适配子路径部署
      window.location.href = import.meta.env.BASE_URL + 'login'
    }
    return Promise.reject(err)
  }
)

export function login(data) { return api.post('/api/auth/login', data) }
export function getUserInfo() { return api.get('/api/auth/info') }
export function updateProfile(data) { return api.put('/api/auth/profile', data) }
export function updatePassword(data) { return api.put('/api/auth/password', data) }
export function getRuntimeSettings() { return api.get('/api/admin/settings/runtime') }
export function updateRuntimeSettings(data) { return api.put('/api/admin/settings/runtime', data) }

export function getDashboardOverview() { return api.get('/api/admin/dashboard/overview') }

export function uploadFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
}

export function getOperationLogs(params) { return api.get('/api/admin/logs', { params }) }

export function getContracts() { return api.get('/api/workspace/contracts') }
export function getContractCase(id) { return api.get(`/api/workspace/contracts/${id}`) }
export function getContractPortfolio() { return api.get('/api/workspace/contracts/portfolio') }
export function getContractRun(runId) { return api.get(`/api/workspace/contracts/runs/${runId}`) }
export function getAdminContractCases(params = {}) { return api.get('/api/admin/contracts/cases', { params }) }
export function getAdminContractDeleteImpact(id) { return api.get(`/api/admin/contracts/cases/${id}/delete-impact`) }
export function deleteAdminContractCase(id) { return api.delete(`/api/admin/contracts/cases/${id}`) }
export function restoreAdminContractCase(id) { return api.post(`/api/admin/contracts/cases/${id}/restore`) }
export function getAgentRuns() { return api.get('/api/workspace/runs/recent') }
export function getAgentReports() { return api.get('/api/admin/contracts/reports') }
export function getAgentActions(params = {}) { return api.get('/api/admin/contracts/actions', { params }) }
export function deleteAgentRun(id) { return api.delete(`/api/admin/contracts/runs/${id}`) }
export function cancelAgentRun(id) { return api.put(`/api/admin/contracts/runs/${id}/cancel`) }
export function deleteAgentReport(id) { return api.delete(`/api/admin/contracts/reports/${id}`) }
export function deleteAgentAction(id) { return api.delete(`/api/admin/contracts/actions/${id}`) }

export function getKbSpaces() { return api.get('/api/admin/kb/spaces') }
export function createKbSpace(data) { return api.post('/api/admin/kb/spaces', data) }
export function updateKbSpace(id, data) { return api.put(`/api/admin/kb/spaces/${id}`, data) }
export function deleteKbSpace(id) { return api.delete(`/api/admin/kb/spaces/${id}`) }

export function getKbDocuments(params) { return api.get('/api/admin/kb/documents', { params }) }
export function getKbDocument(id) { return api.get(`/api/admin/kb/documents/${id}`) }
export function getKbDocumentChunks(id) { return api.get(`/api/admin/kb/documents/${id}/chunks`) }
export function uploadKbDocument(spaceId, file, title = '', parseMode = 'OCR', projectIds = []) {
  const formData = new FormData()
  formData.append('spaceId', spaceId)
  formData.append('file', file)
  if (title) formData.append('title', title)
  if (parseMode) formData.append('parseMode', parseMode)
  projectIds.forEach(id => formData.append('projectIds', id))
  return api.post('/api/admin/kb/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: KB_UPLOAD_TIMEOUT
  })
}
export function uploadKbDocumentChunk({ uploadId, fileName, fileSize, chunkIndex, totalChunks, chunk }) {
  const formData = new FormData()
  formData.append('uploadId', uploadId)
  formData.append('fileName', fileName)
  formData.append('fileSize', fileSize)
  formData.append('chunkIndex', chunkIndex)
  formData.append('totalChunks', totalChunks)
  formData.append('chunk', chunk)
  return api.post('/api/admin/kb/documents/upload/chunk', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: KB_UPLOAD_TIMEOUT
  })
}
export function completeKbDocumentUpload({ spaceId, uploadId, fileName, fileSize, totalChunks, title = '', parseMode = 'OCR', projectIds = [] }) {
  const formData = new FormData()
  formData.append('spaceId', spaceId)
  formData.append('uploadId', uploadId)
  formData.append('fileName', fileName)
  formData.append('fileSize', fileSize)
  formData.append('totalChunks', totalChunks)
  if (title) formData.append('title', title)
  if (parseMode) formData.append('parseMode', parseMode)
  projectIds.forEach(id => formData.append('projectIds', id))
  return api.post('/api/admin/kb/documents/upload/complete', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: KB_UPLOAD_TIMEOUT
  })
}
export function importDebugRecord() { return api.post('/api/admin/kb/documents/import-debug-record') }
export function deleteKbDocument(id) { return api.delete(`/api/admin/kb/documents/${id}`) }
export function restoreKbDocument(id) { return api.post(`/api/admin/kb/documents/${id}/restore`) }
export function permanentDeleteKbDocument(id) { return api.delete(`/api/admin/kb/documents/${id}/permanent`) }
export function reparseKbDocument(id) { return api.post(`/api/admin/kb/documents/${id}/reparse`) }
export function reindexKbDocument(id) { return api.post(`/api/admin/kb/documents/${id}/reindex`) }
export function bindKbDocumentProjects(id, projectIds = []) {
  return api.put(`/api/admin/kb/documents/${id}/projects`, { projectIds })
}
export function testKbQa(data) { return api.post('/api/admin/kb/qa/test', data) }

export function getAiObservabilityTraces(params) {
  return api.get('/api/admin/ai-observability/traces', { params })
}

export function getAiObservabilityTrace(id) {
  return api.get(`/api/admin/ai-observability/traces/${id}`)
}

export function getAiObservabilityAgentRuns(params) {
  return api.get('/api/admin/ai-observability/agent-runs', { params })
}

export function getAiObservabilityAgentRun(id) {
  return api.get(`/api/admin/ai-observability/agent-runs/${id}`)
}

export function getAiObservabilityDocumentPipelines(params) {
  return api.get('/api/admin/ai-observability/document-pipelines', { params })
}

export function getAiObservabilityDocumentPipeline(id) {
  return api.get(`/api/admin/ai-observability/document-pipelines/${id}`)
}

export function getKbNotifications(params) { return api.get('/api/admin/kb/notifications', { params }) }
export function getKbUnreadCount() { return api.get('/api/admin/kb/notifications/unread-count') }
export function readKbNotification(id) { return api.put(`/api/admin/kb/notifications/${id}/read`) }
export function readAllKbNotifications() { return api.put('/api/admin/kb/notifications/read-all') }

export default api
