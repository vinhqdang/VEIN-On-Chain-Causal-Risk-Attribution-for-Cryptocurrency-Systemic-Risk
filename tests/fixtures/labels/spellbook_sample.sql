-- Synthetic six-row fixture in the layout of Spellbook's cex_evms_addresses.sql.
-- It is not the real list. Addresses are made up.
{{config(tags = ['static'], schema = 'cex_evms', alias = 'addresses')}}

SELECT address, cex_name, distinct_name, added_by, added_date
FROM (VALUES
    -- Binance
    (0x1111111111111111111111111111111111111111, 'Binance', 'Binance 1', 'tester', date '2022-08-28')
    -- Coinbase Prime deposit address
    , (0x2222222222222222222222222222222222222222, 'Coinbase Prime', 'Coinbase Prime Deposit 1', 'tester', date '2023-11-19')
    , (0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD, 'Gate', 'Gate.io 1', 'tester', date '2024-01-02')
    , (0x4444444444444444444444444444444444444444, 'Binance', 'Binance Charity', 'tester', date '2024-01-02')
    , (0x5555555555555555555555555555555555555555, 'Bithumb', 'Bithumb 1 kaia', 'tester', date '2026-01-02')
    , (0x6666666666666666666666666666666666666666, 'Unknown Venue', 'Unknown Venue 1', 'tester', date '2025-06-25')
    ) AS x (address, cex_name, distinct_name, added_by, added_date)
