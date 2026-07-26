import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 10000
})

export function getArticles(params) {
  return api.get('/api/articles', { params })
}

export function getArticleDetail(id) {
  return api.get(`/api/articles/${id}`)
}

export function getCategories() {
  return api.get('/api/categories')
}

export function getTags() {
  return api.get('/api/tags')
}

export function getArticleNav(id) {
  return api.get(`/api/articles/${id}/nav`)
}

export function getComments(articleId) {
  return api.get(`/api/articles/${articleId}/comments`)
}

export function addComment(articleId, data) {
  return api.post(`/api/articles/${articleId}/comments`, data)
}

export function getSiteInfo() {
  return api.get('/api/site/info')
}

export function getRuntimeConfig() {
  return api.get('/api/site/runtime-config')
}

export function getMoments(params) {
  return api.get('/api/moments', { params })
}

export function getGuestbookMessages(params) {
  return api.get('/api/guestbook', { params })
}

export function addGuestbookMessage(data) {
  return api.post('/api/guestbook', data)
}

export function getAbout() {
  return api.get('/api/about')
}

export function toggleLike(articleId) {
  return api.post(`/api/articles/${articleId}/like`)
}

export function getArticleLikes(articleId) {
  return api.get(`/api/articles/${articleId}/likes`)
}

export function searchArticles(keyword, params = {}) {
  return api.get('/api/articles/search', { params: { keyword, ...params } })
}

export function getArchive() {
  return api.get('/api/articles/archive')
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
