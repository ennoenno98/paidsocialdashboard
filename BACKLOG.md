# Backlog

Items agreed with the team but not built yet. One entry per idea: what, why, what the data already allows.

## Organic dashboard: split organic followers vs boost followers

Requested 2026-11-05 (to be discussed in person after the vacation).

- **What**: on Home and Organic vs Boosted, show follower growth as organic follows and boost-driven follows
  side by side, per account and period, instead of one net figure.
- **Data already there**: `net_follows` / `new_followers` / `unfollows` per day from the Instagram account
  insights (Meta keeps 30 days), and `boosted_follows` per period from the Meta boost campaigns
  (`instagram_profile_follow` per ad, `api_metrics.boosted_periods`, with `cost_per_follow`).
- **Proposed definition**: organic follows = `new_followers` (gross follows) − `boosted_follows`;
  net organic = organic follows − `unfollows`. Label both; keep `boosted_follows` and `cost_per_follow` next to them.
- **Caveats to settle in person**: boost follows are ad-attributed (7-day click / 1-day view) while account
  follows are counted on the day, so the two can disagree by a few per day; the sheet's net follows for months
  older than 30 days has no boost split; TikTok has no boost follow metric.
