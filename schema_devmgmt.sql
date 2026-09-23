-- Schema for the Device Management tab.
-- Power Automate writes here daily after reading the SharePoint Excel.
-- Run once on both your local PG and Zeabur PG.

CREATE TABLE IF NOT EXISTS laptops (
    serial_number               TEXT PRIMARY KEY,
    device_name                 TEXT,
    unique_device               INTEGER,
    enrollment_date             DATE,
    manufacturer                TEXT,
    model                       TEXT,
    category                    TEXT,
    primary_user_upn            TEXT,
    primary_user_display_name   TEXT,
    device_per_user             INTEGER,
    remarks                     TEXT,
    status                      TEXT,
    last_synced                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sim_cards (
    sim_no                          TEXT PRIMARY KEY,    -- keep as TEXT to be safe with leading zeros
    telcom                          TEXT,
    contract_site                   TEXT,
    contract_no                     TEXT,
    monthly_fee                     NUMERIC,
    sim_owner                       TEXT,
    contract_start_date             DATE,
    contract_end_date               DATE,
    site_contract                   DATE,
    count_day_of_sim_contract_end   INTEGER,
    last_synced                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One-row metadata table so the dashboard can show "Last synced …"
CREATE TABLE IF NOT EXISTS device_mgmt_sync (
    id            INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_synced   TIMESTAMPTZ,
    laptops_count INTEGER DEFAULT 0,
    sims_count    INTEGER DEFAULT 0
);
INSERT INTO device_mgmt_sync (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
