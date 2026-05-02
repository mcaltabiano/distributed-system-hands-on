CREATE TABLE IF NOT EXISTS orders (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  TEXT        NOT NULL,
    quantity    INT         NOT NULL CHECK (quantity > 0),
    status      TEXT        NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Outbox table: events are written here inside the same DB transaction as the
-- order insert, then picked up by outbox_relay.py and forwarded to Kafka.
-- This guarantees at-least-once delivery without 2PC.
CREATE TABLE IF NOT EXISTS outbox (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic       TEXT        NOT NULL,
    key         TEXT,
    payload     JSONB       NOT NULL,
    published   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outbox_unpublished ON outbox (created_at) WHERE published = FALSE;
