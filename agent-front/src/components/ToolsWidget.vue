<template>
  <div class="tools-widget" @mouseenter="showPanel = true" @mouseleave="showPanel = false">
    <button class="tools-trigger" :class="{ active: showPanel }" title="小工具">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
    <transition name="panel">
      <div v-if="showPanel" class="tools-panel">
        <div class="panel-arrow"></div>
        <div class="panel-header">小工具</div>
        <div
          v-for="tool in tools"
          :key="tool.id"
          class="tool-item"
          @click="openTool(tool)"
        >
          <span class="tool-icon">{{ tool.icon }}</span>
          <div class="tool-info">
            <div class="tool-name">{{ tool.name }}</div>
            <div class="tool-desc">{{ tool.description }}</div>
          </div>
        </div>
      </div>
    </transition>

    <!-- Modal -->
    <Teleport to="body">
      <transition name="modal">
        <div v-if="activeTool" class="modal-overlay" @click.self="closeModal">
          <div class="modal-container">
            <div class="modal-header">
              <span class="modal-title">{{ activeTool.name }}</span>
              <button class="modal-close" @click="closeModal">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
            <div class="modal-body">
              <div v-if="iframeLoading" class="iframe-loading">
                <div class="loading-spinner"></div>
                <span>{{ loadingText }}</span>
              </div>
              <div v-if="loadError" class="iframe-error">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                <p>工具加载失败</p>
                <span>{{ loadError }}</span>
                <button class="retry-btn" @click="retryLoad">重试</button>
              </div>
              <iframe
                v-show="activeTool && !loadError"
                :src="activeTool?.devUrl"
                class="tool-iframe"
                @load="onIframeLoad"
                @error="onIframeError"
                frameborder="0"
              ></iframe>
            </div>
          </div>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { tools } from '../config/tools.js'

const showPanel = ref(false)
const activeTool = ref(null)
const iframeLoading = ref(false)
const loadingText = ref('加载中...')
const loadError = ref('')
let loadTimer = null
let progressTimer = null

function openTool(tool) {
  activeTool.value = tool
  iframeLoading.value = true
  loadingText.value = '加载中...'
  loadError.value = ''
  showPanel.value = false

  // Simulate progress updates
  let dots = 0
  progressTimer = setInterval(() => {
    dots = (dots + 1) % 4
    loadingText.value = '加载中' + '.'.repeat(dots)
  }, 400)

  // Timeout fallback after 20s
  loadTimer = setTimeout(() => {
    if (iframeLoading.value) {
      clearInterval(progressTimer)
      loadingText.value = ''
      iframeLoading.value = false
      loadError.value = '连接超时，请确认 ' + tool.name + ' 服务已启动（端口 ' + (tool.devUrl || '').split(':').pop() + '）'
    }
  }, 20000)
}

function onIframeLoad() {
  clearTimeout(loadTimer)
  clearInterval(progressTimer)
  iframeLoading.value = false
  loadError.value = ''
}

function onIframeError() {
  clearTimeout(loadTimer)
  clearInterval(progressTimer)
  iframeLoading.value = false
  loadError.value = '无法连接到工具服务，请检查服务是否已启动'
}

function retryLoad() {
  if (activeTool.value) {
    openTool(activeTool.value)
  }
}

function closeModal() {
  clearTimeout(loadTimer)
  clearInterval(progressTimer)
  activeTool.value = null
  iframeLoading.value = false
  loadError.value = ''
}

onUnmounted(() => {
  clearTimeout(loadTimer)
  clearInterval(progressTimer)
})
</script>

<style scoped>
.tools-widget {
  position: fixed; bottom: 84px; right: 32px; z-index: 101;
}

/* Trigger Button */
.tools-trigger {
  width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: #909399; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative; z-index: 2;
}
.tools-trigger:hover, .tools-trigger.active {
  transform: translateY(-2px);
  color: #426fa6;
  box-shadow: 0 4px 12px rgba(64,158,255,0.15), 0 8px 24px rgba(0,0,0,0.08);
}

/* Panel */
.tools-panel {
  position: absolute; bottom: 50px; right: 0;
  width: 280px; background: rgba(255,255,255,0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.6);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08), 0 8px 32px rgba(0,0,0,0.1);
  padding: 8px;
  overflow: hidden;
}
.panel-arrow {
  position: absolute; bottom: -6px; right: 14px;
  width: 12px; height: 12px;
  background: rgba(255,255,255,0.92);
  border-right: 1px solid rgba(255,255,255,0.6);
  border-bottom: 1px solid rgba(255,255,255,0.6);
  transform: rotate(45deg);
}
.panel-header {
  font-size: 12px; color: #909399; font-weight: 500;
  padding: 6px 10px 8px;
  border-bottom: 1px solid rgba(0,0,0,0.05);
  margin-bottom: 4px;
}

.tool-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px; border-radius: 8px; cursor: pointer;
  transition: background 0.15s;
}
.tool-item:hover { background: rgba(64,158,255,0.06); }
.tool-icon { font-size: 22px; flex-shrink: 0; line-height: 1; }
.tool-info { flex: 1; min-width: 0; }
.tool-name { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 2px; }
.tool-desc { font-size: 12px; color: #909399; line-height: 1.4; }

/* Transitions */
.panel-enter-active { transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); }
.panel-leave-active { transition: all 0.15s ease; }
.panel-enter-from, .panel-leave-to {
  opacity: 0; transform: translateY(8px) scale(0.95);
}

/* Modal */
.modal-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.45);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
}
.modal-container {
  width: 90vw; height: 90vh;
  background: #fff; border-radius: 16px;
  overflow: hidden; display: flex; flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.12), 0 16px 64px rgba(0,0,0,0.16);
}
.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #e8ecf0;
  flex-shrink: 0;
}
.modal-title { font-size: 16px; font-weight: 600; color: #303133; }
.modal-close {
  width: 32px; height: 32px; border: none; border-radius: 8px;
  background: transparent; color: #909399; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.modal-close:hover { background: #f5f7fa; color: #303133; }
.modal-body { flex: 1; min-height: 0; position: relative; }
.tool-iframe { width: 100%; height: 100%; border: none; }

.iframe-loading {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; color: #909399; font-size: 14px;
}
.loading-spinner {
  width: 32px; height: 32px; border: 3px solid #e8ecf0;
  border-top-color: #426fa6; border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.iframe-error {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; color: #909399; font-size: 14px; text-align: center; padding: 20px;
}
.iframe-error p { font-size: 16px; font-weight: 600; color: #606266; margin: 0; }
.iframe-error span { font-size: 13px; color: #c0c4cc; }
.retry-btn {
  margin-top: 8px; padding: 6px 20px; border: 1px solid #426fa6; border-radius: 8px;
  background: #fff; color: #426fa6; cursor: pointer; font-size: 14px;
  transition: all 0.15s;
}
.retry-btn:hover { background: #ecf5ff; }

.modal-enter-active { transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.modal-leave-active { transition: all 0.2s ease; }
.modal-enter-from { opacity: 0; }
.modal-enter-from .modal-container { transform: scale(0.95); opacity: 0; }
.modal-leave-to { opacity: 0; }

/* Dark Mode */
[data-theme="dark"] .tools-trigger {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(255,255,255,0.08);
  color: #94a3b8;
}
[data-theme="dark"] .tools-trigger:hover { color: #60a5fa; }
[data-theme="dark"] .tools-panel {
  background: rgba(30, 41, 59, 0.94);
  border-color: rgba(255,255,255,0.08);
}
[data-theme="dark"] .panel-arrow {
  background: rgba(30, 41, 59, 0.94);
  border-color: rgba(255,255,255,0.08);
}
[data-theme="dark"] .panel-header {
  color: #64748b;
  border-bottom-color: rgba(255,255,255,0.06);
}
[data-theme="dark"] .tool-item:hover { background: rgba(64,158,255,0.1); }
[data-theme="dark"] .tool-name { color: #e2e8f0; }
[data-theme="dark"] .tool-desc { color: #94a3b8; }

[data-theme="dark"] .modal-overlay { background: rgba(0,0,0,0.6); }
[data-theme="dark"] .modal-container { background: #1e293b; }
[data-theme="dark"] .modal-header { border-bottom-color: rgba(255,255,255,0.08); }
[data-theme="dark"] .modal-title { color: #e2e8f0; }
[data-theme="dark"] .modal-close:hover { background: rgba(255,255,255,0.06); color: #e2e8f0; }
[data-theme="dark"] .iframe-error p { color: #cbd5e1; }
[data-theme="dark"] .iframe-error span { color: #64748b; }
[data-theme="dark"] .retry-btn { background: #1e293b; }
</style>
