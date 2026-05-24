---
name: alphasift_candidate_discovery
title: AlphaSift Candidate Discovery
description: Use AlphaSift only when the user asks for screening, candidate discovery, strategy pools, or top-pick exploration.
category: candidate_discovery
allowed-tools:
  - alphasift_healthcheck
  - alphasift_list_strategies
  - alphasift_screen
required-tools:
  - alphasift_screen
aliases:
  - 机会发现
  - 选股
  - candidate discovery
user-invocable: true
default-active: false
default-router: false
---

当用户明确要求“选股”“机会发现”“候选池”“策略筛选”“找一批股票”时，才使用 AlphaSift。

工作流：

1. 先调用 `alphasift_healthcheck` 判断本机是否启用并安装 AlphaSift。
2. 如需了解可用策略，调用 `alphasift_list_strategies`。
3. 调用 `alphasift_screen` 获取候选股，限制 `max_results`，并解释任何 degradation 或 source_errors。
4. 不要自动把候选股加入自选，也不要自动批量深度分析；这些动作需要用户确认。
5. 对候选结果做保守表述：AlphaSift 是候选发现，不是买入建议。最终判断仍需结合 DSA 个股分析、风险、仓位和交易计划。
