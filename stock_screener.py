#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两阶段选股系统 - 第一阶段：量化筛选
从全市场筛选出200只候选股票

运行方式: python stock_screener.py
输出: data/screener_result.json
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import sys
import time
from pathlib import Path

# 筛选条件配置
SCREENER_CONFIG = {
    # 基础过滤
    "min_market_cap": 30,  # 最小市值(亿)
    "max_market_cap": 5000,  # 最大市值(亿)
    "min_price": 3,  # 最小股价
    "max_price": 100,  # 最大股价
    "exclude_st": True,  # 排除ST股
    "exclude_new": 60,  # 排除上市不足N天的新股
    
    # 技术面筛选
    "min_volume_ratio": 1.2,  # 最小量比
    "min_turnover_rate": 2.0,  # 最小换手率(%)
    "max_turnover_rate": 15.0,  # 最大换手率(%)
    
    # 趋势条件
    "require_ma_trend": True,  # 要求均线多头排列
    "max_bias_rate": 8.0,  # 最大乖离率(%)
    
    # 最终输出数量
    "target_count": 200,
}


def get_all_stocks():
    """获取全市场股票列表"""
    print("📊 获取全市场股票列表...")
    try:
        # 使用东方财富实时行情
        df = ak.stock_zh_a_spot_em()
        print(f"  ✅ 获取到 {len(df)} 只股票")
        return df
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return None


def basic_filter(df):
    """基础过滤：市值、股价、ST、新股"""
    print("\n🔍 基础过滤...")
    initial_count = len(df)
    
    # 排除ST股
    if SCREENER_CONFIG["exclude_st"]:
        df = df[~df["名称"].str.contains("ST|退市", na=False)]
        print(f"  排除ST/退市: {len(df)} 只 (排除 {initial_count - len(df)} 只)")
    
    # 市值过滤
    if "总市值" in df.columns:
        df["总市值(亿)"] = df["总市值"] / 1e8
        df = df[
            (df["总市值(亿)"] >= SCREENER_CONFIG["min_market_cap"]) &
            (df["总市值(亿)"] <= SCREENER_CONFIG["max_market_cap"])
        ]
        print(f"  市值过滤: {len(df)} 只")
    
    # 股价过滤
    if "最新价" in df.columns:
        df = df[
            (df["最新价"] >= SCREENER_CONFIG["min_price"]) &
            (df["最新价"] <= SCREENER_CONFIG["max_price"])
        ]
        print(f"  股价过滤: {len(df)} 只")
    
    return df


def technical_filter(df):
    """技术面筛选：量比、换手率"""
    print("\n📈 技术面筛选...")
    
    # 量比过滤
    if "量比" in df.columns:
        df = df[df["量比"] >= SCREENER_CONFIG["min_volume_ratio"]]
        print(f"  量比>={SCREENER_CONFIG['min_volume_ratio']}: {len(df)} 只")
    
    # 换手率过滤
    if "换手率" in df.columns:
        df = df[
            (df["换手率"] >= SCREENER_CONFIG["min_turnover_rate"]) &
            (df["换手率"] <= SCREENER_CONFIG["max_turnover_rate"])
        ]
        print(f"  换手率 {SCREENER_CONFIG['min_turnover_rate']}%-{SCREENER_CONFIG['max_turnover_rate']}%: {len(df)} 只")
    
    return df


def trend_filter(df):
    """趋势筛选：均线多头排列、乖离率"""
    print("\n📉 趋势筛选...")
    
    filtered_stocks = []
    total = len(df)
    
    for i, (idx, row) in enumerate(df.iterrows()):
        code = row.get("代码", "")
        if not code:
            continue
        
        # 进度显示
        if (i + 1) % 50 == 0:
            print(f"  进度: {i + 1}/{total} ({(i+1)/total*100:.1f}%)")
        
        try:
            # 获取历史数据
            hist = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                       start_date=(datetime.now() - timedelta(days=60)).strftime("%Y%m%d"),
                                       end_date=datetime.now().strftime("%Y%m%d"),
                                       adjust="qfq")
            
            if hist is None or len(hist) < 20:
                continue
            
            # 计算均线
            hist["MA5"] = hist["收盘"].rolling(5).mean()
            hist["MA10"] = hist["收盘"].rolling(10).mean()
            hist["MA20"] = hist["收盘"].rolling(20).mean()
            
            latest = hist.iloc[-1]
            
            # 检查均线多头排列
            if SCREENER_CONFIG["require_ma_trend"]:
                if not (latest["MA5"] > latest["MA10"] > latest["MA20"]):
                    continue
            
            # 检查乖离率
            bias = (latest["收盘"] - latest["MA20"]) / latest["MA20"] * 100
            if abs(bias) > SCREENER_CONFIG["max_bias_rate"]:
                continue
            
            # 添加到结果
            filtered_stocks.append({
                "代码": code,
                "名称": row.get("名称", ""),
                "最新价": latest["收盘"],
                "涨跌幅": row.get("涨跌幅", 0),
                "量比": row.get("量比", 0),
                "换手率": row.get("换手率", 0),
                "总市值(亿)": round(row.get("总市值(亿)", 0), 2),
                "MA5": round(latest["MA5"], 2),
                "MA10": round(latest["MA10"], 2),
                "MA20": round(latest["MA20"], 2),
                "乖离率": round(bias, 2),
            })
            
            # 避免请求过快
            time.sleep(0.1)
            
        except Exception as e:
            continue
    
    print(f"  趋势筛选后: {len(filtered_stocks)} 只")
    return pd.DataFrame(filtered_stocks)


def score_and_rank(df):
    """综合评分排序"""
    print("\n🏆 综合评分排序...")
    
    if df.empty:
        return df
    
    # 评分维度
    df["量比得分"] = df["量比"].clip(0, 5) / 5 * 25  # 量比越高越好，满分25
    df["换手率得分"] = (5 - abs(df["换手率"] - 5)) / 5 * 25  # 换手率接近5%最好
    df["乖离率得分"] = (10 - abs(df["乖离率"])) / 10 * 25  # 乖离率越小越好
    df["涨跌幅得分"] = df["涨跌幅"].clip(-5, 5).apply(lambda x: 25 - abs(x) * 5)  # 涨跌幅适中最好
    
    # 总分
    df["综合得分"] = df["量比得分"] + df["换手率得分"] + df["乖离率得分"] + df["涨跌幅得分"]
    
    # 排序
    df = df.sort_values("综合得分", ascending=False)
    
    print(f"  评分完成，最高分: {df['综合得分'].max():.2f}")
    
    return df


def main():
    """主函数"""
    print("=" * 60)
    print("📊 两阶段选股系统 - 第一阶段：量化筛选")
    print("=" * 60)
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 目标: 从全市场筛选出 {SCREENER_CONFIG['target_count']} 只候选股票")
    
    # 1. 获取全市场数据
    df = get_all_stocks()
    if df is None:
        print("❌ 获取股票数据失败")
        sys.exit(1)
    
    # 2. 基础过滤
    df = basic_filter(df)
    
    # 3. 技术面筛选
    df = technical_filter(df)
    
    # 4. 趋势筛选（需要获取历史数据，较慢）
    print(f"\n⚠️ 趋势筛选需要获取 {len(df)} 只股票的历史数据，请耐心等待...")
    df = trend_filter(df.head(500))  # 限制最多检查500只，避免太慢
    
    # 5. 综合评分排序
    df = score_and_rank(df)
    
    # 6. 取前200只
    result = df.head(SCREENER_CONFIG["target_count"])
    
    # 7. 保存结果
    output_file = Path("data/screener_result.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换为列表格式
    stock_list = []
    for _, row in result.iterrows():
        stock_list.append({
            "code": row["代码"],
            "name": row["名称"],
            "price": float(row["最新价"]),
            "change_pct": float(row["涨跌幅"]),
            "volume_ratio": float(row["量比"]),
            "turnover_rate": float(row["换手率"]),
            "market_cap": float(row["总市值(亿)"]),
            "ma5": float(row["MA5"]),
            "ma10": float(row["MA10"]),
            "ma20": float(row["MA20"]),
            "bias_rate": float(row["乖离率"]),
            "score": float(row["综合得分"]),
        })
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": len(stock_list),
            "stocks": stock_list
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 筛选完成！")
    print(f"  📁 结果已保存: {output_file}")
    print(f"  📊 共筛选出 {len(stock_list)} 只候选股票")
    
    # 8. 输出股票代码列表（用于第二阶段）
    codes = [s["code"] for s in stock_list]
    codes_str = ",".join(codes)
    
    # 写入临时文件供workflow使用
    with open("data/screener_codes.txt", "w") as f:
        f.write(codes_str)
    
    print(f"\n📋 股票代码列表已保存: data/screener_codes.txt")
    print(f"   前10只: {codes_str[:100]}...")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
