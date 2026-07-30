# Deferred raise-stub tests (not enrolled)

These modules intentionally `raise AssertionError` under the 2026-07-29
**no DUT Force / no TB placeholder** policy. Catalog: `../testlists/deferred.toml`.

Do **not** report as PASS. Live enrolled tests remain in `../tests/`.
See `hw/sys/smc/doc/dv_hack_cleanup_checklist.md` Phase 1.3.
