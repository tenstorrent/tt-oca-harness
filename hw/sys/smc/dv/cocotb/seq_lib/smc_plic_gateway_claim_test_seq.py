# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PLIC gateway: one request in flight, re-pend after completion, sticky status untouched.

Sources: hw/sys/smc/doc/interrupts.adoc (PLIC Sources and Contexts: "A gateway admits one
request and waits for completion before accepting another. It does not count repeated pulses
while one request is in flight"; Interrupt Control: "Completion releases the source's gateway,
so a still-asserted source pends again; claim and complete do not clear a peripheral's own
sticky status"), hw/sys/smc/regs/blocks/plic/plic.rdl, hw/ip/axi_lite_mailbox_unit axil_mailbox.rdl.

Context 0 claims and completes over SEP_IN. External input 0 (raw bit 0, PLIC source 1) is the
level source the bench pulses while a claim is open; inbound mailbox 0 (raw bit 288, PLIC source
289) is the peripheral whose `IRQS.wtirq` is the sticky status read back after the claim and the
completion.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_mbx_inbound_irq_vector_test_seq import (
    CLOCK_GATE_CONTROL,
    IRQ_ALL,
    MAILBOX_CG_EN,
    RFLUSH,
    WFLUSH,
    WORD,
    WTIRQ,
)

EXT_SOURCE = 1
MBX_SOURCE = 289
MBX_RAW_BIT = 288
PULSES = 8
PULSE_RISES = 8
RISE_BOUND = 64
MAILBOX_BOUND = 128
QUIET_RISES = 128
REGION_SIZE_256M = 0x1000_0000
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
CTX0 = "CORE0_MEIP"
THRESHOLD0 = smc_addr(PLIC + f"{CTX0}_THRESHOLD_BASE_ADDR")
CLAIM0 = smc_addr(PLIC + f"{CTX0}_CLAIM_COMPLETE_BASE_ADDR")
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_ORDER = (
    ("CHK-PLIC-REPEND-AFTER-COMPLETE", "S3"),
    ("CHK-PLIC-GATEWAY-ONE-IN-FLIGHT", "S4"),
    ("CHK-PLIC-STICKY-STATUS", "S5"),
    ("CHK-TIMEOUT-PATHS", "S6"),
)


def _priority_addr(source: int) -> int:
    return smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", source)


def _enable_addr(word: int) -> int:
    return smc_indexed_addr(PLIC + f"{CTX0}_ENABLE_BASE_ADDR", word)


def _pending_addr(word: int) -> int:
    return smc_indexed_addr(PLIC + "PENDING_BASE_ADDR", word)


def _mbx0(reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_{reg}_BASE_ADDR")


class smc_plic_gateway_claim_test_seq(SmcCsrSeq):
    """Claim and complete on context 0 around pulses of input 0 and a sticky mailbox status."""

    def __init__(self, name: str = "smc_plic_gateway_claim_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[str] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    @staticmethod
    def _probe(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    def _pending1(self) -> int:
        return self._probe("tb_plic_pending_low") & 1

    def _raw0(self) -> int:
        return self._probe("tb_cpu_interrupts") & 1

    def _meip0(self) -> int:
        return self._probe("tb_plic_meip") & 1

    async def _wait_meip0(self, label: str, want: int) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(1, RISE_BOUND + 1):
            await RisingEdge(clk)
            if self._meip0() == want:
                self._waits.append(f"{label}: bound={RISE_BOUND} rises matched at {n}")
                return n
        raise AssertionError(
            f"CHK-PLIC-REPEND-AFTER-COMPLETE: {label}: tb_plic_meip bit 0 did not read {want} "
            f"within {RISE_BOUND} rises (pending bit 0 = {self._pending1()})"
        )

    async def _wait_pending1(self, label: str, want: int) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(1, RISE_BOUND + 1):
            await RisingEdge(clk)
            if self._pending1() == want:
                self._waits.append(f"{label}: bound={RISE_BOUND} rises matched at {n}")
                return n
        raise AssertionError(
            f"{label}: tb_plic_pending_low bit 0 did not read {want} within {RISE_BOUND} rises "
            f"(raw bit 0 = {self._raw0()})"
        )

    async def _wait_raw(self, label: str, bit: int, want: int) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(1, MAILBOX_BOUND + 1):
            await RisingEdge(clk)
            if (self._probe("tb_cpu_interrupts") >> bit) & 1 == want:
                self._waits.append(f"{label}: bound={MAILBOX_BOUND} rises matched at {n}")
                return n
        raise AssertionError(
            f"{label}: raw bit {bit} did not read {want} within {MAILBOX_BOUND} rises"
        )

    async def _hold_pending1_zero(self, label: str, rises: int) -> int:
        """Raw bit 0 rising edges seen while tb_plic_pending_low bit 0 stays 0 at every rise."""
        clk = cocotb.top.clk_smc_i
        edges = 0
        prev = self._raw0()
        for n in range(1, rises + 1):
            await RisingEdge(clk)
            now = self._raw0()
            edges += int(now == 1 and prev == 0)
            prev = now
            assert self._pending1() == 0, (
                f"CHK-PLIC-GATEWAY-ONE-IN-FLIGHT: {label}: tb_plic_pending_low bit 0 read 1 at rise "
                f"{n} of {rises} with a claim of source {EXT_SOURCE} open (raw bit 0 edges so far "
                f"{edges})"
            )
        return edges

    async def _pulse_pin0(self, label: str, end_high: bool) -> int:
        """Pulse input 0 low/high PULSES times with a claim open; return the raw bit 0 edges."""
        pin = cocotb.top.tb_ext_interrupt_0_i
        edges = 0
        for _ in range(PULSES):
            pin.value = 0
            edges += await self._hold_pending1_zero(label, PULSE_RISES)
            pin.value = 1
            edges += await self._hold_pending1_zero(label, PULSE_RISES)
        if not end_high:
            pin.value = 0
            edges += await self._hold_pending1_zero(label, PULSE_RISES)
        return edges

    async def _claim(self, label: str, expected: int) -> int:
        claim = await self.csr_read(f"CLAIM0_{label}", CLAIM0)
        assert claim == expected, f"{label}: context 0 claim read {claim}, expected {expected}"
        return claim

    async def _complete(self, label: str, source: int) -> None:
        await self.csr_write(f"COMPLETE0_{label}", CLAIM0, source)

    async def _mbx(self, label: str, reg: str, data: int | None = None, expected=None) -> int:
        if data is None:
            return await self.csr_read(f"MBX0_{label}", _mbx0(reg), expected=expected, length=8)
        await self.csr_write(f"MBX0_{label}", _mbx0(reg), data, length=8)
        return data

    async def body(self) -> None:
        dut = cocotb.top
        for sig in (
            "tb_plic_pending_low",
            "tb_plic_meip",
            "tb_cpu_interrupts",
            "tb_ext_interrupt_0_i",
        ):
            assert hasattr(dut, sig), f"{sig} not exported"
        pin = dut.tb_ext_interrupt_0_i

        # S1
        await self.wait_fuse_sense_done()
        pin.value = 0
        await RisingEdge(dut.clk_smc_i)
        assert self._pending1() == 0 and self._raw0() == 0, (
            f"entry: pending bit 0 = {self._pending1()}, raw bit 0 = {self._raw0()}, expected 0, 0"
        )
        self._stamp("S1")

        # S2
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        ext_word, ext_bit = divmod(EXT_SOURCE, 32)
        mbx_word, mbx_bit = divmod(MBX_SOURCE, 32)
        saved = {
            "prio_ext": await self.csr_read("PRIORITY_EXT_SAVE", _priority_addr(EXT_SOURCE)),
            "prio_mbx": await self.csr_read("PRIORITY_MBX_SAVE", _priority_addr(MBX_SOURCE)),
            "en_ext": await self.csr_read("ENABLE_EXT_SAVE", _enable_addr(ext_word)),
            "en_mbx": await self.csr_read("ENABLE_MBX_SAVE", _enable_addr(mbx_word)),
            "threshold": await self.csr_read("THRESHOLD0_SAVE", THRESHOLD0),
        }
        await self.csr_write("PRIORITY_EXT_7", _priority_addr(EXT_SOURCE), 7)
        await self.csr_write("PRIORITY_MBX_7", _priority_addr(MBX_SOURCE), 7)
        await self.csr_write("ENABLE_EXT_ON", _enable_addr(ext_word), 1 << ext_bit)
        await self.csr_write("ENABLE_MBX_OFF", _enable_addr(mbx_word), 0)
        await self.csr_write("THRESHOLD0_ZERO", THRESHOLD0, 0)
        await self._claim("IDLE", 0)
        self._stamp("S2")

        # S3
        pin.value = 1
        rise = await self._wait_pending1("ext0_pending", 1)
        meip_rise = await self._wait_meip0("ext0_meip", 1)
        await self._claim("FIRST", EXT_SOURCE)
        assert self._pending1() == 0, (
            f"CHK-PLIC-GATEWAY-ONE-IN-FLIGHT: pending bit 0 still 1 after the claim of source "
            f"{EXT_SOURCE}"
        )
        meip_fall = await self._wait_meip0("ext0_meip_claimed", 0)
        edges_a = await self._pulse_pin0("pulses with the first claim open", end_high=True)
        edges_a += await self._hold_pending1_zero("held high before completion", RISE_BOUND)
        assert edges_a == PULSES, (
            f"CHK-PLIC-GATEWAY-ONE-IN-FLIGHT: raw bit 0 rose {edges_a} times during {PULSES} "
            "pulses (positive control: the pulses reach the raw vector)"
        )
        await self._complete("FIRST", EXT_SOURCE)
        repend = await self._wait_pending1("repend_after_complete", 1)
        meip_again = await self._wait_meip0("ext0_meip_repend", 1)
        await self._claim("SECOND", EXT_SOURCE)
        self._stamp("S3")
        self._chk(
            "CHK-PLIC-REPEND-AFTER-COMPLETE",
            f"input 0 held high: source {EXT_SOURCE} pended at rise {rise} and context 0 MEIP rose "
            f"at rise {meip_rise}, claim read {EXT_SOURCE} and MEIP fell at rise {meip_fall}, "
            f"pending stayed 0 through {PULSES} pulses and {RISE_BOUND} held rises, and after the "
            f"completion it pended again at rise {repend}, MEIP rose at rise {meip_again} and the "
            f"claim read {EXT_SOURCE} again",
        )

        # S4
        edges_b = await self._pulse_pin0("pulses with the second claim open", end_high=False)
        assert edges_b == PULSES, (
            f"CHK-PLIC-GATEWAY-ONE-IN-FLIGHT: raw bit 0 rose {edges_b} times during the second "
            f"{PULSES} pulses"
        )
        await self._complete("SECOND", EXT_SOURCE)
        quiet = await self._hold_pending1_zero("after completion with input 0 low", QUIET_RISES)
        assert quiet == 0, f"raw bit 0 rose {quiet} times with input 0 held low"
        await self._claim("AFTER_PULSES", 0)
        self._stamp("S4")
        self._chk(
            "CHK-PLIC-GATEWAY-ONE-IN-FLIGHT",
            f"with a claim of source {EXT_SOURCE} open, {edges_a} then {edges_b} rising edges of "
            f"raw bit 0 left tb_plic_pending_low bit 0 at 0 at every rise; after the second "
            f"completion with input 0 low the pending bit stayed 0 for {QUIET_RISES} rises and "
            "the claim read 0: the pulses were not counted",
        )

        # S5
        await self.csr_write("ENABLE_MBX_ON", _enable_addr(mbx_word), 1 << mbx_bit)
        await self._mbx("IRQEN_WTIRQ", "IRQEN", WTIRQ)
        await self._mbx("PUSH", "WRITE_DATA", WORD)
        await self._wait_raw("mbx0_raw288", MBX_RAW_BIT, 1)
        pend = await self.csr_read("PENDING_MBX_SET", _pending_addr(mbx_word))
        assert (pend >> mbx_bit) & 1 == 1, (
            f"CHK-PLIC-STICKY-STATUS: PENDING[{mbx_word}] 0x{pend:x} lacks bit {mbx_bit} (source "
            f"{MBX_SOURCE}) with raw bit {MBX_RAW_BIT} high"
        )
        irqs_before = await self._mbx("IRQS_BEFORE_CLAIM", "IRQS")
        assert irqs_before & WTIRQ, f"IRQS read 0x{irqs_before:x} after the push, wtirq clear"
        await self._claim("MBX", MBX_SOURCE)
        await self._complete("MBX", MBX_SOURCE)
        irqs_after = await self._mbx("IRQS_AFTER_COMPLETE", "IRQS")
        assert irqs_after & WTIRQ, (
            f"CHK-PLIC-STICKY-STATUS: mailbox 0 IRQS read 0x{irqs_after:x} after the claim and "
            f"completion of source {MBX_SOURCE}, wtirq cleared (was 0x{irqs_before:x})"
        )
        raw288 = (self._probe("tb_cpu_interrupts") >> MBX_RAW_BIT) & 1
        pend_again = await self.csr_read("PENDING_MBX_AGAIN", _pending_addr(mbx_word))
        assert (pend_again >> mbx_bit) & 1 == 1, (
            f"CHK-PLIC-STICKY-STATUS: PENDING[{mbx_word}] 0x{pend_again:x} after the completion "
            f"with IRQS 0x{irqs_after:x} still set, expected source {MBX_SOURCE} pending again"
        )
        await self._claim("MBX_AGAIN", MBX_SOURCE)
        await self._mbx("FLUSH", "CTRL", WFLUSH | RFLUSH)
        await self._mbx("ACK", "IRQS", IRQ_ALL)
        await self._wait_raw("mbx0_raw288_clear", MBX_RAW_BIT, 0)
        await self._complete("MBX_AGAIN", MBX_SOURCE)
        irqs_cleared = await self._mbx("IRQS_CLEARED", "IRQS")
        pend_clear = await self.csr_read("PENDING_MBX_CLEAR", _pending_addr(mbx_word))
        assert (pend_clear >> mbx_bit) & 1 == 0 and irqs_cleared & WTIRQ == 0, (
            f"after the write-one-to-clear IRQS 0x{irqs_cleared:x} PENDING[{mbx_word}] "
            f"0x{pend_clear:x}, expected wtirq and bit {mbx_bit} clear"
        )
        await self._claim("MBX_CLEARED", 0)
        await self._mbx("IRQEN_OFF", "IRQEN", 0)
        self._stamp("S5")
        self._chk(
            "CHK-PLIC-STICKY-STATUS",
            f"mailbox 0 push: IRQS 0x{irqs_before:x}, PENDING[{mbx_word}] bit {mbx_bit} set, claim "
            f"read {MBX_SOURCE}; after the completion IRQS read 0x{irqs_after:x} (wtirq still set), "
            f"raw bit {MBX_RAW_BIT} = {raw288}, PENDING[{mbx_word}] 0x{pend_again:x} pending again "
            f"and the claim read {MBX_SOURCE} again; after the write-one-to-clear IRQS "
            f"0x{irqs_cleared:x}, PENDING 0x{pend_clear:x}, claim 0",
        )

        # S6
        await self.csr_write("PRIORITY_EXT_RESTORE", _priority_addr(EXT_SOURCE), saved["prio_ext"])
        await self.csr_write("PRIORITY_MBX_RESTORE", _priority_addr(MBX_SOURCE), saved["prio_mbx"])
        await self.csr_write("ENABLE_EXT_RESTORE", _enable_addr(ext_word), saved["en_ext"])
        await self.csr_write("ENABLE_MBX_RESTORE", _enable_addr(mbx_word), saved["en_mbx"])
        await self.csr_write("THRESHOLD0_RESTORE", THRESHOLD0, saved["threshold"])
        await self.csr_read("THRESHOLD0_RESTORE_RB", THRESHOLD0, expected=saved["threshold"])
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
        self._stamp("S6")
        self.assert_all_reachable(self.accesses, "PLIC and mailbox")
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"fuse sense wait bound 200000 clk_smc_i rises (AssertionError on expiry); "
            f"{len(self._waits)} bounded waits: {'; '.join(self._waits)}; SEP_IN accesses "
            f"x{self.accesses} bound={self.cfg.axi_timeout_ns} ns allow_timeout False",
        )
        self._fence()

    def _fence(self) -> None:
        steps = tuple(s for s, _ in self._stamps)
        assert steps == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP<PLIC_PROGRAMMED<REPEND<GATEWAY_IN_FLIGHT<"
            "STICKY_STATUS<RESTORED; checker lines %s; stamps %s",
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
