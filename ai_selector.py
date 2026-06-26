#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两阶段选股系统 - 第二阶段：AI精选
从第一阶段筛选的200只股票中，AI选出最佳的10只

运行方式: python ai_selector.py
输入: data/screener_result.json
输出: data/ai_selected_stocks.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import os

# 尝试导入litellm用于AI分析
try:
    from litellm import completion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    print("⚠️ litellm未安装，将使用简单规则选股")


def load_screener_result():
    """加载第一阶段筛选结果"""
    input_file = Path("data/screener_result.json")
    if not input_file.exists():
        print(f"❌ 找不到第一阶段结果文件: {input_file}")
        print("   请先运行: python stock_screener.py")
        sys.exit(1)
    
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"✅ 加载第一阶段结果: {data['count']} 只股票")
    print(f"   日期: {data['date']}")
    return data["stocks"]


def analyze_with_ai(stocks):
    """使用AI进行综合分析选股"""
    if not LITELLM_AVAILABLE:
        print("⚠️ AI不可用，使用规则选股")
        return rule_based_selection(stocks)
    
    print("\n🤖 AI分析阶段...")
    print(f"   分析 {len(stocks)} 只候选股票...")
    
    # 准备股票数据摘要
    stock_summary = []
    for i, stock in enumerate(stocks[:50]):  # 限制前50只进行AI分析，避免token过多
        ma5 = stock.get('ma5', 0)
        ma10 = stock.get('ma10', 0)
        ma20 = stock.get('ma20', 0)
        bias_rate = stock.get('bias_rate', 0)
        
        summary = f"""
股票{i+1}: {stock['name']}({stock['code']})
- 价格: {stock['price']:.2f}元
- 涨跌幅: {stock['change_pct']:+.2f}%
- 量比: {stock['volume_ratio']:.2f}
- 换手率: {stock['turnover_rate']:.2f}%
- 市值: {stock['market_cap']:.2f}亿
"""
        if ma5 > 0:
            summary += f"- MA5: {ma5:.2f}, MA10: {ma10:.2f}, MA20: {ma20:.2f}\n"
            summary += f"- 乖离率: {bias_rate:.2f}%\n"
        
        summary += f"- 综合得分: {stock['score']:.2f}\n"
        stock_summary.append(summary)
    
    # 构建AI提示词
    prompt = f"""你是一位专业的A股投资顾问。请从以下{len(stock_summary)}只候选股票中，选出最适合明天买入的10只股票。

选股标准：
1. 趋势向好：均线多头排列，乖离率适中
2. 量价配合：量比合理，换手率适中
3. 风险控制：涨跌幅不过大，市值适中
4. 综合评分：参考第一阶段综合得分

候选股票数据：
{''.join(stock_summary)}

请输出JSON格式，包含10只推荐股票，每只股票包含：
- code: 股票代码
- name: 股票名称
- reason: 推荐理由（50字以内）
- confidence: 信心度(0-100)
- target_price: 目标价位
- stop_loss: 止损价位

输出格式：
{{
  "selected_stocks": [
    {{
      "code": "000001",
      "name": "平安银行",
      "reason": "均线多头，量价配合良好",
      "confidence": 85,
      "target_price": 12.50,
      "stop_loss": 11.20
    }},
    ...
  ],
  "analysis_summary": "整体市场分析和策略说明（100字以内）"
}}
"""
    
    try:
        # 调用AI模型
        response = completion(
            model=os.getenv("LITELLM_MODEL", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000
        )
        
        # 解析AI返回的JSON
        content = response.choices[0].message.content
        
        # 尝试提取JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            print(f"✅ AI分析完成，选出 {len(result.get('selected_stocks', []))} 只股票")
            return result
        else:
            print("⚠️ AI返回格式异常，使用规则选股")
            return rule_based_selection(stocks)
            
    except Exception as e:
        print(f"⚠️ AI分析失败: {e}")
        print("   使用规则选股")
        return rule_based_selection(stocks)


def rule_based_selection(stocks):
    """规则选股（AI不可用时的备选方案）"""
    print("\n📊 规则选股阶段...")
    
    # 多维度评分
    scored_stocks = []
    for stock in stocks:
        score = 0
        
        # 1. 综合得分（权重30%）
        score += stock['score'] * 0.3
        
        # 2. 量比评分（权重20%）- 量比1.5-3最佳
        if 1.5 <= stock['volume_ratio'] <= 3:
            score += 20
        elif 1.2 <= stock['volume_ratio'] < 1.5 or 3 < stock['volume_ratio'] <= 5:
            score += 10
        
        # 3. 换手率评分（权重20%）- 换手率3-8%最佳
        if 3 <= stock['turnover_rate'] <= 8:
            score += 20
        elif 2 <= stock['turnover_rate'] < 3 or 8 < stock['turnover_rate'] <= 12:
            score += 10
        
        # 4. 乖离率评分（权重15%）- 乖离率-3%到3%最佳
        if -3 <= stock['bias_rate'] <= 3:
            score += 15
        elif -5 <= stock['bias_rate'] < -3 or 3 < stock['bias_rate'] <= 5:
            score += 8
        
        # 5. 涨跌幅评分（权重15%）- 涨跌幅-2%到5%最佳
        if -2 <= stock['change_pct'] <= 5:
            score += 15
        elif -5 <= stock['change_pct'] < -2 or 5 < stock['change_pct'] <= 8:
            score += 8
        
        scored_stocks.append({
            **stock,
            'ai_score': score
        })
    
    # 排序并取前10
    scored_stocks.sort(key=lambda x: x['ai_score'], reverse=True)
    selected = scored_stocks[:10]
    
    # 构建输出格式
    result = {
        "selected_stocks": [
            {
                "code": s['code'],
                "name": s['name'],
                "reason": f"综合得分{s['score']:.1f}，量比{s['volume_ratio']:.2f}，换手率{s['turnover_rate']:.1f}%",
                "confidence": min(95, int(s['ai_score'])),
                "target_price": round(s['price'] * 1.05, 2),  # 目标价+5%
                "stop_loss": round(s['price'] * 0.95, 2)  # 止损价-5%
            }
            for s in selected
        ],
        "analysis_summary": "基于量化指标综合评估，优选量价配合良好、趋势稳健的个股。建议分批建仓，严格控制风险。"
    }
    
    print(f"✅ 规则选股完成，选出 {len(selected)} 只股票")
    return result


def save_result(result):
    """保存AI选股结果"""
    output_file = Path("data/ai_selected_stocks.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 添加元数据
    output_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "count": len(result.get("selected_stocks", [])),
        **result
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n📁 AI选股结果已保存: {output_file}")
    
    # 同时生成可读的文本报告
    report_file = Path("reports/ai_selection_report.md")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(f"# AI精选股票报告\n\n")
        f.write(f"**日期**: {output_data['date']}\n")
        f.write(f"**选出数量**: {output_data['count']} 只\n\n")
        f.write(f"## 分析总结\n\n{result.get('analysis_summary', '无')}\n\n")
        f.write(f"## 推荐股票\n\n")
        
        for i, stock in enumerate(result.get("selected_stocks", []), 1):
            f.write(f"### {i}. {stock['name']} ({stock['code']})\n")
            f.write(f"- **推荐理由**: {stock['reason']}\n")
            f.write(f"- **信心度**: {stock['confidence']}%\n")
            f.write(f"- **目标价**: {stock['target_price']}元\n")
            f.write(f"- **止损价**: {stock['stop_loss']}元\n\n")
    
    print(f"📄 可读报告已生成: {report_file}")
    
    # 生成股票代码列表（用于后续分析）
    codes = [s['code'] for s in result.get("selected_stocks", [])]
    codes_str = ",".join(codes)
    
    with open("data/ai_selected_codes.txt", "w") as f:
        f.write(codes_str)
    
    print(f"📋 精选股票代码: {codes_str}")


def main():
    """主函数"""
    print("=" * 60)
    print("🤖 两阶段选股系统 - 第二阶段：AI精选")
    print("=" * 60)
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 加载第一阶段结果
    stocks = load_screener_result()
    
    # 2. AI分析选股
    result = analyze_with_ai(stocks)
    
    # 3. 保存结果
    save_result(result)
    
    print("\n" + "=" * 60)
    print("✅ AI选股完成！")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
