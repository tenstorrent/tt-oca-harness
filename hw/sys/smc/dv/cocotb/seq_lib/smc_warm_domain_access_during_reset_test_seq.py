# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A SCRATCH_COLD_WARM read during the warm reset errors and leaves the fabric live.

`smc_misc_wrap.sv` places `SCRATCH_COLD_WARM` on `rst_warm_ni` behind an
`axi_lite_demux` that sits on the primary reset. `cpu.adoc` states the rule for
a slave held in reset behind a live demux, and the CPU cluster implements it
with `axi_isolate`: an access made during the reset is answered with an error,
and the demux never records a request its slave cannot answer. Held to that
rule, a read of `SCRATCH_COLD_WARM` while `rst_warm_smc_clk_n` is low completes
with SLVERR or DECERR, and once the reset releases every read of
`SCRATCH_COLD_WARM`, `SCRATCH_COLD`, `CHIP_CONFIG.CHIP_ID` and
`RESET_UNIT.SS_CONFIG` completes.

The generated cpuif of `scratch_reg.sv` presents ready while it is held in reset
and drops the request, so the demux keeps a read it never gets an answer for,
its one-deep FIFO stays full, and the next read for the miscellaneous window
waits in the peripheral crossbar's spill register in front of every other
target on that channel. Only the primary reset drains it.

The warm reset is entered through the SEP watchdog reset input
(`tb_sep_wdt_reset_n` held low), which `smc_reset_ctrl.sv` folds into the warm
reset, so the entry does not depend on the watchdog register path. One read is
made during the reset: a write that hangs blocks the write channel the same
way, and since nothing short of the primary reset drains either, one leaf
holds one access.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

CHK = "CHK-WARM-DOMAIN-ACCESS-IN-RESET"
FUSE_SENSE_MAX_CYCLES = 200_000
ASSERT_BOUND_CYCLES = 300
IN_RESET_SETTLE_CYCLES = 50
RELEASE_BOUND_CYCLES = 20_000
POST_RELEASE_CYCLES = 200
BOUNDED_NS = 2_000
SCRATCH_PATTERN = 0xC0FFEE42
WARM_SCRATCH_PATTERN = 0x5A5AA5A5
COLD_SCRATCH_PATTERN = 0x3C3CC3C3
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
_ERROR_RESPS = ("SLVERR", "DECERR")


class _ReadPortMonitor:
    """Count SEP_IN AR and R handshakes, so a missing response is visible at the port."""

    def __init__(self) -> None:
        self.ar = 0
        self.r = 0

    def start(self) -> None:
        cocotb.start_soon(self._run())

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            if int(dut.s_axi_arvalid.value) and int(dut.s_axi_arready.value):
                self.ar += 1
            if int(dut.s_axi_rvalid.value) and int(dut.s_axi_rready.value):
                self.r += 1


class smc_warm_domain_access_during_reset_test_seq(SmcCsrSeq):
    """Read SCRATCH_COLD_WARM during the warm reset, release it, then probe the fabric."""

    def __init__(self, name: str = "smc_warm_domain_access_during_reset_test_seq") -> None:
        super().__init__(name)
        self.mon = _ReadPortMonitor()
        self.results: dict[str, str] = {}

    async def _bounded_read(self, phase: str, addr: int, length: int = 4) -> str:
        """Bounded read reported as the value, the error response name or TIMEOUT."""
        item = SmcSysAxiItem(f"rd_{phase}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = BOUNDED_NS
        ar0, r0 = self.mon.ar, self.mon.r
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.bounded_accesses += 1
        if item.timed_out:
            self.timeouts += 1
            res = "TIMEOUT"
        elif item.resp_code not in (None, 0):
            res = _RESP_NAMES.get(item.resp_code, str(item.resp_code))
        else:
            res = f"0x{item.rdata:x}"
        cocotb.log.info(
            "OBS-WARM-DOMAIN-ACCESS phase=%s addr=0x%x rd=%s warm_rst_n=%d ar_hs=+%d r_hs=+%d",
            phase,
            addr,
            res,
            int(cocotb.top.tb_rst_warm_smc_clk_n.value),
            self.mon.ar - ar0,
            self.mon.r - r0,
        )
        self.results[phase] = res
        return res

    async def _first_level(self, sig, want: int, bound: int) -> int | None:
        clk = cocotb.top.clk_smc_i
        for i in range(bound):
            await RisingEdge(clk)
            if sig.value.is_resolvable and int(sig.value) == want:
                return i + 1
        return None

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        scratch = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
        warm_scratch = smc_indexed_addr(
            "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0
        )
        cold_scratch = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
        chip_id = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR")
        ss_config = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")

        self.mon.start()
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        await ClockCycles(clk, 16)
        assert int(dut.tb_sep_wdt_reset_n.value) == 1, "SEP WDT reset input not idle high"
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 1, "warm reset asserted after boot"

        await self.csr_write("SCRATCH0_BOOT", scratch, SCRATCH_PATTERN, length=8)
        await self.csr_read("SCRATCH0_BOOT_RB", scratch, expected=SCRATCH_PATTERN, length=8)
        await self.csr_write("WARM_SCRATCH0_BOOT", warm_scratch, WARM_SCRATCH_PATTERN)
        await self.csr_read("WARM_SCRATCH0_BOOT_RB", warm_scratch, expected=WARM_SCRATCH_PATTERN)
        await self.csr_write("COLD_SCRATCH0_BOOT", cold_scratch, COLD_SCRATCH_PATTERN)
        await self.csr_read("COLD_SCRATCH0_BOOT_RB", cold_scratch, expected=COLD_SCRATCH_PATTERN)
        boot_chip_id = await self._bounded_read("boot_chip_id", chip_id)
        boot_ss_config = await self._bounded_read("boot_ss_config", ss_config)
        assert "TIMEOUT" not in (boot_chip_id, boot_ss_config), (
            f"a miscellaneous-window read timed out before the reset: CHIP_ID={boot_chip_id} "
            f"SS_CONFIG={boot_ss_config}"
        )

        dut.tb_sep_wdt_reset_n.value = 0
        fall = await self._first_level(dut.tb_rst_warm_smc_clk_n, 0, ASSERT_BOUND_CYCLES)
        assert fall is not None, (
            f"rst_warm_smc_clk_n still 1 {ASSERT_BOUND_CYCLES} cycles after the SEP WDT reset "
            f"input fell"
        )
        await ClockCycles(clk, IN_RESET_SETTLE_CYCLES)
        in_reset = await self._bounded_read("in_reset", warm_scratch)
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 0, "warm reset released during the read"
        dut.tb_sep_wdt_reset_n.value = 1
        released = await self._first_level(dut.tb_rst_warm_smc_clk_n, 1, RELEASE_BOUND_CYCLES)
        assert released is not None, (
            f"rst_warm_smc_clk_n still 0 {RELEASE_BOUND_CYCLES} cycles after the SEP WDT reset "
            f"input rose"
        )
        await ClockCycles(clk, POST_RELEASE_CYCLES)

        primary = await self._bounded_read("after_release_primary", scratch, length=8)
        assert primary == f"0x{SCRATCH_PATTERN:x}", (
            f"CPU_CTRL.SCRATCH[0] on the CPU-control crossbar reads {primary} after the release, "
            f"want 0x{SCRATCH_PATTERN:x}"
        )
        post = {
            "SCRATCH_COLD_WARM": await self._bounded_read("after_release_warm", warm_scratch),
            "SCRATCH_COLD": await self._bounded_read("after_release_cold", cold_scratch),
            "CHIP_ID": await self._bounded_read("after_release_chip_id", chip_id),
            "SS_CONFIG": await self._bounded_read("after_release_ss_config", ss_config),
        }
        post_text = " ".join(f"{name}={res}" for name, res in post.items())
        hung = [name for name, res in post.items() if res == "TIMEOUT"]
        if in_reset not in _ERROR_RESPS or hung:
            raise AssertionError(
                f"{CHK} FAIL: the read of SCRATCH_COLD_WARM during the warm reset answered "
                f"{in_reset} (want SLVERR or DECERR); after the release {post_text}; "
                f"{len(hung)} of 4 reads on the peripheral crossbar never completed"
            )
        cocotb.log.info(
            "%s PASS: the read of SCRATCH_COLD_WARM during the warm reset answered %s and after "
            "the release %s",
            CHK,
            in_reset,
            post_text,
        )
