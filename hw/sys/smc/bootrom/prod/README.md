# SMC production boot ROM (placeholder)

Reserved for the self-contained production SMC boot ROM firmware: its own
includes/drivers, not shared with `hw/sys/smc/dv/fw/` (the DV-only dummy
stub lives in the sibling [`dummy/`](../dummy) directory instead).

Not ported yet. When it is, port from `tt-oca-hw`'s `fw/smc/prod_rom/` and
give it its own `Makefile` built on the same shared engine
([`hw/common/dv/fw/compile.mk`](../../../../common/dv/fw/compile.mk)) as
every other DV/production firmware build in this repo.
