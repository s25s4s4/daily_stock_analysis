#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
两阶段选股系统 - 第一阶段：量化筛选
从全市场筛选出200只候选股票

运行方式: python stock_screener.py
输出: data/screener_result.json
"""

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


def get_all_stocks_akshare_em():
    """数据源1: akshare东方财富"""
    print("  尝试 akshare 东方财富...")
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    print(f"  ✅ akshare东方财富: {len(df)} 只")
    return df


def get_all_stocks_efinance():
    """数据源2: efinance东方财富"""
    print("  尝试 efinance...")
    import efinance as ef
    df = ef.stock.get_realtime_quotes()
    # efinance列名映射
    column_mapping = {
        '股票代码': '代码',
        '股票名称': '名称',
        '最新价': '最新价',
        '涨跌幅': '涨跌幅',
        '成交量': '成交量',
        '成交额': '成交额',
        '换手率': '换手率',
        '量比': '量比',
        '总市值': '总市值',
    }
    df = df.rename(columns=column_mapping)
    print(f"  ✅ efinance: {len(df)} 只")
    return df


def get_all_stocks_akshare_sina():
    """数据源3: akshare新浪"""
    print("  尝试 akshare 新浪...")
    import akshare as ak
    df = ak.stock_zh_a_spot()
    # 新浪接口列名不同，需要映射
    column_mapping = {
        '代码': '代码',
        '名称': '名称',
        '最新价': '最新价',
        '涨跌额': '涨跌额',
        '涨跌幅': '涨跌幅',
        '买入': '买入',
        '卖出': '卖出',
        '昨收': '昨收',
        '今开': '今开',
        '最高': '最高',
        '最低': '最低',
        '成交量': '成交量',
        '成交额': '成交额',
    }
    df = df.rename(columns=column_mapping)
    # 新浪接口没有量比、换手率、总市值，需要后续计算
    print(f"  ✅ akshare新浪: {len(df)} 只")
    return df


def get_all_stocks_with_retry(max_retries=3):
    """带重试的多数据源获取"""
    print("📊 获取全市场股票列表...")
    
    data_sources = [
        ("akshare东方财富", get_all_stocks_akshare_em),
        ("efinance", get_all_stocks_efinance),
        ("akshare新浪", get_all_stocks_akshare_sina),
    ]
    
    for source_name, source_func in data_sources:
        for attempt in range(max_retries):
            try:
                print(f"\n[{source_name}] 第 {attempt + 1}/{max_retries} 次尝试...")
                df = source_func()
                if df is not None and len(df) > 0:
                    return df
            except Exception as e:
                print(f"  ❌ 失败: {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    print(f"  ⏳ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
    
    return None


def basic_filter(df):
    """基础过滤：市值、股价、ST、新股"""
    print("\n🔍 基础过滤...")
    initial_count = len(df)
    
    # 排除ST股
    if SCREENER_CONFIG["exclude_st"] and "名称" in df.columns:
        df = df[~df["名称"].str.contains("ST|退市", na=False)]
        print(f"  排除ST/退市: {len(df)} 只 (排除 {initial_count - len(df)} 只)")
    
    # 市值过滤
    if "总市值" in df.columns:
        # 处理可能的字符串类型
        df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
        df["总市值(亿)"] = df["总市值"] / 1e8
        df = df[
            (df["总市值(亿)"] >= SCREENER_CONFIG["min_market_cap"]) &
            (df["总市值(亿)"] <= SCREENER_CONFIG["max_market_cap"])
        ]
        print(f"  市值过滤: {len(df)} 只")
    else:
        print(f"  ⚠️ 无市值数据，跳过市值过滤")
    
    # 股价过滤
    if "最新价" in df.columns:
        df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
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
        df["量比"] = pd.to_numeric(df["量比"], errors="coerce")
        df = df[df["量比"] >= SCREENER_CONFIG["min_volume_ratio"]]
        print(f"  量比>={SCREENER_CONFIG['min_volume_ratio']}: {len(df)} 只")
    else:
        print(f"  ⚠️ 无量比数据，跳过量比过滤")
    
    # 换手率过滤
    if "换手率" in df.columns:
        df["换手率"] = pd.to_numeric(df["换手率"], errors="coerce")
        df = df[
            (df["换手率"] >= SCREENER_CONFIG["min_turnover_rate"]) &
            (df["换手率"] <= SCREENER_CONFIG["max_turnover_rate"])
        ]
        print(f"  换手率 {SCREENER_CONFIG['min_turnover_rate']}%-{SCREENER_CONFIG['max_turnover_rate']}%: {len(df)} 只")
    else:
        print(f"  ⚠️ 无换手率数据，跳过换手率过滤")
    
    return df


def trend_filter_simple(df):
    """简化版趋势筛选：基于涨跌幅"""
    print("\n📉 趋势筛选（简化版）...")
    
    # 过滤涨跌幅
    if "涨跌幅" in df.columns:
        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        # 只保留涨幅在-5%到8%之间的（排除涨停和暴跌）
        df = df[(df["涨跌幅"] >= -5) & (df["涨跌幅"] <= 8)]
        print(f"  涨跌幅过滤(-5%~8%): {len(df)} 只")
    
    return df


def score_and_rank(df):
    """综合评分排序"""
    print("\n🏆 综合评分排序...")
    
    if df.empty:
        return df
    
    score = pd.Series(0.0, index=df.index)
    
    # 1. 量比评分（权重25%）
    if "量比" in df.columns:
        df["量比"] = pd.to_numeric(df["量比"], errors="coerce").fillna(1)
        score += df["量比"].clip(0, 5) / 5 * 25
    
    # 2. 换手率评分（权重25%）- 换手率3-8%最佳
    if "换手率" in df.columns:
        df["换手率"] = pd.to_numeric(df["换手率"], errors="coerce").fillna(5)
        score += (5 - abs(df["换手率"] - 5)) / 5 * 25
    
    # 3. 涨跌幅评分（权重25%）- 涨跌幅-2%到5%最佳
    if "涨跌幅" in df.columns:
        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
        score += df["涨跌幅"].clip(-5, 5).apply(lambda x: 25 - abs(x) * 5)
    
    # 4. 市值评分（权重25%）- 中小市值优先
    if "总市值(亿)" in df.columns:
        df["总市值(亿)"] = pd.to_numeric(df["总市值(亿)"], errors="coerce").fillna(500)
        # 市值越小得分越高（但有下限）
        score += (1 - df["总市值(亿)"].clip(30, 1000) / 1000) * 25
    
    df["综合得分"] = score
    
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
    
    # 1. 获取全市场数据（带重试和多数据源）
    df = get_all_stocks_with_retry(max_retries=3)
    if df is None:
        print("❌ 获取股票数据失败（所有数据源均失败）")
        sys.exit(1)
    
    # 2. 基础过滤
    df = basic_filter(df)
    
    # 3. 技术面筛选
    df = technical_filter(df)
    
    # 4. 简化版趋势筛选（不获取历史数据，避免超时）
    df = trend_filter_simple(df)
    
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
        stock_data = {
            "code": str(row.get("代码", "")),
            "name": str(row.get("名称", "")),
            "price": float(row.get("最新价", 0) or 0),
            "change_pct": float(row.get("涨跌幅", 0) or 0),
            "volume_ratio": float(row.get("量比", 0) or 0),
            "turnover_rate": float(row.get("换手率", 0) or 0),
            "market_cap": float(row.get("总市值(亿)", 0) or 0),
            "score": float(row.get("综合得分", 0) or 0),
        }
        stock_list.append(stock_data)
    
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
