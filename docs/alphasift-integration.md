# AlphaSift 集成说明

AlphaSift 以 DSA 内置、默认关闭的 Extension Runtime 插件接入，用于候选发现和策略筛选。它不是 `data_provider` 行情源，不会改变既有每日分析流程；只有显式启用插件并调用对应 Action 时才会运行。

## 启用方式

在 `.env` 中配置：

```bash
EXTENSIONS_ENABLED=true
EXTENSIONS_AUTOLOAD_BUILTIN=true
EXTENSIONS_ALPHASIFT_ENABLED=true
ALPHASIFT_API_URL=
ALPHASIFT_CLI_PATH=alphasift
EXTENSIONS_ALPHASIFT_CLI_FALLBACK_ENABLED=false
ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY=em_datacenter,efinance,akshare_em
EXTENSIONS_ALPHASIFT_TIMEOUT_SECONDS=180
EXTENSIONS_CLI_STDOUT_MAX_BYTES=10485760
EXTENSIONS_CLI_STDERR_MAX_BYTES=1048576
```

AlphaSift 默认关闭。启用后，DSA 优先使用同一 Python 环境中的 `alphasift` package；package 不可用时，可配置 `ALPHASIFT_API_URL` 作为 HTTP fallback，或在确认本机 CLI 参数兼容后打开 `EXTENSIONS_ALPHASIFT_CLI_FALLBACK_ENABLED=true`。

CLI fallback 默认关闭，因为 DSA 会调用 `alphasift screen <strategy> --market <market> --max-output <n> --json --no-llm --no-post-analysis`。启用前请先确认本机 `alphasift screen --help` 支持这些参数。

PyPI 当前没有公开 `alphasift` 包。集成本地开发版本时，请在运行 DSA 的同一 Python 环境中安装：

```bash
python -m pip install -e /path/to/alphasift
```

## Action

- `alphasift.healthcheck`：检查插件是否启用，以及 Python/HTTP/CLI adapter 是否可用。
- `alphasift.list_strategies`：从 Python package 或 HTTP adapter 列出策略；不会解析面向人类的 CLI 输出。
- `alphasift.screen`：执行候选发现，归一候选为 `{rank, code, name, score, tags, ranking_reason, risk_summary}`，并保留 `source_chain`、`source_errors` 与降级信息。
- `alphasift.analyze_top_picks`：把选中的候选交给内部 `dsa.analyze_stock` Action 创建分析任务，需要确认。
- `alphasift.import_picks_to_watchlist`：把候选代码交给内部 `stock_pool.import` Action 合并进 `STOCK_LIST`，需要确认。

筛选阶段默认关闭 AlphaSift 内部的 DSA 反向深度分析：Python adapter 传入 `deep_analysis=False`，并在新版本支持时传入 `post_analyzers=[]`；CLI fallback 传入 `--no-llm --no-post-analysis`。如果已安装的 Python package 无法接受任何递归保护参数，adapter 会拒绝执行，避免 DSA 与 AlphaSift 互相递归调用。

## 阶段边界

P2 只落地内置 AlphaSift Action、adapter、schema、配置项和文档。Plugin API、Web 机会发现页、CLI/Bot/Scheduler 入口、MCP 导出、运行历史持久化和 result/link/extra Evidence Store 均属于后续批次。

`alphasift.analyze_top_picks` 与 `alphasift.import_picks_to_watchlist` 复用内部 DSA core action，不直接写任务队列或配置文件。持久化 run link 后续接入时，应只作为审计关联补充，不改变这两个内部复用边界。

## 限制

- AlphaSift 是候选发现工具，不是买卖建议引擎；交易前仍需结合 DSA 个股分析、风险和仓位计划复核。
- Python package 调用超时后只能由外层 runtime 标记失败，不能强杀已进入运行的 Python 线程；CLI fallback 可走 subprocess timeout。
- 当前 P2 没有开放远端第三方插件目录，也不从浏览器执行安装命令。
