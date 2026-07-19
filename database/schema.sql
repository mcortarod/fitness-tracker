-- =========================================================================
-- Fitness Tracker — v1 schema (SQLite)
-- =========================================================================
-- Dimensional model:
--   * dim_date          — calendar dimension, one row per day (pre-loaded).
--   * profile           — user's static attributes (single row).
--   * fact_mass         — daily grain: body mass in kg.
--   * fact_perimeters   — weekly grain (ISO week): body perimeters in cm,
--                        keyed by the Monday of the ISO week.
--
-- Calculated metrics (BMI, body fat %, ratios) are exposed via VIEWs
-- (v_daily_metrics, v_weekly_metrics) — never materialized.
--
-- NOTE on foreign keys: SQLite requires `PRAGMA foreign_keys = ON` per
-- connection to enforce FKs. The schema declares them for documentation
-- and future portability (Postgres v2); enforcement is enabled in the
-- Python data-access layer.
-- =========================================================================


-- -------------------------------------------------------------------------
-- Calendar dimension
-- -------------------------------------------------------------------------
CREATE TABLE dim_date (
    date                TEXT PRIMARY KEY,       -- ISO 8601: 'YYYY-MM-DD'
    year                INTEGER NOT NULL,
    month               INTEGER NOT NULL,
    day                 INTEGER NOT NULL,
    day_of_week         INTEGER NOT NULL,       -- 0 = Monday ... 6 = Sunday
    week_start_date     TEXT NOT NULL,          -- Monday of the ISO week
    iso_week            INTEGER NOT NULL        -- ISO week number 1...53
);


-- -------------------------------------------------------------------------
-- User profile (single-row table by design)
-- -------------------------------------------------------------------------
CREATE TABLE profile (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    height_cm   REAL NOT NULL CHECK (height_cm > 0),
    sex         TEXT NOT NULL CHECK (sex IN ('M', 'F')),
    birth_date  TEXT                                        -- optional, ISO
);


-- -------------------------------------------------------------------------
-- Daily fact: body mass
-- -------------------------------------------------------------------------
CREATE TABLE fact_mass (
    date        TEXT PRIMARY KEY,
    mass_kg     REAL NOT NULL CHECK (mass_kg > 0),
    FOREIGN KEY (date) REFERENCES dim_date(date)
);


-- -------------------------------------------------------------------------
-- Weekly fact: body perimeters (all in cm)
-- -------------------------------------------------------------------------
-- Grain: one row per ISO week.
-- PK is the Monday of the ISO week the measurement represents, even if
-- the reading was physically taken on the following Sunday. `measured_on`
-- captures the actual reading date for traceability (optional).
CREATE TABLE fact_perimeters (
    week_start_date     TEXT PRIMARY KEY,                       -- Monday, ISO
    measured_on         TEXT,                                   -- actual reading date, ISO
    neck_cm             REAL NOT NULL CHECK (neck_cm > 0),
    shoulder_cm         REAL NOT NULL CHECK (shoulder_cm > 0),
    right_arm_cm        REAL NOT NULL CHECK (right_arm_cm > 0),
    left_arm_cm         REAL NOT NULL CHECK (left_arm_cm > 0),
    waist_cm            REAL NOT NULL CHECK (waist_cm > 0),
    hip_cm              REAL NOT NULL CHECK (hip_cm > 0),
    right_thigh_cm      REAL NOT NULL CHECK (right_thigh_cm > 0),
    left_thigh_cm       REAL NOT NULL CHECK (left_thigh_cm > 0),
    FOREIGN KEY (week_start_date) REFERENCES dim_date(date)
);


-- =========================================================================
-- VIEWs — calculated metrics
-- =========================================================================

-- -------------------------------------------------------------------------
-- Daily metrics: BMI (requires mass + height from profile)
-- -------------------------------------------------------------------------
CREATE VIEW v_daily_metrics AS 
SELECT
    fm.date,
    fm.mass_kg,
    p.height_cm,
    ROUND(fm.mass_kg / ((p.height_cm / 100.0) * (p.height_cm / 100.0)), 2) AS bmi
FROM fact_mass fm 
CROSS JOIN profile p;


-- -------------------------------------------------------------------------
-- Weekly metrics: body fat % (US Navy formula) + ratios
-- -------------------------------------------------------------------------
-- US Navy body fat formula (all lengths in cm):
--   Men:   %BF = 495 / (1.0324 - 0.19077*log10(waist - neck)
--                       + 0.15456*log10(height)) - 450
--   Women: %BF = 495 / (1.29579 - 0.35004*log10(waist + hip - neck)
--                       + 0.22100*log10(height)) - 450
-- SQLite's LOG10() is available in modern builds.
-- -------------------------------------------------------------------------
CREATE VIEW v_weekly_metrics AS 
SELECT
    fp.week_start_date,
    fp.waist_cm,
    fp.hip_cm,
    fp.neck_cm,
    fp.shoulder_cm,
    p.height_cm,
    p.sex,
    -- Waist-to-hip ratio
    ROUND(fp.waist_cm / fp.hip_cm, 3) AS waist_hip_ratio,
    -- Shoulder-to-waist ratio (Adonis index, ideal ≈ 1.618, higher is better)
    ROUND(fp.shoulder_cm / fp.waist_cm, 3) AS shoulder_waist_ratio,
    -- Body fat % (US Navy) - branches by sex
    CASE
        WHEN p.sex = 'M' THEN
            ROUND(
                495.0 / (
                    1.0324
                    - 0.19077 * LOG10(fp.waist_cm - fp.neck_cm)
                    + 0.15456 * LOG10(p.height_cm)
                ) - 450.0,
            2)
        WHEN p.sex = 'F' THEN
            ROUND(
                495.0 / (
                    1.29579
                    - 0.35004 * LOG10(fp.waist_cm + fp.hip_cm - fp.neck_cm)
                    + 0.22100 * LOG10(p.height_cm)
                ) - 450.0,
            2)
    END AS body_fat_pct
FROM fact_perimeters fp
CROSS JOIN profile p;