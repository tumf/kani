# Kani Dashboard

Kani routes request analytics with both **lightweight HTML UI** and **Grafana integration**.

## Deployment note

Current canonical runtime is Docker Compose, not launchd.

- Public endpoint: `https://kani.mini.tumf.dev`
- Caddy upstream: `kani:18420`
- Runtime: `dotenvx run -f ~/.env -- docker-compose up -d` in `~/services/kani`
- Reason: `OPENROUTER_API_KEY` and other secrets live in encrypted `~/.env`, so plain `docker-compose up -d` starts Kani without classifier env vars
- Shared log dir: `~/.local/state/kani/log`
- Shared dashboard DB: `~/.local/share/kani/dashboard.db`

The dashboard depends on the Docker container seeing the same host-side log directory that the router writes to. If metrics stay at 0 while requests are flowing, check the compose volume mounts first.

## Phase 1: HTML Dashboard (Immediate)

Simple, dependency-free dashboard showing routing analytics.

### Access

```bash
# Start kani proxy
uv run kani serve

# Open dashboard in browser
open http://localhost:18420/dashboard
```

Shows:
- Total requests (24h)
- Tier distribution (pie chart)
- Average scores by tier
- Confidence level breakdown

### API

**Stats (JSON):**
```bash
curl http://localhost:18420/dashboard/stats?hours=24
```

## Phase 2: Grafana Integration (Production)

### Setup

1. **Copy datasource config** to your Grafana provisioning directory:
   ```bash
   cp grafana-datasource-kani-sqlite.yml /path/to/grafana/provisioning/datasources/
   ```

2. **Import dashboard**:
   - Open Grafana → Dashboards → Import
   - Upload `grafana-dashboard-kani.json`
   - Select "Kani SQLite" as datasource

### Data Ingestion

The dashboard endpoints automatically ingest recent JSONL logs into SQLite. For continuous ingestion:

```bash
# Every 5 minutes, ingest last 24h of logs
*/5 * * * * cd /path/to/kani && uv run python -c \
  "from kani.dashboard import ingest_jsonl_logs; ingest_jsonl_logs(days=1)"
```

### Database

SQLite database location: `~/.local/share/kani/dashboard.db`

**Tables:**
- `routing_logs`: All routed requests (timestamp, tier, score, confidence, signals)

## Notes

- Dashboard is **exempt from API authentication** (open endpoint)
- JSONL ingestion is idempotent (safe to run multiple times)
- Database grows ~1KB per request
