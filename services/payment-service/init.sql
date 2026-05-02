CREATE TABLE IF NOT EXISTS payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL UNIQUE,   -- idempotency key
    amount_cents    INT  NOT NULL,
    status          TEXT NOT NULL DEFAULT 'processed',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
