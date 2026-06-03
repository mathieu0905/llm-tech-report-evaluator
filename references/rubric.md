# LLM Technical Report Evaluation Rubric

## Scoring Formula

Use a 10-point scale for each dimension.

`Total = 0.40 * Innovation + 0.40 * Intrinsic Paper Value + 0.20 * Rigor`

`Aesthetics` is a separate reference score and does not affect ranking.

## Anonymous Multi-Reviewer Protocol

Use this protocol when the user asks for paper scoring, ranking, or review.

1. Spawn multiple anonymous sub-agents or independent blind review passes.
2. Give each reviewer the same paper text and rubric, but different review styles.
3. Recommended reviewer styles:
   - `strict-rigor`: focuses on methodology detail, ablations, evaluation protocol, and reproducibility.
   - `innovation`: focuses on novelty, technical idea quality, and whether the paper changes the practice.
   - `value`: focuses on transferable lessons, reusable mechanisms, and negative or surprising findings.
   - `skeptical-meta`: checks for overclaiming, weak evidence, benchmark chasing, and hidden caveats.
4. Keep reviewers blind to each other's scores and rationales until after they submit.
5. The main agent acts as area chair: reconcile disagreements, note uncertainty, and report the final score.
6. If anonymous sub-agents cannot be spawned, simulate separate blind passes locally and disclose that limitation.

## Dimensions

### Innovation, 40%

Score whether the report proposes genuinely new architecture, training paradigm, RL algorithm, system design, data construction, evaluation method, or scientific framing. Reward ideas that solve explicit bottlenecks and are backed by ablations or analysis. Penalize simple scaling, benchmark chasing, or repackaging known techniques without new insight.

### Intrinsic Paper Value, 40%

Score whether the report teaches transferable lessons beyond "this model is strong." Reward reusable principles, mechanisms, negative results, failure modes, counterintuitive findings, and clear recipes that can influence future research. Industrial deployment or business value is weak evidence only.

### Rigor, 20%

Score whether the report gives enough concrete support: training/data/post-training pipeline, infrastructure details, hyperparameters where useful, evaluation protocol, ablations, efficiency measurements, stability analysis, and limitations. Penalize opaque internal-only claims, narrow evaluations, missing setup details, or absent failure discussion.

### Aesthetics, reference only

Score readability and visual presentation: structure, figure/table clarity, typography, narrative discipline, and layout polish. Do not include this in totals unless the user explicitly changes the rule.

## Score Anchors

- 9.5-10.0: field-shaping or paradigm-level contribution with strong evidence.
- 9.0-9.4: very strong method line or system recipe with broad reusable value.
- 8.5-8.9: solid, high-value technical report; often strong engineering or applied research.
- 8.0-8.4: useful but more system/capability report than foundational paper.
- 7.0-7.9: domain-specific or mostly integration; still technically meaningful.
- below 7.0: thin disclosure, weak novelty, weak evidence, or mostly marketing.

## Five Tiers

- `S 夯爆`: paradigm-level paper; likely to affect how others train/build models.
- `A 很夯`: strong method route with broad research value.
- `B 够硬`: robust and valuable; may be more engineering/system recipe.
- `C 能打`: credible and useful but less foundational or less novel.
- `D 偏拉`: mostly capability report, vertical-domain integration, or limited paper insight.

## Standard Output Table

Use this table format:

| Rank | Report | Innovation | Paper Value | Rigor | Aesthetics (ref) | Total |
|---:|---|---:|---:|---:|---:|---:|

Then add short per-paper comments. For each paper mention:

- primary contribution
- why it scores where it does
- main limitation or reason it does not rank higher

## A4 Infographic Prompt Template

Use this when the user asks for a visual ranking prompt:

```text
生成一张竖版 A4 比例中文信息图，主题是“大模型基座技术报告：由夯到拉五档排序”。整体风格：高端科技论文评审海报，白底，黑灰主色，少量深蓝和红色强调，排版干净。不要卡通，不要营销风，不要复杂背景。

顶部标题：大模型基座技术报告五档排序
副标题：评分口径 = 40% 创新性 + 40% 论文本身价值 + 20% 论证/工程扎实性；美观不计入总分

中间用 5 个横向档位区块，从上到下排列：
S 档：夯爆，范式级论文
A 档：很夯，强方法路线
B 档：够硬，扎实高价值
C 档：能打，但偏系统整合
D 档：偏拉，更多是能力报告或垂直场景总结

每个模型用紧凑卡片展示：排名、模型名、总分、核心创新关键词。

[insert tiered model list]

底部小字：评分基于技术报告文本本身，不验证 benchmark 真实性，不计产业商业价值。
A4 portrait, high-resolution, clean Chinese typography, precise table layout, readable text.
```

## Per-Model Image Prompt Template

```text
生成一张竖版 A4 中文科技论文评审卡片，主题：[MODEL]｜总分 [SCORE]。风格：[visual style]. 中央视觉：[metaphor tied to core innovation]. 不要真实人物，不要公司 logo。

必须包含文字：
[MODEL]
总分：[SCORE]
档位：[TIER]
核心创新：
1. [innovation 1]
2. [innovation 2]
3. [innovation 3]
4. [innovation 4]
一句评价：[one-line judgment]

A4 portrait, high-resolution, premium academic technology poster, clean Chinese typography, strong hierarchy.
```
