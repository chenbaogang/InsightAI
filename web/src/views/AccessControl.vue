<script setup lang="ts">
/* 权限管理：部门 / 角色 / 用户。身份来自登录后的 Bearer token（管理员角色由后端判定）。 */
import { onMounted, ref } from 'vue'
import { authHeaders, errText, handleUnauthorized } from '../auth'

interface Dept { code: string; name: string; parent_code: string | null; data_values: string[]; active: boolean; n_users: number }
interface Role { code: string; name: string; admin: boolean; builtin: boolean; comment: string; n_users: number }
interface UserRow {
  id: number; username: string; display_name: string; dept_code: string | null; dept_name: string | null
  data_values: string[]; role_code: string; role_name: string; is_admin: boolean; active: boolean
  created_at: string | null; last_login_at: string | null; initial_password?: string
}

const tab = ref<'dept' | 'role' | 'user'>('dept')
const depts = ref<Dept[]>([])
const roles = ref<Role[]>([])
const users = ref<UserRow[]>([])
const busy = ref(false)
const msg = ref('')

const deptEdit = ref<Dept | null>(null)
const deptNew = ref(false)
const deptForm = ref({ code: '', name: '', parent_code: '', valuesText: '', active: true })

const roleEdit = ref<Role | null>(null)
const roleNew = ref(false)
const roleForm = ref({ code: '', name: '', admin: false, comment: '' })

const userEdit = ref<UserRow | null>(null)
const userNew = ref(false)
const userForm = ref({ username: '', display_name: '', dept_code: '', role_code: 'user', password: '', active: true })
const justCreated = ref('')

function H() {
  return authHeaders()
}

async function call(method: string, path: string, body?: object) {
  busy.value = true
  try {
    const r = await fetch(path, { method, headers: H(), body: body ? JSON.stringify(body) : undefined })
    handleUnauthorized(r.status)
    const d = await r.json()
    if (!r.ok) throw new Error(errText(d, r.status))
    msg.value = ''
    return d
  } catch (e: any) {
    msg.value = `${e.message}`
    return null
  } finally {
    busy.value = false
  }
}

async function reload() {
  const [d, r, u] = await Promise.all([
    call('GET', '/api/rbac/departments'),
    call('GET', '/api/rbac/roles'),
    call('GET', '/api/rbac/users'),
  ])
  if (d) depts.value = d
  if (r) roles.value = r
  if (u) users.value = u
}

function valuesToText(vs: string[]) {
  return vs.join('\n')
}
function textToValues(t: string) {
  return t.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
}

/* ---------- 部门 ---------- */
function newDept() {
  deptNew.value = true
  deptEdit.value = null
  deptForm.value = { code: '', name: '', parent_code: '', valuesText: '', active: true }
  msg.value = ''
}
function editDept(d: Dept) {
  deptNew.value = false
  deptEdit.value = d
  deptForm.value = {
    code: d.code, name: d.name, parent_code: d.parent_code || '',
    valuesText: valuesToText(d.data_values), active: d.active,
  }
  msg.value = ''
}
async function saveDept() {
  const body = {
    name: deptForm.value.name,
    data_values: textToValues(deptForm.value.valuesText),
    parent_code: deptForm.value.parent_code || null,
    active: deptForm.value.active,
  }
  const ok = deptNew.value
    ? await call('POST', '/api/rbac/departments', { ...body, code: deptForm.value.code })
    : await call('PUT', `/api/rbac/departments/${encodeURIComponent(deptForm.value.code)}`, body)
  if (ok) { deptEdit.value = null; deptNew.value = false; await reload() }
}
async function removeDept(d: Dept) {
  if (!confirm(`删除部门 ${d.code}（${d.name}）？`)) return
  if (await call('DELETE', `/api/rbac/departments/${encodeURIComponent(d.code)}`) !== null) await reload()
}

/* ---------- 角色 ---------- */
function newRole() {
  roleNew.value = true
  roleEdit.value = null
  roleForm.value = { code: '', name: '', admin: false, comment: '' }
  msg.value = ''
}
function editRole(r: Role) {
  roleNew.value = false
  roleEdit.value = r
  roleForm.value = { code: r.code, name: r.name, admin: r.admin, comment: r.comment }
  msg.value = ''
}
async function saveRole() {
  const body = { name: roleForm.value.name, admin: roleForm.value.admin, comment: roleForm.value.comment }
  const ok = roleNew.value
    ? await call('POST', '/api/rbac/roles', { ...body, code: roleForm.value.code })
    : await call('PUT', `/api/rbac/roles/${encodeURIComponent(roleForm.value.code)}`, body)
  if (ok) { roleEdit.value = null; roleNew.value = false; await reload() }
}
async function removeRole(r: Role) {
  if (!confirm(`删除角色 ${r.code}（${r.name}）？`)) return
  if (await call('DELETE', `/api/rbac/roles/${encodeURIComponent(r.code)}`) !== null) await reload()
}

/* ---------- 用户 ---------- */
function newUser() {
  userNew.value = true
  userEdit.value = null
  userForm.value = { username: '', display_name: '', dept_code: '', role_code: 'user', password: '', active: true }
  justCreated.value = ''
  msg.value = ''
}
function closeUser() {
  userNew.value = false
  userEdit.value = null
  justCreated.value = ''
}
function editUser(u: UserRow) {
  userNew.value = false
  userEdit.value = u
  userForm.value = {
    username: u.username, display_name: u.display_name, dept_code: u.dept_code || '',
    role_code: u.role_code, password: '', active: u.active,
  }
  justCreated.value = ''
  msg.value = ''
}
async function saveUser() {
  const common = {
    display_name: userForm.value.display_name,
    dept_code: userForm.value.dept_code || null,
    role_code: userForm.value.role_code,
  }
  if (userEdit.value) {
    const body: Record<string, unknown> = { ...common, active: userForm.value.active }
    if (userForm.value.password) body.password = userForm.value.password
    const ok = await call('PUT', `/api/rbac/users/${userEdit.value.id}`, body)
    if (ok) { closeUser(); await reload() }
    return
  }
  const body: Record<string, unknown> = { ...common, username: userForm.value.username }
  if (userForm.value.password) body.password = userForm.value.password
  const created = await call('POST', '/api/rbac/users', body)
  if (created) {
    justCreated.value = created.initial_password
      ? `已创建 ${created.username}，初始口令（仅本次可见）：${created.initial_password}`
      : `已创建 ${created.username}`
    userForm.value.password = ''
    await reload()
  }
}
async function removeUser(u: UserRow) {
  if (!confirm(`删除用户 ${u.username}？其历史会话记录保留。`)) return
  if (await call('DELETE', `/api/rbac/users/${u.id}`) !== null) await reload()
}

onMounted(reload)
</script>

<template>
  <div class="rbac">
    <div class="tabs">
      <button :class="['tab', { on: tab === 'dept' }]" @click="tab = 'dept'">部门（{{ depts.length }}）</button>
      <button :class="['tab', { on: tab === 'role' }]" @click="tab = 'role'">角色（{{ roles.length }}）</button>
      <button :class="['tab', { on: tab === 'user' }]" @click="tab = 'user'">用户（{{ users.length }}）</button>
      <button class="btn2" :disabled="busy" @click="reload">刷新</button>
    </div>
    <div v-if="msg" class="metamsg">{{ msg }}</div>
    <div v-if="justCreated && tab === 'user'" class="okmsg">{{ justCreated }}</div>

    <template v-if="tab === 'dept'">
      <div class="toolbar">
        <button class="save" @click="newDept">新增部门</button>
        <span class="hint">单位码集合决定行级过滤取值：1 个→等值，多个→IN；留空则该部门不做行级限制。</span>
      </div>
      <table class="metatable">
        <thead><tr><th>编码</th><th>名称</th><th>上级</th><th>单位码集合</th><th>用户数</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="d in depts" :key="d.code">
            <td>{{ d.code }}</td>
            <td>{{ d.name }}</td>
            <td>{{ d.parent_code || '—' }}</td>
            <td class="enumcell">{{ d.data_values.length ? d.data_values.join('、') : '（不过滤）' }}</td>
            <td>{{ d.n_users }}</td>
            <td>{{ d.active ? '启用' : '停用' }}</td>
            <td>
              <button class="btn2" @click="editDept(d)">编辑</button>
              <button class="btn2" @click="removeDept(d)">删除</button>
            </td>
          </tr>
          <tr v-if="!depts.length"><td colspan="7" class="empty">还没有部门，点「新增部门」</td></tr>
        </tbody>
      </table>
    </template>

    <template v-else-if="tab === 'role'">
      <div class="toolbar">
        <button class="save" @click="newRole">新增角色</button>
        <span class="hint">管理员角色可进管理页；内置角色不可删除。</span>
      </div>
      <table class="metatable">
        <thead><tr><th>编码</th><th>名称</th><th>管理员</th><th>内置</th><th>说明</th><th>用户数</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in roles" :key="r.code">
            <td>{{ r.code }}</td>
            <td>{{ r.name }}</td>
            <td>{{ r.admin ? '是' : '否' }}</td>
            <td>{{ r.builtin ? '是' : '否' }}</td>
            <td>{{ r.comment }}</td>
            <td>{{ r.n_users }}</td>
            <td>
              <button class="btn2" @click="editRole(r)">编辑</button>
              <button v-if="!r.builtin" class="btn2" @click="removeRole(r)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <template v-else>
      <div class="toolbar">
        <button class="save" @click="newUser">新增用户</button>
        <span class="hint">口令留空则生成随机初始口令，只在创建成功的这一刻显示。用户档案会覆盖请求头身份。</span>
      </div>
      <table class="metatable">
        <thead><tr><th>用户名</th><th>姓名</th><th>部门</th><th>角色</th><th>行级取值</th><th>状态</th><th>最近登录</th><th></th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.username }}</td>
            <td>{{ u.display_name }}</td>
            <td>{{ u.dept_name || u.dept_code || '—' }}</td>
            <td>{{ u.role_name }}</td>
            <td class="enumcell">{{ u.data_values.length ? u.data_values.join('、') : '—' }}</td>
            <td>{{ u.active ? '启用' : '停用' }}</td>
            <td>{{ u.last_login_at ? u.last_login_at.slice(0, 10) : '从未' }}</td>
            <td>
              <button class="btn2" @click="editUser(u)">编辑</button>
              <button class="btn2" @click="removeUser(u)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <div v-if="deptNew || deptEdit" class="modal">
      <div class="dialog">
        <h3>{{ deptNew ? '新增部门' : `编辑部门 ${deptForm.code}` }}</h3>
        <label class="field">部门编码
          <input v-model="deptForm.code" :disabled="!deptNew" placeholder="EAST" />
        </label>
        <label class="field">名称<input v-model="deptForm.name" placeholder="华东区" /></label>
        <label class="field">上级部门
          <select v-model="deptForm.parent_code">
            <option value="">（无）</option>
            <option v-for="d in depts" :key="d.code" :value="d.code" :disabled="d.code === deptForm.code">{{ d.code }}（{{ d.name }}）</option>
          </select>
        </label>
        <label class="field">单位码集合（每行一个，与业务库 dept 列取值一致）
          <textarea v-model="deptForm.valuesText" rows="6" placeholder="TW001&#10;TW002"></textarea>
        </label>
        <label class="check"><input v-model="deptForm.active" type="checkbox" /> 启用</label>
        <div class="dialogbar">
          <button class="save" :disabled="busy" @click="saveDept">保存</button>
          <button class="btn2" @click="deptNew = false; deptEdit = null">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="roleNew || roleEdit" class="modal">
      <div class="dialog">
        <h3>{{ roleNew ? '新增角色' : `编辑角色 ${roleForm.code}` }}</h3>
        <label class="field">角色编码
          <input v-model="roleForm.code" :disabled="!roleNew" placeholder="auditor" />
        </label>
        <label class="field">名称<input v-model="roleForm.name" placeholder="审计员" /></label>
        <label class="field">说明<input v-model="roleForm.comment" /></label>
        <label class="check"><input v-model="roleForm.admin" type="checkbox" /> 管理员（可进管理页）</label>
        <div class="dialogbar">
          <button class="save" :disabled="busy" @click="saveRole">保存</button>
          <button class="btn2" @click="roleNew = false; roleEdit = null">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="userNew || userEdit" class="modal">
      <div class="dialog">
        <h3>{{ userEdit ? `编辑用户 ${userForm.username}` : '新增用户' }}</h3>
        <label class="field">用户名
          <input v-model="userForm.username" :disabled="!!userEdit" placeholder="zhangsan" />
        </label>
        <label class="field">姓名<input v-model="userForm.display_name" /></label>
        <label class="field">部门
          <select v-model="userForm.dept_code">
            <option value="">（不限部门）</option>
            <option v-for="d in depts" :key="d.code" :value="d.code">{{ d.name || d.code }}（{{ d.code }}）</option>
          </select>
        </label>
        <label class="field">角色
          <select v-model="userForm.role_code">
            <option v-for="r in roles" :key="r.code" :value="r.code">{{ r.name }}（{{ r.code }}）</option>
          </select>
        </label>
        <label class="field">{{ userEdit ? '重置口令（留空不改）' : '口令（留空自动生成）' }}
          <input v-model="userForm.password" type="password" autocomplete="new-password" />
        </label>
        <label v-if="userEdit" class="check"><input v-model="userForm.active" type="checkbox" /> 启用</label>
        <div class="dialogbar">
          <button class="save" :disabled="busy" @click="saveUser">保存</button>
          <button class="btn2" @click="closeUser">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>
