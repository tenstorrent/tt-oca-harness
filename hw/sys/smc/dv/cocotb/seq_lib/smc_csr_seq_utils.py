# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Small helpers for real SEP_IN AXI CSR sequences."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    GPIO_INTF_STRIDE,
    I2C_CG_EN,
    smc_addr,
    smc_indexed_addr,
)
from .smc_base_test_seq import smc_base_test_seq
from .smc_efuse_vip_utils import EFUSE_BLOCKED_READ_DATA


class SmcCsrSeq(smc_base_test_seq):
    """Base sequence with compact SEP_IN AXI CSR helpers."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.accesses = 0
        self.timeouts = 0
        # Accesses issued through a helper that TOLERATES a no-response
        # (`csr_read_bounded` / `csr_short_timeout`). Only these can ever make
        # `self.timeouts` non-zero: every other helper leaves `allow_timeout`
        # False, and the driver raises on a no-response before the sequence
        # regains control. Tracking them is what lets `assert_all_reachable`
        # tell a real reachability leg from one that cannot fail.
        self.bounded_accesses = 0

    async def csr_read(
        self, name: str, addr: int, expected: int | None = None, length: int = 4, prot: int = 0
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        item.prot = prot
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def csr_write(
        self, name: str, addr: int, data: int, length: int = 4, prot: int = 0
    ) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.prot = prot
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def rw_coresident(
        self,
        entries: list[tuple[str, int, int, int]],
        length: int = 4,
    ) -> None:
        """Write every ``(label, addr, pattern, restore)`` first, then read all back.

        The patterns and the addresses must be pairwise distinct: with the
        writes batched, a decode that collapses two of the addresses onto one
        register holds the last pattern written and the first readback fails.
        Every address is then restored and the restore read back exactly.
        """
        assert len({e[1] for e in entries}) == len(entries), "co-resident addresses not distinct"
        assert len({e[2] for e in entries}) == len(entries), "co-resident patterns not distinct"
        for label, addr, pattern, _restore in entries:
            await self.csr_write(f"{label}_PATTERN", addr, pattern, length=length)
        for label, addr, pattern, _restore in entries:
            await self.csr_read(f"{label}_PATTERN_RB", addr, expected=pattern, length=length)
        for label, addr, _pattern, restore in entries:
            await self.csr_write(f"{label}_RESTORE", addr, restore, length=length)
        for label, addr, _pattern, restore in entries:
            await self.csr_read(f"{label}_RESTORE_RB", addr, expected=restore, length=length)

    async def csr_read_many(self, regs: list[tuple[str, int, int | None]]) -> None:
        for name, addr, expected in regs:
            await self.csr_read(name, addr, expected)

    async def csr_read_many_allow_error(self, regs: list[tuple[str, int, int | None]]) -> None:
        """Read a list of windows that are terminated as AXI error
        slaves. ``allow_error`` lets the DECERR/SLVERR response count as a
        completed access, so the sequence still proves the fabric decodes/
        routes to the window and the bus never hangs, without asserting a real
        register value the terminator cannot provide. The per-entry ``expected``
        field is ignored here (the reg tables stay uniform)."""
        for name, addr, _expected in regs:
            await self.csr_read_allow_error(name, addr)

    # Data word an AXI error slave returns alongside its error response. The
    # one place the value is specified is the eFuse architecture document
    # (``hw/ip/efuse/doc/architecture.adoc``, JTAG access control: "When a
    # request is blocked, the error slave returns an error response with data
    # value 0xbadcab1e"); ``EFUSE_BLOCKED_READ_DATA`` is the DV-owned copy of
    # that sentence. The document states the word for the eFuse error slave
    # only; expecting it from the other error-terminated windows the sweeps
    # probe is a DV-owned assumption, declared here rather than cited.
    ERR_SLAVE_SIGNATURE = EFUSE_BLOCKED_READ_DATA

    async def csr_read_err_signature(
        self, name: str, addr: int, length: int = 4, prot: int = 0
    ) -> int:
        """Read a window terminated by an AXI error slave and
        DETERMINISTICALLY assert its known error signature: the access must
        complete with an error response (SLVERR/DECERR) AND return
        ``ERR_SLAVE_SIGNATURE``, the data word the eFuse architecture document
        specifies for a blocked request. Used for TB-side terminators (e.g. DTP
        CSR) and design-side error slaves that return that signature."""
        mask = (1 << (length * 8)) - 1
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True  # scoreboard also enforces the error response
        item.prot = prot
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: expected an error-slave response "
            f"(SLVERR/DECERR), got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        got = item.rdata & mask
        assert got == (self.ERR_SLAVE_SIGNATURE & mask), (
            f"{name} @ 0x{addr:08x}: expected error-slave signature "
            f"0x{self.ERR_SLAVE_SIGNATURE & mask:0{length * 2}x}, got 0x{got:0{length * 2}x}"
        )
        return item.rdata

    async def csr_read_many_err_signature(self, regs: list[tuple[str, int, int | None]]) -> None:
        """Deterministic error-signature sweep over a reg table (see
        csr_read_err_signature)."""
        for name, addr, _expected in regs:
            await self.csr_read_err_signature(name, addr)

    async def csr_read_decerr_zero(self, name: str, addr: int, length: int = 4) -> int:
        """Read a window that must complete with an AXI error response
        (SLVERR/DECERR) and an all-zero data word.

        The zero is a DV-owned expectation, not a document-cited value: an
        error response carries no payload, so a terminator that hands back a
        neighbouring register's contents or a stale bus word fails here. Two
        sequences call it: ``smc_gpio_ctrl_full_sweep_test_seq`` (the external
        GPIO_CTRL windows) relies on this DV-owned zero alone;
        ``smc_sideband_protocol_smoke_test_seq`` reads AVS_READBACK on an empty
        FIFO, where memmap.adoc does fix the zero, and cites it at the call."""
        mask = (1 << (length * 8)) - 1
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True
        item.expected = 0
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: expected DECERR/SLVERR, "
            f"got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        got = item.rdata & mask
        assert got == 0, f"{name} @ 0x{addr:08x}: expected rdata=0, got 0x{got:0{length * 2}x}"
        return item.rdata

    async def csr_read_expect_error(self, name: str, addr: int, length: int = 4) -> int:
        """Read a window that deterministically returns an AXI error response
        (SLVERR/DECERR) without asserting a data signature."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.expect_error = True  # scoreboard also enforces the error response
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: expected an error response (SLVERR/DECERR), "
            f"got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        return item.rdata

    async def csr_write_expect_error(
        self, name: str, addr: int, data: int, length: int = 4, prot: int = 0
    ) -> int:
        """Write a register that must refuse it with an AXI error response.

        Returns the response code so the caller can report which refusal the
        DUT gave. The caller pairs this with a readback proving the refused
        write took no effect."""
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_error = True
        item.expect_error = True  # scoreboard also enforces the error response
        item.prot = prot
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: expected an error response (SLVERR/DECERR), "
            f"got resp={item.resp_code}"
        )
        return item.resp_code

    async def csr_read_allow_error(self, name: str, addr: int, length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def csr_read_bounded(
        self, name: str, addr: int, length: int = 4, timeout_ns: int = 200
    ) -> int:
        """Bounded read: tolerates DECERR **and** timeout (no-decode).

        Intended for coverage-gap CSR probes where the block may be
        clock-gated or absent from this bench and there is no
        AXI responder to send back OKAY/DECERR. Increments `timeouts` on
        no-response, `accesses` unconditionally.
        """
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        # allow_timeout: helper for unreachable CSR windows; caller must score
        # timeouts/accesses (second evidence). Default csr_read stays strict.
        item.allow_timeout = True
        item.timeout_ns = timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.bounded_accesses += 1
        if item.timed_out:
            self.timeouts += 1
        return item.rdata

    async def csr_write_readback(self, name: str, addr: int, data: int) -> None:
        await self.csr_write(name, addr, data)
        await self.csr_read(name, addr, expected=data)

    async def csr_restore(self, name: str, addr: int, data: int = 0) -> None:
        await self.csr_write(f"{name}_RESTORE", addr, data)
        await self.csr_read(f"{name}_RESTORE", addr, expected=data)

    async def csr_short_timeout(self, name: str, addr: int, timeout_ns: int = 50) -> None:
        item = SmcSysAxiItem(f"timeout_rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_timeout = True  # the assert below requires timed_out
        item.timeout_ns = timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        assert item.timed_out, f"{name} completed before the short timeout"
        self.accesses += 1
        self.bounded_accesses += 1
        self.timeouts += 1

    async def drain_axi(self, cycles: int = 200) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, cycles)

    # --- DUT I2C0 controller register->pin proof (model-free real DUT gate) ---
    # SMC_BASE_CONFIG clock-gate + I2C0 ctrl/ovrd CSRs. Used by the SMBus/PMBus
    # tests (and mirrors smc_i2c_master_target_test) to gate on real DUT behaviour
    # rather than pure VIP-side protocol math.
    _I2C0_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
    _I2C0_CG_EN = I2C_CG_EN
    _I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
    _I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", 0)
    _I2C0_CTRL_ENABLE = 0x11
    _I2C0_OVRD_RELEASE = 0x7
    _I2C0_OVRD_SCL_LOW = 0x5
    _I2C0_OVRD_SDA_LOW = 0x3
    _I2C0_OVRD_BOTH_LOW = 0x1

    # Bound for the OVRD-write -> open-drain pad settle. The path is
    # CSR write ack (clk_smc) -> i2c_wrap OVRD -> GPIO pad mux -> the tb_top
    # open-drain resolver (tb_top.sv:644-647), i.e. a handful of clk_smc cycles
    # plus the AXI-Lite write completion the caller already awaited. The bound is
    # generous so a slow build cannot flake; expiry is a FAILURE, never a pass
    # ([TIMEOUT-MUST-FAIL]).
    _I2C0_PAD_SETTLE_TIMEOUT_CYCLES = 400
    _I2C0_PAD_POLL_CYCLES = 2
    # After the expected level is first seen, require it to still hold this many
    # cycles later, so a one-cycle glitch that happens to match cannot be
    # accepted as the settled register->pin state.
    _I2C0_PAD_STABLE_CYCLES = 8

    async def _i2c0_check_line(self, name: str, exp_scl: int, exp_sda: int) -> None:
        """Bounded poll of the real I2C0 open-drain pad nets after an OVRD write.

        Polls ``tb_i2c0_scl`` / ``tb_i2c0_sda`` ([NO-BLIND-DELAY-SYNC]; the
        tb_top open-drain resolution of the DUT-driven pads) until they match the
        level the just-written OVRD value demands, then re-sample to confirm the
        level is stable. Expiry raises with the last observed state, so a pad
        that never reaches the commanded level FAILS the testcase instead of
        being masked by a longer delay.
        """
        dut = cocotb.top
        deadline = self._I2C0_PAD_SETTLE_TIMEOUT_CYCLES
        waited = 0
        scl = int(dut.tb_i2c0_scl.value)
        sda = int(dut.tb_i2c0_sda.value)
        while (scl, sda) != (exp_scl, exp_sda) and waited < deadline:
            await ClockCycles(dut.clk_smc_i, self._I2C0_PAD_POLL_CYCLES)
            waited += self._I2C0_PAD_POLL_CYCLES
            scl = int(dut.tb_i2c0_scl.value)
            sda = int(dut.tb_i2c0_sda.value)
        assert (scl, sda) == (exp_scl, exp_sda), (
            f"{name}: DUT-driven I2C0 pads never reached scl={exp_scl} "
            f"sda={exp_sda} within {deadline} clk_smc_i cycles after the OVRD "
            f"write (last observed scl={scl} sda={sda}); the I2C0 "
            f"register->pin path is broken, gated, or the pad mux is not on LSIO"
        )
        await ClockCycles(dut.clk_smc_i, self._I2C0_PAD_STABLE_CYCLES)
        scl_hold = int(dut.tb_i2c0_scl.value)
        sda_hold = int(dut.tb_i2c0_sda.value)
        assert (scl_hold, sda_hold) == (exp_scl, exp_sda), (
            f"{name}: DUT-driven I2C0 pads reached scl={exp_scl} sda={exp_sda} "
            f"but did not hold it for {self._I2C0_PAD_STABLE_CYCLES} clk_smc_i "
            f"cycles (now scl={scl_hold} sda={sda_hold}): a transient, not the "
            f"settled OVRD state"
        )
        cocotb.log.info(
            "%s: DUT-driven scl=%d sda=%d == expected (settled after %d "
            "clk_smc_i cycle(s), held %d)",
            name,
            scl_hold,
            sda_hold,
            waited,
            self._I2C0_PAD_STABLE_CYCLES,
        )

    # I2C0 pads 37..40 (SCL/SDA/ALERT/SUS). DATA_CTRL stride 0x10 from GPIO0.
    _GPIO_INTF0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
    _GPIO_INTF_STRIDE = GPIO_INTF_STRIDE
    _I2C0_SCL_PAD = 37
    _GPIO_LSIO_SELECT = 1 << 17

    async def _arm_i2c0_gpio_lsio(self, label: str) -> None:
        """Force I2C0 pad mux onto LSIO via GPIO DATA_CTRL.lsio_select.

        Verilator codegen of ``i2c_wrap``'s ``MAX_NUM_I2CS`` always_comb writes
        OOB and then zeros ``i2c_en_o`` / ``i2c_controller_mode_en_o``, so the
        CDC'd ``i2c_enable_smc_clk`` never rises and GPIO holds ``scl_i/sda_i``
        at 0. Software ``lsio_select`` is the supported override (same as
        gpio_intf.rdl) and restores pad sense without touching RTL.
        """
        for pad in range(self._I2C0_SCL_PAD, self._I2C0_SCL_PAD + 4):
            addr = self._GPIO_INTF0_DATA_CTRL + pad * self._GPIO_INTF_STRIDE
            cur = await self.csr_read(f"{label}_GPIO{pad}_SAVE", addr)
            await self.csr_write(
                f"{label}_GPIO{pad}_LSIO",
                addr,
                cur | self._GPIO_LSIO_SELECT,
            )

    async def wait_i2c0_lsio_ready(self, label: str = "I2C0_LSIO") -> None:
        """Wait until I2C0 pad sense tracks the OD bus (host can leave idle).

        When LSIO is inactive, gpio forces ``i2c_scl_i/sda_i`` to 0 even if the
        TB OD bus is high — the OpenTitan host then waits forever for SCL
        release (HOSTIDLE / FMT stuck).
        """
        dut = cocotb.top
        await self._arm_i2c0_gpio_lsio(label)
        if not hasattr(dut, "tb_i2c0_scl_i"):
            await ClockCycles(dut.clk_smc_i, 64)
            return
        for _ in range(2000):
            bus_scl = int(dut.tb_i2c0_scl.value)
            scl_i = int(dut.tb_i2c0_scl_i.value)
            en = int(dut.tb_i2c0_enable.value) if hasattr(dut, "tb_i2c0_enable") else -1
            # Sense path is what the host needs; enable may stay 0 on Verilator
            # (i2c_wrap OOB wipe) even after WRAP I2C_EN=1 + GPIO lsio_select.
            if bus_scl == 1 and scl_i == 1:
                cocotb.log.info("%s ready: bus_scl=1 scl_i=1 enable=%s", label, en)
                return
            await ClockCycles(dut.clk_smc_i, 4)
        en = int(dut.tb_i2c0_enable.value) if hasattr(dut, "tb_i2c0_enable") else -1
        raise AssertionError(
            f"{label}: I2C0 LSIO sense not ready "
            f"(en={en} "
            f"bus_scl={int(dut.tb_i2c0_scl.value)} "
            f"scl_i={int(dut.tb_i2c0_scl_i.value)} "
            f"sda_i={int(dut.tb_i2c0_sda_i.value)})"
        )

    async def prove_dut_i2c0_pins(self) -> None:
        """Real, model-free DUT gate: enable the DUT I2C0 controller over SEP_IN
        AXI and verify it physically drives the tb_i2c0_scl/sda pins through the
        OVRD register (register -> pin path). Fails if the DUT I2C0 controller is
        broken/absent or a CSR readback mismatches. Restores clock-gate + OVRD
        state before returning. (Same proof as smc_i2c_master_target_test.)"""
        cg = await self.csr_read("I2C0_CG_SAVE", self._I2C0_CLOCK_GATE_CONTROL)
        await self.csr_write("I2C0_UNGATE", self._I2C0_CLOCK_GATE_CONTROL, cg & ~self._I2C0_CG_EN)
        await self.csr_write("I2C0_CTRL_EN", self._I2C0_CTRL, self._I2C0_CTRL_ENABLE)
        await self.csr_read("I2C0_CTRL_EN_RB", self._I2C0_CTRL, expected=self._I2C0_CTRL_ENABLE)
        await self.csr_write("I2C0_OVRD_REL", self._I2C0_OVRD, self._I2C0_OVRD_RELEASE)
        await self._i2c0_check_line("i2c0_release", 1, 1)
        await self.csr_write("I2C0_OVRD_SCL_LOW", self._I2C0_OVRD, self._I2C0_OVRD_SCL_LOW)
        await self._i2c0_check_line("i2c0_scl_low", 0, 1)
        await self.csr_write("I2C0_OVRD_SDA_LOW", self._I2C0_OVRD, self._I2C0_OVRD_SDA_LOW)
        await self._i2c0_check_line("i2c0_sda_low", 1, 0)
        await self.csr_write("I2C0_OVRD_BOTH_LOW", self._I2C0_OVRD, self._I2C0_OVRD_BOTH_LOW)
        await self._i2c0_check_line("i2c0_both_low", 0, 0)
        await self.csr_write("I2C0_OVRD_REL_RESTORE", self._I2C0_OVRD, self._I2C0_OVRD_RELEASE)
        await self._i2c0_check_line("i2c0_release_restore", 1, 1)
        await self.csr_write("I2C0_CG_RESTORE", self._I2C0_CLOCK_GATE_CONTROL, cg)

    def assert_all_reachable(self, expected_accesses: int, block: str) -> None:
        """Gate a CSR sweep on MEASURED reachability, never on a self-count.

        Three legs. The first is the weakest and does not carry the claim on
        its own:

        1. ``accesses == expected`` -- loop integrity only. `accesses` is bumped
           unconditionally by every helper regardless of what the DUT did, so
           this can fail only on a short-circuited loop or a source edit; it is
           NOT reachability evidence and is not presented as such.
        2. scoreboard cross-check -- ``sys_axi_checks_seen`` is incremented by
           the *scoreboard* when it checks an item it received, and every such
           check asserts ``resp_ok``. Comparing it against the accesses this
           sequence issued therefore fails when the traffic never reached the
           scoreboard (mis-bound/disconnected analysis path), which the
           sequence's own counter cannot see ([NO-ZERO-ACTIVITY-PASS]).
        3. bounded-read reachability -- ``timeouts == 0``. `timeouts` is only
           ever non-zero for ``csr_read_bounded`` / ``csr_short_timeout``, the
           two helpers that tolerate a no-response; for a sweep that issued
           neither, ``timeouts == 0`` is a leg that cannot fail on any RTL. So
           it is asserted only when such an access actually ran, and otherwise
           reported as not-applicable rather than logged as a passing
           reachability check ([NO-DUMMY-DEAD-CODE]): on a strict sweep,
           reachability is enforced per-access by the driver (a no-response
           raises there), not here.
        """
        assert self.accesses == expected_accesses, (
            f"{block}: issued {self.accesses} accesses, expected "
            f"{expected_accesses} (loop integrity, not reachability)"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            f"{block}: no scoreboard on this sequence's env, so the CSR traffic "
            f"cannot be corroborated independently of the sequence's own counter"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"{block}: the scoreboard checked only {sb.sys_axi_checks_seen} SYS "
            f"AXI item(s) but this sequence issued {self.accesses} access(es) -- "
            f"the traffic never reached the scoreboard, so none of it is checked "
            f"evidence"
        )
        if self.bounded_accesses:
            assert self.timeouts == 0, (
                f"{block}: {self.timeouts} of {self.bounded_accesses} bounded "
                f"read(s) got NO AXI response (periph route/decode unreachable "
                f"or CSR master would hang)"
            )
            cocotb.log.info(
                "%s: all %d access(es) checked by the scoreboard; %d of them "
                "tolerated a no-response and all of them answered.",
                block,
                expected_accesses,
                self.bounded_accesses,
            )
        else:
            cocotb.log.info(
                "%s: all %d access(es) checked by the scoreboard. No bounded "
                "read ran, so `timeouts == 0` would be a check that cannot "
                "fail and is NOT asserted here: on this path a no-response "
                "already raises in the AXI driver.",
                block,
                expected_accesses,
            )

    def assert_reachable_or_gated(
        self, expected_accesses: int, block: str, gated_note: str
    ) -> None:
        """Reachability gate for windows that are clock-gated or
        absent in this OSS bench (e.g. the CPU cluster before firmware
        boot, a Verilator/vendor-stubbed macro).

        Unlike ``assert_all_reachable`` this does not hard-fail on a no-response,
        because for these windows the block genuinely is not exercisable in this
        proxy bench -- forcing OKAY/DECERR here would invent coverage that does
        not exist. It still enforces the real, in-scope properties:

        * ``accesses == expected`` -- every probe returned (via response or a
          bounded timeout), so the sequence never deadlocked the shared CSR
          master, and
        * the reachable subset is response-gated (those reads DID get an AXI
          answer), giving genuine decode coverage for whatever is present.

        Any gated window is logged (not silently swallowed) so the register-level
        coverage this bench cannot take is visible rather than hidden behind a
        green vacuous ``accesses == N``.
        """
        assert self.accesses == expected_accesses, (
            f"{block}: issued {self.accesses} accesses, expected "
            f"{expected_accesses} (loop integrity, not reachability)"
        )
        # Same scoreboard cross-check as assert_all_reachable: the sequence's own
        # counter cannot tell that the traffic reached the checker at all.
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            f"{block}: no scoreboard on this sequence's env, so the CSR traffic "
            f"cannot be corroborated independently of the sequence's own counter"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"{block}: the scoreboard checked only {sb.sys_axi_checks_seen} SYS "
            f"AXI item(s) but this sequence issued {self.accesses} access(es) -- "
            f"the traffic never reached the scoreboard"
        )
        reachable = self.accesses - self.timeouts
        if self.timeouts:
            cocotb.log.warning(
                "%s: %d/%d window(s) reachable; %d gated/absent in this OSS "
                "bring-up (%s). No-hang verified (every bounded probe returned); "
                "register-level decode deferred for the gated window(s).",
                block,
                reachable,
                expected_accesses,
                self.timeouts,
                gated_note,
            )
        else:
            cocotb.log.info(
                "%s: all %d window(s) reachable (AXI response received).",
                block,
                expected_accesses,
            )
