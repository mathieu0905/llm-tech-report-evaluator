---
name: llm-tech-report-evaluator
description: Evaluate, compare, and rank research papers or LLM/foundation-model technical reports from PDFs or extracted text, and optionally auto-discover same-topic comparison papers from top venues. Use when Claude is asked to score papers on innovation/value/rigor, find or gather comparison/related papers on the same topic as a target paper, compare model tech reports, update rankings after new papers are added, create tier lists, or write image-generation prompts summarizing rankings.
---

# LLM Tech Report Evaluator

## Workflow

0. (Optional) Assemble the comparison set by auto-discovery.
   - Trigger this step when the user has not supplied a full set of PDFs to compare, or asks Claude to "find", "gather", or "pull in" comparison / related / same-topic papers.
   - Anchor on the user's target paper(s). First read (or extract) the target paper and derive its topic signature: title, problem statement, core method/technique, task, and 3-8 keywords. If the user gave only a topic instead of a target paper, use that topic directly.
   - Find same-topic comparison papers with Claude's built-in `WebSearch` and `WebFetch` tools. Do NOT depend on third-party scholarly APIs (Semantic Scholar, DBLP, the arXiv Atom API): they rate-limit or may be network-blocked. `WebSearch`/`WebFetch` are the primary discovery path.
   - Pick target venues by the paper's own field. Both SE and AI top venues are in scope by default — do NOT restrict to the target paper's own subfield; an SE paper can be compared against relevant AI-venue work and vice versa. Put venue names directly in the search query, e.g.:
     - SE: ICSE, FSE/ESEC-FSE, ASE, ISSTA, TSE, TOSEM
     - ML/AI: NeurIPS, ICML, ICLR, AAAI, JMLR
     - NLP: ACL, EMNLP, NAACL, TACL
     - CV: CVPR, ICCV, ECCV, TPAMI
     - Security/Systems/DB/etc.: the corresponding top venues
   - Search recipe: run a few `WebSearch` queries combining the topic keywords with venue + "arxiv", e.g. `"<topic keywords>" accepted ICSE OR FSE OR NeurIPS 2025 arxiv`. The official proceedings (IEEE Xplore / ACM DL) are paywalled, so steer toward the author-posted arXiv/preprint version for the PDF — but the paper itself must already be accepted/published (see acceptance gate below).
   - Default selection rule: gather the closest same-topic works to the target paper (same problem + comparable method line), not just any high-citation paper in the broad area. Aim for ~5-8 strong comparison papers unless the user asks for more.
   - Comparability is the goal; paper type is a soft preference, not a hard filter. Note the target's type (empirical study, method/system, benchmark/dataset, survey) and lean toward some overlap, but a MIXED set of genuinely comparable same-topic papers is good — do not reject a relevant, well-matched paper just for being a different type. The one thing to avoid is a set dominated by a single off-type bucket when the target isn't that type (e.g. all NeurIPS Datasets & Benchmarks papers when the target is an empirical study). Label each kept paper's type so the mix is visible.
   - HARD acceptance gate (default): only keep papers that are ALREADY ACCEPTED or PUBLISHED at a top venue. Exclude arXiv-only preprints with no venue, no matter how relevant or novel they look. Verify acceptance via the arXiv "Comments" field ("Accepted to ...", "To appear in ...") or the venue's program/proceedings; if you cannot confirm a venue, drop the paper or list it separately as "unverified — not counted".
   - Prefer MAIN / research track. Down-rank or exclude secondary tracks — workshops, ICSE-SEIP / industry / in-practice tracks, ACL Findings, short/demo/poster papers — unless the user asks for them. When a paper's only acceptance is a secondary track, label it as such so it is not mistaken for a main-track result.
   - Prefer OpenReview venues for a quality signal. For ICLR, NeurIPS, COLM (and other OpenReview-hosted venues), the reviewer ratings and decision are PUBLIC — use them to keep the best-reviewed papers.
     - Do NOT `WebFetch` the forum page for scores: it is JS-rendered and the ratings are not in the static HTML. Use the OpenReview REST API instead:
       `curl -s "https://api2.openreview.net/notes?forum=<id>&details=replies"` then read each reply's `content.rating.value` (and `content.decision.value` for the outcome). Older venues may live on `api.openreview.net` (v1).
     - Compute the average rating, record it + the decision next to the venue, and preferentially keep higher-rated papers. Note the venue's rating scale (e.g. NeurIPS 1–6, ICLR 1–10) so scores are interpreted correctly; only compare scores within the same scale.
     - You can also download the PDF straight from OpenReview: `curl -L -o <slug>.pdf "https://openreview.net/pdf?id=<id>"`.
     - SE-only venues (ICSE/FSE/ISSTA/TSE/TOSEM) do not expose review scores, so for those rely on acceptance + main-track status alone.
   - Recency (default): prefer papers from within the last ~18 months. Treat anything older as "too early" and include it only when the user explicitly asks, labeled as an older baseline. Confirm each candidate's date and venue on its arXiv page before keeping it.
   - Fetch each candidate's PDF into the working directory:
     - Confirm the right paper with `WebFetch` on its arXiv abstract page; the venue is usually stated in the arXiv "Comments" field (e.g. "Accepted to ICSE 2024").
     - Download the open PDF directly — `curl -L -o <slug>.pdf https://arxiv.org/pdf/<arxiv-id>` is verified to work. Try ACL Anthology / OpenReview PDFs the same way.
     - For papers with no open preprint (paywalled-only), do not fabricate a PDF: record title + venue + year + abstract from search results and either score from the abstract with an explicit lower-confidence note, or ask the user to supply the PDF.
   - Show the candidate list (title, venue, year, PDF-or-metadata-only, why it is a relevant comparison) and let the user prune before scoring. Disclose every paper you could not fetch as a full PDF.

1. Inventory the reports.
   - Use `rg --files -g '*.pdf'` in the target directory (including anything just downloaded in step 0).
   - If PDFs have not been extracted, run the extraction script (see "Extraction Script" below).
   - Prefer local extracted text over web search for the scoring itself. Only browse during scoring if the user explicitly asks for external verification or a referenced paper is missing locally.

2. Read each report with a paper-value lens.
   - Prioritize method sections, training/infrastructure details, ablations, evaluation protocol, limitations, and appendices.
   - Do not over-weight raw benchmark wins, business value, deployment popularity, or marketing claims.
   - Treat internal benchmarks as useful but less reliable than transparent ablations, protocols, and failure analysis.

3. Use anonymous multi-reviewer scoring by default.
   - Spawn multiple anonymous reviewers using the `Agent` tool (subagent_type `Explore` or `general-purpose`) when the user has asked for scoring, ranking, or review. Launch them in a single message so they run concurrently and stay blind to each other.
   - Do not expose one reviewer's identity, scores, or rationale to another reviewer before they submit their judgment.
   - Assign reviewers different evaluation styles or granularity, such as strict-rigor reviewer, innovation-focused reviewer, transferable-value reviewer, and skeptical meta-reviewer.
   - Give each reviewer the same fixed rubric and local extracted paper text; let style affect scrutiny and evidence selection, not the scoring formula.
   - The main agent acts as area chair: collect the anonymous reviews, reconcile large disagreements, and produce the final ranking with a short note on consensus and uncertainty.
   - If sub-agents are unavailable or the user declines them, simulate separate blind review passes locally and explicitly say that real anonymous sub-agents were not used.

4. Score with the fixed rubric.
   - `Total = 0.40 * Innovation + 0.40 * Intrinsic Paper Value + 0.20 * Rigor`
   - Keep `Aesthetics` as a separate reference column only; never include it in the total unless the user asks.
   - Use one decimal place for dimensions and two decimals for totals.

5. Rank and explain.
   - Provide a table with rank, report/model, Innovation, Intrinsic Paper Value, Rigor, Aesthetics, Total.
   - Add concise per-paper rationales grounded in concrete contributions.
   - If a new paper is added, update the full ranking rather than appending it in isolation.

6. Optional tiering and image prompts.
   - Use five tiers from strongest to weakest: `S 夯爆`, `A 很夯`, `B 够硬`, `C 能打`, `D 偏拉`.
   - For image prompts, generate vertical A4 Chinese infographic prompts with model name, score, tier, key innovations, and one-line judgment.

## Rubric Reference

Use `references/rubric.md` (in this skill directory) for the detailed scoring prompts, tier definitions, output templates, and image-prompt structure.

## Extraction Script

Run from the target directory containing the PDFs:

```bash
python3 ~/.claude/skills/llm-tech-report-evaluator/scripts/extract_pdf_reports.py .
```

The script writes:

- `analysis/text/<pdf-stem>.txt`
- `analysis/pdf_summaries.json`
- optional representative page PNGs with `--render-pages`

It depends on PyMuPDF (`fitz`). If it is missing, install with `pip install pymupdf`. If the repository already has its own extraction script, prefer that one.
