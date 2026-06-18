---
name: llm-tech-report-evaluator
description: Evaluate, compare, calibrate, and rank research papers or LLM/foundation-model technical reports from PDFs, extracted text, or paper titles/topics. Use when Codex is asked to score papers on innovation/value/rigor, find related comparison papers, compare model technical reports, use public reviews for calibration, analyze historical score drift, create tier lists, or write image-generation prompts summarizing rankings.
---

# LLM Tech Report Evaluator

## Core Contract

Treat each invocation as one self-contained evaluation run. For a single target paper, Codex finds or accepts a comparison pool, scores that target with the pool, calibrates the judgment, and ranks only that run's papers.

For multiple target papers that are candidate submissions, manuscripts to review, or otherwise separate evaluation objects, use **multi-target local-review mode** by default: keep one coordinator run, but split the work into one independent sub-run per target paper. Each target gets its own closest-topic comparison pool and its own target-focused judgment. Do not rank the target papers against each other unless the user explicitly asks for a head-to-head ranking.

When the user asks for submission outcome, "中稿几率", PC-style review, or venue decision risk for SE venues, use the 10-point Innovation / Paper Value / Rigor rubric as the default scoring output. Do not output four-point reviewer recommendation scores unless the user explicitly asks for four-point PC simulation. Instead, provide several independent reviewer-style textual concerns and an area-chair style synthesis. The reviewers are independent complete reviewers, not preassigned personas: each reviewer considers novelty, value, rigor, presentation, fit, and risk. Do not force one reviewer to be "strict rigor", one to be "innovation", and one to be "balanced"; any emphasis differences should emerge naturally from independent readings. If four-point recommendations are explicitly requested, derive them under the same standard as the local comparison pool and warn that the scale is coarse and can hide meaningful 10-point quality differences.

Three rules make repeated use reliable:

1. Keep every run isolated. Store target papers, downloaded comparison PDFs, extracted text, review payloads, pairwise judgments, and the final report inside that run's own directory. Inventory, extraction, and scoring must touch only that directory.
2. Never carry over rankings. Do not pull in, re-score, re-rank, or update papers from earlier runs unless the user explicitly asks to reuse or merge a previous run. If reusing material, confirm the exact directory and state what is being reused.
3. Use history as calibration evidence only. Public reviews, historical scores, anchors, and prior pairwise judgments can reveal bias or drift, but every run still needs fresh reading, fresh comparison, and fresh scoring.
4. In multi-target local-review mode, isolate target judgments. Other target papers from the same user request are not comparison baselines unless they are genuinely same-topic anchors and the user asks to compare them.

## Multi-Target Local-Review Mode

Use this mode when the user supplies several papers as "targets", "submissions", "待审文章", or similar, and asks for review-quality evaluation.

- Start one coordinator run directory, then create one subdirectory per target such as `per_target/<target_id>/{target,pool,reviews,analysis,judgments}`.
- Spawn one independent subagent per target when subagent tooling is available. Each subagent evaluates exactly one target paper, builds or verifies that target's local pool, and writes a target-local review. If subagents are unavailable, simulate one isolated pass per target and disclose that limitation.
- Give each subagent only its target paper, the rubric, and its own local pool instructions. Do not give it the other target papers' scores or conclusions.
- For each target, build a closest-topic pool with both sides of the venue threshold when available:
  - accepted or published top-venue papers as positive anchors
  - rejected, withdrawn, arXiv-only, secondary-track, workshop, or otherwise unaccepted/unverified papers as negative or boundary calibration controls
- Label each pool paper's status clearly: accepted main-track, accepted secondary-track, rejected, withdrawn, arXiv-only, unverified, or metadata-only. Use non-accepted papers for calibration, not as evidence that the target is weak by association.
- Score the target and every paper in that target's local pool with the same rubric. The target-local report must include a calibration table with target, accepted anchors, and boundary controls all assigned Innovation, Paper Value, Rigor, Aesthetics, Total, confidence, and a short calibration note. For SE submission judgments, include independent reviewer-style textual concerns and an AC synthesis, but do not include four-point reviewer scores by default. Mark pool-paper scores as target-local calibration scores, not global or historical truth.
- The coordinator reconciles scale after subagents finish: check review evidence, historical drift, pairwise consistency within each local pool, and only then create a cross-target summary matrix. The final report is organized by target paper, not by a global rank of all target papers.

## Workflow

1. Set up the isolated run directory before any search or extraction.
   - Identify the target paper paths, extracted-text files, titles, or topic supplied by the user.
   - Build a run slug from the primary target's filename stem, title, or topic, for example `Run_Less_ISSTA.pdf` to `run_less`.
   - Create a fresh run directory at the invocation cwd root, not inside the user's source-paper folder:
     ```bash
     RUN_DIR="$PWD/eval_runs/<slug>__$(date +%Y%m%d_%H%M)"
     mkdir -p "$RUN_DIR/targets" "$RUN_DIR/pool" "$RUN_DIR/reviews" "$RUN_DIR/analysis" "$RUN_DIR/judgments"
     ```
   - For multi-target local-review mode, also create one isolated workspace per target:
     ```bash
     mkdir -p "$RUN_DIR/per_target/<target_id>"/{target,pool,reviews,analysis,judgments}
     ```
   - Link local target PDFs into `targets/` when possible so source files remain untouched:
     ```bash
     ln -s "/abs/path/to/Target.pdf" "$RUN_DIR/targets/Target.pdf"
     ```
   - If the user supplies extracted text instead of PDFs, copy or link it into `analysis/text/` and record the source in `run.md`.
   - Write `run.md` with date, target source paths or topic, and an initially empty pool list. This manifest is the source of truth for what is in scope.
   - From this point on, read PDFs and write artifacts only under `$RUN_DIR`.

2. Assemble the comparison pool, unless the user supplied a complete pool.
   - Check the local evidence library before web search:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py search "<target topic keywords>"
     ```
   - For same-topic, accepted, cached-PDF hits, reuse them by linking:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py link <id> "$RUN_DIR/pool"
     ```
   - Use web/search/browser tools when the user has not supplied a complete pool or asks to find/gather related papers. Derive a topic signature from the target: title, problem statement, method family, task, and 3-8 keywords.
   - Prefer same-topic comparability over broad fame. Aim for about 5-8 strong comparison papers unless the user asks for a different pool size.
   - Search across relevant top venues, not only the target paper's home field. Typical venues:
     - SE: ICSE, FSE/ESEC-FSE, ASE, ISSTA, TSE, TOSEM
     - ML/AI: NeurIPS, ICML, ICLR, AAAI, JMLR
     - NLP: ACL, EMNLP, NAACL, TACL
     - CV: CVPR, ICCV, ECCV, TPAMI
     - Security, systems, databases, and other fields: use the corresponding top venues
   - Apply a hard default acceptance gate for ordinary comparison pools: keep only papers already accepted or published at a top venue. Exclude arXiv-only papers without confirmed venue unless the user explicitly wants them.
   - In multi-target local-review mode, or whenever the user asks for rejected/unaccepted calibration, keep two labeled subsets instead of one pool: accepted top-venue anchors and non-accepted/secondary/unverified boundary controls.
   - Prefer main/research-track papers. Label or down-rank secondary tracks such as workshops, industry/in-practice tracks, Findings, short papers, demos, and posters.
   - Prefer recent papers from the last roughly 18 months. Include older baselines only when they are essential or requested, and label them as older baselines.
   - For OpenReview-hosted venues, fetch public review evidence with the bundled harvester:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/openreview_reviews.py \
       --paper-id <paper_id> \
       --forum <openreview_forum_id> \
       --output "$RUN_DIR/reviews/<paper_id>.openreview.json"
     ```
     Record average rating, rating scale, and decision when available. Use scores only as within-venue quality signals, not cross-scale absolutes.
   - Download every kept PDF into `$RUN_DIR/pool/`; never download into the repo root or the user's source folder. For arXiv PDFs:
     ```bash
     curl -L -o "$RUN_DIR/pool/<slug>.pdf" "https://arxiv.org/pdf/<arxiv-id>"
     ```
   - If no open PDF is available, record title, venue, year, abstract, and source URL. Either score from metadata with a lower-confidence note or ask the user for the PDF.
   - Append each kept paper to `run.md` with title, venue, year, type, PDF or metadata-only status, and why it is comparable. Show this pool to the user before scoring when the pool was auto-discovered.
   - Add newly confirmed pool papers back to the evidence library:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py add --id <id> --title "<title>" --pdf "$RUN_DIR/pool/<file>.pdf" --venue "<venue>" --year <year> --ptype "<type>" --accepted yes --keywords "<keywords>" --source-url "<url>"
     ```
     The library is a material and calibration evidence store, not a ranking store. Scores are recomputed fresh for each run.

3. Inventory and extract the run, scoped to `$RUN_DIR` only.
   - List PDFs with:
     ```bash
     rg --files -g '*.pdf' "$RUN_DIR"
     ```
   - Extract text with:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/extract_pdf_reports.py "$RUN_DIR"
     ```
   - Outputs go under `$RUN_DIR/analysis/`:
     - `analysis/text/<pdf-stem>.txt`
     - `analysis/pdf_summaries.json`
     - optional page PNGs when using `--render-pages`
   - Prefer local extracted text for scoring. Browse only for pool discovery, acceptance verification, missing paper metadata, or when the user asks for external verification.

4. Read each report with a paper-value lens.
   - Prioritize method sections, training or infrastructure details, ablations, evaluation protocol, limitations, and appendices.
   - Do not over-weight raw benchmark wins, business value, deployment popularity, or marketing claims.
   - Treat internal benchmarks as useful but weaker than transparent ablations, reproducible protocols, and failure analysis.

5. Use anonymous multi-reviewer scoring by default.
   - For multi-target local-review mode, first parallelize by target: spawn one independent subagent per target paper. Within each target subagent, use the reviewer styles below when tooling and budget allow.
   - When subagent tooling is available, run multiple blind reviewers concurrently and point each reviewer only at `$RUN_DIR/analysis/text/` plus the rubric. Use available multi-agent tooling rather than leaking one reviewer's conclusions into another.
   - Recommended reviewer styles: `strict-rigor`, `innovation`, `transferable-value`, and `skeptical-meta`.
   - Give each reviewer the same fixed rubric. Let style affect scrutiny and evidence selection, not the scoring formula.
- Ask reviewers to provide both dimension scores and pairwise comparisons for close papers. Store useful pairwise judgments as JSONL in `$RUN_DIR/judgments/pairwise_<dimension>.jsonl`.
   - For SE submission judgment, ask each reviewer pass for independent textual concerns and a confidence note. Do not ask for four-point recommendation scores unless explicitly requested. Reviewers should be independent complete reviewers rather than fixed personas. Each reviewer should evaluate the full paper, including novelty, value, rigor, presentation, fit, and risk; do not preassign one reviewer to be strict, positive, or skeptical.
   - The main Codex instance acts as area chair: collect reviews, reconcile large disagreements, and produce the final ranking with a short consensus/uncertainty note.
   - If subagents are unavailable, simulate separate blind review passes locally and explicitly disclose that real anonymous subagents were not used.

6. Score, compare, and calibrate with the fixed rubric.
   - Use `references/rubric.md` for dimension definitions, score anchors, tier labels, output format, calibration rules, and image-prompt templates.
   - Use `references/calibration.md` when public reviews, historical scores, anchors, or pairwise judgments are present.
   - `Total = 0.40 * Innovation + 0.40 * Intrinsic Paper Value + 0.20 * Rigor`
   - Keep `Aesthetics` as a separate reference column only. Do not include it in total unless the user changes the rule.
   - Use one decimal place for dimension scores and two decimals for totals.
   - Aggregate pairwise JSONL when available:
     ```bash
     python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/pairwise_rank.py "$RUN_DIR/judgments/pairwise_innovation.jsonl" --markdown
     ```
   - Before finalizing each paper, run `paper_db.py reviews <id>`, `paper_db.py history <id>`, and `paper_db.py drift-check <id> ...` when evidence exists. Record material score changes or justified disagreements with `record-calibration`.

7. Rank and explain.
   - Provide a table with rank, report/model, role, type, Innovation, Paper Value, Rigor, Aesthetics, Total, confidence, and calibration note. If the user's question is about submission outcome, keep the main table 10-point based and add likely AC read plus decisive risks. Include four-point recommendation scores only when explicitly requested.
   - Mark the user's target paper rows so they stand out from the comparison pool.
   - In multi-target local-review mode, organize the report by target paper. For each target, include its topic signature, accepted anchors, non-accepted/boundary controls, relative position, calibrated score, confidence, and likely review-style verdict. Include a target-local scoring table covering every pool paper and the target. Include a final cross-target summary matrix only as a coordinator calibration view, not as the main ranking.
   - Add concise per-paper rationales grounded in concrete contributions, close comparisons, public review evidence when available, and any score-drift explanation.
   - Rank only this run's target and pool papers. If the user adds another paper mid-run, add it to this run's pool and re-rank within this run.
   - Save the final table and rationales to `$RUN_DIR/REPORT.md`.
   - After finalization, record run membership and final scores in the evidence library with `record-run` and `record-score` so future runs can audit drift.

8. Optional tiering and image prompts.
   - Use five tiers from strongest to weakest: `S 夯爆`, `A 很夯`, `B 够硬`, `C 能打`, `D 偏拉`.
   - For image prompts, use the A4 Chinese infographic templates in `references/rubric.md`.

## Bundled Resources

### Rubric

Read `references/rubric.md` when scoring, ranking, tiering, or writing image-generation prompts. It contains the fixed scoring formula, score anchors, reviewer protocol, output table format, calibration rules, and prompt templates.

### Calibration

Read `references/calibration.md` when public reviews, historical scores, anchors, pairwise comparisons, or calibration notes are involved. It explains how to use review evidence and history without converting the library into a stale leaderboard.

### PDF Extraction

Run:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/extract_pdf_reports.py "$RUN_DIR"
```

The extractor recurses through `targets/` and `pool/` while avoiding the output directory. It prefers PyMuPDF (`fitz`) and falls back to `pypdf`. If neither exists, install one with `pip install pymupdf` or `pip install pypdf`.

### Evidence Library

`scripts/paper_db.py` manages a local SQLite evidence library plus cached PDFs under this skill directory:

- `cache/papers.db`
- `cache/pdfs/<id>.pdf`

Use it to avoid re-downloading already-vetted comparison PDFs and to calibrate future runs with public reviews, historical score drift, anchors, pairwise judgments, and calibration events. Do not treat cached scores or past rankings as authoritative for a new run.

Common commands:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py init
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py search "<keywords>"
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py link <id> "$RUN_DIR/pool"
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py add --id <id> --title "<title>" --pdf <path>
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py get <id> --with-evidence
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py reviews <id>
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py history <id>
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py drift-check <id> --innovation <n> --value <n> --rigor <n> --aesthetics <n> --total <n>
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py record-run ...
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py record-score ...
```

Use `--cache-dir` for isolated testing.

### OpenReview Reviews

Use `scripts/openreview_reviews.py` for OpenReview-hosted venues:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/openreview_reviews.py --paper-id <id> --forum <forum_id>
```

It stores public review and decision evidence into the evidence library.

### Pairwise Ranking

Use `scripts/pairwise_rank.py` to aggregate JSONL pairwise judgments into a transparent ranking cross-check. Pairwise ranking informs calibration; it does not replace the final area-chair synthesis.
