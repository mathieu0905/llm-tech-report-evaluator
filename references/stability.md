# Stability-Locked Evaluation

Use this reference when repeated runs reuse comparison papers, when the user asks about score drift, or when stable acceptance-bar calibration matters more than producing a fresh global leaderboard.

## Principle

Recurring pool papers are measuring instruments. The target paper is the object being measured. Do not let a new target's topic framing, writing style, or pool composition freely reshuffle the ruler.

Stable evaluation has two products:

- **Target-local placement**: where the target lands relative to nearby anchors in this run.
- **Anchor audit**: whether any recurring anchor truly needs a score/order change.

Unless the user explicitly asks for a new global ranking, the final report should emphasize target-local placement and keep anchor scores as canonical bands.

## Anchor States

Classify each recurring comparison paper before scoring:

- `locked anchor`: at least 2 prior scores, total std <= 0.35, and no unresolved calibration event. Use its historical mean or curated anchor score as the canonical score.
- `provisional anchor`: only 1 prior score or std in `(0.35, 0.60]`. Use it as a rough boundary; pairwise evidence can adjust the target placement but should not rewrite the anchor without explanation.
- `unstable anchor`: total std > 0.60, total range > 1.0, contradictory public reviews, or known pool mismatch. Use it as qualitative context only, not a hard ruler.
- `fresh pool paper`: no prior score. Score it only if needed for local context, and label it as run-local.

For locked anchors, report a score band:

`band = historical mean +/- max(0.20, historical std)`

If no dimension history exists, use total history plus the current paper reading to preserve the known order, and mark dimension scores as lower-confidence.

## Target Insertion Protocol

1. Pick 3-5 anchors around the expected threshold: one stronger, one similar, one weaker, plus any same-topic accepted paper.
2. For each dimension, make pairwise judgments before numeric scoring:
   - target vs stronger anchor
   - target vs similar anchor
   - target vs weaker anchor
3. Convert pairwise placement into a numeric score by interpolation:
   - clearly above upper anchor: score just above that anchor's band, unless evidence supports a larger jump
   - between two anchors: score inside the interval, closer to the anchor it resembles
   - clearly below lower anchor: score just below that anchor's band
4. Check the absolute score against rubric anchors. If pairwise placement and rubric score disagree, resolve the disagreement before finalizing.
5. Do not change locked-anchor scores just because the target scores near them.

## Drift Thresholds

Use these as defaults:

- Anchor total movement <= 0.25: acceptable noise; no note needed.
- Movement > 0.25 and <= 0.50: write a short calibration note.
- Movement > 0.50: requires explicit evidence and `record-calibration`.
- Movement >= 0.80: treat as a likely evaluation error unless public reviews, newly read evidence, or prior thin reading clearly explains it.
- Rank movement among locked anchors > 1 position: audit pairwise consistency before publishing.

For dimensions, use a looser threshold of 0.50 because dimension labels are noisier than total score. A recurring paper should not jump a full point in Innovation, Value, or Rigor without a concrete evidence change.

## Pool Strength Normalization

Pool strength affects scores. Before final scoring, write a one-line pool-strength note:

- `strong pool`: accepted anchors are mostly top-tier or field-shaping; target scores may be conservative.
- `ordinary top-venue pool`: normal accepted-paper anchors; no offset.
- `boundary-heavy pool`: many rejected/arXiv/secondary-track controls; avoid inflating target score just because controls are weak.
- `mixed-topic pool`: use pairwise placement only against closest-topic anchors; keep distant anchors as broad references.

Do not apply a mechanical offset. Use the note to explain uncertainty and to prevent anchor drift.

## Report Shape

Prefer this structure for repeated submission judgments:

1. `Stable Ruler`: a small table of locked/provisional anchors with canonical score bands and status.
2. `Target Placement`: target score, nearest upper/lower anchors, and pairwise reasons.
3. `Run-Local Table`: includes target and any fresh pool papers. Locked anchors retain canonical scores or bands.
4. `Drift Audit`: only for anchors that moved or contradicted pairwise evidence.

Avoid presenting every run as a brand-new global ranking unless the user explicitly wants a global leaderboard. A global leaderboard invites artificial anchor movement.

## Stability Commands

Check anchor stability:

```bash
python3 ~/.codex/skills/paper-review-evaluator/scripts/paper_db.py stability-report --ids <id1,id2,id3>
```

Use `--dimension innovation`, `--dimension value`, or `--dimension rigor` when the drift concern is dimension-specific.

Record an anchor movement only when it is intentional:

```bash
python3 ~/.codex/skills/paper-review-evaluator/scripts/paper_db.py record-calibration \
  --run-id <run_id> \
  --paper-id <paper_id> \
  --trigger-type historical_drift \
  --dimension total \
  --before-score <old> \
  --after-score <new> \
  --severity high \
  --explanation "Re-read revealed the prior run over-weighted benchmark wins and missed absent ablations."
```

