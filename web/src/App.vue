<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AccessControl from './views/AccessControl.vue'
import CodeDict from './views/CodeDict.vue'
import Login from './views/Login.vue'
import MetricDefs from './views/MetricDefs.vue'
import { authHeaders, errText, fetchMe, handleUnauthorized, logout, setUnauthorizedHandler, type Who } from './auth'

interface ChartSpec { type: string; x: number; series: number[] }
interface Msg {
  role: 'user' | 'ai'
  text: string
  question?: string
  columns?: string[]
  rows?: any[][]
  chart?: ChartSpec
  sqlRaw?: string
  sqlGuarded?: string
  status?: string
  truncated?: boolean
  maskedColumns?: string[]
  decodedColumns?: string[]
}

// crypto.randomUUID 仅在安全上下文（https / localhost）可用，
// http://192.168.0.18 这类局域网访问需回退到 getRandomValues 生成 v4 UUID
function genId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const b = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(b)
  } else {
    for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  }
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

const messages = ref<Msg[]>([])
const input = ref('')
const loading = ref(false)
let chartInst: echarts.ECharts | null = null

const sessionId = ref(localStorage.getItem('insightai_sid') || genId())
localStorage.setItem('insightai_sid', sessionId.value)

const who = ref<Who | null>(null)
const isAdmin = computed(() => !!who.value?.admin)
setUnauthorizedHandler(() => { who.value = null })

interface SessionInfo { id: string; title: string; summary: string; turns: number; created_at: string; updated_at: string }
const sessions = ref<SessionInfo[]>([])
const renamingId = ref('')
const renameText = ref('')
const sideErr = ref('')

function headers() {
  return authHeaders()
}

/** 统一请求：带 Bearer token，登录态失效时回到登录页 */
async function apiCall(path: string, init: RequestInit = {}) {
  const r = await fetch(path, { ...init, headers: { ...headers(), ...(init.headers || {}) } })
  handleUnauthorized(r.status)
  if (!r.ok) throw new Error(errText(await r.json().catch(() => ({})), r.status))
  return r.json()
}

const apiGet = (path: string) => apiCall(path)
const apiPost = (path: string, body: object) => apiCall(path, { method: 'POST', body: JSON.stringify(body) })
const apiPatch = (path: string, body: object) => apiCall(path, { method: 'PATCH', body: JSON.stringify(body) })
const apiDelete = (path: string) => apiCall(path, { method: 'DELETE' })

async function loadSessions() {
  try {
    sessions.value = await apiGet('/api/sessions')
    sideErr.value = ''
  } catch (e: any) {
    sideErr.value = `会话列表加载失败: ${e.message}`
  }
}

function pickSession(id: string) {
  sessionId.value = id
  localStorage.setItem('insightai_sid', id)
  messages.value = []
  chartInst?.dispose()
  chartInst = null
}

async function resumeSession() {
  const cur = sessions.value.find((s) => s.id === sessionId.value)
  if (cur) {
    await loadHistory().catch(() => {})
    return
  }
  if (sessions.value.length) {
    pickSession(sessions.value[0].id)
    await loadHistory().catch(() => {})
    return
  }
  await newSession()
}

async function openSession(s: SessionInfo) {
  if (s.id === sessionId.value) return
  pickSession(s.id)
  try {
    await loadHistory()
  } catch (e: any) {
    sideErr.value = `历史加载失败: ${e.message}`
  }
}

async function newSession() {
  try {
    const d = await apiPost('/api/sessions', {})
    pickSession(d.id)
    sideErr.value = ''
  } catch (e: any) {
    pickSession(genId())
    sideErr.value = `新建会话失败: ${e.message}`
  }
  await loadSessions()
}

function startRename(s: SessionInfo) {
  renamingId.value = s.id
  renameText.value = s.title || '未命名会话'
}

async function doRename() {
  const id = renamingId.value
  if (!id) return
  renamingId.value = ''
  const title = renameText.value.trim()
  if (!title) return
  try {
    await apiPatch(`/api/sessions/${encodeURIComponent(id)}`, { title })
  } catch (e: any) {
    sideErr.value = `重命名失败: ${e.message}`
  }
  await loadSessions()
}

async function removeSession(s: SessionInfo) {
  const name = s.title || '未命名会话'
  if (!confirm(`删除会话「${name}」？该会话的历史与已归档口径会一并清除，不可恢复。`)) return
  const wasCurrent = s.id === sessionId.value
  try {
    await apiDelete(`/api/sessions/${encodeURIComponent(s.id)}`)
    sideErr.value = ''
  } catch (e: any) {
    sideErr.value = `删除失败: ${e.message}`
    return
  }
  await loadSessions()
  if (!wasCurrent) return
  const next = sessions.value[0]
  if (next) {
    pickSession(next.id)
    await loadHistory().catch(() => {})
  } else {
    await newSession()
  }
}

async function onLoggedIn(w: Who) {
  who.value = w
  await loadSessions()
  await resumeSession()
}

async function doLogout() {
  await logout()
  who.value = null
  view.value = 'chat'
  messages.value = []
  sessions.value = []
}

const pwdOpen = ref(false)
const pwdDone = ref(false)
const pwdBusy = ref(false)
const pwdOld = ref('')
const pwdNew = ref('')
const pwdNew2 = ref('')
const pwdMsg = ref('')

function openPwd() {
  pwdOpen.value = true
  pwdDone.value = false
  pwdBusy.value = false
  pwdOld.value = pwdNew.value = pwdNew2.value = pwdMsg.value = ''
}

/** 改口令的 401 是「旧口令错了」，不能走统一的掉线处理，所以这里不经过 apiCall */
async function submitPwd() {
  pwdMsg.value = ''
  if (pwdNew.value !== pwdNew2.value) {
    pwdMsg.value = '两次输入的新口令不一致'
    return
  }
  pwdBusy.value = true
  try {
    const r = await fetch('/api/auth/password', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ old_password: pwdOld.value, new_password: pwdNew.value }),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) {
      pwdMsg.value = errText(d, r.status)
      return
    }
    pwdOld.value = pwdNew.value = pwdNew2.value = ''
    pwdDone.value = true
    pwdMsg.value = d.message || '口令已修改，请重新登录'
  } catch (e) {
    pwdMsg.value = `请求失败：${(e as Error).message}`
  } finally {
    pwdBusy.value = false
  }
}

async function loadHistory() {
  const turns = await apiGet(`/api/history/${sessionId.value}`)
  messages.value = turns.flatMap((t) => [
    { role: 'user', text: t.question } as Msg,
    {
      role: 'ai',
      text: t.answer ?? '',
      columns: t.columns,
      rows: t.rows,
      chart: t.chart,
      sqlRaw: t.sql_raw,
      sqlGuarded: t.sql_guarded,
      truncated: t.truncated,
      maskedColumns: t.masked_columns,
      decodedColumns: t.decoded_columns,
    } as Msg,
  ])
  renderChart()
}

function exportCsv(m: Msg) {
  if (!m.columns?.length || !m.rows?.length) return
  const esc = (v: any) => `"${String(v ?? '').replaceAll('"', '""')}"`
  const csv = [m.columns, ...m.rows].map((r) => r.map(esc).join(',')).join('\r\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `insightai_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

/* ---------- 语义层管理面板（码表 / 敏感列 / 行级权限列）---------- */
interface TableInfo { name: string; comment: string; domain: string; dept_column: string | null; n_cols: number; n_enum: number; n_sensitive: number }
interface ColInfo { name: string; data_type: string; comment: string; enum_dict: Record<string, string>; is_sensitive: boolean; code_dict: string | null; effective_enum: Record<string, string> }
interface CodeDictOpt { code: string; name: string; entries: Record<string, string> }

const view = ref<'chat' | 'meta' | 'rbac' | 'codedict' | 'metric'>('chat')
const tables = ref<TableInfo[]>([])
const curTable = ref('')
const tableFilter = ref('')
const filteredTables = computed(() => {
  const q = tableFilter.value.trim().toLowerCase()
  const list = q
    ? tables.value.filter((t) => t.name.toLowerCase().includes(q) || (t.comment || '').toLowerCase().includes(q))
    : tables.value
  if (curTable.value && !list.some((t) => t.name === curTable.value)) {
    const cur = tables.value.find((t) => t.name === curTable.value)
    if (cur) return [cur, ...list]
  }
  return list
})
const cols = ref<ColInfo[]>([])
const deptCol = ref('')
const tableComment = ref('')
const metaBusy = ref(false)
const metaMsg = ref('')
const syncBusy = ref(false)
const syncPrefixes = ref('')
const editCol = ref<ColInfo | null>(null)
const enumText = ref('')
const enumMsg = ref('')
const editComment = ref('')
const codeDicts = ref<CodeDictOpt[]>([])
const editCodeDict = ref('')

const metaPut = (path: string, body: object) => apiCall(path, { method: 'PUT', body: JSON.stringify(body) })

function enumToText(d: Record<string, string>) {
  return Object.entries(d || {}).map(([k, v]) => `${k}=${v}`).join('\n')
}

function parseEnum(text: string): { dict: Record<string, string>; bad: string[] } {
  const dict: Record<string, string> = {}
  const bad: string[] = []
  for (const line of text.split(/\r?\n/)) {
    const s = line.trim()
    if (!s) continue
    const i = s.indexOf('=')
    if (i <= 0) bad.push(s)
    else dict[s.slice(0, i).trim()] = s.slice(i + 1).trim()
  }
  return { dict, bad }
}

function enumSummary(c: ColInfo) {
  const d = c.effective_enum || {}
  const ks = Object.keys(d)
  if (!ks.length) return '—'
  const txt = ks.slice(0, 3).map((k) => `${k}=${d[k]}`).join('，')
  const base = ks.length > 3 ? `${txt} 等${ks.length}项` : txt
  return c.code_dict ? `${base}（全局${c.code_dict}）` : base
}

function refreshCounts() {
  const t = tables.value.find((x) => x.name === curTable.value)
  if (!t) return
  t.n_enum = cols.value.filter((c) => Object.keys(c.effective_enum || {}).length).length
  t.n_sensitive = cols.value.filter((c) => c.is_sensitive).length
  t.dept_column = deptCol.value || null
}

function toggleView(target: 'meta' | 'rbac' | 'codedict' | 'metric') {
  if (view.value === target) {
    view.value = 'chat'
    return
  }
  if (target === 'meta') openMeta()
  else view.value = target
}

async function openMeta() {
  view.value = 'meta'
  metaBusy.value = true
  metaMsg.value = ''
  try {
    tables.value = await apiGet('/api/meta/tables')
    codeDicts.value = await apiGet('/api/code-dicts')
    if (!curTable.value || !tables.value.some((t) => t.name === curTable.value)) {
      curTable.value = tables.value[0]?.name ?? ''
    }
    await loadCols()
  } catch (e: any) {
    metaMsg.value = `加载失败: ${e.message}`
  } finally {
    metaBusy.value = false
  }
}

async function loadCols() {
  cols.value = await apiGet(`/api/meta/tables/${encodeURIComponent(curTable.value)}/columns`)
  const t = tables.value.find((t) => t.name === curTable.value)
  deptCol.value = t?.dept_column ?? ''
  tableComment.value = t?.comment ?? ''
  refreshCounts()
  metaMsg.value = ''
}

async function syncMeta() {
  syncBusy.value = true
  metaMsg.value = '正在启动同步…'
  try {
    const prefixes = syncPrefixes.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    await apiPost('/api/meta/sync', { prefixes })
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000))
      const st = await apiGet('/api/meta/sync/status')
      metaMsg.value = st.message
      if (st.status === 'done') {
        await openMeta()
        metaMsg.value = st.message
        break
      }
      if (st.status === 'error' || st.status === 'idle') break
    }
  } catch (e: any) {
    metaMsg.value = `同步失败: ${e.message}`
  } finally {
    syncBusy.value = false
  }
}

function onSens(c: ColInfo, e: Event) {
  toggleSensitive(c, !!(e.target as HTMLInputElement).checked)
}

async function toggleSensitive(c: ColInfo, v: boolean) {
  try {
    await metaPut(`/api/meta/columns/${encodeURIComponent(curTable.value)}/${encodeURIComponent(c.name)}`, { is_sensitive: v })
    c.is_sensitive = v
  } catch (e: any) {
    c.is_sensitive = !v
    metaMsg.value = `敏感标记保存失败: ${e.message}`
  }
  refreshCounts()
}

async function saveTable() {
  try {
    await metaPut(`/api/meta/tables/${encodeURIComponent(curTable.value)}`, { dept_column: deptCol.value })
    refreshCounts()
    metaMsg.value = deptCol.value ? `行级权限列已设为 ${deptCol.value}，下次查询即生效` : '已清除行级权限列'
  } catch (e: any) {
    metaMsg.value = `表设置保存失败: ${e.message}`
  }
}

async function saveTableComment() {
  try {
    const r = await metaPut(`/api/meta/tables/${encodeURIComponent(curTable.value)}`, { comment: tableComment.value })
    const t = tables.value.find((x) => x.name === curTable.value)
    if (t) t.comment = r.comment
    tableComment.value = r.comment
    metaMsg.value = '表注释已保存，语义召回向量已同步更新；同步元数据不会覆盖已有注释'
  } catch (e: any) {
    metaMsg.value = `表注释保存失败: ${e.message}`
  }
}

function openEditor(c: ColInfo) {
  editCol.value = c
  enumText.value = enumToText(c.enum_dict)
  editCodeDict.value = c.code_dict || ''
  editComment.value = c.comment || ''
  enumMsg.value = ''
}

async function pullCodes() {
  if (!editCol.value) return
  metaBusy.value = true
  try {
    const vals: string[] = (await apiGet(`/api/meta/probe/${encodeURIComponent(curTable.value)}/${encodeURIComponent(editCol.value.name)}`)).values
    const dict = parseEnum(enumText.value).dict
    let added = 0
    for (const v of vals) {
      if (!(v in dict)) { dict[v] = ''; added++ }
    }
    enumText.value = enumToText(dict)
    enumMsg.value = `拉取 ${vals.length} 个码值，新增 ${added} 行待填含义`
  } catch (e: any) {
    enumMsg.value = `码值拉取失败: ${e.message}`
  } finally {
    metaBusy.value = false
  }
}

async function saveEnum() {
  const c = editCol.value
  if (!c) return
  const { dict, bad } = parseEnum(enumText.value)
  if (bad.length) { enumMsg.value = `以下行缺少“码值=含义”：${bad.slice(0, 3).join(' / ')}`; return }
  try {
    const r = await metaPut(`/api/meta/columns/${encodeURIComponent(curTable.value)}/${encodeURIComponent(c.name)}`, { enum_dict: dict, code_dict: editCodeDict.value, comment: editComment.value })
    c.enum_dict = dict
    c.code_dict = r.code_dict
    c.effective_enum = r.effective_enum
    c.comment = r.comment
    refreshCounts()
    editCol.value = null
  } catch (e: any) {
    enumMsg.value = `保存失败: ${e.message}`
  }
}

async function clearEnum() {
  const c = editCol.value
  if (!c) return
  try {
    const r = await metaPut(`/api/meta/columns/${encodeURIComponent(curTable.value)}/${encodeURIComponent(c.name)}`, { enum_dict: {} })
    c.enum_dict = {}
    c.effective_enum = r.effective_enum
    refreshCounts()
    editCol.value = null
  } catch (e: any) {
    enumMsg.value = `清空失败: ${e.message}`
  }
}

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return
  messages.value.push({ role: 'user', text: q })
  input.value = ''
  loading.value = true
  try {
    const d = await apiPost('/api/chat', { question: q, session_id: sessionId.value })
    messages.value.push({
      role: 'ai',
      text: d.answer ?? `[${d.status}] ${d.error ?? '无结果'}`,
      question: q,
      columns: d.columns,
      rows: d.rows,
      chart: d.chart,
      sqlRaw: d.sql_raw,
      sqlGuarded: d.sql_guarded,
      status: d.status,
      truncated: d.truncated,
      maskedColumns: d.masked_columns,
      decodedColumns: d.decoded_columns,
    })
  } catch (e: any) {
    messages.value.push({ role: 'ai', text: `请求失败: ${e.message}` })
  } finally {
    loading.value = false
    await renderChart()
    scrollBottom()
    await loadSessions()
  }
}

function buildOption(m: Msg): echarts.EChartsOption | null {
  if (!m.chart || !m.columns || !m.rows || !m.rows.length) return null
  const { chart, columns, rows } = m
  if (chart.type === 'table' || chart.type === 'kpi') return null
  const cats = rows.map((r) => String(r[chart.x]))
  if (chart.type === 'pie') {
    return {
      tooltip: {},
      series: [{
        type: 'pie', radius: '60%',
        data: rows.map((r) => ({ name: String(r[chart.x]), value: r[chart.series[0]] })),
      }],
    }
  }
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: cats },
    yAxis: { type: 'value' },
    series: chart.series.map((si) => ({
      name: columns[si],
      type: chart.type === 'line' ? 'line' : 'bar',
      data: rows.map((r) => r[si]),
    })),
  }
}

async function renderChart() {
  await nextTick()
  const el = document.querySelector('.chart') as HTMLDivElement | null
  const last = [...messages.value].reverse().find((m) => m.role === 'ai' && m.chart)
  if (!el || !last) return
  const opt = buildOption(last)
  if (!opt) { chartInst?.dispose(); chartInst = null; return }
  if (!chartInst || chartInst.getDom() !== el) {
    chartInst?.dispose()
    chartInst = echarts.init(el, null, { width: el.clientWidth || 640, height: el.clientHeight || 320 })
  }
  chartInst.setOption(opt, true)
}

const msglist = ref<HTMLDivElement | null>(null)

async function scrollBottom(instant = false) {
  await nextTick()
  const el = msglist.value
  if (el) el.scrollTo({ top: el.scrollHeight, behavior: instant ? 'auto' : 'smooth' })
}

watch(() => messages.value.length, () => scrollBottom())
watch(loading, (v) => { if (v) scrollBottom() })
watch(sessionId, () => scrollBottom(true))

onMounted(async () => {
  who.value = await fetchMe()
  if (!who.value) return
  await loadSessions()
  await resumeSession()
})
</script>

<template>
  <Login v-if="!who" @logged-in="onLoggedIn" />
  <div v-else class="page">
    <header class="topbar">
      <div class="brand" title="回到对话" @click="view = 'chat'">
        <span class="logo">IA</span>
        <b>InsightAI</b>
        <small>智能数据分析</small>
      </div>
      <nav class="navbtns">
        <button :class="['btn2', { on: view === 'chat' }]" @click="view = 'chat'">对话</button>
        <template v-if="isAdmin">
          <button :class="['btn2', { on: view === 'meta' }]" @click="toggleView('meta')">语义管理</button>
          <button :class="['btn2', { on: view === 'codedict' }]" @click="toggleView('codedict')">全局码值</button>
          <button :class="['btn2', { on: view === 'metric' }]" @click="toggleView('metric')">指标口径</button>
          <button :class="['btn2', { on: view === 'rbac' }]" @click="toggleView('rbac')">权限管理</button>
        </template>
      </nav>
      <span class="spacer"></span>
      <span class="whoami">
        {{ who.display_name || who.username }}
        <em v-if="who.dept_name">· {{ who.dept_name }}</em>
        <em v-if="isAdmin">· 管理员</em>
        <em v-else-if="who.data_values && who.data_values.length">· {{ who.data_values.length }} 个单位码</em>
      </span>
      <button class="btn2" @click="openPwd">修改口令</button>
      <button class="btn2" @click="doLogout">退出</button>
    </header>

    <div class="workspace">
      <template v-if="view === 'chat'">
        <aside class="sidelist">
          <div class="sidehead">
            <b>会话</b>
            <button class="btn2" @click="newSession">＋ 新建</button>
          </div>
          <p v-if="sideErr" class="sideerr">{{ sideErr }}</p>
          <ul>
            <li v-for="s in sessions" :key="s.id" :class="{ cur: s.id === sessionId }">
              <input v-if="renamingId === s.id"
                     v-model="renameText" class="renamein" autofocus
                     @keyup.enter="doRename" @blur="doRename" />
              <template v-else>
                <a @click="openSession(s)">{{ s.title || '未命名会话' }}</a>
                <small>{{ s.turns }} 轮<em v-if="s.summary"> · 已归档口径</em></small>
                <span class="sideops">
                  <button class="btn2" @click="startRename(s)">重命名</button>
                  <button class="btn2" @click="removeSession(s)">删除</button>
                </span>
              </template>
            </li>
          </ul>
        </aside>
        <div class="chatpane">
          <div ref="msglist" class="msglist">
            <div class="msginner">
              <div v-if="!messages.length && !loading" class="emptystate">
                <div class="biglogo">IA</div>
                <h2>用自然语言查询业务数据</h2>
                <p>自动生成 SQL · 部门行级权限 · 敏感脱敏 · 码值翻译</p>
                <div class="examples">
                  <span>按单位统计学籍数量</span>
                  <span>休学类的学籍异动有多少条</span>
                  <span>教职工总人数</span>
                </div>
              </div>
              <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
                <template v-if="m.role === 'user'">{{ m.text }}</template>
                <template v-else>
                  <p class="answer">{{ m.text }}</p>
                  <p v-if="m.maskedColumns?.length || m.decodedColumns?.length" class="presentnote">
                    <span v-if="m.maskedColumns?.length">敏感列已脱敏：{{ m.maskedColumns.join('、') }}</span>
                    <span v-if="m.decodedColumns?.length">码值已翻译为含义：{{ m.decodedColumns.join('、') }}</span>
                  </p>
                  <div v-if="m.chart && m.chart.type !== 'table' && m.chart.type !== 'kpi' && i === messages.length - 1"
                       class="chart"></div>
                  <table v-if="m.columns && m.rows && m.rows.length && (m.chart?.type === 'table' || m.chart?.type === 'kpi')">
                    <thead><tr><th v-for="c in m.columns" :key="c">{{ c }}</th></tr></thead>
                    <tbody><tr v-for="(r, ri) in m.rows.slice(0, 50)" :key="ri"><td v-for="(v, ci) in r" :key="ci">{{ v }}</td></tr></tbody>
                  </table>
                  <button v-if="m.rows && m.rows.length" class="btn2" @click="exportCsv(m)">导出CSV</button>
                  <details v-if="m.sqlRaw">
                    <summary>SQL（生成 → 守卫改写后）</summary>
                    <pre class="raw">{{ m.sqlRaw }}</pre>
                    <pre class="guarded">{{ m.sqlGuarded }}</pre>
                  </details>
                </template>
              </div>
              <div v-if="loading" class="msg ai"><span class="typing"><i></i><i></i><i></i>查询中…</span></div>
            </div>
          </div>
          <div class="composer">
            <div class="composerbar">
              <input v-model="input" placeholder="输入问题，例如：按单位统计学籍数量" @keyup.enter="send" />
              <button :disabled="loading" @click="send">提问</button>
            </div>
          </div>
        </div>
      </template>

      <main v-else-if="view === 'meta'" class="adminpane">
        <div class="admininner meta">
      <div v-if="metaMsg" class="metamsg">{{ metaMsg }}</div>
      <div class="metabar">
        <label>表
          <input v-model="tableFilter" class="tblfilter" placeholder="筛选表名/注释" />
          <select v-model="curTable" @change="loadCols(); refreshCounts()">
            <option v-for="t in filteredTables" :key="t.name" :value="t.name">
              {{ t.name }}（{{ t.comment }}，{{ t.n_cols }}列，码表{{ t.n_enum }}/敏感{{ t.n_sensitive }}）
            </option>
          </select>
          <span v-if="tableFilter.trim()">{{ filteredTables.length }}/{{ tables.length }}</span>
        </label>
        <label>行级权限列
          <select v-model="deptCol">
            <option value="">（不过滤）</option>
            <option v-for="c in cols" :key="c.name" :value="c.name">{{ c.name }}（{{ c.comment }}）</option>
          </select>
        </label>
        <label>表注释
          <input v-model="tableComment" placeholder="手工维护表中文说明" />
        </label>
        <button class="btn2" @click="saveTableComment">保存注释</button>
        <button class="btn2" @click="saveTable">保存表设置</button>
        <button class="btn2" :disabled="metaBusy || syncBusy" @click="openMeta">重新加载</button>
        <label>同步前缀
          <input v-model="syncPrefixes" :disabled="syncBusy" placeholder="dwd_,dws_（空=不过滤）" />
        </label>
        <button class="btn2" :disabled="metaBusy || syncBusy" @click="syncMeta">{{ syncBusy ? '同步中…' : '同步元数据' }}</button>
      </div>

      <table class="metatable">
        <thead>
          <tr><th>列</th><th>类型</th><th>说明</th><th>枚举码表</th><th>敏感</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="c in cols" :key="c.name">
            <td>{{ c.name }}</td>
            <td class="type">{{ c.data_type }}</td>
            <td>{{ c.comment }}</td>
            <td class="enumcell">{{ enumSummary(c) }}</td>
            <td><input type="checkbox" :checked="c.is_sensitive" @change="onSens(c, $event)" /></td>
            <td><button class="btn2" @click="openEditor(c)">编辑</button></td>
          </tr>
        </tbody>
      </table>

      <div v-if="editCol" class="modal">
        <div class="dialog">
          <h3>{{ curTable }}.{{ editCol.name }} <small>{{ editCol.comment }}</small></h3>
          <div class="bindrow">列注释
            <input v-model="editComment" type="text" placeholder="手工维护列中文说明，保存后同步更新语义召回向量" />
          </div>
          <div class="bindrow">全局码表
            <select v-model="editCodeDict">
              <option value="">（不绑定）</option>
              <option v-for="d in codeDicts" :key="d.code" :value="d.code">{{ d.code }}（{{ d.name }}，{{ Object.keys(d.entries || {}).length }}项）</option>
            </select>
          </div>
          <p class="hint">每行一个 <code>码值=含义</code>，保存后立即进入 SQL 生成提示词。{{ editCodeDict ? `已选全局码表 ${editCodeDict}：生效码值 = 全局码值 + 下方本地码值（本地覆盖同 key）。` : '' }}</p>
          <textarea v-model="enumText" rows="12" placeholder="11=转专业&#10;12=休学"></textarea>
          <div v-if="enumMsg" class="metamsg">{{ enumMsg }}</div>
          <div class="dialogbar">
            <button class="btn2" :disabled="metaBusy" @click="pullCodes">从业务库拉取码值</button>
            <button class="save" :disabled="metaBusy" @click="saveEnum">保存</button>
            <button class="btn2" @click="clearEnum">清空</button>
            <button class="btn2" @click="editCol = null">关闭</button>
          </div>
        </div>
      </div>
        </div>
      </main>

      <main v-else-if="view === 'rbac'" class="adminpane">
        <div class="admininner"><AccessControl /></div>
      </main>
      <main v-else-if="view === 'codedict'" class="adminpane">
        <div class="admininner"><CodeDict /></div>
      </main>
      <main v-else-if="view === 'metric'" class="adminpane">
        <div class="admininner"><MetricDefs /></div>
      </main>
    </div>

    <div v-if="pwdOpen" class="modal">
      <div class="dialog">
        <h3>修改登录口令 <small>{{ who.display_name || who.username }}</small></h3>
        <template v-if="!pwdDone">
          <label><span>当前口令</span><input v-model="pwdOld" type="password" autocomplete="current-password" /></label>
          <label><span>新口令</span><input v-model="pwdNew" type="password" autocomplete="new-password" /></label>
          <label><span>确认新口令</span><input v-model="pwdNew2" type="password" autocomplete="new-password" @keyup.enter="submitPwd" /></label>
          <p class="hint">至少 8 位，需含字母与数字，并再包含符号或大小写混合。修改后所有设备上的旧登录态立即失效。</p>
          <div v-if="pwdMsg" class="metamsg">{{ pwdMsg }}</div>
          <div class="dialogbar">
            <button class="save" :disabled="pwdBusy" @click="submitPwd">确认修改</button>
            <button class="btn2" :disabled="pwdBusy" @click="pwdOpen = false">取消</button>
          </div>
        </template>
        <template v-else>
          <div class="okmsg">{{ pwdMsg }}</div>
          <div class="dialogbar">
            <button class="save" @click="doLogout">重新登录</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style>
/* 样式统一见 src/styles.css */
</style>
