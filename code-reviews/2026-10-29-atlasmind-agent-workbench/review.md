# 代码 Review 报告（全量快照 · 第 2 轮）

> **项目**: AtlasMind-Agent-Workbench（全仓快照） | **分支**: master | **Commit**: 82a434b
> **扫描时间**: 2026-10-29 13:40 | **操作人**: DSH AI（DeepSeek-V4.1-Flash）+ 5 个并行子评审
> **范围**: 307 个源文件（Python 46,397 行 / Java 12,321 行 / Vue-JS 14,929 行），含测试与脚本
> **规则**: python-rules.md 13 条 · java-rules.md 15 条 · js-ts-rules.md 18 条，逐条应用
> **业务规范**: `docs/benchmark-labeling-spec-v1.md`（标注金标与发布门禁）· `CONTEXT.md`（领域术语）

---

## 概览

| 等级 | 含义 | 数量 |
|------|------|------|
| 🔴 Critical | 必须修复，影响正确性或安全 | 4 |
| 🟠 High     | 强烈建议修复，存在明显风险 | 16 |
| 🟡 Medium   | 建议修复，影响可维护性 | 16 |
| 🔵 Low      | 可选优化 | 6 |
| **合计**    |                           | **42** |

> Critical / High 给出问题代码与修复后代码；Medium / Low 以汇总表 + 修复要点呈现。

---

## 问题详情（Critical）

### C1. [Critical] 命令注入 + 子进程无超时（MinerU 解析）

**文件**: `tools/chat-assistant/backend/app/services/mineru_service.py` 第 `30-42` 行
**描述**: `settings.mineru_command.format(input=str(pdf_path), output=str(job_dir))` 把上传文件名拼进 shell 命令串后以 `shell=True` 执行；文件名含 `;`、`&&`、`|`、`$(...)`、空格或引号即改变命令语义。另显式写了 `timeout=None`，MinerU 卡死会永久占用该请求。
**规则来源**: `python-rules.md#3 命令注入风险`

```python
command = settings.mineru_command.format(input=str(pdf_path), output=str(job_dir))
result = subprocess.run(command, shell=True, cwd=str(pdf_path.parent),
                        text=True, capture_output=True, timeout=None)
```

**修复后**:

```python
safe = re.sub(r"[^\w\u4e00-\u9fff.-]", "_", pdf_path.name)
argv = [p.format(input=str(pdf_path.with_name(safe)), output=str(job_dir))
        for p in settings.mineru_command_argv]          # 模板数组，不再拼串
result = subprocess.run(argv, shell=False, cwd=str(pdf_path.parent), text=True,
                        capture_output=True, timeout=settings.mineru_timeout_seconds)
```

---

### C2. [Critical] 评测把运行时崩溃当成"跳过"，失败用例计为通过

**文件**: `tools/chat-assistant/backend/app/api/routes.py` 第 `4886-4890` 行
**描述**: `except ValueError` 把 Agent 运行时抛出的 `ValueError`（含 pydantic 校验失败、`json.JSONDecodeError`、`int()` 解析失败）当作"任务类型不支持"主动跳过，只写 `{"skipped": true}` 就 `continue`；随后仍用空 artifact 打分并 `success_count += 1`。gold 无 HIGH 期望项时 `highRecall` 直接为 1.0，`schemaValid` 恒为 1。
**影响**: 崩溃用例被统计成"通过"，release gate 与评测结论整体失真，可能放行实际跑不通的审查 Agent。
**规则来源**: `python-rules.md#5 过于宽泛的异常捕获`

```python
except EvalCaseConfigurationError:
    raise
except ValueError as skip_exc:
    stage_outputs[task_type] = {"skipped": True, "reason": str(skip_exc)}
    continue
```

**修复后**:

```python
except EvalCaseConfigurationError:
    raise                                   # 只有配置类问题允许跳过
except ValueError as exc:
    logger.warning("Eval run %s case %s stage %s crashed: %s",
                   eval_run_id, case_key, task_type, exc)
    raise                                   # 计入 failed_count，不得算通过
```

---

### C3. [Critical] Redis 缓存启用"全放行"默认类型信息，可致反序列化 RCE

**文件**: `agent-server/src/main/java/com/atlasmind/config/CacheConfig.java` 第 `33-37` 行
**描述**: `mapper.activateDefaultTyping(mapper.getPolymorphicTypeValidator(), NON_FINAL, As.PROPERTY)`。新建 `ObjectMapper` 的 validator 就是 `LaissezFaireSubTypeValidator`（允许任意类型），等于让 JSON 里的 `@class` 指示真实类名。第 30 行注释还写着"禁用类型信息"，与实现相反。
**影响**: Redis 中一条攻击者可控的 value（dev 环境 Redis 无密码、内网可达即满足）被 `CacheManager` 读取时触发任意类实例化，配合 gadget 链可达成 RCE。
**规则来源**: `java-rules.md#2 高风险安全漏洞`

```java
mapper.activateDefaultTyping(
        mapper.getPolymorphicTypeValidator(),   // = LaissezFaireSubTypeValidator
        ObjectMapper.DefaultTyping.NON_FINAL,
        JsonTypeInfo.As.PROPERTY);
```

**修复后**:

```java
PolymorphicTypeValidator validator = BasicPolymorphicTypeValidator.builder()
        .allowIfSubType("com.atlasmind.")
        .allowIfSubType("java.util.")
        .build();
mapper.activateDefaultTyping(validator, ObjectMapper.DefaultTyping.NON_FINAL, JsonTypeInfo.As.PROPERTY);
```

---

### C4. [Critical] 明文管理员凭据硬编码进测试配置

**文件**: `api-tests/conftest.py` 第 `14-16` 行（`test_auth.py:22-23` 另有一份独立硬编码）
**描述**: `ADMIN_PASSWORD = os.getenv("ATLASMIND_ADMIN_PASS", "admin123")`，且 `test_auth.py` 绕过该环境变量直接写死同一组凭据。拿到仓库即得到后台口令，把 `ATLASMIND_BASE_URL` 指向测试/预发即可登录；改密后 `test_change_and_restore` 必然失败。
**规则来源**: `python-rules.md#2 硬编码密钥和敏感信息`

```python
ADMIN_USERNAME = os.getenv("ATLASMIND_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ATLASMIND_ADMIN_PASS", "admin123")
```

**修复后**:

```python
ADMIN_USERNAME = os.environ["ATLASMIND_ADMIN_USER"]   # 缺失即报错
ADMIN_PASSWORD = os.environ["ATLASMIND_ADMIN_PASS"]   # 不再有默认口令
```

---

## 问题详情（High）

### H1. [High] 富文本 XSS：`marked.parse()` 直接 `v-html`，无消毒

**文件**: `agent-front/src/components/ChatWindow.vue` 第 `79`、`309-310` 行；`ReportArtifactModal.vue` 第 `124`、`201` 行
**描述**: 两处把 `marked.parse()` 输出直接塞进 `v-html`，内容来自模型输出与报告 Markdown，属不可信输入；全仓无 DOMPurify。对照 `EvalCenter.vue:1203-1210` 已手工转义，说明知道风险但 Markdown 两处漏了。
**规则来源**: `js-ts-rules.md#2 严重错误的代码逻辑（安全）`

```js
function renderMd(text) { return text ? marked.parse(text, { breaks: true }) : '' }
```

**修复后**:

```js
import DOMPurify from 'dompurify'
function renderMd(text) {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text, { breaks: true }), {
    ALLOWED_TAGS: ['p','br','strong','em','code','pre','ul','ol','li','a','table','thead','tbody','tr','th','td','blockquote'],
    ALLOWED_ATTR: ['href','title'],
  })
}
```

---

### H2. [High] 配额回调无超时无重试，额度可能永久不结算

**文件**: `tools/chat-assistant/backend/app/agent_runtime/runner.py` 第 `1393-1410` 行
**描述**: `aiohttp.ClientSession()` 用默认超时（每读/连各 5 分钟）且无重试；异常被 `except Exception` 吞掉只留日志，该 run 的 `confirm/refund` 既未成功也无补偿记录。
**规则来源**: `python-rules.md#4 未处理的异常`

```python
async with aiohttp.ClientSession() as session:
    async with session.post(url, headers={"X-Internal-Token": settings.java_internal_token}) as resp:
        if resp.status != 200:
            logger.warning("Quota %s for run %s returned %s", endpoint, run_id, resp.status)
except Exception:
    logger.error("Quota callback failed for run %s (status=%s)", run_id, status, exc_info=True)
```

**修复后**: 加 `ClientTimeout(total=5)` + 指数退避 3 次重试；最终失败写 `mark_quota_pending(run_id, status)`，由定时任务重放。

---

### H3. [High] Java 侧 13 处 `catch (Exception ignored) {}`，DDL 失败被静默吞掉

**文件**: `agent-server/src/main/java/com/atlasmind/config/AgentWorkbenchSchemaInitializer.java` 第 `539-644`、`745` 行；`ContractCaseServiceImpl.java:1220`
**描述**: 建表/加列/建索引逐条包在 `catch (Exception ignored) {}`，异常对象丢弃、无日志无计数；MySQL DDL 非事务，部分成功会留下半成品 schema。
**规则来源**: `java-rules.md#1 异常处理错误`

```java
try { jdbcTemplate.execute("ALTER TABLE contract_case ADD COLUMN is_evaluation TINYINT NOT NULL DEFAULT 0"); }
catch (Exception ignored) { }
```

**修复后**: 仅对幂等错误（`ER_DUP_FIELDNAME`/`ER_DUP_KEYNAME`）忽略并记 debug，其余 `log.error` 后抛出，启动即失败。

---

### H4. [High] 超时分支引用不存在的 `self.trace_store`，唯一事故路径必然抛 AttributeError

**文件**: `tools/chat-assistant/backend/app/agent_runtime/runner.py` 第 `1334` 行（`RunDispatcher.__init__` 在 `1270` 行，只存 runner/run_store/report_store）
**描述**: `RunDispatcher` 从不设置 `self.trace_store`（全库仅 `AgentRunner:96` 与 `routes.py:149` 的三参构造有），因此 `HARNESS_TIMEOUT` trace 永不落库，用户看到 `'RunDispatcher' object has no attribute 'trace_store'` 而非可执行的超时提示。
**规则来源**: `python-rules.md#7 未定义的变量使用`

```python
except asyncio.TimeoutError:
    await self.trace_store.append_trace(run_id, "HARNESS_TIMEOUT", f"Agent 执行超时（{TIMEOUT_SECONDS}s）…")
```

**修复后**: `await self.runner.trace_store.append_trace(...)`，并在 `__init__` 显式注入 trace_store + 补单测。

---

### H5. [High] 失败落库用 f-string 拼 JSON，且异常被 `pass` 吞掉

**文件**: `tools/chat-assistant/backend/app/api/routes.py` 第 `1979-1991` 行
**描述**: `(f'{{"error": "{error}"}}', eval_run_id)`——`error` 含双引号/反斜杠/换行（如 pymysql 的 `(1054, "Unknown column ...")`）即写出非法 `summary_json`；外层 `except Exception: pass` 让写库失败完全无声。
**影响**: 失败原因丢失，且该 `agent_eval_run` 永远停在 RUNNING/QUEUED，前端无限轮询。
**规则来源**: `python-rules.md#4 未处理的异常`

```python
cur.execute("UPDATE agent_eval_run SET status='FAILED', summary_json=%s, finished_at=NOW() WHERE id=%s",
            (f'{{"error": "{error}"}}', eval_run_id))
except Exception:
    pass
```

**修复后**: `json.dumps({"error": error}, ensure_ascii=False)`；`except Exception: logger.exception("Could not mark eval run %s as FAILED", eval_run_id)`。

---

### H6. [High] SSE 流式写入非响应式对象，增量内容不渲染

**文件**: `agent-front/src/components/ChatWindow.vue` 第 `353-410` 行
**描述**: `assistantMsg` 是普通对象，push 进 `ref` 数组后只能通过代理访问；后续流式片段写的是原始对象（`assistantMsg.content += data.content`），不经过 Proxy，模板仅在 `streamingStatus` 变化时重绘，导致流式输出实际看不到增量。
**规则来源**: `js-ts-rules.md#5 Vue 响应式错误`

```js
const assistantMsg = { role: 'assistant', content: '', sources: [] }
messages.value.push(assistantMsg)
assistantMsg.content += data.content      // 原始对象赋值，不触发渲染
```

**修复后**: `const assistantMsg = reactive({ role: 'assistant', content: '', sources: [] })`，或改为 `messages.value[i].content += data.content`。

---

### H7. [High] 知识库页 `onMounted` 串行 await 无 catch，单接口失败即整页空白

**文件**: `agent-admin/src/views/KnowledgeBase.vue` 第 `383-408` 行（`fetchSpaces` 410-421 只有 finally）
**描述**: 任一接口 4xx/5xx/超时都会中断 await 序列，后续 `fetchDocuments()`、`startDocumentPolling()` 永不执行，页面永远空白且不再轮询解析进度。
**规则来源**: `js-ts-rules.md#1 异常处理错误`

```js
onMounted(async () => {
  await fetchSpaces()
  await fetchProjects()      // 无 try/catch，抛错即中断后两步
  await fetchDocuments()
  startDocumentPolling()
})
```

**修复后**: `await Promise.allSettled([fetchSpaces(), fetchProjects(), fetchRuntimeSettings()])`，再 `fetchDocuments()` / `startDocumentPolling()`；每个加载函数自带 catch + `ElMessage.error`。

---

### H8. [High] 编辑后新增规则仍带旧 `id`，POST 冲突或误覆盖

**文件**: `agent-admin/src/views/RuleManage.vue` 第 `67-74` 行（`ClauseLibrary.vue:68-79` 同款）
**描述**: `openEdit` 用 `Object.assign(form, r)` 把整行（含 `id`、`createTime`）灌入同一个 reactive `form`；`openCreate` 只重置固定字段、不清 `id`。于是"先编辑再新增"时 `doSave` 走 POST 但请求体带旧 `id`。
**规则来源**: `js-ts-rules.md#2 严重错误的代码逻辑`

```js
function openCreate() { Object.assign(form, { ruleKey: '', ruleSet: 'SERVICE_PROCUREMENT_V1', ... }); dialog.isEdit = false }
function openEdit(r) { Object.assign(form, r); dialog.isEdit = true; dialog.visible = true }
```

**修复后**: `doSave` 中 `const { id, createTime, updateTime, ...payload } = form`，PUT 用 `id`、POST 用 `payload`；或 `openCreate` 里 `delete form.id`。

---

### H9. [High] 更新合同时把 `ownerId` 直接当列名，SQL 必然 Unknown column

**文件**: `agent-server/src/main/java/com/atlasmind/service/impl/ContractCaseServiceImpl.java` 第 `939-941` 行
**描述**: `String[] numFields = {"amount", "ownerId"}` 直接拼成 `sets.add(f + "=?")`，而 `contract_case` 实际列名是 `owner_id`（同文件 321/355 行 `c.owner_id AS ownerId`、901 行 `owner_id=?` 可证）。请求体只要带 `ownerId`（前端编辑表单回传 GET 结果即带）就 500。
**规则来源**: `java-rules.md#5 严重的代码逻辑错误`

```java
String[] numFields = {"amount", "ownerId"};
for (String f : numFields) { if (request.containsKey(f)) { sets.add(f + "=?"); params.add(request.get(f)); } }
```

**修复后**: 字段名与列名显式分离：`if (request.containsKey("ownerId")) { sets.add("owner_id=?"); params.add(request.get("ownerId")); }`。

---

### H10. [High] `LAST_INSERT_ID()` 与 INSERT 不在同一连接，评测会派发到错误的 run

**文件**: `agent-server/src/main/java/com/atlasmind/controller/admin/EvalAdminController.java` 第 `226-234` 行
**描述**: 方法无 `@Transactional`，`jdbc.update(INSERT…)` 与 `jdbc.queryForObject("SELECT LAST_INSERT_ID()")` 各自借还连接；`LAST_INSERT_ID()` 是连接级状态，连接池下可能取到其它线程的 id 或 0。
**影响**: 给错误 evalRun 派发评测；新建那条永远 QUEUED，且 217-224 行"已有评测在跑"的拦截会让该数据集此后无法再发起评测。
**规则来源**: `java-rules.md#5 严重的代码逻辑错误`

```java
jdbc.update("INSERT INTO agent_eval_run (dataset_id, runtime_engine, features_json, status, started_at) VALUES (?,?,?,'QUEUED',NOW())", datasetId, runtime, featuresJson);
Long evalRunId = jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
aiGateway.runEvaluation(evalRunId);
```

**修复后**: 用 `GeneratedKeyHolder` + `Statement.RETURN_GENERATED_KEYS`；或给方法加 `@Transactional` 绑定同一连接。

---

### H11. [High] 限流 key 取可伪造的 `X-Forwarded-For`，登录暴破防护失效

**文件**: `agent-server/src/main/java/com/atlasmind/aspect/RateLimitAspect.java` 第 `71-78` 行
**描述**: 取 `X-Forwarded-For` 且只取逗号前第一段，无任何可信代理校验。攻击者每请求换一个 XFF 即换一个计数桶，`AuthController:41` 的 5 次/分钟登录限制完全失效；审计日志 IP 亦可伪造。
**规则来源**: `java-rules.md#2 高风险安全漏洞`

```java
String ip = request.getHeader("X-Forwarded-For");
if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) { ip = request.getRemoteAddr(); }
return ip != null ? ip.split(",")[0].trim() : "unknown";
```

**修复后**: 以 `request.getRemoteAddr()` 为准；仅当对端属于配置化受信代理 CIDR 时才采信 XFF，且取**最后**一跳。

---

### H12. [High] 上传文件整体读入堆（上限 300MB），可被图片炸弹打到 OOM

**文件**: `agent-server/src/main/java/com/atlasmind/service/impl/LocalFileStorageService.java` 第 `49-54` 行（`S3FileStorageService.java:59` 同）
**描述**: `file.getBytes()` 一次性读全量进堆，而 multipart 上限配置为 300MB（`application.yml:19-20`）；图片分支随后 `ImageIO.read` 解码整幅图像，像素总量不受字节数约束。
**规则来源**: `java-rules.md#9 内存溢出/泄露风险`

**修复后**: `try (InputStream in = file.getInputStream()) { Files.copy(in, dest, REPLACE_EXISTING); }`；解码前先用 `ImageIO` reader 读尺寸并校验像素上限。

---

### H13. [High] 发布门禁失效：`labelStatus` 缺省即视为 APPROVED，且唯一数据集是 schema v1

**文件**: `tools/chat-assistant/backend/app/agent_runtime/evaluation/benchmark.py` 第 `71`、`97` 行；`evaluation/metrics.py` 第 `57-65` 行；`benchmarks/contract-review-v1/manifest.yaml`
**描述**: `manifest.get("labelStatus", "APPROVED")` 与 `raw.setdefault("annotationStatus", …"APPROVED")` 把缺失标注状态默认成已批准；而 `metrics.py` 的 `provisionalCaseCount`/`approvedCaseCount` 门禁包在 `if schema_v2:` 内。仓库唯一数据集 `contract-review-v1` 的 `schemaVersion` 仍是 **1** 且无 `labelStatus`，因此 `PROVISIONAL_GOLD_LABELS`、`INSUFFICIENT_APPROVED_CASES` 两个 gate 永远不会触发。
**影响**: 违反 `docs/benchmark-labeling-spec-v1.md`「只有 APPROVED 计入发布门禁」的口径——未评审标签可被当作金标参与发布决策，且无任何告警。
**规则来源**: `变更的业务规范: docs/benchmark-labeling-spec-v1.md`（Review lifecycle / Schema v2）

**修复要点**: 缺省值改 `PROVISIONAL`；把标注状态校验移出 `schema_v2` 分支（v1 数据集按 PROVISIONAL 处理或直接拒绝发布门禁）；把该数据集升级到 schema v2 并补 `labelStatus`。

---

### H14. [High] 标注生成失败后写空金标，基准集期望风险集被静默清空

**文件**: `scripts/build_private_benchmark_corpus.py` 第 `218-231` 行
**描述**: 标注模型调用被 `except Exception` 包住，失败只 `print` 后 `return None`；调用方退化成 `_fallback_labels_from_text`，其中 `"risks": []`。于是 LOCAL_SOURCE 合同被写成 `expected: {risks: []}` 的"金标"，构建仍以 0 退出。
**影响**: 召回评估在空金标上恒满分或无意义，基准结论失真且不可察觉。
**规则来源**: `python-rules.md#5 过于宽泛的异常捕获`

**修复要点**: 收窄异常类型并**抛出**（构建失败优于写空金标）；若必须容忍，把该 case 标 `labelStatus: FAILED` 且不写盘。

---

### H15. [High] 种子脚本默认开启全表 `DELETE` 且非幂等

**文件**: `scripts/seed_eval_datasets.py` 第 `1604-1612` 行
**描述**: `EVAL_SEED_CLEAR` 缺省为 `yes`，对 `agent_eval_result/run/case/dataset` 四表执行无 `WHERE` 的全表删除并立即 commit；随后每数据集各自 commit、无 rollback。append 模式重复执行还会插入同名同版本数据集。
**影响**: 一次误跑即不可恢复地清空全部评测历史（含金标基线）；中途失败留下半初始化数据。
**规则来源**: `python-rules.md#4 未处理的异常`

**修复要点**: 默认值改 `no`；清库只针对本次 seed 的数据集（按 name 查 ID）；单事务 + 异常 rollback；append 前校验 name+version 是否存在。

---

### H16. [High] 后台接口无鉴权的缺陷被 xfail 永久粉饰

**文件**: `api-tests/test_admin.py` 第 `295-303` 行；`api-tests/pytest.ini`（未开 `xfail_strict`）
**描述**: 唯一验证"未登录不得访问 /api/admin/**"的用例整体 `@pytest.mark.xfail(reason="BUG: Sa-Token 未拦截…")`，断言还写成 `in [200, 401, 403]`（把 200 也算通过）。缺陷在时是 xfail（绿），修好时是 XPASS（仍非失败）。
**影响**: 后台 7 个管理接口的无鉴权风险永远不会让 CI 变红。
**规则来源**: `python-rules.md#4 未处理的异常`

**修复要点**: 去掉 xfail，严格断言 `(401, 403)`；修复前用 `skip` + issue 编号显式记录，或开 `xfail_strict = true`。

---

## 问题汇总（Medium / Low）

| ID | 等级 | 规则 | 位置 | 问题 | 修复要点 |
|---|---|---|---|---|---|
| M1 | Medium | python#10 | `routes.py:2152` | `_run_evaluation_background_legacy` 461 行且全库无调用方，与新实现并存 | 删除；如需留档移入 `scripts/legacy/` |
| M2 | Medium | python#10 | `routes.py:750,4757`；`persistence.py:1102-1400` | `chat_send` 441 行、`_run_evaluation_background` 509 行、`_save_sync` 299 行 | 按阶段/写域拆函数，主函数只做编排 |
| M3 | Medium | python#5 | `routes.py`（30 处）、`es_service.py:280-283`、`worker.py:186-188` | 宽泛捕获聚合；`search_articles` 失败直接 `return []` 无日志；`XAUTOCLAIM` 失败被 `pass` 吞掉，崩溃 worker 的 PEL 不再被领取 | 收窄异常类型 + 至少 warning 留痕 |
| M4 | Medium | python#2 / java#3 | `config.py:45`；`application-dev.yml:9,35,37` | MySQL 默认口令 `123456` 且 `validate()` 不校验；dev profile 内置 `admin123`、`atlasmind-internal-dev-token` | 默认值留空 + 启动校验；dev 凭据走 `.env` |
| M5 | Medium | js-ts#2 | `ChatWindow.vue:270,282-283,300-301` | 会话 token 明文存 `localStorage`（变量名却叫 sessionStorageKey），无 HttpOnly | 改 HttpOnly+SameSite Cookie；短期至少换 `sessionStorage` |
| M6 | Medium | python#7 | `routes.py:5249,5254`（根因 `2951-2957`、`4864`） | `_create_eval_temp_case` 收了 `temp_case_ids` 却从不 append，`if temp_case_ids:` 恒假 → 临时案件清理分支形同虚设 | 新建分支单独登记"本次新建且未复用"的 id 再清理 |
| M7 | Medium | python#4 | `contract_store.py:866-868,1296-1298,1505-1508` | 三处裸 `except: pass` 吞掉 `semantic_elements` 解码失败，规则引擎随后判"字段未约定"，产出假阳性风险发现 | 捕获 `json.JSONDecodeError` 并记录 clause id |
| M8 | Medium | js-ts#1 | `App.vue:35,47` | 根组件 setup 直接 `localStorage.getItem`，隐私模式抛 `SecurityError` → 整站白屏 | 包安全读写函数，异常回退 `'light'` |
| M9 | Medium | js-ts#2 | `AiObservability.vue:15-32` | 筛选/搜索不重置 `agentPage`，翻页后改条件返回空页显示"无数据"（pipeline/chat tab 同） | 统一 `searchXxx(){ page=1; fetch() }` |
| M10 | Medium | java#5 | `ContractCaseServiceImpl.java:1915-1922` | 审计 `new_value_json` 用字符串拼 `reason`（用户输入），含引号即非法 JSON，异常随后被吞 | 用 `objectMapper.writeValueAsString(Map…)` |
| M11 | Medium | java#5 | `ContractCaseServiceImpl.java:655` | 缺省 `caseKey = "SRV-" + currentTimeMillis % 100000`，键空间 10 万，`case_key` 有唯一索引 → 撞键后创建随机 500 | 复用同文件 743/867 的 `CTR-年-8位UUID` 写法 |
| M12 | Medium | java#14 | `ContractCaseServiceImpl.java:2461-2469`（调用方 341） | `listCases` 每行再查 2 次（时间线 + 履约核验），单次列表固定 1+2N 条 SQL，50 条约 101 条 | 按 `case_id IN (...)` 批量查后内存分组 |
| M13 | Medium | python#8 | `contract_store.py:88-96`（调用点 242-245） | `_field_is_present` 对每条规则每字段重复 `json.loads` 全量 `semantic_elements`，R×F×C 次解析吃掉 300s 预算 | 每案解析一次，按索引复用 |
| M14 | Medium | python#4 / #12 | `test_fulfillment_check_v2.py:253,539`；`test_timeline_v2.py:131,199`；`test_evaluation.py:17-35`；`rescore_eval_high_recall.py:40-43`；`check_baseline_runs.py:26` | 测试有效性三连：`assert durationMs >= 0` 恒真；数据集缺失静默 `skip`；脚本写死自增 ID（9/20/23、25-29），清库重灌后静默空转并以 0 退出 | 换成有语义的断言、缺失即失败、按 name+version 解析 ID 并缺失即 `SystemExit` |
| M15 | Medium | design | `routes.py:1748-1766` | 图调度分支在幂等检查（1775-1786）之前就创建并返回 task，同 `requestId` 重试会重复派发 | 把幂等检查前移到创建之前 |
| M16 | Medium | perf/design | `routes.py:4864,4504-4507` | async 工作线程内直接调用同步 MySQL/ES 函数（`_create_eval_temp_case`、`_seed_eval_fulfillment_evidence`），阻塞事件循环 | 改用 `asyncio.to_thread` 或线程池执行 |
| L1 | Low | python#1 | `kb_store.py:282`；`routes.py:3272-3280`；`contract_intake_extractor.py:888` | 动态 SQL 列名/子句拼接（值均已参数化，当前不可注入） | 加列名白名单断言或 `sql.Identifier` |
| L2 | Low | python#6 | `evaluation/metrics.py:8`；`evaluation/runner.py:9-10`；`contract_store.py:9`；`graph/fulfillment_check.py:20`；`routes.py:126,171-178`；`scripts/watch_baseline_runs.py:6` | 未使用导入（含 `AgentExecutionPolicy`、`asyncio`、`BaseGraphState`），且 `RunRecovery`/`settings` 在函数内重复导入 | 删除；CI 加 `ruff --select F401` |
| L3 | Low | python#12 | `contract_store.py:633,701` | RRF 平滑常数 `60` 在合同/制度两条融合路径各写一遍，改一处即排序不可比 | 提为模块级 `RRF_K = 60` |
| L4 | Low | python#9 | `timeline_extraction.py:419-426` | 用 `len([...])` 做两处计数，为计数各建临时列表 | 改 `sum(1 for …)` |
| L5 | Low | python#8 | `routes.py:2943-2947` | `_risk_dimension(item)` 在同一集合推导里调用两次 | 海象运算符只算一次 |
| L6 | Low | js-ts#8 | `MyAccount.vue:49-53` | 可 `splice` 的社交链接列表用 index 当 `:key`，删中间行后输入框错位 | 为每项生成稳定 `uid` |

---

## 做得好（P1）

- **内部接口鉴权 fail-closed**：`routes.py:74-80` 在 `internal_token` 未配置时直接 500 拒绝，且用 `secrets.compare_digest`；`docker-compose.yml:73-76` 用 `${VAR:?}` 强制注入，杜绝"忘配密钥=无鉴权"。
- **SQL 值绑定到位**：抽查 12 处动态 SQL，值全部 `%s` 参数化；三个独立评审也未发现可注入点。
- **私有语料边界被正确隔离**：`benchmark-private/` 已在 `.gitignore:65`；入库的 `benchmarks/contract-review-v1` 用 `XX科技有限公司 / YY技术服务有限公司` 占位，符合 spec「不得入库真实合同标题/当事人/账号」。
- **人工确认不可绕过**：`human_confirm.py:95-145` 的 `manualResult` 只来自人工响应，`persistence.py:1258` 对 `PENDING/NEEDS_MORE_EVIDENCE` 单独处理，符合 spec「模型不得自动确认履约」。

---

## 代码解读

### 🧩 设计决策解释

**文件**: `tools/chat-assistant/backend/app/agent_runtime/`

- **识别到的方案**: 显式状态机/任务图（`graph/nodes/*` 按 retrieval → extraction → judgment → reflection 分节点，`checkpoint.py` 断点，`harness/budget.py` 预算）+ 多路召回融合管道（`_fuse_contract_retrieval`、`_fuse_policy_retrieval` + `reranker.py`）+ 证据快照与 groundedness 校验（`evidence_snapshot.py`、`harness/validation.py`）。
- **选择理由**: 合同/时间线抽取是长链路、需可中断、需可评测的任务；图式编排让"断点续跑、单节点替换、逐阶段打分"成立，`evaluation/` 才能复用同一套打分器。
- **替代方案**: 单函数顺序流水线代码量小得多，但 LLM 失败只能整体重跑（成本翻倍）、无法定位"检索错还是判断错"、换节点要改全链路。代价是抽象层变多——M2/M3 正是该代价的体现。

### ⚠️ 潜在风险识别

| # | 风险场景 | 触发条件 | 规避建议 |
|---|---------|---------|---------|
| 1 | Redis 反序列化 RCE（C3） | 攻击者可写 Redis value + 内网可达（dev 无密码） | 白名单 validator + Redis 强制密码 + 网络隔离 |
| 2 | 评测结论整体失真（C2/H13） | 运行时抛 ValueError / 数据集缺 labelStatus | 崩溃即 FAILED；门禁不依赖 schema 版本分支 |
| 3 | 评测临时案件泄漏（M6） | 每轮评测新建但未登记的 case/document/chunk 与 ES 向量 | 显式登记新建 id + 定时对账 `is_evaluation=1` 过期记录 |
| 4 | 配额结算漂移（H2） | Java 重启、网络抖动 | 待补偿表 + 定时重放 + 对账 |
| 5 | 上传 OOM（H12） | 300MB 文件并发上传、超大像素图片 | 流式落盘 + 像素上限 + 并发限制 |
| 6 | 台前页面假死（H7/M8） | 后端 5xx、浏览器禁存储 | allSettled + 安全存储读写 + 错误提示 |

### 🔧 可维护性评估

**文件**: `tools/chat-assistant/backend/app/api/routes.py`

- **职责边界**: 5273 行 / 117 个顶层函数，同时承担 HTTP 校验、评测编排、临时用例构造、打分、清理、后台调度——违反单一职责，是 M1/M2/M3/M6/M15/M16 的共同根源。前端 `EvalCenter.vue`（1849 行 / 71 个函数）同构。
- **需求变化修改路径**:
  - 场景 1「评测口径变更」→ `_score_fulfillment_check`(4053)、`_score_timeline_extraction`(3873)、`_run_evaluation_background`(4757)、`evaluation/metrics.py`；务必同时处理 M1 的 legacy 实现。
  - 场景 2「评测接口增字段」→ `routes.py` 十余个 eval 函数 + `EvalCenter.vue` 同步。
- **重构建议**: 拆 `api/routers/eval.py` + `services/evaluation_orchestrator.py` + `services/eval_case_factory.py`；第一步把 M2 涉及的超大函数抽到 orchestrator，`routes.py` 只留路由与校验，再补编排层单测。

---

## 汇总

共发现 **42** 个问题：Critical 4，High 16，Medium 16，Low 6。

> **方法说明**：静态评审，未执行构建/测试/依赖扫描，未连库验证 DDL 实际执行。Python 覆盖 `app/` 全部 + 测试 + 脚本（151 个文件）；Java 覆盖 108 个类与 3 个 profile；前端覆盖 48 个 `.vue/.js/.ts`。
> **已排除的误报**：内部接口鉴权 fail-closed、SQL 值绑定、`EvalCenter.vue` 合同文本已转义、`benchmark-private/` 隔离、`manualResult` 人工确认——均经代码核对后确认合规。
> **本轮相比首轮**：由 10 条扩展至 42 条，新增 Java/前端/测试脚本维度、业务规范缺口（H13）与跨模块深读结论（C2/H4/H9/H10/H11/H12）。
