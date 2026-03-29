## ADDED Requirements

### Requirement: Dashboard model/provider usage tables show average throughput

The dashboard model/provider usage tables MUST display average throughput in tokens per second for each `(model, provider)` group.

#### Scenario: Dashboard renders average TPS for grouped usage rows

- GIVEN execution analytics contain one or more rows for a `(model, provider)` group with positive `elapsed_ms`
- WHEN an operator opens `GET /dashboard`
- THEN each `Model / Provider Usage` table for `24h`, `7d`, and `30d` MUST include an `AVG TPS` column as the last column
- AND the displayed value MUST equal the arithmetic mean of per-request `total_tokens / elapsed_seconds` within that grouped time window

#### Scenario: Dashboard handles missing or invalid latency for TPS

- GIVEN a `(model, provider)` group has no execution rows with positive `elapsed_ms`
- WHEN an operator opens `GET /dashboard`
- THEN the `AVG TPS` cell for that group MUST render `-`
- AND the dashboard MUST continue rendering the rest of the usage table normally
