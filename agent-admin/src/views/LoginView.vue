<template>
  <div class="login-page">
    <div class="login-card">
      <div class="card-inner">
        <div class="logo">
          <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true">
            <path d="M4 4h16v16H4z" />
            <path d="M8 8h16v16H8z" />
          </svg>
          <span class="logo-text">AtlasMind</span>
        </div>
        <p class="subtitle">管理后台</p>

        <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="doLogin" class="login-form">
          <el-form-item prop="username">
            <el-input
              v-model="form.username" placeholder="用户名" size="large"
              :prefix-icon="UserIcon"
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password" type="password" placeholder="密码" size="large"
              show-password :prefix-icon="LockIcon"
              @keyup.enter="doLogin"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="doLogin" :loading="loading" size="large" class="login-btn">
              <span v-if="!loading">登 录</span>
            </el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, h } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user.js'

const UserIcon = h('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2, innerHTML: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>' })
const LockIcon = h('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2, innerHTML: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>' })

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const formRef = ref(null)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function doLogin() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await userStore.login(form.username, form.password)
    router.push('/')
  } catch {} finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh; display: flex; justify-content: center; align-items: center;
  perspective: 1000px;
}

.login-card {
  width: 400px;
  animation: cardEnter 0.7s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes cardEnter {
  from {
    opacity: 0;
    transform: translateY(40px) scale(0.94);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.card-inner {
  background: rgba(255,255,255,0.75);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 18px;
  padding: 48px 40px 40px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.04), 0 12px 40px rgba(0,0,0,0.08);
  transition: box-shadow 0.3s;
}
.card-inner:hover {
  box-shadow: 0 4px 8px rgba(0,0,0,0.06), 0 16px 56px rgba(0,0,0,0.12);
}

/* Logo */
.logo {
  text-align: center;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  margin-bottom: 8px;
  animation: logoReveal 0.6s ease both;
  animation-delay: 0.3s;
}

@keyframes logoReveal {
  from { opacity: 0; transform: scale(0.8); }
  to { opacity: 1; transform: scale(1); }
}

.logo-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: #426fa6; color: #fff;
  font-size: 18px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  animation: iconPulse 2s ease-in-out infinite;
  animation-delay: 1s;
}

.logo-mark {
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  fill: none;
  stroke: #426fa6;
  stroke-width: 2;
  stroke-linejoin: round;
}

@keyframes iconPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(64,158,255,0.3); }
  50% { box-shadow: 0 0 0 8px rgba(64,158,255,0); }
}

.logo-text { font-size: 22px; font-weight: 700; color: #303133; }

.subtitle {
  text-align: center; color: #909399; font-size: 13px;
  margin-bottom: 36px;
  animation: fadeText 0.5s ease both;
  animation-delay: 0.5s;
}

@keyframes fadeText {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Form */
.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
  animation: fieldSlideIn 0.5s ease both;
}
.login-form :deep(.el-form-item:nth-child(1)) { animation-delay: 0.55s; }
.login-form :deep(.el-form-item:nth-child(2)) { animation-delay: 0.65s; }
.login-form :deep(.el-form-item:nth-child(3)) { animation-delay: 0.75s; }

@keyframes fieldSlideIn {
  from { opacity: 0; transform: translateX(-12px); }
  to { opacity: 1; transform: translateX(0); }
}

.login-btn {
  width: 100%; height: 44px !important;
  font-size: 15px !important; font-weight: 600 !important;
  border-radius: 8px !important;
  margin-top: 4px;
  box-shadow: 0 4px 14px rgba(64,158,255,0.25);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.login-btn:hover {
  box-shadow: 0 6px 20px rgba(64,158,255,0.35);
  transform: translateY(-1px);
}

/* Typewriter effect for title */
.logo-text {
  overflow: hidden;
  white-space: nowrap;
  animation: typing 1s steps(8, end);
}

@keyframes typing {
  from { max-width: 0; }
  to { max-width: 200px; }
}

/* Dark mode */
[data-theme="dark"] .login-page { background: transparent; }
[data-theme="dark"] .card-inner {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(255,255,255,0.08);
}
[data-theme="dark"] .logo-text { color: #e2e8f0; }
[data-theme="dark"] .subtitle { color: #94a3b8; }
[data-theme="dark"] .logo-mark { stroke: #8fb1d8; }

/* Hallmark | quiet login surface */
.login-page {
  background: #f3f6fa;
}

.card-inner {
  background: #fbfcfe;
  border: 1px solid #d4dde8;
  border-radius: 4px;
  box-shadow: 0 12px 28px rgba(31, 45, 61, 0.08);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.logo-text {
  font-family: Georgia, 'Times New Roman', serif;
}

.login-btn {
  background: #426fa6 !important;
  border-color: #426fa6 !important;
  box-shadow: none;
}

.login-btn:hover {
  background: #315987 !important;
  border-color: #315987 !important;
  box-shadow: none;
  transform: none;
}

[data-theme="dark"] .login-page {
  background: #152235;
}

[data-theme="dark"] .card-inner {
  background: #1d2d42;
  border-color: rgba(218, 229, 241, 0.14);
  box-shadow: none;
}
</style>
