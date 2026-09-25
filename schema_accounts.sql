-- Schema for app-level accounts + business-unit (site) permission control.
-- Independent of ADMIN_PASSWORD (that gates only the DB /config page).

CREATE TABLE IF NOT EXISTS accounts (
    email       TEXT PRIMARY KEY,
    name        TEXT,
    pass_hash   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user'
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Site codes match the ones already derived from laptops.category /
-- sim_cards.contract_site in device_management.js (BO, CHT, KTT, KWH, LRT,
-- PWH, SMT, TKOT). A row here grants that email read access to that site;
-- role='admin' accounts bypass this table entirely (see fetch_device_management).
CREATE TABLE IF NOT EXISTS account_sites (
    email       TEXT NOT NULL REFERENCES accounts(email) ON DELETE CASCADE,
    site_code   TEXT NOT NULL,
    PRIMARY KEY (email, site_code)
);
