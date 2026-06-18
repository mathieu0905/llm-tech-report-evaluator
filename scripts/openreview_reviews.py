#!/usr/bin/env python3
"""Fetch public OpenReview evidence into the local paper evidence library.

Usage:
    openreview_reviews.py --paper-id <library-id> --forum <openreview-id>

The script intentionally uses the OpenReview REST API instead of scraping the
JS-rendered forum page. It stores official reviews, meta reviews, decisions,
ratings, and confidence values as calibration evidence in paper_db.py's SQLite
library.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import paper_db


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "codex-llm-tech-report-evaluator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def content_value(content: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name not in content:
            continue
        value = content[name]
        if isinstance(value, dict) and "value" in value:
            return value["value"]
        return value
    return None


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def infer_rating_scale(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    match = re.search(r"/\s*(\d+(?:\.\d+)?)", text)
    if match:
        return f"1-{match.group(1)}"
    if "10" in text:
        return "1-10"
    if "6" in text:
        return "1-6"
    return ""


def note_kind(note: dict[str, Any]) -> str:
    invitations = " ".join(note.get("invitations") or [])
    signatures = " ".join(note.get("signatures") or [])
    text = f"{invitations} {signatures}".lower()
    if "decision" in text:
        return "decision"
    if "meta" in text:
        return "meta-review"
    if "official" in text and "review" in text:
        return "official-review"
    if "review" in text:
        return "review"
    if "comment" in text:
        return "comment"
    return "note"


def flatten_replies(payload: dict[str, Any]) -> list[dict[str, Any]]:
    notes = payload.get("notes") or []
    out: list[dict[str, Any]] = []
    for note in notes:
        out.append(note)
        details = note.get("details") or {}
        replies = details.get("replies") or note.get("replies") or []
        out.extend(replies)
    seen = set()
    unique = []
    for note in out:
        note_id = note.get("id") or json.dumps(note, sort_keys=True)
        if note_id in seen:
            continue
        seen.add(note_id)
        unique.append(note)
    return unique


def review_payload(paper_id: str, forum: str, note: dict[str, Any]) -> dict[str, Any] | None:
    content = note.get("content") or {}
    kind = note_kind(note)
    rating_raw = content_value(content, "rating", "recommendation")
    confidence_raw = content_value(content, "confidence")
    decision = content_value(content, "decision", "recommendation")
    review_text = content_value(content, "review", "main_review", "comment")
    summary = content_value(content, "summary", "paper_summary", "metareview", "meta_review")
    strengths = content_value(content, "strengths", "strength")
    weaknesses = content_value(content, "weaknesses", "weakness", "limitations")

    has_signal = any([rating_raw, confidence_raw, decision, review_text, summary, strengths, weaknesses])
    if kind == "note" and not has_signal:
        return None

    source_id = note.get("id") or f"{forum}:{kind}:{len(json.dumps(note, sort_keys=True))}"
    signatures = note.get("signatures") or []
    metadata = {
        "forum": forum,
        "kind": kind,
        "invitation": note.get("invitation", ""),
        "invitations": note.get("invitations", []),
        "raw_rating": rating_raw,
        "raw_confidence": confidence_raw,
    }
    return {
        "paper_id": paper_id,
        "source": "openreview",
        "source_id": source_id,
        "reviewer": ", ".join(signatures),
        "rating": parse_number(rating_raw),
        "rating_scale": infer_rating_scale(rating_raw),
        "confidence": parse_number(confidence_raw),
        "decision": str(decision or "") if kind in {"decision", "meta-review"} or decision else "",
        "review_text": str(review_text or ""),
        "strengths": str(strengths or ""),
        "weaknesses": str(weaknesses or ""),
        "summary": str(summary or ""),
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
        "kind": kind,
    }


def update_paper_openreview_fields(conn: sqlite3.Connection, paper_id: str, rows: list[dict[str, Any]]) -> None:
    ratings = [row["rating"] for row in rows if row.get("rating") is not None]
    scales = [row["rating_scale"] for row in rows if row.get("rating_scale")]
    decisions = [row["decision"] for row in rows if row.get("decision")]
    rating_text = ""
    if ratings:
        rating_text = f"mean={mean(ratings):.2f}; std={(pstdev(ratings) if len(ratings) > 1 else 0.0):.2f}; n={len(ratings)}"
        if scales:
            rating_text += f"; scale={scales[0]}"
    decision_text = "; ".join(sorted(set(decisions)))
    conn.execute(
        """UPDATE papers
           SET openreview_rating=CASE WHEN ? != '' THEN ? ELSE openreview_rating END,
               openreview_decision=CASE WHEN ? != '' THEN ? ELSE openreview_decision END
           WHERE id=?""",
        (rating_text, rating_text, decision_text, decision_text, paper_id),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OpenReview reviews into paper_db evidence tables.")
    parser.add_argument("--paper-id", required=True, help="Paper id in the local evidence library.")
    parser.add_argument("--forum", required=True, help="OpenReview forum id, usually the paper id in the URL.")
    parser.add_argument("--cache-dir", default=str(paper_db.DEFAULT_CACHE), help="paper_db cache directory.")
    parser.add_argument("--api-base", default="https://api2.openreview.net", help="OpenReview API base URL.")
    parser.add_argument("--output", default="", help="Optional JSON file for the raw fetched payload.")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir).expanduser().resolve()
    conn = paper_db.connect(cache_dir)
    if not paper_db.paper_exists(conn, args.paper_id):
        print(f"Warning: {args.paper_id} is not in papers table yet; reviews will still be stored.", file=sys.stderr)

    query = urllib.parse.urlencode({"forum": args.forum, "details": "replies"})
    url = f"{args.api_base.rstrip('/')}/notes?{query}"
    payload = fetch_json(url, timeout=args.timeout)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    stored: list[dict[str, Any]] = []
    for note in flatten_replies(payload):
        row = review_payload(args.paper_id, args.forum, note)
        if not row:
            continue
        paper_db.save_review(conn, row)
        stored.append(row)
    update_paper_openreview_fields(conn, args.paper_id, stored)
    conn.commit()

    ratings = [row["rating"] for row in stored if row.get("rating") is not None]
    decisions = sorted({row["decision"] for row in stored if row.get("decision")})
    kinds: dict[str, int] = {}
    for row in stored:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    result = {
        "paper_id": args.paper_id,
        "forum": args.forum,
        "stored": len(stored),
        "kinds": kinds,
        "rating_mean": round(mean(ratings), 3) if ratings else None,
        "rating_count": len(ratings),
        "decisions": decisions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
