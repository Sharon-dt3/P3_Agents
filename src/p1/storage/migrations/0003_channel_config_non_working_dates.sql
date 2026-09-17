-- 0003_channel_config_non_working_dates.sql
-- One-off calendar exceptions per channel (CHN-07 fix): a specific date
-- that falls on an otherwise-working weekday but is configured as never
-- counting as a missed-update day (e.g. a holiday). Distinct from
-- working_days, which is a recurring weekday pattern.

ALTER TABLE channel_config ADD COLUMN non_working_dates TEXT NOT NULL DEFAULT '[]';
