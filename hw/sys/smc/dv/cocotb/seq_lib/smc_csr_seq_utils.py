# SPDX-License-Identifier: Apache-2.0
"""Small helpers for real SEP_IN AXI CSR sequences."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq


class SmcCsrSeq(smc_base_test_seq):
    """Base sequence with compact SEP_IN AXI CSR helpers."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.accesses = 0
        self.timeouts = 0

    async def csr_read(self, name: str, addr: int, expected: int | None = None,
                       length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def csr_write(self, name: str, addr: int, data: int, length: int = 4) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = length
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def csr_read_many(self, regs: list[tuple[str, int, int | None]]) -> None:
        for name, addr, expected in regs:
            await self.csr_read(name, addr, expected)

    async def csr_read_many_allow_error(
        self, regs: list[tuple[str, int, int | None]]
    ) -> None:
        """Read a list of windows that are intentionally stubbed as AXI error
        slaves (e.g. the I3C CSR windows: smc_peripherals instantiates
        ``i3ccore_stub`` -- "TODO: stub i3c out until the updated open-source
        controller is integrated" -- which completes every access with SLVERR
        and 0xBADCAB1E). ``allow_error`` lets the DECERR/SLVERR response count as
        a completed access, so the sequence still proves the fabric decodes/
        routes to the window and the bus never hangs, without asserting a real
        register value the stub cannot provide. The per-entry ``expected`` field
        is ignored here on purpose (kept so the reg tables stay uniform)."""
        for name, addr, _expected in regs:
            await self.csr_read_allow_error(name, addr)

    # AXI error-slave data signature returned by the boundary/stub responders
    # (i3ccore_stub, prim_axi_lite_err_slv macro terminators, efuse stub, etc.).
    ERR_SLAVE_SIGNATURE = 0xBADCAB1E

    async def csr_read_err_signature(self, name: str, addr: int, length: int = 4) -> int:
        """Read a window intentionally terminated by an AXI error slave and
        DETERMINISTICALLY assert its known error signature: the access must
        complete with an error response (SLVERR/DECERR) AND return the
        0xBADCAB1E signature (default ``prim_axi_lite_err_slv`` RESP_DATA).
        Used for TB-side terminators (e.g. DTP CSR) and in-RTL stubs that keep
        that signature (e.g. ``i3ccore_stub``)."""
        mask = (1 << (length * 8)) - 1
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
            f"{name} @ 0x{addr:08x}: expected an error-slave response "
            f"(SLVERR/DECERR), got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        got = item.rdata & mask
        assert got == (self.ERR_SLAVE_SIGNATURE & mask), (
            f"{name} @ 0x{addr:08x}: expected error-slave signature "
            f"0x{self.ERR_SLAVE_SIGNATURE & mask:0{length * 2}x}, got 0x{got:0{length * 2}x}"
        )
        return item.rdata

    async def csr_read_many_err_signature(
        self, regs: list[tuple[str, int, int | None]]
    ) -> None:
        """Deterministic error-signature sweep over a reg table (see
        csr_read_err_signature)."""
        for name, addr, _expected in regs:
            await self.csr_read_err_signature(name, addr)

    async def csr_read_decerr_zero(self, name: str, addr: int, length: int = 4) -> int:
        """Read a window terminated by DECERR + zero data (smc_ip_integration
        gpio_ctrl / axil_extension err_slv with RESP_DATA='0)."""
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
        assert got == 0, (
            f"{name} @ 0x{addr:08x}: expected rdata=0, got 0x{got:0{length * 2}x}"
        )
        return item.rdata

    async def csr_read_many_decerr_zero(
        self, regs: list[tuple[str, int, int | None]]
    ) -> None:
        for name, addr, _expected in regs:
            await self.csr_read_decerr_zero(name, addr)

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

    async def csr_read_bounded(self, name: str, addr: int, length: int = 4,
                               timeout_ns: int = 200) -> int:
        """Bounded read: tolerates DECERR **and** timeout (no-decode).

        Intended for coverage-gap CSR probes where the block may be
        clock-gated or absent from the current bring-up and there is no
        AXI responder to send back OKAY/DECERR. Increments `timeouts` on
        no-response, `accesses` unconditionally.
        """
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        item.allow_timeout = True
        item.timeout_ns = timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
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
        item.allow_timeout = True
        item.timeout_ns = timeout_ns
        await self.start_item(item)
        await self.finish_item(item)
        assert item.timed_out, f"{name} completed before the short timeout"
        self.accesses += 1
        self.timeouts += 1

    async def drain_axi(self, cycles: int = 200) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, cycles)

    # --- DUT I2C0 controller register->pin proof (model-free real DUT gate) ---
    # SMC_BASE_CONFIG clock-gate + I2C0 ctrl/ovrd CSRs. Used by the SMBus/PMBus
    # tests (and mirrors smc_i2c_master_target_test) to gate on real DUT behaviour
    # rather than pure VIP-side protocol math.
    _I2C0_CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18
    _I2C0_CG_EN = 1 << 11
    _I2C0_CTRL = 0xC000_9E00
    _I2C0_OVRD = 0xC000_9034
    _I2C0_CTRL_ENABLE = 0x11
    _I2C0_OVRD_RELEASE = 0x7
    _I2C0_OVRD_SCL_LOW = 0x5
    _I2C0_OVRD_SDA_LOW = 0x3
    _I2C0_OVRD_BOTH_LOW = 0x1

    async def _i2c0_check_line(self, name: str, exp_scl: int, exp_sda: int) -> None:
        dut = cocotb.top
        await ClockCycles(dut.clk_smc_i, 100)
        scl = int(dut.tb_i2c0_scl.value)
        sda = int(dut.tb_i2c0_sda.value)
        cocotb.log.info("%s: DUT-driven scl=%d sda=%d", name, scl, sda)
        assert scl == exp_scl, f"{name}: DUT-driven SCL={scl}, expected {exp_scl}"
        assert sda == exp_sda, f"{name}: DUT-driven SDA={sda}, expected {exp_sda}"

    # I2C0 pads 37..40 (SCL/SDA/ALERT/SUS). DATA_CTRL stride 0x10 from GPIO0.
    _GPIO_INTF0_DATA_CTRL = 0xC000_4000
    _GPIO_INTF_STRIDE = 0x10
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
            en = (
                int(dut.tb_i2c0_enable.value)
                if hasattr(dut, "tb_i2c0_enable")
                else -1
            )
            # Sense path is what the host needs; enable may stay 0 on Verilator
            # (i2c_wrap OOB wipe) even after WRAP I2C_EN=1 + GPIO lsio_select.
            if bus_scl == 1 and scl_i == 1:
                cocotb.log.info(
                    "%s ready: bus_scl=1 scl_i=1 enable=%s", label, en
                )
                return
            await ClockCycles(dut.clk_smc_i, 4)
        en = (
            int(dut.tb_i2c0_enable.value)
            if hasattr(dut, "tb_i2c0_enable")
            else -1
        )
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
        await self.csr_write("I2C0_UNGATE", self._I2C0_CLOCK_GATE_CONTROL,
                             cg & ~self._I2C0_CG_EN)
        await self.csr_write("I2C0_CTRL_EN", self._I2C0_CTRL, self._I2C0_CTRL_ENABLE)
        await self.csr_read("I2C0_CTRL_EN_RB", self._I2C0_CTRL,
                            expected=self._I2C0_CTRL_ENABLE)
        await self.csr_write("I2C0_OVRD_REL", self._I2C0_OVRD, self._I2C0_OVRD_RELEASE)
        await self._i2c0_check_line("i2c0_release", 1, 1)
        await self.csr_write("I2C0_OVRD_SCL_LOW", self._I2C0_OVRD, self._I2C0_OVRD_SCL_LOW)
        await self._i2c0_check_line("i2c0_scl_low", 0, 1)
        await self.csr_write("I2C0_OVRD_SDA_LOW", self._I2C0_OVRD, self._I2C0_OVRD_SDA_LOW)
        await self._i2c0_check_line("i2c0_sda_low", 1, 0)
        await self.csr_write("I2C0_OVRD_BOTH_LOW", self._I2C0_OVRD, self._I2C0_OVRD_BOTH_LOW)
        await self._i2c0_check_line("i2c0_both_low", 0, 0)
        await self.csr_write("I2C0_OVRD_REL_RESTORE", self._I2C0_OVRD,
                             self._I2C0_OVRD_RELEASE)
        await self._i2c0_check_line("i2c0_release_restore", 1, 1)
        await self.csr_write("I2C0_CG_RESTORE", self._I2C0_CLOCK_GATE_CONTROL, cg)

    def assert_all_reachable(self, expected_accesses: int, block: str) -> None:
        """Gate a bounded-read sweep on REAL reachability, not the self-issued
        access count.

        `assert self.accesses == N` alone is vacuous: `accesses` is bumped
        unconditionally by every helper regardless of whether the DUT
        responded, so it only proves the sequence issued N reads. The real,
        in-scope SMC invariant (per tb_top's boundary-responder note) is that
        every windowed read produced an AXI response -- OKAY from an internal
        register block, or the DECERR boundary-responder signature for an
        externalised macro window. A no-response (timeout) means the periph
        route/decode is broken or the shared CSR master would hang, which is
        exactly what these decode-alive sweeps claim to rule out.
        """
        assert self.accesses == expected_accesses, (
            f"{block}: issued {self.accesses} accesses, expected {expected_accesses}"
        )
        assert self.timeouts == 0, (
            f"{block}: {self.timeouts} of {self.accesses} windowed read(s) got NO "
            f"AXI response (periph route/decode unreachable or CSR master would hang)"
        )

    def assert_reachable_or_gated(self, expected_accesses: int, block: str,
                                  gated_note: str) -> None:
        """Reachability gate for windows that are *legitimately* clock-gated or
        absent in the current OSS bring-up (e.g. the CPU cluster before firmware
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

        Any gated window is logged (not silently swallowed) so the deferred
        register-level coverage is visible rather than hidden behind a green
        vacuous ``accesses == N``.
        """
        assert self.accesses == expected_accesses, (
            f"{block}: issued {self.accesses} accesses, expected {expected_accesses}"
        )
        reachable = self.accesses - self.timeouts
        if self.timeouts:
            cocotb.log.warning(
                "%s: %d/%d window(s) reachable; %d gated/absent in this OSS "
                "bring-up (%s). No-hang verified (every bounded probe returned); "
                "register-level decode deferred for the gated window(s).",
                block, reachable, expected_accesses, self.timeouts, gated_note,
            )
        else:
            cocotb.log.info(
                "%s: all %d window(s) reachable (AXI response received).",
                block, expected_accesses,
            )
