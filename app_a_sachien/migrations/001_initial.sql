-- Application A initial schema (PostgreSQL). Apply with:
--   psql "$DATABASE_URL" -f migrations/001_initial.sql
CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    expense_date DATE NOT NULL,
    merchant VARCHAR(200) NOT NULL,
    amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'INR',
    category VARCHAR(50) NOT NULL,
    payment_method VARCHAR(50) NOT NULL DEFAULT 'Card',
    description TEXT,
    source VARCHAR(30) NOT NULL DEFAULT 'manual',
    external_id VARCHAR(120),
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_expense_source_external UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS ix_expenses_expense_date ON expenses (expense_date);
CREATE INDEX IF NOT EXISTS ix_expenses_category ON expenses (category);
CREATE INDEX IF NOT EXISTS ix_expense_month ON expenses (expense_date, category);

CREATE TABLE IF NOT EXISTS category_rules (
    id SERIAL PRIMARY KEY,
    pattern VARCHAR(200) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    month VARCHAR(7) NOT NULL,
    category VARCHAR(50) NOT NULL,
    limit_amount NUMERIC(12,2) NOT NULL CHECK (limit_amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_budget_month_category UNIQUE (month, category)
);
CREATE INDEX IF NOT EXISTS ix_budgets_month ON budgets (month);

CREATE TABLE IF NOT EXISTS sync_logs (
    id SERIAL PRIMARY KEY,
    source_app VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_imported INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
