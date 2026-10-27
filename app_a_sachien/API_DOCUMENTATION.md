# Application A — API Documentation

Base URL (production placeholder): `https://sachien-expense-api.onrender.com`
Local development: `http://localhost:8001` (development only — never used for production integration).
All request/response bodies are JSON. Interactive docs: **`/docs`** (Swagger UI), `/redoc`.

## Authentication

| Scope | Mechanism |
|---|---|
| Write endpoints (`POST`, `PUT`, `DELETE`) | `Authorization: Bearer <API_TOKEN>` header. Token comes from the `API_TOKEN` environment variable. Missing/invalid → `401`. |
| Peer service-to-service calls (App A → B/C) | `Authorization: Bearer <SUBSCRIPTION_API_TOKEN / ELECTRICITY_API_TOKEN>` configured per deployment. |
| Read endpoints (`GET`) | Public by design (dashboard is public) — see privacy note in README. |

If `API_TOKEN` is unset, writes are rejected with `401` in production. (Tests may set
`ALLOW_UNAUTHENTICATED_WRITES=1` locally; this flag must never be set in deployments.)

## Error format

All errors use FastAPI's standard shape:

```json
{ "detail": "Expense not found" }
```

Status codes used: `200`, `201`, `204`, `400`, `401`, `404`, `422` (validation), `502` (peer API failure where relevant), `500`.

---

## Endpoints

### Health & meta
| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","app":"expense-manager","time":"<ISO-8601>"}` |
| GET | `/categories` | List of the 7 canonical categories (consumed by Apps B and C) |
| GET | `/category/{name}` | Spend total + count for a category; `404` if unknown |
| GET | `/categorize?merchant=Netflix` | Rule-based merchant→category prediction |

### Expenses
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/expenses` | – | Paginated list. Query: `page` (≥1), `page_size` (1–200), `search`, `category`, `source`, `date_from`, `date_to`, `sort` (e.g. `-amount`). Returns `{total, page, page_size, items[]}` |
| POST | `/expenses` | ✔ | Create. Body: `expense_date`, `merchant`, `amount` (>0, ≤2dp), `currency` (ISO-4217, default INR), `category` (one of 7), `payment_method`, `description?` → `201` |
| GET | `/expenses/{id}` | – | Single expense; `404` if missing |
| PUT | `/expenses/{id}` | ✔ | Partial update (any subset); `422` if empty body |
| DELETE | `/expenses/{id}` | ✔ | `204`; `404` if missing |

Example expense object:

```json
{
  "id": 1, "expense_date": "2026-10-27", "merchant": "Zomato",
  "amount": 450.50, "currency": "INR", "category": "Food",
  "payment_method": "Card", "description": null,
  "source": "manual", "external_id": null,
  "last_synced_at": null, "created_at": "2026-10-27T10:00:00Z"
}
```

`source` ∈ `manual | csv | app_b_subscription | app_c_electricity`. Imported records
carry `external_id` (the peer's record id) and `last_synced_at`; unique
`(source, external_id)` prevents duplicates. Manual records are never overwritten by sync.

### Categorization rules
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/rules` | – | Editable rules ordered by priority |
| POST | `/rules` | ✔ | Upsert `{pattern, category, priority}` |
| DELETE | `/rules/{id}` | ✔ | Remove rule |

### Budgets
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/budgets?month=YYYY-MM` | – | Budgets + utilization (`spent`, `remaining`, `percent_used`, `overspent`) |
| POST | `/budgets` | ✔ | Create `{month, category, limit_amount>0}`; duplicate month+category → `409` |
| PUT | `/budgets/{id}` | ✔ | Update limit |
| DELETE | `/budgets/{id}` | ✔ | `204` |

### Summary & CSV
| Method | Path | Description |
|---|---|---|
| GET | `/summary?month=2026-10` | `{month, total_spent, by_category[], budgets[], external_sources{}}`. Month validated against `^\d{4}-(0[1-9]|1[0-2])$` |
| GET | `/export/csv` | File download `expenses.csv` |
| POST | `/import/csv` | Multipart form field `file`; required columns `date,merchant,amount,category`; returns `{imported, errors[]}` |

### Integration & synchronization
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/integration/status` | – | Peer health probes + last successful sync per source app |
| POST | `/sync/subscriptions` | ✔ | Pull eligible recurring costs from App B (`GET /subscriptions` on `SUBSCRIPTION_API_URL`). Idempotent → `{imported, skipped, status}` |
| POST | `/sync/electricity` | ✔ | Pull eligible electricity expenses from App C (`GET /integration/expenses`). Idempotent |
| GET | `/sync/history?limit=20` | – | SyncLog entries (status, counts, message, timestamp) |

Behavior when a peer is unreachable/misconfigured: sync returns
`{"status":"unavailable"/"failed", ...}` and logs it — the rest of App A keeps working.
External payloads are validated with Pydantic; invalid rows are counted as `skipped`,
never inserted.

## Contract exposed to peers

Apps B and C call `GET https://<app-a-url>/categories` (no auth) to keep categorization
consistent. Retries: bounded (`HTTP_MAX_RETRIES`, default 3) with timeout
(`HTTP_TIMEOUT_SECONDS`, default 10 s). Production traffic is HTTPS only.
