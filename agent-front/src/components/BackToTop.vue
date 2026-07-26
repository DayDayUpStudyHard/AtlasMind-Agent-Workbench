<template>
  <transition name="fade">
    <button v-show="visible" class="back-to-top" @click="scrollToTop" title="回到顶部">
      <svg class="progress-ring" width="40" height="40" viewBox="0 0 40 40">
        <circle class="ring-bg" cx="20" cy="20" r="16" fill="none" stroke-width="2.5" />
        <circle
          class="ring-progress"
          cx="20" cy="20" r="16" fill="none" stroke-width="2.5"
          :stroke-dasharray="circumference"
          :stroke-dashoffset="progressOffset"
        />
      </svg>
      <svg class="arrow-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="18 15 12 9 6 15"/>
      </svg>
    </button>
  </transition>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const visible = ref(false)
const scrollPercent = ref(0)
const circumference = 2 * Math.PI * 16

const progressOffset = computed(() => {
  return circumference - (scrollPercent.value / 100) * circumference
})

function onScroll() {
  visible.value = window.scrollY > 300
  const scrollTop = window.scrollY
  const docHeight = document.documentElement.scrollHeight - window.innerHeight
  scrollPercent.value = docHeight > 0 ? Math.min(100, Math.round((scrollTop / docHeight) * 100)) : 0
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<style scoped>
.back-to-top {
  position: fixed; bottom: 32px; right: 32px; z-index: 100;
  width: 40px; height: 40px; border-radius: 50%;
  border: none; padding: 0;
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.back-to-top:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(64,158,255,0.15), 0 8px 24px rgba(0,0,0,0.08);
}

.progress-ring {
  position: absolute; inset: 0;
  transform: rotate(-90deg);
}
.ring-bg {
  stroke: #e8ecf0;
}
.ring-progress {
  stroke: var(--atlas-primary);
  stroke-linecap: round;
  transition: stroke-dashoffset 0.15s linear;
}

.arrow-icon {
  position: relative; z-index: 1; color: var(--atlas-primary);
}

.fade-enter-active, .fade-leave-active { transition: all 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(8px); }
</style>
