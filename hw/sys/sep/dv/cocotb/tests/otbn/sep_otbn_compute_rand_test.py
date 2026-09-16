# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN as a compute engine (RANDCFG).

Loads a tiny RV32I program into IMEM over the CPU-LSU AXI master, stages two
seeded DMEM operands, issues EXECUTE, and checks ERR_BITS==0 plus DMEM result
against an independent Python golden. Walks ADD, XOR, and AND in one
invocation. Distinct from sep_otbn_mem_smoke_test (write/readback, no EXECUTE)
and from the KM sideload key-dump (WSR reconstruct, no ALU golden).

no_cpu + +skip_fuse_sense + +esrc_noise_force: post-reset secure wipe consumes
OTBN URND, so the real entropy stack is brought up and other crypto-EDN
clients are parked.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_otbn_compute_seq import SepOtbnCompute, SepOtbnComputeCfg


@pyuvm.test()
class sep_otbn_compute_rand_test(sep_base_test):
    """IMEM program + EXECUTE + ERR_BITS==0 + DMEM==golden."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac"))
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"otbn_urnd": "observe"}
        )
        self.start_fifo_drain()

        cfg = SepOtbnComputeCfg.from_seed(self.random_seed())
        self.logger.info("OTBN compute RANDCFG %s", cfg.summary())
        otbn = SepOtbnCompute(self)
        await otbn.wait_idle("post-wipe", timeout=8_000)

        for op, a, b, expect in cfg.cells():
            err, got = await otbn.run_cell(op, a, b, expect)
            assert err == 0, f"CHK-ERRBITS FAIL: OTBN {op} ERR_BITS=0x{err:08x}, expected 0"
            assert got == expect, (
                f"CHK-DMEM FAIL: OTBN {op} DMEM[8]=0x{got:08x} "
                f"!= golden 0x{expect:08x} (a=0x{a:08x} b=0x{b:08x})"
            )
            self.logger.info(
                "CHK-CELL PASS: OTBN %s a=0x%08x b=0x%08x result=0x%08x ERR_BITS=0", op, a, b, got
            )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()

        self.logger.info(
            "CHK-RANDCFG PASS: walked all %d discrete ops %s (seed=%d)",
            cfg.n_cells(),
            list(op for op, *_ in cfg.cells()),
            cfg.seed,
        )
        self.logger.info("CHK-ERRBITS PASS: every compute cell retired with ERR_BITS=0")
        self.logger.info("CHK-DMEM PASS: every compute cell DMEM result matched the golden")
