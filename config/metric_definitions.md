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
| `cost_per_follow` | `boost_spend / boosted_follows` | follows Meta attributes to the 'Instagram post' ads (`instagram_profile_follow`, Business Suite "Follows from ads"), per account of the promoted post; the sheet's boosting-block definition. Business Suite's post-level "from ads" also counts other ads that reuse the post |
| `cost_per_new_follower` | `boost_spend / new_followers` | all new followers of the account in the period (organic effect included); Meta exposes new followers for 30 days |
| `unfollows` (Instagram) | `follows_and_unfollows − follower_count` per day | Meta reports gross follows and follows+unfollows; 30-day window. TikTok: `daily_lost_followers`. `net_follows = new_followers − unfollows`; the Overview tile shows net where unfollows are known, else the sheet's net follows for periods beyond 30 days |
| `followers` (now) | instagram_public `profile_followers_count` per own handle | the instagram connector's `followers_count` arrives for one account only; the public profile field covers every own account and feeds the followers history |
| `reach_daily_sum` (account, API) | sum of Meta's daily unique reach | overstates true period reach (a person reached on 3 days counts 3×); comparable with itself, never with a de-duplicated 28-day figure |
| boost market | account of the promoted post (caption match, Instagram posts only) | ad account → brand only; `targeting` (ad-set countries) shown as a check on Data quality |
| `cpm_boosted` | `boost_spend / boosted_reach × 1000` | = cost per boosted reach; benchmark for influencer CPM |
| `boosted_reach_share` | `boosted_reach / (organic_reach + boosted_reach)` | only where boosted reach exists |
| `n_stories`, `story_reach_sum`, `story_exit_rate` | stories per period; reach summed per story; exits / views | Meta exposes a story for 24 h: collected daily, accumulated by story_id. `scope='api'` |
| Collab posts | Instagram Collab posts owned by a creator, own account as co-author | likes/comments/saves/shares only, no reach → ER n/a; never counted as own posts |
| influencer `cpm` | `klar costs (fixed + variable) / reach × 1000` | reach priority: Klar `reach` → `Reach` column of the Klar influencer sheet (`klar_sheet`) → `data/manual/influencer_reach.csv` → n/a. `reach_source` always shown. **Never followers or likes** |
| `interactions_per_post` | mean(likes + comments) over Business-Discovery media | secondary creator metric; not ER |
| `roas`, `cac`, `cpo` | Klar `net_revenue / costs`, `costs / new_customers`, `costs / orders` | recomputed from sums, not averaged from Klar rows |
| `ctr_link` (creatives) | `link_clicks / impressions` | Meta ad feed, summed per asset x funnel stage x period, then divided. Never a mean of daily CTRs |
| `cpc`, `cpm`, `cpa` (creatives) | `spend / link_clicks`, `spend / impressions × 1000`, `spend / purchases` | same rule; `purchases` = `actions_omni_purchase`, Meta-attributed 7-day click / 1-day view |
| `roas`, `cpa`, `orders` (creatives) | Klar: `klar_gross_revenue / spend`, `spend / klar_orders` (Klar `marketing_flex` row for the same date, campaign and ad name, split across ad sets by Meta spend); fallback Meta: `purchase_value / spend`, `spend / purchases` | `roas_source` per row (`klar` / `meta`); `roas_meta` / `cpa_meta` always kept alongside. Spend is always Meta spend. Never a mean of row ROAS |
| `lpv_rate`, `cvr` (creatives) | `lpv / link_clicks`, `purchases / lpv` | |
| `revenue` (creatives) | Klar `klar_gross_revenue` where Klar matched, else Meta `purchase_value` | the ROAS numerator, same source rule as `roas` |
| `thruplay_rate` | `thruplays / video_plays` | |
| `funnel_stage` | rule chain in `config/creatives.yaml` on campaign name, ad set name, targeting JSON | `prospecting` / `retargeting` / `unknown` (Data quality). Separate views; an asset is never collapsed across stages or optimisation goals |
| `objective` | Meta `campaign_objective` -> `objectives` label (sales, leads, traffic …) | shown and filterable |
| `event` | `adset_promoted_object.custom_event_type` -> `events` label; ad sets without a pixel event take `events_by_optimization_goal` | primary axis inside a stage view. Profile visits / page likes / post engagement rows are excluded as organic |
| `judge_kpi`, `verdict` | KPI by conversion event (`kpi_by_event`: purchase / initiate checkout / add to cart → `roas`, landing page view / link click / lead → `ctr_link`, thruplay / reach / impressions → `cpm`); Performing / Underperforming vs target (account average of the selection or a pinned number; lower-is-better KPIs compared the right way round), Low data below the min spend | |
| creative tags | `visual_subject`, `claim` from the naming convention → LLM vision pass → manual `Creative tags` tab (always wins); `tag_source` shown | controlled vocabulary in `src/transform/creatives.py::TAG_VOCAB` |
| `weekly_rollup` | weekly sheet flows summed to the month of the ISO week's Thursday; followers = last week | explicit `scope` label; not comparable to the monthly sheet without it |

Synonym map (sheet label → canonical): see `src/ingest/labels.py::METRIC_SYNONYMS`
(`AD Spent`/`Total Spent`/`Boosting Spent`/`Ad cost` → `boost_spend`; `Overall`/`Overall Follows`/`Net Followers` → `net_follows`;
`Total Followers`/`Followers` → `followers`; `Like` → `likes`; `Save` → `saves`; `Repost` → `reposts`; `Share` → `shares`;
`Video Views` → `video_views`; `Play Time` → `play_time` (minutes)).

Cells `/`, `#DIV/0!`, `-`, blanks and names (e.g. `justus`) → NaN. `3,5%` → 0.035. Sheet ER values > 1 are treated as percent numbers.
