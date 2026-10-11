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

## model.json (SlipScore section) — `update_model_stats.py`
https://raw.githubusercontent.com/zimmmz21/slipbuilder-stats/main/model.json
- **graded_props:** all graded props the system holds: the 247,510 rows of `props-all/graded_props_2023_2025.parquet` (`graded_props_2023_2025`) plus unique graded 2026 props (`graded_props_2026`). A 2026 prop is one (NFL week, player, market, line), counted once no matter which side or source it came from. Sources are checked in this order: the v3 2026 DK board lines with a graded outcome, then `why-tags/why_tags_2026.parquet` rows graded OVER/UNDER, then ledger legs graded HIT/MISS (regular season). `graded_2026_by_first_source` shows how many unique props each source added. Different lines for the same player and market count as separate props, the same way the 2023-25 file does. The total grows as games are graded.
- **trained_lines:** exact number of graded lines SlipScore v3 is fit on (`lines_all.pkl`, graded rows in modeled categories, same filter as `fit_final.py` and the nightly retrain).
- **prop_categories:** distinct prop categories in that training set.
- **trained_through:** latest season/week in the training set.
- **lines_scanned / slate_games / slate_markets:** unique (player, market, line) props in the latest board scan (`ledger/board-scan/<date>.jsonl`), plus the games and markets that scan covered.
- **calib_under_*:** walk-forward calibration of confident Under picks (P ≥ 0.58): stated vs actual hit rate (REPORT_REFINE.md). Static until that analysis is re-run.
- **updated_at:** ISO 8601 timestamp in CT of the last change.
