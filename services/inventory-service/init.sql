CREATE TABLE IF NOT EXISTS products (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    stock       INT  NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS reservations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID NOT NULL UNIQUE,
    product_id  TEXT NOT NULL,
    quantity    INT  NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed some products so load tests have data to work with
INSERT INTO products (id, name, stock) VALUES
    ('abc', 'Laptop Pro',  50),
    ('xyz', 'Headphones',  200)
ON CONFLICT DO NOTHING;
