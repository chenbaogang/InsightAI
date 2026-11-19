CREATE TABLE meta_table (
  id SERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  comment TEXT NOT NULL DEFAULT '',
  domain VARCHAR(64) NOT NULL DEFAULT 'trade',
  dept_column VARCHAR(128),
  CONSTRAINT uk_meta_table_name UNIQUE (name)
);
COMMENT ON TABLE meta_table IS '语义层：允许提问的业务表清单';
COMMENT ON COLUMN meta_table.id IS '主键';
COMMENT ON COLUMN meta_table.name IS '业务表名';
COMMENT ON COLUMN meta_table.comment IS '表中文说明，直接进 SQL 生成提示词';
COMMENT ON COLUMN meta_table.domain IS '主题域标签；当前只在管理页展示，未参与召回过滤';
COMMENT ON COLUMN meta_table.dept_column IS '行级权限列名；NULL=该表不裁剪；与 department.data_values 组合成 IN 条件';

CREATE TABLE code_dict (
  id SERIAL PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  entries JSON NOT NULL,
  comment TEXT NOT NULL,
  CONSTRAINT code_dict_code_key UNIQUE (code)
);
COMMENT ON TABLE code_dict IS '全局码表';
COMMENT ON COLUMN code_dict.id IS '主键';
COMMENT ON COLUMN code_dict.code IS '码表编码';
COMMENT ON COLUMN code_dict.name IS '码表名称';
COMMENT ON COLUMN code_dict.entries IS '码值→含义';
COMMENT ON COLUMN code_dict.comment IS '码表说明';

CREATE TABLE meta_column (
  id SERIAL PRIMARY KEY,
  table_id INTEGER NOT NULL,
  name VARCHAR(128) NOT NULL,
  data_type VARCHAR(64) NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  enum_dict JSON,
  is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
  code_dict_id INTEGER,
  CONSTRAINT fk_meta_column_table FOREIGN KEY (table_id) REFERENCES meta_table (id) ON DELETE CASCADE,
  CONSTRAINT fk_meta_column_code_dict FOREIGN KEY (code_dict_id) REFERENCES code_dict (id)
);
COMMENT ON TABLE meta_column IS '语义层：列元数据（注释/码表/敏感标记）';
COMMENT ON COLUMN meta_column.id IS '主键';
COMMENT ON COLUMN meta_column.table_id IS '所属表，删表级联';
COMMENT ON COLUMN meta_column.name IS '列名，与业务库实际列名一致';
COMMENT ON COLUMN meta_column.data_type IS '业务库类型字符串';
COMMENT ON COLUMN meta_column.comment IS '列中文说明，向量+BM25 召回和选列提示词都靠它';
COMMENT ON COLUMN meta_column.enum_dict IS '码值→含义，如 {"11":"转专业"}；NULL=无码表；有码表的列必定进选列提示词，结果层把码值替换为含义';
COMMENT ON COLUMN meta_column.is_sensitive IS '敏感列标记：结果层部分掩码（保留前 1/4 后 1/4，长度不变）；管理员 token 看原文';
COMMENT ON COLUMN meta_column.code_dict_id IS '绑定的全局码表；NULL=未绑定；生效码值=全局码值+本地 enum_dict（本地覆盖同 key）；删码表时接口先解绑';
CREATE INDEX ix_meta_column_table_id ON meta_column (table_id);
CREATE INDEX ix_meta_column_name ON meta_column (name);

CREATE TABLE metric (
  id SERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  aliases JSON,
  sql_expr TEXT NOT NULL,
  source_table VARCHAR(128) NOT NULL,
  default_filters JSON,
  grain VARCHAR(32) NOT NULL DEFAULT 'daily',
  comment TEXT NOT NULL DEFAULT '',
  CONSTRAINT uk_metric_name UNIQUE (name)
);
COMMENT ON TABLE metric IS '指标口径：预定义业务口径';
COMMENT ON COLUMN metric.id IS '主键';
COMMENT ON COLUMN metric.name IS '指标名';
COMMENT ON COLUMN metric.aliases IS '别名数组，用于识别不同问法，如 ["营收","销售收入"]';
COMMENT ON COLUMN metric.sql_expr IS '聚合表达式，如 SUM(pay_amount)';
COMMENT ON COLUMN metric.source_table IS '所属业务表名，必须是已同步的元数据表';
COMMENT ON COLUMN metric.default_filters IS '默认过滤条件数组，如 ["sfsc = ''0''"]，注入提示词拼进 WHERE';
COMMENT ON COLUMN metric.grain IS '统计粒度：daily/monthly/yearly/none';
COMMENT ON COLUMN metric.comment IS '口径说明，进提示词';

CREATE TABLE department (
  id SERIAL PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL DEFAULT '',
  parent_code VARCHAR(64),
  data_values JSON,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT uk_department_code UNIQUE (code)
);
COMMENT ON TABLE department IS '部门与行级数据权限取值集合';
COMMENT ON COLUMN department.id IS '主键';
COMMENT ON COLUMN department.code IS '部门编码';
COMMENT ON COLUMN department.name IS '部门名称';
COMMENT ON COLUMN department.parent_code IS '上级部门编码';
COMMENT ON COLUMN department.data_values IS '该部门在业务库的单位码集合：1 个→等值过滤，多个→IN 过滤；空=不过滤（普通用户无值时提问被 403 拦）';
COMMENT ON COLUMN department.active IS '停用后该部门用户失去数据权限';
COMMENT ON COLUMN department.created_at IS '创建时刻';

CREATE TABLE role (
  id SERIAL PRIMARY KEY,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL DEFAULT '',
  admin BOOLEAN NOT NULL DEFAULT FALSE,
  builtin BOOLEAN NOT NULL DEFAULT FALSE,
  comment TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT uk_role_code UNIQUE (code)
);
COMMENT ON TABLE role IS '角色，固定两级';
COMMENT ON COLUMN role.id IS '主键';
COMMENT ON COLUMN role.code IS '角色编码';
COMMENT ON COLUMN role.name IS '角色显示名';
COMMENT ON COLUMN role.admin IS '管理员：可进语义管理/权限管理页，且查询结果不脱敏';
COMMENT ON COLUMN role.builtin IS '内置角色（admin/user），不可删除';
COMMENT ON COLUMN role.comment IS '角色说明';
COMMENT ON COLUMN role.created_at IS '创建时刻';

CREATE TABLE app_user (
  id SERIAL PRIMARY KEY,
  username VARCHAR(64) NOT NULL,
  display_name VARCHAR(128) NOT NULL DEFAULT '',
  dept_code VARCHAR(64),
  role_code VARCHAR(64) NOT NULL DEFAULT 'user',
  pwd_hash VARCHAR(256) NOT NULL DEFAULT '',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL,
  last_login_at TIMESTAMP,
  failed_count INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMP,
  pwd_changed_at TIMESTAMP,
  CONSTRAINT uk_app_user_username UNIQUE (username)
);
COMMENT ON TABLE app_user IS '账号、口令与登录锁定状态';
COMMENT ON COLUMN app_user.id IS '主键';
COMMENT ON COLUMN app_user.username IS '登录名';
COMMENT ON COLUMN app_user.display_name IS '显示名';
COMMENT ON COLUMN app_user.dept_code IS '所属部门编码；NULL=没绑数据权限（普通用户会被 403 拦），管理员可为 NULL';
COMMENT ON COLUMN app_user.role_code IS '角色编码；改角色即时生效，无需重新登录';
COMMENT ON COLUMN app_user.pwd_hash IS '密码';
COMMENT ON COLUMN app_user.active IS '停用后已有 token 立刻 401（身份每次重读）';
COMMENT ON COLUMN app_user.created_at IS '创建时刻';
COMMENT ON COLUMN app_user.last_login_at IS '最近一次登录成功时刻';
COMMENT ON COLUMN app_user.failed_count IS '连错次数，达到最大失败次数触发锁定并清零；改口令成功也清零';
COMMENT ON COLUMN app_user.locked_until IS '锁定截止时刻；未到期时登录/改口令返回 423';
COMMENT ON COLUMN app_user.pwd_changed_at IS '最近一次改口令时刻；iat 早于它的 token 一律 401「口令已修改，请重新登录」';
CREATE INDEX ix_app_user_dept_code ON app_user (dept_code);

CREATE TABLE chat_turn (
  id SERIAL PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  user_id VARCHAR(64) NOT NULL DEFAULT '',
  question TEXT NOT NULL,
  rewritten TEXT NOT NULL DEFAULT '',
  sql_guarded TEXT NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL DEFAULT 'ok',
  payload JSON,
  created_at TIMESTAMP NOT NULL
);
COMMENT ON TABLE chat_turn IS '会话轮次';
COMMENT ON COLUMN chat_turn.id IS '主键';
COMMENT ON COLUMN chat_turn.session_id IS '会话ID';
COMMENT ON COLUMN chat_turn.user_id IS '提问用户';
COMMENT ON COLUMN chat_turn.question IS '用户原话';
COMMENT ON COLUMN chat_turn.rewritten IS '多轮改写后的独立问题';
COMMENT ON COLUMN chat_turn.sql_guarded IS '护栏改写后的最终SQL，即实际执行的那条';
COMMENT ON COLUMN chat_turn.status IS 'ok / rejected_by_intent / missing_field / blocked_by_guard / engine_error；只有 ok 会被读回多轮历史';
COMMENT ON COLUMN chat_turn.payload IS '整轮结果';
COMMENT ON COLUMN chat_turn.created_at IS '落库时刻';
CREATE INDEX ix_chat_turn_session_id ON chat_turn (session_id);
CREATE INDEX ix_chat_turn_created_at ON chat_turn (created_at);


CREATE TABLE chat_session (
  id VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL DEFAULT '',
  title VARCHAR(200) NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  summary_from_id INTEGER NOT NULL DEFAULT 0,
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
COMMENT ON TABLE chat_session IS '会话';
COMMENT ON COLUMN chat_session.id IS '会话ID';
COMMENT ON COLUMN chat_session.user_id IS '归属账号，会话列表与历史读取都按它隔离，跨账号访问返回 404/403';
COMMENT ON COLUMN chat_session.title IS '会话标题；首轮自动取问题前60字，之后可重命名';
COMMENT ON COLUMN chat_session.summary IS '远期记忆：更早轮次的口径摘要（禁含统计数值）';
COMMENT ON COLUMN chat_session.summary_from_id IS 'summary 已归档到的最后一个 chat_turn.id，增量压缩的游标';
COMMENT ON COLUMN chat_session.deleted IS '软删除标记；删除时清 chat_turn，会话行保留以便审计追溯';
COMMENT ON COLUMN chat_session.created_at IS '创建时刻';
COMMENT ON COLUMN chat_session.updated_at IS '最近提问时刻';
CREATE INDEX ix_chat_session_user_id ON chat_session (user_id, updated_at);


CREATE TABLE audit_log (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL DEFAULT '',
  dept VARCHAR(64) NOT NULL DEFAULT '',
  question TEXT NOT NULL,
  sql_raw TEXT NOT NULL,
  sql_guarded TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'ok',
  "rows" INTEGER NOT NULL DEFAULT 0,
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL
);
COMMENT ON TABLE audit_log IS '问答审计';
COMMENT ON COLUMN audit_log.id IS '主键';
COMMENT ON COLUMN audit_log.user_id IS '提问用户';
COMMENT ON COLUMN audit_log.dept IS '提问时的部门名快照';
COMMENT ON COLUMN audit_log.question IS '用户原话';
COMMENT ON COLUMN audit_log.sql_raw IS '模型生成的原始SQL（护栏改写前）';
COMMENT ON COLUMN audit_log.sql_guarded IS '护栏改写后的SQL';
COMMENT ON COLUMN audit_log.status IS 'ok / rejected_by_intent / blocked_by_guard / engine_error';
COMMENT ON COLUMN audit_log."rows" IS '返回行数';
COMMENT ON COLUMN audit_log.elapsed_ms IS '端到端耗时（毫秒），与评测口径同源';
COMMENT ON COLUMN audit_log.created_at IS '落库时刻';
CREATE INDEX ix_audit_log_created_at ON audit_log (created_at);
CREATE INDEX ix_audit_log_user_id ON audit_log (user_id);

-- 角色
INSERT INTO "role" ("id", "code", "name", "admin", "builtin", "comment", "created_at") VALUES (1, 'admin', '管理员', 't', 't', '可进管理页：语义层、部门/角色/用户维护', '2026-10-29 11:36:32.922471');
INSERT INTO "role" ("id", "code", "name", "admin", "builtin", "comment", "created_at") VALUES (2, 'user', '普通用户', 'f', 't', '仅提问与查看自己的会话', '2026-10-29 11:36:32.923463');

--部门
INSERT INTO "department" ("id", "code", "name", "parent_code", "data_values", "active", "created_at") VALUES (1, 'DEMO', '演示部门', NULL, '[]', 't', '2026-10-31 01:38:19.766209');

--用户
INSERT INTO "app_user" ("id", "username", "display_name", "dept_code", "role_code", "pwd_hash", "active", "created_at", "last_login_at", "failed_count", "locked_until", "pwd_changed_at") VALUES (1, 'admin', '系统管理员', NULL, 'admin', 'pbkdf2_sha256$240000$67faca64a74bbd71aaabef51f098f504$4b05f42c9899e885df9edbed532bf53aae5771c86064c845a5e1e7bfd74f9921', 't', '2026-10-29 11:36:32.982631', '2026-11-10 08:28:54.14639', 0, NULL, '2026-11-10 08:27:38.559048');
INSERT INTO "app_user" ("id", "username", "display_name", "dept_code", "role_code", "pwd_hash", "active", "created_at", "last_login_at", "failed_count", "locked_until", "pwd_changed_at") VALUES (2, 'demo', '演示用户', 'DEMO', 'user', 'pbkdf2_sha256$240000$6af9bb43f75ba61e4d3727e3987612e9$b780fe236fd5a7d93100730c5c30b718ead5f2b603dbbd53362e6194d48c375d', 't', '2026-10-31 01:38:19.82796', '2026-11-10 08:28:01.32921', 0, NULL, '2026-11-10 08:28:35.472104');


