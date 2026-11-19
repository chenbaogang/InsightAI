<script setup lang="ts">
import { ref } from 'vue'
import { login, type Who } from '../auth'
const emit = defineEmits<{ (e: 'logged-in', who: Who): void }>()

const username = ref('')
const password = ref('')
const busy = ref(false)
const err = ref('')

async function submit() {
  if (busy.value) return
  if (!username.value.trim() || !password.value) {
    err.value = '请输入用户名和密码'
    return
  }
  busy.value = true
  err.value = ''
  try {
    const d = await login(username.value.trim(), password.value)
    password.value = ''
    emit('logged-in', d.user as Who)
  } catch (e: any) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="loginwrap">
    <form class="loginbox" @submit.prevent="submit">
      <h2>InsightAI 登录</h2>
      <label>用户名
        <input v-model="username" autocomplete="username" :disabled="busy" />
      </label>
      <label>密码
        <input v-model="password" type="password" autocomplete="current-password" :disabled="busy" />
      </label>
      <div v-if="err" class="loginerr">{{ err }}</div>
      <button type="submit" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</button>
      <p class="tip">账号与部门数据权限由管理员在「权限管理」中分配。</p>
    </form>
  </div>
</template>

<style scoped>
.loginwrap { display: flex; justify-content: center; padding-top: 8vh; }
.loginbox { width: 320px; display: flex; flex-direction: column; gap: 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 24px; }
.loginbox h2 { margin: 0 0 4px; font-size: 18px; color: #111827; }
.loginbox label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: #374151; }
.loginbox input { padding: 9px 10px; border: 1px solid #ccc; border-radius: 8px; font-size: 14px; }
.loginbox button { padding: 10px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-size: 14px; cursor: pointer; }
.loginbox button:disabled { opacity: .6; cursor: default; }
.loginerr { background: #fee2e2; border: 1px solid #fca5a5; color: #b91c1c; border-radius: 6px; padding: 6px 10px; font-size: 13px; }
.tip { color: #6b7280; font-size: 12px; margin: 0; }
</style>
