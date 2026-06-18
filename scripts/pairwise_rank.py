#!/usr/bin/env python3
"""Aggregate pairwise paper judgments into a ranking.

Input is JSONL. Each row should include:
  {"paper_a": "...", "paper_b": "...", "winner": "...", "dimension": "innovation", "margin": 1}

`winner` must be paper_a's id, paper_b's id, or "tie". The script produces a
transparent win-rate table plus a lightweight Bradley-Terry style score from
iterative MM updates. Use this as a ranking cross-check, not as a replacement
for evidence-grounded area-chair synthesis.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_rows(path: str) -> list[dict[str, Any]]:
    source = sys.stdin if path == "-" else Path(path).open(encoding="utf-8")
    rows = []
    with source:
        for line_no, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def filter_rows(rows: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    if not dimension:
        return rows
    return [row for row in rows if row.get("dimension") == dimension]


def win_matrix(rows: list[dict[str, Any]]) -> tuple[set[str], dict[tuple[str, str], float]]:
    papers: set[str] = set()
    wins: dict[tuple[str, str], float] = defaultdict(float)
    for row in rows:
        a, b = row["paper_a"], row["paper_b"]
        winner = row["winner"]
        margin = max(0.1, float(row.get("margin") or 1.0))
        papers.update([a, b])
        if winner == "tie":
            wins[(a, b)] += 0.5
            wins[(b, a)] += 0.5
        elif winner == a:
            wins[(a, b)] += margin
        elif winner == b:
            wins[(b, a)] += margin
        else:
            raise SystemExit(f"winner must be {a}, {b}, or tie: {winner}")
    return papers, wins


def bradley_terry(papers: set[str], wins: dict[tuple[str, str], float], iterations: int = 200, prior: float = 0.5) -> dict[str, float]:
    if not papers:
        return {}
    strength = {paper: 1.0 for paper in papers}
    opponents = {paper: set() for paper in papers}
    for a, b in wins:
        opponents[a].add(b)
        opponents[b].add(a)

    for _ in range(iterations):
        next_strength = {}
        for paper in papers:
            total_wins = prior + sum(wins.get((paper, opp), 0.0) for opp in opponents[paper])
            denom = 0.0
            for opp in opponents[paper]:
                games = wins.get((paper, opp), 0.0) + wins.get((opp, paper), 0.0) + 2 * prior / max(1, len(opponents[paper]))
                if games:
                    denom += games / (strength[paper] + strength[opp])
            next_strength[paper] = total_wins / denom if denom > 0 else strength[paper]
        mean_strength = sum(next_strength.values()) / len(next_strength)
        if mean_strength > 0:
            next_strength = {paper: value / mean_strength for paper, value in next_strength.items()}
        strength = next_strength
    return strength


def summarize(rows: list[dict[str, Any]], dimension: str = "") -> list[dict[str, Any]]:
    rows = filter_rows(rows, dimension)
    papers, wins = win_matrix(rows)
    strength = bradley_terry(papers, wins)
    stats: dict[str, dict[str, float]] = {
        paper: {"wins": 0.0, "losses": 0.0, "ties": 0.0, "games": 0.0, "net_margin": 0.0}
        for paper in papers
    }
    for row in rows:
        a, b = row["paper_a"], row["paper_b"]
        winner = row["winner"]
        margin = max(0.1, float(row.get("margin") or 1.0))
        stats[a]["games"] += 1
        stats[b]["games"] += 1
        if winner == "tie":
            stats[a]["ties"] += 1
            stats[b]["ties"] += 1
        elif winner == a:
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
            stats[a]["net_margin"] += margin
            stats[b]["net_margin"] -= margin
        elif winner == b:
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1
            stats[b]["net_margin"] += margin
            stats[a]["net_margin"] -= margin

    ranking = []
    for paper, item in stats.items():
        games = item["games"] or 1.0
        bt = strength.get(paper, 1.0)
        ranking.append(
            {
                "paper_id": paper,
                "games": int(item["games"]),
                "wins": item["wins"],
                "losses": item["losses"],
                "ties": item["ties"],
                "win_rate": round((item["wins"] + 0.5 * item["ties"]) / games, 3),
                "net_margin": round(item["net_margin"], 3),
                "bt_strength": round(bt, 4),
                "bt_logit": round(math.log(bt), 4) if bt > 0 else None,
            }
        )
    ranking.sort(key=lambda row: (row["bt_strength"], row["win_rate"], row["net_margin"]), reverse=True)
    for idx, row in enumerate(ranking, 1):
        row["rank"] = idx
    return ranking


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate pairwise paper judgments.")
    parser.add_argument("jsonl", help="JSONL input path, or - for stdin.")
    parser.add_argument("--dimension", default="", help="Optional dimension filter.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument("--markdown", action="store_true", help="Print a markdown table instead of JSON.")
    args = parser.parse_args()

    ranking = summarize(load_rows(args.jsonl), args.dimension)
    if args.output:
        Path(args.output).write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown:
        print("| Rank | Paper | BT Strength | Win Rate | W-L-T | Net Margin |")
        print("|---:|---|---:|---:|---:|---:|")
        for row in ranking:
            print(
                f"| {row['rank']} | {row['paper_id']} | {row['bt_strength']:.4f} | "
                f"{row['win_rate']:.3f} | {row['wins']}-{row['losses']}-{row['ties']} | "
                f"{row['net_margin']:.2f} |"
            )
    else:
        print(json.dumps(ranking, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
