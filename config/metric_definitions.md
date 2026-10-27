# Metric definitions (hard rules)

| Metric | Definition | Notes |
|---|---|---|
| `engagements` | likes + comments + saves + shares (TikTok) / reposts (IG) | per post; `follows` from a post is a **separate column**, never inside ER |
| `er` (Instagram) | `engagements / reach` | `er_basis = reach`. NaN if reach missing/0. **Never** / followers, never / views |
| `er` (TikTok) | `engagements / video_views` | sheet has no TikTok reach → `er_basis = views` |
| `er_mean` (account) | mean of per-post `er` over posts in the period | simple average, posts without ER excluded |
| `er_weighted` (account) | `sum(engagements) / sum(denominator)` over posts with ER | reach-weighted; shown next to `er_mean`, labelled |
| `er_sheet` | the sheet's own ER row/cell | reconciliation only; discrepancies > 0.5 pp logged (Data quality) |
| `boost_spend` | `AD Spent` / `Total Spent` (weekly boosting block), `Boosting Spent` / `Ad cost` (monthly), Boosting Susy | paid. Sources are kept apart and reconciled, never merged |
| `cost_per_new_follower` | `boost_spend / new_followers` (boosting block) | weekly only |
| `cost_per_net_follow` | `boost_spend / net_follows` (organic block, same account/period) | includes organic effect; labelled |
| `cpm_boosted` | `boost_spend / boosted_reach × 1000` | = cost per boosted reach; benchmark for influencer CPM |
| `boosted_reach_share` | `boosted_reach / (organic_reach + boosted_reach)` | only where boosted reach exists |
| influencer `cpm` | `klar costs (fixed + variable) / reach × 1000` | reach priority: Klar `reach` → `data/manual/influencer_reach.csv` → n/a. `reach_source` always shown. **Never followers or likes** |
| `interactions_per_post` | mean(likes + comments) over Business-Discovery media | secondary creator metric; not ER |
| `roas`, `cac`, `cpo` | Klar `net_revenue / costs`, `costs / new_customers`, `costs / orders` | recomputed from sums, not averaged from Klar rows |
| `weekly_rollup` | weekly sheet flows summed to the month of the ISO week's Thursday; followers = last week | explicit `scope` label; not comparable to the monthly sheet without it |

Synonym map (sheet label → canonical): see `src/ingest/labels.py::METRIC_SYNONYMS`
(`AD Spent`/`Total Spent`/`Boosting Spent`/`Ad cost` → `boost_spend`; `Overall`/`Overall Follows`/`Net Followers` → `net_follows`;
`Total Followers`/`Followers` → `followers`; `Like` → `likes`; `Save` → `saves`; `Repost` → `reposts`; `Share` → `shares`;
`Video Views` → `video_views`; `Play Time` → `play_time` (minutes)).

Cells `/`, `#DIV/0!`, `-`, blanks and names (e.g. `justus`) → NaN. `3,5%` → 0.035. Sheet ER values > 1 are treated as percent numbers.
