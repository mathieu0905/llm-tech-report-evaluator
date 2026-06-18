#!/usr/bin/env python3
"""Evidence library for the LLM tech report evaluator.

This SQLite library stores reusable paper material, public review evidence,
per-run score history, pairwise judgments, anchors, and calibration events.

It is still not a leaderboard. Every evaluation run must re-read the papers,
build its own comparison context, and recompute scores. Historical data is used
only as calibration evidence: review conflicts, score drift, anchor mismatch,
and uncertainty checks.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = SKILL_DIR / "cache"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    authors       TEXT,
    venue         TEXT,
    year          INTEGER,
    track         TEXT,
    ptype         TEXT,
    accepted      TEXT,
    acceptance_evidence TEXT,
    openreview_rating   TEXT,
    openreview_decision TEXT,
    keywords      TEXT,
    abstract      TEXT,
    source_url    TEXT,
    pdf_path      TEXT,
    added_date    TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    paper_id   TEXT,
    run_slug   TEXT,
    innovation REAL,
    value      REAL,
    rigor      REAL,
    aesthetics REAL,
    total      REAL,
    scored_date TEXT,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id      TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_id     TEXT,
    reviewer      TEXT,
    rating        REAL,
    rating_scale  TEXT,
    confidence    REAL,
    decision      TEXT,
    review_text   TEXT,
    strengths     TEXT,
    weaknesses    TEXT,
    summary       TEXT,
    metadata_json TEXT,
    created_date  TEXT,
    UNIQUE(paper_id, source, source_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    run_slug    TEXT,
    topic       TEXT,
    target_ids  TEXT,
    pool_ids    TEXT,
    anchor_ids  TEXT,
    run_dir     TEXT,
    created_date TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS pairwise_judgments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    dimension    TEXT NOT NULL,
    paper_a      TEXT NOT NULL,
    paper_b      TEXT NOT NULL,
    winner       TEXT NOT NULL,
    margin       REAL,
    confidence   TEXT,
    evidence     TEXT,
    judge        TEXT,
    created_date TEXT
);

CREATE TABLE IF NOT EXISTS calibration_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    paper_id     TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    dimension    TEXT,
    before_score REAL,
    after_score  REAL,
    severity     TEXT,
    explanation  TEXT,
    created_date TEXT
);

CREATE TABLE IF NOT EXISTS anchors (
    topic      TEXT NOT NULL,
    paper_id   TEXT NOT NULL,
    tier       TEXT NOT NULL,
    dimension  TEXT NOT NULL DEFAULT 'overall',
    note       TEXT,
    created_date TEXT,
    PRIMARY KEY(topic, paper_id, dimension)
);
"""

SCORE_EXTRA_COLUMNS = {
    "run_id": "TEXT",
    "paper_role": "TEXT",
    "confidence": "TEXT",
    "calibrated": "TEXT",
    "pool_context": "TEXT",
    "evidence_json": "TEXT",
    "review_alignment": "TEXT",
    "history_note": "TEXT",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(cache_dir: Path) -> sqlite3.Connection:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "pdfs").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_dir / "papers.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(scores)")}
    for name, decl in SCORE_EXTRA_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE scores ADD COLUMN {name} {decl}")
    conn.commit()


def as_json(value: str) -> str:
    if not value:
        return ""
    try:
        json.loads(value)
    except json.JSONDecodeError as exc:
        sys.exit(f"Invalid JSON: {exc}")
    return value


def split_ids(value: str) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        return [str(item) for item in parsed]
    return [item.strip() for item in stripped.replace(";", ",").split(",") if item.strip()]


def parse_score_map(args: argparse.Namespace) -> dict[str, float | None]:
    return {
        "innovation": args.innovation,
        "value": args.value,
        "rigor": args.rigor,
        "aesthetics": args.aesthetics,
        "total": args.total,
    }


def numeric_values(rows: list[sqlite3.Row], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row[key]
        if value is not None:
            values.append(float(value))
    return values


def summarize_scores(rows: list[sqlite3.Row]) -> dict[str, dict[str, float | int | None]]:
    out: dict[str, dict[str, float | int | None]] = {}
    for key in ("innovation", "value", "rigor", "aesthetics", "total"):
        vals = numeric_values(rows, key)
        out[key] = {
            "n": len(vals),
            "mean": round(mean(vals), 3) if vals else None,
            "std": round(pstdev(vals), 3) if len(vals) > 1 else 0.0 if vals else None,
            "min": round(min(vals), 3) if vals else None,
            "max": round(max(vals), 3) if vals else None,
        }
    return out


def summarize_reviews(rows: list[sqlite3.Row]) -> dict[str, Any]:
    ratings = numeric_values(rows, "rating")
    confidences = numeric_values(rows, "confidence")
    decisions = [row["decision"] for row in rows if row["decision"]]
    return {
        "count": len(rows),
        "rating_mean": round(mean(ratings), 3) if ratings else None,
        "rating_std": round(pstdev(ratings), 3) if len(ratings) > 1 else 0.0 if ratings else None,
        "rating_scale": next((row["rating_scale"] for row in rows if row["rating_scale"]), ""),
        "confidence_mean": round(mean(confidences), 3) if confidences else None,
        "decisions": sorted(set(decisions)),
    }


def paper_exists(conn: sqlite3.Connection, paper_id: str) -> bool:
    return conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is not None


def save_review(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO reviews
           (paper_id,source,source_id,reviewer,rating,rating_scale,confidence,decision,
            review_text,strengths,weaknesses,summary,metadata_json,created_date)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(paper_id, source, source_id) DO UPDATE SET
             reviewer=excluded.reviewer,
             rating=excluded.rating,
             rating_scale=excluded.rating_scale,
             confidence=excluded.confidence,
             decision=excluded.decision,
             review_text=excluded.review_text,
             strengths=excluded.strengths,
             weaknesses=excluded.weaknesses,
             summary=excluded.summary,
             metadata_json=excluded.metadata_json,
             created_date=excluded.created_date
        """,
        (
            data.get("paper_id", ""),
            data.get("source", ""),
            data.get("source_id", ""),
            data.get("reviewer", ""),
            data.get("rating"),
            data.get("rating_scale", ""),
            data.get("confidence"),
            data.get("decision", ""),
            data.get("review_text", ""),
            data.get("strengths", ""),
            data.get("weaknesses", ""),
            data.get("summary", ""),
            data.get("metadata_json", ""),
            now_stamp(),
        ),
    )


def cmd_init(args, conn, cache_dir):
    print(f"Initialized evidence library at {cache_dir / 'papers.db'}")


def cmd_add(args, conn, cache_dir):
    pdf_path = ""
    if args.pdf:
        src = Path(args.pdf).expanduser().resolve()
        if not src.exists():
            sys.exit(f"PDF not found: {src}")
        dest = cache_dir / "pdfs" / f"{args.id}.pdf"
        if src != dest:
            shutil.copy2(src, dest)
        pdf_path = str(dest)
    conn.execute(
        """INSERT INTO papers
           (id,title,authors,venue,year,track,ptype,accepted,acceptance_evidence,
            openreview_rating,openreview_decision,keywords,abstract,source_url,pdf_path,added_date)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             title=excluded.title,
             authors=excluded.authors,
             venue=excluded.venue,
             year=excluded.year,
             track=excluded.track,
             ptype=excluded.ptype,
             accepted=excluded.accepted,
             acceptance_evidence=excluded.acceptance_evidence,
             openreview_rating=excluded.openreview_rating,
             openreview_decision=excluded.openreview_decision,
             keywords=excluded.keywords,
             abstract=excluded.abstract,
             source_url=excluded.source_url,
             pdf_path=CASE WHEN excluded.pdf_path != '' THEN excluded.pdf_path ELSE papers.pdf_path END,
             added_date=excluded.added_date
        """,
        (
            args.id,
            args.title,
            args.authors,
            args.venue,
            args.year,
            args.track,
            args.ptype,
            args.accepted,
            args.acceptance_evidence,
            args.openreview_rating,
            args.openreview_decision,
            args.keywords,
            args.abstract,
            args.source_url,
            pdf_path,
            now_iso(),
        ),
    )
    conn.commit()
    suffix = "  (PDF cached)" if pdf_path else "  (metadata only)"
    print(f"Saved {args.id}: {args.title}{suffix}")


def cmd_search(args, conn, cache_dir):
    terms = [t.strip() for t in args.query.replace(",", " ").split() if t.strip()]
    if not terms:
        sys.exit("Provide at least one keyword.")
    clauses, params = [], []
    for term in terms:
        clauses.append("(title LIKE ? OR keywords LIKE ? OR abstract LIKE ? OR venue LIKE ?)")
        params += [f"%{term}%"] * 4
    sql = "SELECT * FROM papers WHERE " + " OR ".join(clauses)
    rows = conn.execute(sql, params).fetchall()

    def score(row: sqlite3.Row) -> int:
        hay = " ".join(str(row[col] or "") for col in ("title", "keywords", "abstract", "venue")).lower()
        return sum(1 for term in terms if term.lower() in hay)

    rows = sorted(rows, key=score, reverse=True)
    if args.json:
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No cached papers match. Proceed with fresh web discovery.")
        return
    print(f"{len(rows)} cached match(es) for: {', '.join(terms)}\n")
    for row in rows:
        has_pdf = "PDF" if (row["pdf_path"] and Path(row["pdf_path"]).exists()) else "meta-only"
        reviews = conn.execute("SELECT COUNT(*) AS n FROM reviews WHERE paper_id=?", (row["id"],)).fetchone()["n"]
        score_rows = conn.execute("SELECT COUNT(*) AS n FROM scores WHERE paper_id=?", (row["id"],)).fetchone()["n"]
        print(f"  [{row['id']}] {row['title']}")
        print(
            f"      {row['venue']} | {row['ptype']} | accepted={row['accepted']} | "
            f"{has_pdf} | reviews={reviews} | score_runs={score_rows} | "
            f"matched={score(row)}/{len(terms)}"
        )


def cmd_get(args, conn, cache_dir):
    row = conn.execute("SELECT * FROM papers WHERE id=?", (args.id,)).fetchone()
    if not row:
        sys.exit(f"Not found: {args.id}")
    data: dict[str, Any] = {"paper": dict(row)}
    if args.with_evidence:
        data["reviews"] = [dict(r) for r in conn.execute("SELECT * FROM reviews WHERE paper_id=? ORDER BY created_date", (args.id,))]
        score_rows = conn.execute("SELECT * FROM scores WHERE paper_id=? ORDER BY scored_date", (args.id,)).fetchall()
        data["score_history"] = [dict(r) for r in score_rows]
        data["score_summary"] = summarize_scores(score_rows)
        data["calibration_events"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM calibration_events WHERE paper_id=? ORDER BY created_date",
                (args.id,),
            )
        ]
    print(json.dumps(data if args.with_evidence else dict(row), ensure_ascii=False, indent=2))


def cmd_list(args, conn, cache_dir):
    rows = conn.execute("SELECT * FROM papers ORDER BY added_date DESC, id").fetchall()
    print(f"{len(rows)} paper(s) in library:")
    for row in rows:
        has_pdf = "PDF" if (row["pdf_path"] and Path(row["pdf_path"]).exists()) else "meta"
        print(f"  [{row['id']}] {row['title']}  ({row['venue']}, {has_pdf})")


def cmd_link(args, conn, cache_dir):
    row = conn.execute("SELECT * FROM papers WHERE id=?", (args.id,)).fetchone()
    if not row:
        sys.exit(f"Not found: {args.id}")
    if not row["pdf_path"] or not Path(row["pdf_path"]).exists():
        sys.exit(f"No cached PDF for {args.id}; fetch it fresh.")
    dest_dir = Path(args.dest_dir).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.id}.pdf"
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(row["pdf_path"])
    print(f"Linked {args.id} -> {dest}")


def cmd_record_run(args, conn, cache_dir):
    run_id = args.run_id or args.run_slug
    if not run_id:
        sys.exit("Provide --run-id or --run-slug.")
    conn.execute(
        """INSERT INTO runs
           (run_id,run_slug,topic,target_ids,pool_ids,anchor_ids,run_dir,created_date,notes)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(run_id) DO UPDATE SET
             run_slug=excluded.run_slug,
             topic=excluded.topic,
             target_ids=excluded.target_ids,
             pool_ids=excluded.pool_ids,
             anchor_ids=excluded.anchor_ids,
             run_dir=excluded.run_dir,
             notes=excluded.notes
        """,
        (
            run_id,
            args.run_slug,
            args.topic,
            json.dumps(split_ids(args.targets), ensure_ascii=False),
            json.dumps(split_ids(args.pool), ensure_ascii=False),
            json.dumps(split_ids(args.anchors), ensure_ascii=False),
            str(Path(args.run_dir).expanduser().resolve()) if args.run_dir else "",
            now_stamp(),
            args.notes,
        ),
    )
    conn.commit()
    print(f"Recorded run {run_id}")


def cmd_runs(args, conn, cache_dir):
    rows = conn.execute("SELECT * FROM runs ORDER BY created_date DESC").fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    print(f"{len(rows)} run(s):")
    for row in rows:
        print(f"  [{row['run_id']}] {row['topic']} | {row['run_slug']} | {row['created_date']}")


def cmd_record_score(args, conn, cache_dir):
    evidence_json = as_json(args.evidence_json)
    conn.execute(
        """INSERT INTO scores
           (paper_id,run_slug,innovation,value,rigor,aesthetics,total,scored_date,note,
            run_id,paper_role,confidence,calibrated,pool_context,evidence_json,
            review_alignment,history_note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            args.id,
            args.run_slug,
            args.innovation,
            args.value,
            args.rigor,
            args.aesthetics,
            args.total,
            now_iso(),
            args.note,
            args.run_id,
            args.role,
            args.confidence,
            args.calibrated,
            args.pool_context,
            evidence_json,
            args.review_alignment,
            args.history_note,
        ),
    )
    conn.commit()
    print(f"Recorded reference score for {args.id} in run {args.run_slug or args.run_id}")


def cmd_history(args, conn, cache_dir):
    rows = conn.execute("SELECT * FROM scores WHERE paper_id=? ORDER BY scored_date", (args.id,)).fetchall()
    summary = summarize_scores(rows)
    if args.json:
        print(json.dumps({"paper_id": args.id, "summary": summary, "scores": [dict(r) for r in rows]}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print(f"No score history for {args.id}.")
        return
    print(f"Score history for {args.id} ({len(rows)} run(s))")
    for key, item in summary.items():
        print(f"  {key}: n={item['n']} mean={item['mean']} std={item['std']} min={item['min']} max={item['max']}")
    print("\nRuns:")
    for row in rows:
        print(
            f"  {row['scored_date']} {row['run_slug'] or row['run_id']}: "
            f"I={row['innovation']} V={row['value']} R={row['rigor']} "
            f"A={row['aesthetics']} T={row['total']} confidence={row['confidence'] or ''}"
        )


def cmd_drift_check(args, conn, cache_dir):
    rows = conn.execute("SELECT * FROM scores WHERE paper_id=? ORDER BY scored_date", (args.id,)).fetchall()
    current = parse_score_map(args)
    summary = summarize_scores(rows)
    events = []
    for key, value in current.items():
        if value is None:
            continue
        hist = summary[key]
        if not hist["n"] or hist["mean"] is None:
            continue
        delta = round(float(value) - float(hist["mean"]), 3)
        std = float(hist["std"] or 0.0)
        threshold = args.threshold
        if abs(delta) >= threshold or (std > 0 and abs(delta) >= args.std_multiplier * std):
            events.append(
                {
                    "dimension": key,
                    "current": value,
                    "historical_mean": hist["mean"],
                    "historical_std": hist["std"],
                    "delta": delta,
                    "history_n": hist["n"],
                    "requires_explanation": True,
                }
            )
    if args.json:
        print(json.dumps({"paper_id": args.id, "events": events, "summary": summary}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print(f"No prior score history for {args.id}; no drift check possible.")
        return
    if not events:
        print(f"No score drift above threshold for {args.id}.")
        return
    print(f"Score drift check for {args.id}:")
    for event in events:
        print(
            f"  {event['dimension']}: current={event['current']} "
            f"history_mean={event['historical_mean']} std={event['historical_std']} "
            f"delta={event['delta']} (n={event['history_n']})"
        )


def cmd_record_review(args, conn, cache_dir):
    save_review(
        conn,
        {
            "paper_id": args.paper_id,
            "source": args.source,
            "source_id": args.source_id or f"manual-{now_stamp()}",
            "reviewer": args.reviewer,
            "rating": args.rating,
            "rating_scale": args.rating_scale,
            "confidence": args.confidence,
            "decision": args.decision,
            "review_text": args.review_text,
            "strengths": args.strengths,
            "weaknesses": args.weaknesses,
            "summary": args.summary,
            "metadata_json": as_json(args.metadata_json),
        },
    )
    conn.commit()
    print(f"Recorded review evidence for {args.paper_id} from {args.source}")


def cmd_reviews(args, conn, cache_dir):
    rows = conn.execute("SELECT * FROM reviews WHERE paper_id=? ORDER BY created_date", (args.id,)).fetchall()
    summary = summarize_reviews(rows)
    if args.json:
        print(json.dumps({"paper_id": args.id, "summary": summary, "reviews": [dict(r) for r in rows]}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print(f"No review evidence for {args.id}.")
        return
    print(
        f"Review evidence for {args.id}: count={summary['count']} "
        f"rating_mean={summary['rating_mean']} scale={summary['rating_scale']} "
        f"confidence_mean={summary['confidence_mean']} decisions={', '.join(summary['decisions'])}"
    )
    if args.verbose:
        for row in rows:
            label = row["source_id"] or row["reviewer"] or row["source"]
            print(f"\n[{label}] rating={row['rating']} confidence={row['confidence']} decision={row['decision']}")
            for key in ("summary", "strengths", "weaknesses", "review_text"):
                text = row[key]
                if text:
                    print(f"{key}: {text[:args.max_chars]}")


def cmd_record_pairwise(args, conn, cache_dir):
    if args.winner not in {args.paper_a, args.paper_b, "tie"}:
        sys.exit("--winner must be paper_a, paper_b, or tie.")
    conn.execute(
        """INSERT INTO pairwise_judgments
           (run_id,dimension,paper_a,paper_b,winner,margin,confidence,evidence,judge,created_date)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            args.run_id,
            args.dimension,
            args.paper_a,
            args.paper_b,
            args.winner,
            args.margin,
            args.confidence,
            args.evidence,
            args.judge,
            now_stamp(),
        ),
    )
    conn.commit()
    print(f"Recorded pairwise judgment for {args.run_id}: {args.paper_a} vs {args.paper_b}")


def cmd_pairwise_summary(args, conn, cache_dir):
    params: list[Any] = [args.run_id]
    where = "run_id=?"
    if args.dimension:
        where += " AND dimension=?"
        params.append(args.dimension)
    rows = conn.execute(f"SELECT * FROM pairwise_judgments WHERE {where}", params).fetchall()
    stats: dict[str, dict[str, float]] = {}
    for row in rows:
        a, b, winner = row["paper_a"], row["paper_b"], row["winner"]
        margin = float(row["margin"] if row["margin"] is not None else 1.0)
        margin = max(0.1, margin)
        for paper in (a, b):
            stats.setdefault(paper, {"wins": 0.0, "losses": 0.0, "ties": 0.0, "margin": 0.0, "games": 0.0})
            stats[paper]["games"] += 1
        if winner == "tie":
            stats[a]["ties"] += 1
            stats[b]["ties"] += 1
        elif winner == a:
            stats[a]["wins"] += 1
            stats[b]["losses"] += 1
            stats[a]["margin"] += margin
            stats[b]["margin"] -= margin
        elif winner == b:
            stats[b]["wins"] += 1
            stats[a]["losses"] += 1
            stats[b]["margin"] += margin
            stats[a]["margin"] -= margin
    ranked = []
    for paper, item in stats.items():
        games = item["games"] or 1.0
        ranked.append(
            {
                "paper_id": paper,
                "wins": item["wins"],
                "losses": item["losses"],
                "ties": item["ties"],
                "games": item["games"],
                "win_rate": round((item["wins"] + 0.5 * item["ties"]) / games, 3),
                "net_margin": round(item["margin"], 3),
            }
        )
    ranked.sort(key=lambda r: (r["win_rate"], r["net_margin"], -r["losses"]), reverse=True)
    if args.json:
        print(json.dumps({"run_id": args.run_id, "dimension": args.dimension, "ranking": ranked}, ensure_ascii=False, indent=2))
        return
    print(f"Pairwise summary for {args.run_id}" + (f" / {args.dimension}" if args.dimension else ""))
    for idx, row in enumerate(ranked, 1):
        print(
            f"  {idx}. {row['paper_id']} win_rate={row['win_rate']} "
            f"W-L-T={row['wins']}-{row['losses']}-{row['ties']} net_margin={row['net_margin']}"
        )


def cmd_record_calibration(args, conn, cache_dir):
    conn.execute(
        """INSERT INTO calibration_events
           (run_id,paper_id,trigger_type,dimension,before_score,after_score,severity,explanation,created_date)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            args.run_id,
            args.paper_id,
            args.trigger_type,
            args.dimension,
            args.before_score,
            args.after_score,
            args.severity,
            args.explanation,
            now_stamp(),
        ),
    )
    conn.commit()
    print(f"Recorded calibration event for {args.paper_id}: {args.trigger_type}")


def cmd_calibrations(args, conn, cache_dir):
    params: list[Any] = []
    where = []
    if args.paper_id:
        where.append("paper_id=?")
        params.append(args.paper_id)
    if args.run_id:
        where.append("run_id=?")
        params.append(args.run_id)
    sql = "SELECT * FROM calibration_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_date DESC"
    rows = conn.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    print(f"{len(rows)} calibration event(s):")
    for row in rows:
        print(
            f"  {row['created_date']} [{row['trigger_type']}] {row['paper_id']} "
            f"{row['dimension'] or ''}: {row['before_score']} -> {row['after_score']} "
            f"severity={row['severity']}"
        )


def cmd_add_anchor(args, conn, cache_dir):
    if not paper_exists(conn, args.paper_id):
        print(f"Warning: {args.paper_id} is not in papers table yet.", file=sys.stderr)
    conn.execute(
        """INSERT INTO anchors (topic,paper_id,tier,dimension,note,created_date)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(topic,paper_id,dimension) DO UPDATE SET
             tier=excluded.tier,
             note=excluded.note,
             created_date=excluded.created_date
        """,
        (args.topic, args.paper_id, args.tier, args.dimension, args.note, now_stamp()),
    )
    conn.commit()
    print(f"Recorded anchor {args.paper_id} for topic {args.topic}")


def cmd_anchors(args, conn, cache_dir):
    params: list[Any] = []
    sql = "SELECT * FROM anchors"
    if args.topic:
        sql += " WHERE topic LIKE ?"
        params.append(f"%{args.topic}%")
    sql += " ORDER BY topic, dimension, tier DESC, paper_id"
    rows = conn.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No anchors recorded.")
        return
    for row in rows:
        print(f"  {row['topic']} | {row['dimension']} | {row['tier']} | {row['paper_id']} | {row['note'] or ''}")


def cmd_evidence_pack(args, conn, cache_dir):
    paper = conn.execute("SELECT * FROM papers WHERE id=?", (args.id,)).fetchone()
    if not paper:
        sys.exit(f"Not found: {args.id}")
    score_rows = conn.execute("SELECT * FROM scores WHERE paper_id=? ORDER BY scored_date", (args.id,)).fetchall()
    review_rows = conn.execute("SELECT * FROM reviews WHERE paper_id=? ORDER BY created_date", (args.id,)).fetchall()
    calibration_rows = conn.execute(
        "SELECT * FROM calibration_events WHERE paper_id=? ORDER BY created_date",
        (args.id,),
    ).fetchall()
    data = {
        "paper": dict(paper),
        "review_summary": summarize_reviews(review_rows),
        "reviews": [dict(r) for r in review_rows],
        "score_summary": summarize_scores(score_rows),
        "scores": [dict(r) for r in score_rows],
        "calibration_events": [dict(r) for r in calibration_rows],
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(description="Evidence library for review-calibrated comparative evaluation.")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="Cache directory (db + pdfs).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    add = sub.add_parser("add")
    add.add_argument("--id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--authors", default="")
    add.add_argument("--venue", default="")
    add.add_argument("--year", type=int, default=None)
    add.add_argument("--track", default="unknown")
    add.add_argument("--ptype", default="")
    add.add_argument("--accepted", default="unverified")
    add.add_argument("--acceptance-evidence", default="")
    add.add_argument("--openreview-rating", default="")
    add.add_argument("--openreview-decision", default="")
    add.add_argument("--keywords", default="")
    add.add_argument("--abstract", default="")
    add.add_argument("--source-url", default="")
    add.add_argument("--pdf", default="", help="Path to PDF to copy into the cache.")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--json", action="store_true")

    get = sub.add_parser("get")
    get.add_argument("id")
    get.add_argument("--with-evidence", action="store_true")

    sub.add_parser("list")

    link = sub.add_parser("link")
    link.add_argument("id")
    link.add_argument("dest_dir")

    run = sub.add_parser("record-run")
    run.add_argument("--run-id", default="")
    run.add_argument("--run-slug", default="")
    run.add_argument("--topic", default="")
    run.add_argument("--targets", default="", help="Comma-separated ids or JSON list.")
    run.add_argument("--pool", default="", help="Comma-separated ids or JSON list.")
    run.add_argument("--anchors", default="", help="Comma-separated ids or JSON list.")
    run.add_argument("--run-dir", default="")
    run.add_argument("--notes", default="")

    runs = sub.add_parser("runs")
    runs.add_argument("--json", action="store_true")

    score = sub.add_parser("record-score")
    score.add_argument("--id", required=True)
    score.add_argument("--run-slug", default="")
    score.add_argument("--run-id", default="")
    score.add_argument("--role", default="")
    score.add_argument("--innovation", type=float, default=None)
    score.add_argument("--value", type=float, default=None)
    score.add_argument("--rigor", type=float, default=None)
    score.add_argument("--aesthetics", type=float, default=None)
    score.add_argument("--total", type=float, default=None)
    score.add_argument("--confidence", default="")
    score.add_argument("--calibrated", default="yes")
    score.add_argument("--pool-context", default="")
    score.add_argument("--evidence-json", default="")
    score.add_argument("--review-alignment", default="")
    score.add_argument("--history-note", default="")
    score.add_argument("--note", default="")

    hist = sub.add_parser("history")
    hist.add_argument("id")
    hist.add_argument("--json", action="store_true")

    drift = sub.add_parser("drift-check")
    drift.add_argument("id")
    drift.add_argument("--innovation", type=float, default=None)
    drift.add_argument("--value", type=float, default=None)
    drift.add_argument("--rigor", type=float, default=None)
    drift.add_argument("--aesthetics", type=float, default=None)
    drift.add_argument("--total", type=float, default=None)
    drift.add_argument("--threshold", type=float, default=1.0)
    drift.add_argument("--std-multiplier", type=float, default=2.0)
    drift.add_argument("--json", action="store_true")

    review = sub.add_parser("record-review")
    review.add_argument("--paper-id", required=True)
    review.add_argument("--source", default="manual")
    review.add_argument("--source-id", default="")
    review.add_argument("--reviewer", default="")
    review.add_argument("--rating", type=float, default=None)
    review.add_argument("--rating-scale", default="")
    review.add_argument("--confidence", type=float, default=None)
    review.add_argument("--decision", default="")
    review.add_argument("--review-text", default="")
    review.add_argument("--strengths", default="")
    review.add_argument("--weaknesses", default="")
    review.add_argument("--summary", default="")
    review.add_argument("--metadata-json", default="")

    reviews = sub.add_parser("reviews")
    reviews.add_argument("id")
    reviews.add_argument("--json", action="store_true")
    reviews.add_argument("--verbose", action="store_true")
    reviews.add_argument("--max-chars", type=int, default=1200)

    pair = sub.add_parser("record-pairwise")
    pair.add_argument("--run-id", required=True)
    pair.add_argument("--dimension", required=True, choices=["innovation", "value", "rigor", "aesthetics", "overall"])
    pair.add_argument("--paper-a", required=True)
    pair.add_argument("--paper-b", required=True)
    pair.add_argument("--winner", required=True)
    pair.add_argument("--margin", type=float, default=1.0)
    pair.add_argument("--confidence", default="")
    pair.add_argument("--evidence", default="")
    pair.add_argument("--judge", default="")

    psum = sub.add_parser("pairwise-summary")
    psum.add_argument("--run-id", required=True)
    psum.add_argument("--dimension", default="")
    psum.add_argument("--json", action="store_true")

    cal = sub.add_parser("record-calibration")
    cal.add_argument("--run-id", default="")
    cal.add_argument("--paper-id", required=True)
    cal.add_argument("--trigger-type", required=True, choices=["review_conflict", "historical_drift", "anchor_mismatch", "pool_strength", "pairwise_absolute_mismatch", "manual"])
    cal.add_argument("--dimension", default="")
    cal.add_argument("--before-score", type=float, default=None)
    cal.add_argument("--after-score", type=float, default=None)
    cal.add_argument("--severity", default="medium")
    cal.add_argument("--explanation", default="")

    cals = sub.add_parser("calibrations")
    cals.add_argument("--paper-id", default="")
    cals.add_argument("--run-id", default="")
    cals.add_argument("--json", action="store_true")

    anchor = sub.add_parser("add-anchor")
    anchor.add_argument("--topic", required=True)
    anchor.add_argument("--paper-id", required=True)
    anchor.add_argument("--tier", required=True, choices=["S", "A", "B", "C", "D"])
    anchor.add_argument("--dimension", default="overall")
    anchor.add_argument("--note", default="")

    anchors = sub.add_parser("anchors")
    anchors.add_argument("--topic", default="")
    anchors.add_argument("--json", action="store_true")

    pack = sub.add_parser("evidence-pack")
    pack.add_argument("id")

    return parser


DISPATCH = {
    "init": cmd_init,
    "add": cmd_add,
    "search": cmd_search,
    "get": cmd_get,
    "list": cmd_list,
    "link": cmd_link,
    "record-run": cmd_record_run,
    "runs": cmd_runs,
    "record-score": cmd_record_score,
    "history": cmd_history,
    "drift-check": cmd_drift_check,
    "record-review": cmd_record_review,
    "reviews": cmd_reviews,
    "record-pairwise": cmd_record_pairwise,
    "pairwise-summary": cmd_pairwise_summary,
    "record-calibration": cmd_record_calibration,
    "calibrations": cmd_calibrations,
    "add-anchor": cmd_add_anchor,
    "anchors": cmd_anchors,
    "evidence-pack": cmd_evidence_pack,
}


def main() -> None:
    args = build_parser().parse_args()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    conn = connect(cache_dir)
    DISPATCH[args.cmd](args, conn, cache_dir)


if __name__ == "__main__":
    main()
