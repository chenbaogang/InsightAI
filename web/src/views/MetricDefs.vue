<script setup lang="ts">
/* 指标口径：预定义业务口径，问答时注入提示词约束 LLM 按口径生成 SQL。 */
import { onMounted, ref } from 'vue'
import { authHeaders, errText, handleUnauthorized } from '../auth'

interface MetricInfo {
  id: number; name: string; aliases: string[]; sql_expr: string; source_table: string
  default_filters: string[]; grain: string; comment: string
}
interface TableOpt { name: string; comment: string }

const metrics = ref<MetricInfo[]>([])
const tableOpts = ref<TableOpt[]>([])
const busy = ref(false)
const msg = ref('')
const editing = ref<MetricInfo | null>(null)
const isNew = ref(false)
const form = ref({ name: '', aliasesText: '', sql_expr: '', source_table: '', filtersText: '', grain: 'daily', comment: '' })

const GRAIN_LABEL: Record<string, string> = { daily: '按日', monthly: '按月', yearly: '按年', none: '不限' }

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
  const [m, t] = await Promise.all([call('GET', '/api/metrics'), call('GET', '/api/meta/tables')])
  if (m) metrics.value = m
  if (t) tableOpts.value = t
}

function linesToText(vs: string[]) {
  return (vs || []).join('\n')
}
function textToLines(t: string) {
  return t.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
}

function openNew() {
  isNew.value = true
  editing.value = null
  form.value = { name: '', aliasesText: '', sql_expr: '', source_table: '', filtersText: '', grain: 'daily', comment: '' }
  msg.value = ''
}

function openEdit(m: MetricInfo) {
  isNew.value = false
  editing.value = m
  form.value = {
    name: m.name, aliasesText: linesToText(m.aliases), sql_expr: m.sql_expr,
    source_table: m.source_table, filtersText: linesToText(m.default_filters),
    grain: m.grain, comment: m.comment,
  }
  msg.value = ''
}

function close() {
  editing.value = null
  isNew.value = false
}

async function save() {
  if (!form.value.name.trim() || !form.value.sql_expr.trim() || !form.value.source_table) {
    msg.value = '指标名、表达式、所属表都不能为空'
    return
  }
  const body = {
    name: form.value.name,
    aliases: textToLines(form.value.aliasesText),
    sql_expr: form.value.sql_expr,
    source_table: form.value.source_table,
    default_filters: textToLines(form.value.filtersText),
    grain: form.value.grain,
    comment: form.value.comment,
  }
  const ok = isNew.value
    ? await call('POST', '/api/metrics', body)
    : await call('PUT', `/api/metrics/${editing.value!.id}`, body)
  if (ok) { close(); await reload() }
}

async function remove(m: MetricInfo) {
  if (!confirm(`删除指标「${m.name}」？删除后问答不再受该口径约束。`)) return
  if (await call('DELETE', `/api/metrics/${m.id}`) !== null) await reload()
}

onMounted(reload)
</script>

<template>
  <div class="rbac metricdefs">
    <div class="toolbar">
      <button class="save" :disabled="busy" @click="openNew">新增指标</button>
      <button class="btn2" :disabled="busy" @click="reload">刷新</button>
      <span class="hint">指标口径在问答时注入提示词：问题命中所属表时，LLM 必须按表达式和默认条件生成 SQL；未配置指标时行为不变。</span>
    </div>
    <div v-if="msg" class="metamsg">{{ msg }}</div>

    <table class="metatable">
      <thead><tr><th>指标名</th><th>别名</th><th>表达式</th><th>所属表</th><th>粒度</th><th>口径说明</th><th></th></tr></thead>
      <tbody>
        <tr v-for="m in metrics" :key="m.id">
          <td>{{ m.name }}</td>
          <td>{{ m.aliases.length ? m.aliases.join('、') : '—' }}</td>
          <td class="enumcell">{{ m.sql_expr }}</td>
          <td>{{ m.source_table }}</td>
          <td>{{ GRAIN_LABEL[m.grain] || m.grain }}</td>
          <td>{{ m.comment || '—' }}</td>
          <td>
            <button class="btn2" @click="openEdit(m)">编辑</button>
            <button class="btn2" @click="remove(m)">删除</button>
          </td>
        </tr>
        <tr v-if="!metrics.length"><td colspan="7" class="empty">还没有指标，点「新增指标」</td></tr>
      </tbody>
    </table>

    <div v-if="isNew || editing" class="modal">
      <div class="dialog">
        <h3>{{ isNew ? '新增指标' : `编辑指标 ${form.name}` }}</h3>
        <label class="field">指标名<input v-model="form.name" placeholder="销售额" /></label>
        <label class="field">别名（每行一个，用于识别不同问法）
          <textarea v-model="form.aliasesText" rows="3" placeholder="营收&#10;销售收入"></textarea>
        </label>
        <label class="field">表达式（聚合 SQL 片段）
          <input v-model="form.sql_expr" placeholder="SUM(pay_amount)" />
        </label>
        <label class="field">所属表
          <select v-model="form.source_table">
            <option value="" disabled>请选择已同步的业务表</option>
            <option v-for="t in tableOpts" :key="t.name" :value="t.name">{{ t.name }}{{ t.comment ? `（${t.comment}）` : '' }}</option>
          </select>
        </label>
        <label class="field">默认条件（每行一个，拼进 WHERE）
          <textarea v-model="form.filtersText" rows="3" placeholder="sfsc = '0'"></textarea>
        </label>
        <label class="field">统计粒度
          <select v-model="form.grain">
            <option value="daily">按日</option>
            <option value="monthly">按月</option>
            <option value="yearly">按年</option>
            <option value="none">不限</option>
          </select>
        </label>
        <label class="field">口径说明（进提示词）
          <textarea v-model="form.comment" rows="3" placeholder="统计已支付订单金额，不含退款"></textarea>
        </label>
        <div class="dialogbar">
          <button class="save" :disabled="busy" @click="save">保存</button>
          <button class="btn2" @click="close">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>