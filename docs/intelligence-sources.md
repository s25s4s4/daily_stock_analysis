# 资讯 / 情报源 MVP

Issue #1707 的首版能力聚焦“合规资讯源采集、本地沉淀、可查询证据”，不把 RSS/Atom 混入按需搜索语义，也不默认新增独立舆情页。

## 能力范围

- 支持配置 RSS / Atom HTTP(S) 资讯源。
- 保存资讯源配置、启用状态、作用域和最近一次拉取状态。
- 拉取条目落库到 `intelligence_items`，保存标题、摘要、URL、来源、发布时间、拉取时间、市场与作用域。
- 按 URL 去重；无 URL 条目使用 `no-url:intel:<hash>` 兜底键。
- 支持 `symbol` / `market` / `sector` 作用域，以及 `cn` / `hk` / `us` / `global` 市场标记。
- 拉取批处理采用 fail-open：单个源失败不会阻塞其他源或主分析链路。
- 支持 retention 清理，避免资讯池无限增长。

## 安全边界

自定义 URL 会做基础校验：

- 只允许绝对 `http` / `https` URL；
- 禁止 URL 中携带 username/password；
- 禁止 `localhost`、`.local`、回环地址、内网地址、链路本地地址、保留地址和组播地址；
- 重定向后的最终 URL 也会再次校验；
- 错误消息会脱敏常见 `token` / `key` / `secret` 查询参数。

明确非目标：不做反爬、模拟登录、Cookie 抓取或非授权门户直抓。

## 配置项

```env
NEWS_INTEL_RETENTION_DAYS=30
NEWS_INTEL_FETCH_TIMEOUT_SEC=8
NEWS_INTEL_MAX_ITEMS_PER_SOURCE=50
```

## API

所有接口位于 `/api/v1/intelligence`。

- `POST /sources`：创建资讯源。
- `GET /sources`：查询资讯源。
- `POST /sources/test`：测试 payload，不落库。
- `POST /sources/{source_id}/fetch?dry_run=false`：拉取单个源。
- `POST /sources/fetch-enabled`：fail-open 拉取全部启用源。
- `GET /items?scope_type=market&market=cn&days=7`：查询资讯条目。

## 后续接入建议

首版基线之上，分析链路会 best-effort 读取本地资讯池：

- 个股传统分析会优先读取 `symbol=<股票代码>` 的资讯，并补充同市场 `market` 级资讯；内容追加到既有 `news_context`，随 AnalysisContextPack 摘要和历史 `news_content` 保存。
- Agent 分析同样通过 `news_context` 注入本地资讯证据，避免 Agent 必须重新搜索才能看到已沉淀新闻。
- 大盘复盘会把同市场 `market` 级资讯合并到市场新闻列表，Prompt、结构化 payload 和报告 news 字段都能看到来源链接。
- 本次能力仅新增本地资讯消费路径，不改模型名、provider/base URL、回退策略或运行时配置语义；兼容现有部署配置，回滚方式为清退本地资讯接入入口或移除本地资讯源配置/数据。

后续 PR 可以继续完善报告 evidence 展示和 Web 设置/报告查看入口。

## 兼容性与回滚说明（Issue #1707）

- 本功能不改动第三方模型/API Provider 语义，不新增 provider/model/base URL/运行时路由或配置迁移分支。
- 结构化检测提示中的模型/API 兼容风险在本次改动中不成立：`news_context` 注入链路仅复用现有 LLM 分析输入构造流程（`src/core/pipeline.py`、`src/market_analyzer.py`、`src/analyzer.py`），且无新增 `.env` 写入、清理、回填逻辑。
- 回滚方式：`revert` 本 PR；如需降级配置，仅需停用并移除本地资讯源配置（含 `sources` 表与 `intelligence_items` 存量）即可，不影响原有模型、provider 或其它历史分析链路。
