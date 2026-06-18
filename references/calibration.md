# Review-Calibrated Comparative Evaluation

Use this reference when scoring, ranking, or writing the final area-chair report.
The goal is not to let historical scores or public reviews replace fresh
judgment. The goal is to make the fresh judgment harder to fool.

## Evidence Library Contract

Use `scripts/paper_db.py` as a reusable evidence library. It stores:

- paper metadata and cached PDFs
- public review evidence
- run membership
- score history
- pairwise judgments
- anchors
- calibration events

Do not treat the database as a leaderboard. For every new run, re-read the
papers in that run and recompute judgments. Use library evidence only for
calibration, drift checks, and audit notes.

## Public Review Calibration

For OpenReview papers, fetch public reviews with:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/openreview_reviews.py \
  --paper-id <paper_id> \
  --forum <openreview_forum_id>
```

Then inspect:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py reviews <paper_id> --verbose
```

Use reviews as calibration evidence:

- If model rigor is high but confident public reviews criticize experiments,
  re-check baselines, ablations, protocols, and limitations.
- If model innovation is low but reviews consistently praise a new formulation
  or mechanism, re-check the contribution against close prior work.
- If public reviews are highly split, increase uncertainty instead of forcing a
  false consensus.
- If the model disagrees with public reviews, allow the disagreement only with
  concrete evidence from the paper and comparison pool.

Record material conflicts:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py record-calibration \
  --run-id <run_id> \
  --paper-id <paper_id> \
  --trigger-type review_conflict \
  --dimension rigor \
  --before-score 8.2 \
  --after-score 7.4 \
  --severity high \
  --explanation "Public reviews and extracted evidence both show missing ablations."
```

## Historical Drift Calibration

Before finalizing a paper with prior scores, check drift:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py drift-check <paper_id> \
  --innovation <score> --value <score> --rigor <score> --aesthetics <score> --total <score>
```

Treat any dimension that differs from the historical mean by about 1.0 point, or
by at least two historical standard deviations, as requiring explanation.

Valid explanations include:

- the current pool is much stronger or weaker
- the paper is being judged under a different paper type
- prior runs had a thinner comparison pool
- public reviews or newly read evidence reveal a missed weakness or strength

Invalid explanations:

- "the model thinks so" without paper evidence
- copying the historical mean
- ignoring drift because the current ranking looks plausible

Record meaningful drift decisions with `record-calibration`, using
`historical_drift` as the trigger type.

## Stability-Locked Anchor Calibration

For repeated runs, do not treat every pool paper as a fresh competitor. Use
`references/stability.md` to decide which papers are locked, provisional, or
unstable anchors. Locked anchors should act as score bands and pairwise
boundaries for the target paper.

Run:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py stability-report \
  --ids <id1,id2,id3>
```

If locked anchors change order because of a new target paper, assume the run is
miscalibrated until proven otherwise. Re-read the close pair, inspect public
reviews/history, and prefer target insertion between anchors over rewriting the
anchor ranking.

## Anchor Calibration

Maintain topic anchors when a topic has enough recurring papers:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py add-anchor \
  --topic "LLM agent evaluation" \
  --paper-id <paper_id> \
  --tier A \
  --dimension overall \
  --note "Strong reusable method, not paradigm-level."
```

Use anchors as tier references:

- S anchor: field-shaping, broad method or paradigm influence
- A anchor: strong and broadly reusable
- B anchor: robust, useful, but less foundational
- C anchor: credible and useful, narrower contribution
- D anchor: weak paper evidence or mostly capability/reporting value

If a new paper is scored above a stronger anchor or below a weaker anchor, write
the reason. If the reason is weak, adjust the score or tier.

## Pairwise Comparison

For each dimension, ask reviewers to compare close papers directly:

- Which paper is more innovative, and by what margin?
- Which paper teaches more transferable value?
- Which paper has stronger evidence and evaluation design?

Record pairwise judgments in `judgments/pairwise_<dimension>.jsonl`:

```json
{"paper_a":"paper-a","paper_b":"paper-b","winner":"paper-a","dimension":"innovation","margin":1.0,"evidence":"A introduces a new training objective; B mostly integrates known components."}
```

Aggregate with:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/pairwise_rank.py \
  "$RUN_DIR/judgments/pairwise_innovation.jsonl" --markdown
```

Use pairwise ranking as a consistency check. If absolute scores imply a ranking
that strongly conflicts with pairwise results, run a calibration pass and either
adjust the scores or explain the mismatch.

## Area-Chair Synthesis

The final report should include:

- rank table with final calibrated scores
- confidence for each paper
- calibration note for each paper: supported, review-conflict, drift-explained,
  anchor-mismatch, or pairwise-mismatch
- concise rationale grounded in paper evidence and comparisons
- uncertainty and disagreement summary

Recommended final table columns:

```markdown
| Rank | Paper | Role | Type | Innovation | Paper Value | Rigor | Aesthetics | Total | Confidence | Calibration |
|---:|---|---|---|---:|---:|---:|---:|---:|---|---|
```

After finalizing, record the run and final scores:

```bash
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py record-run ...
python3 ~/.codex/skills/llm-tech-report-evaluator/scripts/paper_db.py record-score ...
```
