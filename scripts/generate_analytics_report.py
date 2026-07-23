#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generate_analytics_report.py — devPartner 分析型报告 CLI
=======================================================
对真实数据库运行"指标层 + 数据质量门禁 + 报告生成器"，产出可落地的分析型报告。

用法：
  python scripts/generate_analytics_report.py                       # 默认：最近30天
  python scripts/generate_analytics_report.py --days 30 --end 2026-07-23
  python scripts/generate_analytics_report.py --all                # 分析全部历史数据
  python scripts/generate_analytics_report.py --out report.md      # 写入文件

产出：Markdown 报告（答案先行 + DQ 门禁 + KPI 计分卡 + 分维度诊断 + 行动建议）
"""

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta

# 将仓库根加入 path，便于以包方式导入 analytics 子系统
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.business.analytics.metrics import compute_metrics, last_period_range  # noqa: E402
from backend.business.analytics.data_quality import run_dq  # noqa: E402
from backend.business.analytics.profiling import compute_portrait  # noqa: E402
from backend.business.analytics.report_builder import build_report, build_portrait_note  # noqa: E402

DEFAULT_DB = os.path.join(ROOT, "data", "databases", "devpartner.db")


def _data_span(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    r = cur.execute("SELECT MIN(date(timestamp)), MAX(date(timestamp)) FROM conversations").fetchone()
    con.close()
    return r[0], r[1]


def main():
    ap = argparse.ArgumentParser(description="devPartner 分析型报告生成器")
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLite 数据库路径")
    ap.add_argument("--days", type=int, default=30, help="滚动窗口天数（默认30）")
    ap.add_argument("--end", default=date.today().strftime("%Y-%m-%d"), help="窗口结束日 YYYY-MM-DD")
    ap.add_argument("--all", action="store_true", help="分析全部历史数据（上一窗口为空）")
    ap.add_argument("--out", default=None, help="输出 Markdown 文件路径")
    ap.add_argument("--plain", action="store_true", help="输出纯 markdown（关闭 Obsidian frontmatter/wikilink/callout）")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[错误] 数据库不存在: {args.db}")
        sys.exit(1)

    min_d, max_d = _data_span(args.db)
    print(f"[数据范围] conversations: {min_d} ~ {max_d}")

    if args.all:
        if not min_d or not max_d:
            print("[错误] 无对话数据")
            sys.exit(1)
        d0 = datetime.strptime(min_d, "%Y-%m-%d")
        d1 = datetime.strptime(max_d, "%Y-%m-%d")
        mid = d0 + timedelta(days=(d1 - d0).days // 2)
        prev_start, prev_end = min_d, mid.strftime("%Y-%m-%d")
        start = (mid + timedelta(days=1)).strftime("%Y-%m-%d")
        end = max_d
        title = f"devPartner 分析型报告（数据区间对半切：上期 {prev_start}~{prev_end} vs 本期 {start}~{end}）"
        period_type = "snapshot"
    else:
        start, end, prev_start, prev_end = last_period_range(args.end, args.days)
        title = f"devPartner 分析型报告（近 {args.days} 天）"
        period_type = f"rolling_{args.days}d"

    print(f"[周期] 当期 {start}~{end}　对比 {prev_start}~{prev_end}")

    dq = run_dq(args.db)
    metrics = compute_metrics(args.db, start, end, prev_start, prev_end)
    report = build_report(
        metrics, dq, start, end, title=title, obsidian=not args.plain, period_type=period_type
    )

    # 报告输出路径
    report_dir = os.path.dirname(args.out) if args.out else os.path.join(ROOT, "data", "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = args.out or os.path.join(report_dir, "analytics_sample_report.md")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[完成] 报告已写入: {args.out}")
    else:
        print("\n" + "=" * 60)
        print(report)
        print("=" * 60)

    # Obsidian 常青画像笔记（仅 Obsidian 模式）
    if not args.plain:
        con = sqlite3.connect(args.db)
        con.row_factory = sqlite3.Row
        portrait = compute_portrait(con.cursor())
        con.close()
        note = build_portrait_note(portrait, source_report=os.path.basename(report_path).replace(".md", ""))
        note_path = os.path.join(report_dir, "user_portrait.md")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(note)
        print(f"[完成] 用户画像笔记(OBSIDIAN)已写入: {note_path}")

    # 控制台摘要
    print(f"\n[DQ] {dq['summary']}")
    print("[提示] 用 --out report.md 保存；用 --all 看全量快照；指标口径见 backend/business/analytics/registry.py")


if __name__ == "__main__":
    main()
