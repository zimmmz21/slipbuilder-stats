# slipbuilder-stats

Live record for the slipbuilder.io "This week" box.
`record.json` is regenerated from SlipBuilder's graded ledger after every grade by `update_record.py` (committed only when the numbers change).

Raw URL (CORS `Access-Control-Allow-Origin: *`):
https://raw.githubusercontent.com/zimmmz21/slipbuilder-stats/main/record.json

## Definitions (same as the weekly X record card)
- **Scope:** official SlipBuilder Discord cards only (ledger `channel == "discord"`, superseded entries excluded). Personal slips are never counted. Bonus slips count only when posted to Discord.
- **Unit:** individual legs (player props), not slips. A leg is a win if graded HIT, a loss if MISS. VOIDs and ungraded legs are excluded.
- **season_w / season_l:** all graded official Discord legs this season.
- **legs_hit_pct:** season_w / (season_w + season_l) × 100, rounded to 1 decimal.
- **cashed_legs:** number of legs that hit this season (= season_w).
- **last_week_w / last_week_l:** graded legs from the last completed NFL week. NFL weeks run Tuesday to Monday (Week 1 starts Tue 2026-09-08). Uses the ledger's `week` field when present, otherwise the slip date.
- **updated_at:** ISO 8601 timestamp in America/Chicago (CT offset) of the last change.
