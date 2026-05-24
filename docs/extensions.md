# Extension Runtime 与插件化契约

本文定义 DSA Extension Runtime 的阶段性契约，用于按 #1309 渐进实现内置插件、Action、Agent Tool、API、Web、CLI、Scheduler、Bot 和未来 MCP 入口。

当前状态：**P2 AlphaSift Action MVP 已落地**。P1 新增内置 Action 注册执行、JSON Schema 输入校验、权限/确认/超时/调用深度守卫、进程内并发去重、内置 DSA Action 和任务队列扩展元数据；P2 在此基础上接入内置 AlphaSift manifest、Action、schema 与 Python/HTTP/CLI adapter。Plugin API、Web 机会发现页、CLI/Bot/Scheduler/MCP 入口和持久化 Evidence Store 继续后置。

## 1. 目标与边界

目标：

- 用统一契约接入 AlphaSift 等机会发现能力。
- 让 Web、Agent、CLI、Scheduler、Bot、MCP 复用同一 Action Runtime。
- 保持现有单股分析、每日分析、报告、通知主流程默认兼容。
- 将高成本、写操作、批量操作放在统一的权限、预算、确认、并发、审计路径下。

非目标：

- P0/P1 不开放第三方插件目录，不加载远程代码。
- P1/P2 不做动态 Web 插件渲染。
- P2 不新增 Plugin API、Web 机会发现页、CLI/Bot/Scheduler/MCP 入口或持久化 run store。
- AlphaSift 不进入 `data_provider/`，它不是行情源，而是候选发现插件。
- Skill 只描述自然语言使用说明和 allowed tools/actions，不直接执行代码。

## 2. 核心分层

单一声明源：

- `PluginManifest / ActionSpec` 是插件能力唯一声明源。
- `ExtensionRuntime` 负责执行 Action、权限、预算、确认、并发、dedupe、run envelope。
- `ToolRegistry` 是 Agent-facing view，由 ActionSpec 派生 `ToolDefinition`。
- API、CLI、Bot、Scheduler、未来 MCP 也从 ActionSpec 派生入口 schema。

数据流：

```text
plugin.yaml / builtin manifest
  -> PluginManifest
  -> ActionSpec
  -> ExtensionRuntime.execute()
  -> ActionRunEnvelope
  -> Result / Evidence Store

ActionSpec
  -> ToolDefinition        # Agent ToolRegistry view
  -> API schema            # FastAPI / Web view
  -> CLI command metadata  # CLI / Scheduler / Bot view
  -> MCP tool schema       # Future view
```

## 3. ToolDefinition 兼容升级

现有 `src/agent/tools/registry.py` 的 `ToolDefinition.parameters` 是 `List[ToolParameter]`，只能表达扁平参数；ActionSpec 使用 JSON Schema 子集，可能包含嵌套对象或数组对象。为了避免 ActionSpec -> ToolDefinition 有损映射，P1 前先做 PR-A0：

- 保留现有 `parameters: List[ToolParameter]`，不迁移已有工具。
- 新增 `input_schema: Optional[dict] = None`。
- `ToolDefinition.to_openai_tool()` 优先使用 `input_schema`，没有时继续使用 `_params_json_schema()`。
- `@tool` decorator 维持原行为。
- ActionSpec 派生 ToolDefinition 时必须设置 `input_schema`。

建议 PR 标题：

```text
refactor: accept input_schema in agent tool definitions
```

### 3.1 Tool Name 映射

Action ID 使用点号命名，例如 `alphasift.screen`；provider tool name 通常只允许字母、数字、下划线、短横线，并有长度限制。

规则：

- `tool_name = action_id.replace(".", "_")`
- 示例：`alphasift.screen` -> `alphasift_screen`
- tool name 应符合 `^[a-zA-Z0-9_-]{1,64}$`
- 如果替换后超过 64 字符，使用稳定短 hash 后缀防冲突
- `tool_bridge` 必须维护 `action_id <-> tool_name` 双向映射
- Agent 回调 tool name 时先反查原始 `action_id`，再进入 `ExtensionRuntime`

## 4. ActionSpec Schema 子集

P0 先支持 JSON Schema 子集，而不是任意 Draft 全量，便于 OpenAI tool、未来 MCP tool 和 Web 表单生成保持可控。

允许：

- `type`
- `properties`
- `required`
- `items`
- `enum`
- `description`
- `default`
- `minimum` / `maximum`
- `minLength` / `maxLength`
- `minItems` / `maxItems`
- `additionalProperties: false`

暂不允许：

- 跨文件 `$ref`
- `patternProperties`
- `dependencies`
- `if/then/else`
- `allOf` / `anyOf` / `oneOf`
- 动态 schema 生成

后续如确实需要 union 或 `$ref`，先升级 bridge 和 Web 表单生成，再放开子集。

## 5. ActionSpec

最小字段：

- `id`：全局唯一，例如 `alphasift.screen`
- `plugin_id`：例如 `alphasift`
- `name`
- `description`
- `category`：业务域分类，例如 `candidate_discovery | stock_analysis | watchlist | portfolio | notification`
- `mode`：`sync | async`
- `input_schema`：JSON Schema 子集
- `output_schema`：JSON Schema，MVP 可选
- `handler`
- `permissions`
- `supported_callers`：`web | agent | bot | cli | scheduler | mcp | system`
- `requires_confirmation`
- `confirmation_scope`
- `timeout_seconds`
- `budget_hints.max_items`
- `budget_hints.max_llm_calls`
- `concurrency_limit`
- `dedupe_strategy`：`none | input_hash | idempotency_key`
- `cancel_capability`：`none | pending_only | subprocess | cooperative`
- `sensitive_output_paths`

说明：

- `budget_hints.max_llm_calls` 是 hint，不保证能限制上游插件内部 LLM 调用。
- `concurrency_limit` 默认 1，避免全市场 scan 被重复触发。
- ActionSpec 派生为 `ToolDefinition` 时，`category` 统一映射为 `action`，业务域分类保留在 metadata。
- 内置插件的 manifest 元数据应从插件目录的 `plugin.yaml` 读取；运行时可以在代码中补充 handler、timeout、权限、预算等不可序列化或环境相关字段，但不得长期维护两份同义 manifest。

## 6. ActionContext

最小字段：

- `action_id`
- `input`
- `caller`
- `trace_id`
- `traceparent`：可选，W3C trace context 兼容字段，不引入 OpenTelemetry 依赖
- `session_id`
- `request_id`
- `idempotency_key`
- `confirmation_id`
- `dry_run`
- `call_depth`
- `budget.timeout_seconds`
- `budget.max_items`
- `budget_hints.max_llm_calls`
- `context.market`
- `context.locale`
- `context.timezone`

trace / call depth 透传：

- `call_depth` 默认 0，跨 DSA/插件边界时递增。
- `MAX_ACTION_CALL_DEPTH=3`，超过后返回 `E_CALL_DEPTH_EXCEEDED`。
- Python adapter 同进程调用时直接通过 `ActionContext` 传递 `trace_id/traceparent/call_depth`。
- CLI adapter 通过 env 透传：`DSA_TRACE_ID`、`DSA_TRACEPARENT`、`DSA_CALL_DEPTH`。
- HTTP adapter 未来通过 header 透传：`traceparent`、`x-dsa-trace-id`、`x-dsa-call-depth`。

## 7. Idempotency 与 Dedupe

定义：

- `input_hash`：运行时对 canonical JSON input 做 `sha256`，由 DSA 生成。
- `idempotency_key`：调用方传入，代表“这次业务请求只执行一次”。

`effective_dedupe_key` 规则：

- 调用方传入 `idempotency_key` 时，总是优先使用 `caller + action_id + idempotency_key`。
- 未传 `idempotency_key` 且 `dedupe_strategy=input_hash` 时，使用 `caller + action_id + input_hash`。
- 未传 `idempotency_key` 且 `dedupe_strategy=none` 时，不去重，仅受 concurrency limit 约束。
- `dedupe_strategy=idempotency_key` 但未传 `idempotency_key` 时，返回 `E_INPUT_INVALID` 或退化到 `input_hash`，由 ActionSpec 明确声明。

P1.5 要求：

- inflight 去重先在内存实现。
- 若落 `extension_action_runs` 表，只对 `pending/running` 做逻辑去重，不依赖 SQLite partial unique index。

## 8. Confirmation Token

字段：

- `confirmation_id`
- `action_id`
- `caller`
- `scope`
- `bound_to_input_hash`
- `expires_at`
- `one_shot`
- `consumed_at`
- `created_by`

规则：

- 写操作、高成本操作、批量深度分析默认需要确认。
- token 必须绑定 `input_hash`，避免确认 A 输入后执行 B 输入。
- `one_shot=true` 的 token 消费后不可复用。
- Web 通过弹窗确认；CLI 使用 `--confirm <token>` 或交互式确认；Bot 使用回复 token；MCP 后续由 host confirmation 对接。

MVP 限制：

- confirmation token 不跨进程共享。
- 服务重启后 token 全部失效，需要重新申请确认。
- 多 worker 部署下只保证当前 worker 内有效；生产持久化 confirmation store 后续单独实现。

## 9. 状态机

非终态：

- `pending`
- `running`

终态：

- `completed`
- `partial`
- `failed`
- `unavailable`
- `cancelled`

合法转移：

```text
pending -> running
pending -> cancelled
running -> completed
running -> partial
running -> failed
running -> unavailable
running -> cancelled
```

`degraded` 不作为独立状态。降级用：

- `degraded: bool`
- `warnings`
- `degradation`

## 10. 错误码与 i18n

MVP error code：

- `E_PLUGIN_DISABLED`
- `E_PLUGIN_UNAVAILABLE`
- `E_ACTION_NOT_FOUND`
- `E_CALLER_NOT_ALLOWED`
- `E_PERMISSION_DENIED`
- `E_CONFIRMATION_REQUIRED`
- `E_CONFIRMATION_INVALID`
- `E_INPUT_INVALID`
- `E_IDEMPOTENCY_CONFLICT`
- `E_CONCURRENCY_LIMIT`
- `E_BUDGET_EXCEEDED`
- `E_TIMEOUT`
- `E_CALL_DEPTH_EXCEEDED`
- `E_DEPENDENCY_FAILED`
- `E_UPSTREAM_DEGRADED`
- `E_OUTPUT_TOO_LARGE`
- `E_CANCELLED`
- `E_INTERNAL`

错误响应包含：

- `error_code`
- `message`
- `i18n_key`
- `details`
- `retryable`

`i18n_key` 约定：

- 内置通用错误：`extensions.errors.<E_CODE>`，例如 `extensions.errors.E_PLUGIN_UNAVAILABLE`
- 插件自定义错误：`extensions.<plugin_id>.errors.<key>`
- MVP 翻译来源使用 Web 自带 i18n bundle；manifest 自带 i18n 留到 P9 第三方插件治理

## 11. Action Run Envelope

P1.5 最小字段，也对应 P6 `extension_action_runs` 表：

- `run_id`
- `plugin_id`
- `plugin_version`
- `action_id`
- `caller`
- `trace_id`
- `traceparent`
- `input_hash`
- `idempotency_key`
- `status`
- `degraded`
- `warnings`
- `degradation`
- `source_chain`
- `source_errors`
- `error_code`
- `task_id`
- `adapter_mode`
- `duration_ms`
- `candidate_count`
- `summary`
- `created_at`
- `started_at`
- `updated_at`
- `completed_at`

`source_chain` 用于记录数据来源链路，例如 AlphaSift 的 `snapshot_source`、数据源 provider、fallback 路径。

最小结构示例：

```json
[
  {
    "provider": "alphasift.snapshot",
    "status": "ok",
    "fallback_from": null
  }
]
```

P6 再补：

- `extension_action_results`：`run_id`、`normalized_result`、`raw_result`、`summary`
- `extension_action_links`：`run_id`、`link_type`、`target_id`、`target_ref`
- `extension_action_run_extras`：附属扩展字段表；P6 如发现 run 表字段不足，优先新增 extras 表，不 alter 已建 run 表

## 12. Migration / No-Alter 策略

P6 前不引入 Alembic。

规则：

- P1.5 一次性创建 `extension_action_runs` 通用字段。
- P6 不修改 `extension_action_runs` 结构。
- P6 新增结果、链接、扩展字段均使用附属表。
- 如确实需要修改已存在表结构，必须单独提出迁移方案 PR，不混入功能 PR。
- 本地开发环境允许重建 SQLite，但不能把“drop dev DB”作为生产迁移策略。

## 13. 安全与配置默认值

默认配置：

- `EXTENSIONS_ENABLED=true`
- `EXTENSIONS_AUTOLOAD_BUILTIN=true`
- `EXTENSIONS_ALPHASIFT_ENABLED=false`
- `ALPHASIFT_API_URL=`
- `ALPHASIFT_CLI_PATH=alphasift`
- `EXTENSIONS_ALPHASIFT_CLI_FALLBACK_ENABLED=false`
- `ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY=em_datacenter,efinance,akshare_em`
- `EXTENSIONS_ALPHASIFT_TIMEOUT_SECONDS=180`
- `EXTENSIONS_CLI_STDOUT_MAX_BYTES=10485760`
- `EXTENSIONS_CLI_STDERR_MAX_BYTES=1048576`
- `MAX_ACTION_CALL_DEPTH=3`
- AlphaSift Scheduler 配置不属于 P2；后续接入多入口批次时再补。

安全规则：

- CLI adapter 使用 `subprocess.run(..., shell=False)`。
- CLI 参数必须来自白名单模板，不能拼接任意用户字符串为 option。
- stdout 超过 10MB 或 stderr 超过 1MB 时返回 `E_OUTPUT_TOO_LARGE`。
- token、URL secret、路径等敏感字段必须脱敏。
- 默认不开放第三方插件目录，不加载远程代码。
- 外部依赖的安装命令和文档链接来自 manifest 的 `installation_hints` / `setup_doc_url`，Web 不硬编码。

## 14. task_queue 兼容策略

P1.5 不重写现有股票分析去重逻辑。

规则：

- 保留 `_analyzing_stocks` 和 `_dedupe_stock_code_key()`，现有分析任务行为不变。
- 新增 extension/background action 专用 dedupe map，例如 `_background_dedupe_keys: Dict[str, str]`。
- `submit_tasks_batch()` 和 `submit_task()` 仍走 stock_code dedupe。
- `submit_background_task()` 可接受 `dedupe_key`，仅用于 extension/background action。
- `TaskInfo.to_dict()` 现有字段保持兼容；新增字段默认 `None`，只在 plugin task event 中出现。
- P1.5 测试必须覆盖：股票分析任务 dedupe 与 extension/background action dedupe 同时存在时互不干扰。

## 15. Cancel 语义

MVP 的 `cancel_capability` 是能力声明，不承诺所有 action 都能强制中断。

枚举：

- `none`
- `pending_only`
- `subprocess`
- `cooperative`

规则：

- pending future：可调用 `future.cancel()`，成功后状态进入 `cancelled`。
- 已开始的 Python 同步调用：不可强制中断，只记录 `cancel_requested`，完成后根据结果进入终态。
- CLI 子进程：先 `terminate()`，5 秒后仍未退出则 `kill()`。
- Web 对不可强制中断的 action 不展示“取消执行”按钮，只展示“停止监听/后台继续”。
- Python package adapter 的 timeout 只能控制外层等待结果；已进入第三方 Python 调用后通常无法被强杀。此类 action 的 Web 文案不得承诺强取消，只能展示超时失败和后续刷新。

## 16. Manifest MVP 字段

内置插件 manifest MVP 字段：

- `id`
- `name`
- `version`
- `kind`
- `description`
- `requires`
- `permissions`
- `actions`
- `skills`
- `supported_markets`
- `installation_hints`
- `setup_doc_url`
- `default_enabled`
- `ui_contributions`

AlphaSift manifest 必须明确：

- `supported_markets: ["cn"]`
- `default_enabled: false`
- 安装建议来自 `installation_hints`
- Web 文档链接来自 `setup_doc_url`

## 17. Observability

最小日志字段：

- `run_id`
- `action_id`
- `plugin_id`
- `caller`
- `status`
- `duration_ms`
- `error_code`

logger 命名：

- runtime 通用：`dsa.extensions.runtime`
- 插件 action：`dsa.extensions.<plugin_id>.<action_short>`
- `action_short = action_id.removeprefix(f"{plugin_id}.")`
- 示例：`plugin_id=alphasift`、`action_id=alphasift.screen` -> `dsa.extensions.alphasift.screen`

SSE 事件：

- `action_run_created`
- `action_run_started`
- `action_run_progress`
- `action_run_completed`
- `action_run_failed`
- `action_run_cancelled`
- heartbeat

P4 前可复用现有 task stream；P4 后插件 API 应明确事件 schema。

## 18. Action ID 到现有服务映射

| Action ID | 现有服务 / 入口 | 说明 |
| --- | --- | --- |
| `dsa.analyze_stock` | `src.services.task_queue.submit_tasks_batch()` -> `AnalysisService.analyze_stock` | 单股或批量深度分析提交 |
| `stocks.parse_import` | `src.services.import_parser.parse_import_from_text/bytes` | 解析股票列表，不直接写配置 |
| `stock_pool.import` | `ConfigManager.apply_updates()` / `STOCK_LIST` | 将候选股加入自选池；仅供确认后的内部 action 调用 |
| `portfolio.import_trades` | `src.services.portfolio_import_service.PortfolioImportService` | 组合交易导入，不等同自选股 |
| `alphasift.screen` | AlphaSift Python `screen()` / CLI screen JSON | 机会发现 |
| `alphasift.list_strategies` | AlphaSift Python `list_strategies()` | 策略列表 |

内置 DSA core action 可作为插件工作流内部复用层，但默认不作为插件市场条目展示，也不暴露给未启用插件的 Agent 工具列表。

## 19. AlphaSift 上游核对清单

P2 实施前必须核实：

- AlphaSift Python `screen()` 是否继续支持 `post_analyzers` 参数。
- DSA adapter 调用 AlphaSift 时是否可传 `post_analyzers=[]` 和 `deep_analysis=False`。
- AlphaSift CLI `screen` 是否继续支持 `--no-post-analysis`。
- AlphaSift CLI `screen` 是否支持 `--json`，且能稳定被 `json.loads()` 解析。
- AlphaSift CLI `strategies` 是否仍无 JSON 输出；若无，DSA 不做文本解析。
- AlphaSift `ScreenResult` 是否继续包含 `snapshot_source`、`source_errors`、`degradation`。

已核对的当前行为：

- AlphaSift `0.2.0` 的 Python `screen()` 支持 `post_analyzers`。
- CLI `screen` 支持 `--no-post-analysis`。
- CLI `audit` 支持 `--json`。
- CLI `strategies` 当前为人类可读文本。
- `ScreenResult` 包含 `snapshot_source`、`source_errors`、`degradation`。

## 20. Phase 边界

实际提交收敛为四个评审批次，避免把 API/Web/持久化一次性混入运行时基础层：

| Phase | 范围 |
| --- | --- |
| P1 | Extension Runtime MVP；包含 ActionSpec/catalog/runtime、内部 DSA core action 复用层、权限/确认/超时/调用深度守卫和任务队列扩展元数据 |
| P2 | AlphaSift Plugin / Action MVP；包含 manifest、schema、Python/HTTP/CLI adapter、候选归一、高风险 action 回到内部 DSA action |
| P3 | Plugin API、Skill/Tool bridge、Web 插件中心与机会发现页面 |
| P4 | CLI / Scheduler / Bot / MCP 复用 Action，补齐持久化 run/result/link Evidence Store 与第三方插件治理评估 |
