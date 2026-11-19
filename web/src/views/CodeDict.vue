<script setup lang="ts">
/* 全局码值：跨表通用码表维护。列在语义管理中绑定后即时生效（列级码值覆盖同 key）。 */
import { onMounted, ref } from 'vue'
import { authHeaders, errText, handleUnauthorized } from '../auth'

interface CodeDictInfo { code: string; name: string; entries: Record<string, string>; comment: string; n_bindings: number }
interface MatchRow { table: string; table_comment: string; column: string; comment: string; bound_dict: string | null; checked: boolean }

const dicts = ref<CodeDictInfo[]>([])
const busy = ref(false)
const msg = ref('')
const editing = ref<CodeDictInfo | null>(null)
const isNew = ref(false)
const form = ref({ code: '', name: '', comment: '', entriesText: '' })

async function call(method: string, path: string, body?: object) {
  busy.value = true
  try {
    const r = await fetch(path, { method, headers: authHeaders(), body: body ? JSON.stringify(body) : undefined })
    handleUnauthorized(r.status)
    const d = await r.json()
    if (!r.ok) throw new Error(errText(d, r.status))
    msg.value = ''
    return d
  } catch (e: any) {
    msg.value = e.message
    return null
  } finally {
    busy.value = false
  }
}

async function reload() {
  const d = await call('GET', '/api/code-dicts')
  if (d) dicts.value = d
}

function entriesToText(d: Record<string, string>) {
  return Object.entries(d || {}).map(([k, v]) => `${k}=${v}`).join('\n')
}

function parseEntries(text: string): { dict: Record<string, string>; bad: string[] } {
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

function summary(d: CodeDictInfo) {
  const ks = Object.keys(d.entries || {})
  if (!ks.length) return '—'
  const txt = ks.slice(0, 3).map((k) => `${k}=${d.entries[k]}`).join('，')
  return ks.length > 3 ? `${txt} 等${ks.length}项` : txt
}

function openNew() {
  isNew.value = true
  editing.value = null
  form.value = { code: '', name: '', comment: '', entriesText: '' }
  msg.value = ''
}

function openEdit(d: CodeDictInfo) {
  isNew.value = false
  editing.value = d
  form.value = { code: d.code, name: d.name, comment: d.comment, entriesText: entriesToText(d.entries) }
  msg.value = ''
}

function close() {
  editing.value = null
  isNew.value = false
}

async function save() {
  const { dict, bad } = parseEntries(form.value.entriesText)
  if (bad.length) { msg.value = `以下行缺少“码值=含义”：${bad.slice(0, 3).join(' / ')}`; return }
  const body = { name: form.value.name, comment: form.value.comment, entries: dict }
  const ok = isNew.value
    ? await call('POST', '/api/code-dicts', { ...body, code: form.value.code })
    : await call('PUT', `/api/code-dicts/${encodeURIComponent(form.value.code)}`, body)
  if (ok) { close(); await reload() }
}

async function remove(d: CodeDictInfo) {
  const note = d.n_bindings ? `，${d.n_bindings} 个绑定列将自动解绑` : ''
  if (!confirm(`删除全局码表 ${d.code}（${d.name}）${note}？`)) return
  if (await call('DELETE', `/api/code-dicts/${encodeURIComponent(d.code)}`) !== null) await reload()
}

/* ---------- 按列名批量绑定 ---------- */
const bindFor = ref<CodeDictInfo | null>(null)
const bindNames = ref('')
const matches = ref<MatchRow[]>([])
const searched = ref(false)

function openBind(d: CodeDictInfo) {
  bindFor.value = d
  bindNames.value = ''
  matches.value = []
  searched.value = false
  msg.value = ''
}

async function searchMatch() {
  if (!bindFor.value || !bindNames.value.trim()) return
  const rows = await call('GET', `/api/code-dicts/${encodeURIComponent(bindFor.value.code)}/match?column=${encodeURIComponent(bindNames.value.trim())}`)
  if (rows) {
    matches.value = rows.map((r: MatchRow) => ({ ...r, checked: true }))
    searched.value = true
  }
}

function toggleAll(e: Event) {
  const v = (e.target as HTMLInputElement).checked
  matches.value.forEach((r) => { r.checked = v })
}

async function applyBind() {
  if (!bindFor.value) return
  const targets = matches.value.filter((r) => r.checked).map((r) => ({ table: r.table, column: r.column }))
  if (!targets.length) { msg.value = '请先勾选要绑定的列'; return }
  const r = await call('POST', `/api/code-dicts/${encodeURIComponent(bindFor.value.code)}/bind`, { targets })
  if (r) {
    msg.value = `已绑定 ${r.n_bound} 个列到 ${bindFor.value.code}`
    bindFor.value = null
    await reload()
  }
}

onMounted(reload)
</script>

<template>
  <div class="rbac codedict">
    <div class="toolbar">
      <button class="save" :disabled="busy" @click="openNew">新增全局码表</button>
      <button class="btn2" :disabled="busy" @click="reload">刷新</button>
      <span class="hint">在语义管理的列编辑弹窗中绑定全局码表；修改后所有绑定列立即生效，列级码值覆盖同 key。</span>
    </div>
    <div v-if="msg" class="metamsg">{{ msg }}</div>

    <table class="metatable">
      <thead><tr><th>编码</th><th>名称</th><th>码值</th><th>说明</th><th>绑定列数</th><th></th></tr></thead>
      <tbody>
        <tr v-for="d in dicts" :key="d.code">
          <td>{{ d.code }}</td>
          <td>{{ d.name }}</td>
          <td class="enumcell">{{ summary(d) }}</td>
          <td>{{ d.comment }}</td>
          <td>{{ d.n_bindings }}</td>
          <td>
            <button class="btn2" @click="openEdit(d)">编辑</button>
            <button class="btn2" @click="openBind(d)">批量绑定</button>
            <button class="btn2" @click="remove(d)">删除</button>
          </td>
        </tr>
        <tr v-if="!dicts.length"><td colspan="6" class="empty">还没有全局码表，点「新增全局码表」</td></tr>
      </tbody>
    </table>

    <div v-if="isNew || editing" class="modal">
      <div class="dialog">
        <h3>{{ isNew ? '新增全局码表' : `编辑全局码表 ${form.code}` }}</h3>
        <label class="field">编码
          <input v-model="form.code" :disabled="!isNew" placeholder="XJZT" />
        </label>
        <label class="field">名称<input v-model="form.name" placeholder="学籍状态" /></label>
        <label class="field">说明<input v-model="form.comment" /></label>
        <label class="field">码值（每行一个 码值=含义）
          <textarea v-model="form.entriesText" rows="10" placeholder="11=在读&#10;12=休学&#10;13=毕业"></textarea>
        </label>
        <div class="dialogbar">
          <button class="save" :disabled="busy" @click="save">保存</button>
          <button class="btn2" @click="close">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="bindFor" class="modal">
      <div class="dialog wide">
        <h3>批量绑定 {{ bindFor.code }}（{{ bindFor.name }}）</h3>
        <p class="hint">输入列名（多个用英文逗号分隔，如 sfsc,XQM），查询所有表中的同名列，勾选后绑定。同名不同义的列请取消勾选。</p>
        <div class="bindsearch">
          <input v-model="bindNames" placeholder="列名，如 sfsc" @keyup.enter="searchMatch" />
          <button class="btn2" :disabled="busy" @click="searchMatch">查询匹配</button>
        </div>
        <template v-if="searched">
          <p class="hint">命中 {{ matches.length }} 列，已勾选 {{ matches.filter(r => r.checked).length }} 列</p>
          <div class="matchwrap">
            <table class="metatable">
              <thead><tr>
                <th style="width:36px"><input type="checkbox" :checked="matches.length > 0 && matches.every(r => r.checked)" @change="toggleAll" /></th>
                <th>表</th><th>列</th><th>说明</th><th>当前绑定</th>
              </tr></thead>
              <tbody>
                <tr v-for="r in matches" :key="r.table + '.' + r.column">
                  <td><input type="checkbox" v-model="r.checked" /></td>
                  <td :title="r.table_comment">{{ r.table }}</td>
                  <td>{{ r.column }}</td>
                  <td>{{ r.comment }}</td>
                  <td>{{ r.bound_dict || '—' }}</td>
                </tr>
                <tr v-if="!matches.length"><td colspan="5" class="empty">没有匹配的列</td></tr>
              </tbody>
            </table>
          </div>
        </template>
        <div class="dialogbar">
          <button class="save" :disabled="busy || !matches.some(r => r.checked)" @click="applyBind">绑定选中列</button>
          <button class="btn2" @click="bindFor = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>