<template>
  <div class="login-page">
    <section class="login-panel">
      <div class="brand-block">
        <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true">
          <path d="M4 4h16v16H4z" />
          <path d="M8 8h16v16H8z" />
        </svg>
        <div>
          <span>AtlasMind</span>
          <strong>R&D Agent Workbench</strong>
        </div>
      </div>
      <form class="login-form" @submit.prevent="doLogin">
        <label>
          <span>账号</span>
          <input v-model="form.username" autocomplete="username" required placeholder="username" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="form.password" type="password" autocomplete="current-password" required placeholder="password" />
        </label>
        <button class="primary-button" type="submit" :disabled="loading">
          {{ loading ? '登录中' : '进入工作台' }}
        </button>
        <p v-if="error" class="error-copy">{{ error }}</p>
      </form>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '../api/index.js'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const form = ref({ username: '', password: '' })

async function doLogin() {
  error.value = ''
  loading.value = true
  try {
    const response = await login(form.value)
    localStorage.setItem('atlasmind-token', response.data.data.token)
    router.push('/')
  } catch (err) {
    error.value = err.response?.data?.message || '登录失败，请检查账号和密码'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* Hallmark | macrostructure: Focused Login | tone: calm enterprise workspace | anchor hue: ink blue */
.login-page {
  display: grid;
  min-height: calc(100vh - 180px);
  place-items: center;
  padding: 30px 16px;
}

.login-panel {
  width: min(420px, 100%);
  padding: 26px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 20px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--atlas-border);
}

.logo-mark {
  width: 34px;
  height: 34px;
  fill: none;
  stroke: var(--atlas-primary);
  stroke-linejoin: round;
  stroke-width: 2;
}

.brand-block div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.brand-block span {
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.brand-block strong {
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 24px;
  line-height: 1.15;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.login-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: var(--atlas-text);
  font-size: 12px;
  font-weight: 800;
}

.login-form input {
  min-height: 42px;
  padding: 0 12px;
  color: var(--atlas-text);
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  outline: 0;
  font: inherit;
  font-weight: 400;
}

.login-form input:focus {
  border-color: var(--atlas-primary);
  box-shadow: 0 0 0 3px rgba(66, 111, 166, .12);
}

.primary-button {
  min-height: 42px;
  margin-top: 4px;
  color: #fff;
  background: var(--atlas-primary);
  border: 1px solid var(--atlas-primary);
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
}

.primary-button:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: .6;
}

.error-copy {
  margin: 0;
  color: #b35c56;
  font-size: 12px;
  line-height: 1.5;
}
</style>
