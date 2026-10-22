# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1/I2C2 target ACK Control Mode against a DUT controller on the shared bus.

Contract: the `smc_i2c1_target_ack_ctrl_test` card (section 541) of hw/sys/smc/dv/docs/SMC_VPLAN.adoc.
Sources: hw/ip/i2c/regs/gen/adoc/i2c.adoc (CTRL.ACK_CTRL_EN, STATUS.ACK_CTRL_STRETCH,
INTR_STATE.ACQ_STRETCH, ACQDATA.SIGNAL, TARGET_NACK_COUNT, TARGET_ACK_CTRL, ACQ_FIFO_NEXT_DATA,
CONTROLLER_EVENTS), hw/sys/smc/doc/periphs.adoc (target RX FIFO depth).

`+smc_i2c_shared_bus` puts the three instances on one open-drain bus. I2C0 stays disabled;
I2C1 is the target at 0x26 with I2C2 as the controller, then the roles swap. The bench wire
monitor counts the data bytes the target acknowledges between ACK-control holds. The NBYTES
read-backs between bytes and the 0x1FF leg's ACK count are logged and not compared (SF-005).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import I2cWireFrame, SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_STATUS_FMTLVL_BM,
    I2C_STATUS_ACK_CTRL_STRETCH,
    I2C_STATUS_ACQFULL,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_TARGET_ACK_CTRL_NACK,
    I2C_TARGET_ACK_CTRL_NBYTES_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_u32
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
INTR_ACQ_STRETCH = _i2c_u32("I2C__INTR_STATE__ACQ_STRETCH_bm")
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
EV_NACK = I2C_CONTROLLER_EVENTS_NACK

INSTANCES = (0, 1, 2)
TARGET_ADDR = 0x26
#: Target instance -> the instance that is the controller for it.
CONTROLLER_FOR = {1: 2, 2: 1}
#: THIGH, TLOW, T_R, T_F, TSU_STA, THD_STA, TSU_DAT, THD_DAT, TSU_STO, T_BUF in clk_i cycles:
#: THIGH and TLOW a few cycles above the documented minimum of 2.
FAST_TIMING = (6, 8, 1, 1, 6, 6, 1, 1, 6, 8)

NBYTES_PAYLOAD = tuple(range(0xD0, 0xD6))
RELOADS = (3, 2, 1)
NACK_PAYLOAD = tuple(range(0xE0, 0xE4))
RANGE_NS = (1, 64, 0x1FF)
NBYTES_MAX = 0x1FF
#: Format FIFO level the S5 feeder tops up to.
FMT_FILL = 32
_ABYTE_BM = 0xFF

HOLD_POLLS = 2000
HOLD_STEP = 4
DONE_POLLS = 2000
DONE_STEP = 8
RANGE_POLLS = 8000
RANGE_STEP = 4
EVENT_POLLS = 600
EVENT_STEP = 25
DRAIN_POLLS = 200
DRAIN_STEP = 20
BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4

FENCE_ORDER = [
    "BRINGUP",
    "I2C_ACKCTRL_NBYTES3",
    "I2C_ACKCTRL_DECREMENT",
    "I2C_ACKCTRL_RELOAD",
    "I2C_ACKCTRL_RANGE",
    "I2C_ACKCTRL_SW_NACK",
]
CHECKER_BEFORE = {
    "CHK-I2C1-ACKCTRL-NBYTES3": "I2C_ACKCTRL_NBYTES3",
    "CHK-I2C1-ACKCTRL-DECREMENT": "I2C_ACKCTRL_DECREMENT",
    "CHK-I2C1-ACKCTRL-RELOAD": "I2C_ACKCTRL_RELOAD",
    "CHK-I2C1-ACKCTRL-NBYTES-RANGE": "I2C_ACKCTRL_RANGE",
    "CHK-I2C1-ACKCTRL-SW-NACK": "I2C_ACKCTRL_SW_NACK",
    "CHK-I2C1-ACKCTRL-NACK-RECORD": "I2C_ACKCTRL_SW_NACK",
}


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _write_words(data: tuple[int, ...] | list[int]) -> list[int]:
    words = [_fdata(TARGET_ADDR << 1, I2C_FDATA_START)]
    last = len(data) - 1
    words += [_fdata(b, I2C_FDATA_STOP if i == last else 0) for i, b in enumerate(data)]
    return words


class smc_i2c1_target_ack_ctrl_test_seq(SmcCsrSeq):
    """Reload, range and NACK legs of TARGET_ACK_CTRL on target instances 1 and 2."""

    def __init__(self, name: str = "smc_i2c1_target_ack_ctrl_test_seq") -> None:
        super().__init__(name)
        self.monitor: SmcFwI2cWireMonitor | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.frame_base = 0
        self.nbytes3_rows: list[str] = []
        self.decrement_rows: list[str] = []
        self.nbytes_seq_rows: list[str] = []
        self.reload_rows: list[str] = []
        self.nack_rows: list[str] = []
        self.record_rows: list[str] = []

    # ---------------------------------------------------------------- helpers
    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _bit(handle, name: str) -> int:
        value = handle.value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value) & 1

    async def _poll(self, name: str, polls: int, step: int, probe) -> None:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry."""
        state = "never sampled"
        for _ in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, f"{polls}x{step} clk_smc_i", state))
                return
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self.waits.append((name, f"{polls}x{step} clk_smc_i", f"EXPIRED {state}"))
        raise AssertionError(f"{name}: not satisfied within {polls}x{step} cycles; last {state}")

    def _frame(self) -> I2cWireFrame | None:
        frames = [f for f in self.monitor.frames[self.frame_base :] if f.addr7 == TARGET_ADDR]
        return frames[0] if frames else None

    def _acked(self) -> int:
        frame = self._frame()
        return frame.data_bytes(acked_only=True) if frame is not None else 0

    async def _wait_bus_released(self, name: str) -> None:
        dut = cocotb.top

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)

    async def _program_timing(self, idx: int) -> None:
        t = FAST_TIMING
        for reg, value in (
            ("TIMING0", _pack_timing0(t[0], t[1])),
            ("TIMING1", _pack_timing1(t[2], t[3])),
            ("TIMING2", _pack_timing2(t[4], t[5])),
            ("TIMING3", _pack_timing3(t[6], t[7])),
            ("TIMING4", _pack_timing4(t[8], t[9])),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", _reg(reg, idx), value)

    async def _disable(self, idx: int) -> None:
        await self.csr_write(f"I2C{idx}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"I2C{idx}_WRAP_OFF", _wrap(idx), 0)

    async def _enable_target(self, idx: int, label: str) -> None:
        await self.csr_write(f"{label}_TGT{idx}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"{label}_TGT{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_TARGET)
        await self.csr_write(
            f"{label}_TGT{idx}_TARGET_ID",
            _reg("TARGET_ID", idx),
            _pack_target_id(TARGET_ADDR, 0x7F, 0, 0),
        )
        await self.csr_write(
            f"{label}_TGT{idx}_FIFO",
            _reg("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            f"{label}_TGT{idx}_CTRL",
            _reg("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACK_CTRL_EN | I2C_CTRL_ACQ_START_STOP_EN,
        )
        ctrl = await self.csr_read(f"{label}_TGT{idx}_CTRL_RB", _reg("CTRL", idx))
        assert ctrl & I2C_CTRL_ACK_CTRL_EN, (
            f"{label}: I2C{idx} CTRL.ACK_CTRL_EN did not take (CTRL=0x{ctrl:08x})"
        )
        status = await self.csr_read(f"{label}_TGT{idx}_STATUS_ENTRY", _reg("STATUS", idx))
        assert not status & I2C_STATUS_ACK_CTRL_STRETCH, (
            f"{label}: I2C{idx} STATUS.ACK_CTRL_STRETCH set before any transfer "
            f"(STATUS=0x{status:08x})"
        )

    async def _enable_controller(self, idx: int, label: str) -> None:
        await self.csr_write(f"{label}_CTL{idx}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"{label}_CTL{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_HOST)
        await self.csr_write(
            f"{label}_CTL{idx}_FIFO", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(
            f"{label}_CTL{idx}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), 0xFFFF_FFFF
        )
        await self.csr_write(f"{label}_CTL{idx}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_CTL{idx}_ENABLEHOST", _reg("CTRL", idx), I2C_CTRL_ENABLEHOST)
        self.frame_base = len(self.monitor.frames)

    async def _queue(self, idx: int, words: list[int], label: str) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA_{i}", _reg("FDATA", idx), word)

    async def _pop(self, idx: int, label: str, into: list[tuple[int, int]]) -> int:
        fifo = await self.csr_read(f"{label}_ACQLVL", _reg("TARGET_FIFO_STATUS", idx))
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read(f"{label}_ACQDATA", _reg("ACQDATA", idx))
            into.append(((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & _ABYTE_BM))
        return level

    async def _sample_hold(self, name: str, tgt: int) -> tuple[int, int, bool]:
        """Read the target's STATUS; ``stable`` is no byte acknowledged during the read."""
        before = self._acked()
        status = await self.csr_read(f"{name}_STATUS", _reg("STATUS", tgt))
        acked = self._acked()
        return status, acked, acked == before

    async def _wait_release(self, name: str, held_at: int) -> None:
        """Wait for the byte pending at a hold to be acknowledged on the wire."""

        async def probe() -> tuple[bool, str]:
            acked = self._acked()
            return acked > held_at, f"acked={acked} held_at={held_at} {self.monitor.summary()}"

        await self._poll(name, HOLD_POLLS, HOLD_STEP, probe)

    async def _wait_hold(
        self, name: str, tgt: int, stops_base: int, after: int, nbytes_log: list | None
    ) -> int:
        """Poll the target's STATUS until a new ACK-control hold; return the wire ACK count.

        A hold is new once the wire shows more acknowledged bytes than ``after`` (``after``
        is -1 for the first hold of a transfer). With ``nbytes_log`` set, TARGET_ACK_CTRL is
        read each time the acknowledged count grows.
        """
        status = [0]
        seen = [self._acked()]

        async def probe() -> tuple[bool, str]:
            acked = self._acked()
            if nbytes_log is not None and acked > seen[0]:
                seen[0] = acked
                rb = await self.csr_read(f"{name}_NBYTES_RB", _reg("TARGET_ACK_CTRL", tgt))
                nbytes_log.append((acked, rb & I2C_TARGET_ACK_CTRL_NBYTES_BM))
            status[0], acked, stable = await self._sample_hold(name, tgt)
            state = f"STATUS=0x{status[0]:08x} acked={acked} {self.monitor.summary()}"
            if stable and status[0] & I2C_STATUS_ACK_CTRL_STRETCH and acked > after:
                return True, state
            if self.monitor.stops > stops_base:
                raise AssertionError(f"{name}: STOP on the wire before the hold; {state}")
            return False, state

        await self._poll(name, HOLD_POLLS, HOLD_STEP, probe)
        return self._acked()

    async def _wait_ctrl_done(self, ctl: int, tgt: int, label: str, stops_base: int) -> None:
        """Wait for the STOP and an idle controller; the target must not hold meanwhile."""
        last = ["never sampled"]

        async def probe() -> tuple[bool, str]:
            tstat = await self.csr_read(f"{label}_TGT_STATUS", _reg("STATUS", tgt))
            assert not tstat & I2C_STATUS_ACK_CTRL_STRETCH, (
                f"{label}: target I2C{tgt} held again after the last reload "
                f"(STATUS=0x{tstat:08x}, acked={self._acked()})"
            )
            cstat = await self.csr_read(f"{label}_CTL_STATUS", _reg("STATUS", ctl))
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            done = cstat & want == want and self.monitor.stops > stops_base
            last[0] = f"ctl STATUS=0x{cstat:08x} tgt STATUS=0x{tstat:08x} {self.monitor.summary()}"
            return done, last[0]

        await self._poll(f"{label}_stop", DONE_POLLS, DONE_STEP, probe)

    async def _drain(self, tgt: int, label: str, until_signal: int) -> list[tuple[int, int]]:
        got: list[tuple[int, int]] = []

        async def probe() -> tuple[bool, str]:
            await self._pop(tgt, label, got)
            done = bool(got) and got[-1][0] == until_signal
            return done, f"acq={[(s, hex(b)) for s, b in got]}"

        await self._poll(f"{label}_drain", DRAIN_POLLS, DRAIN_STEP, probe)
        return got

    # -------------------------------------------------------------------- S1
    async def _bring_up(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c1_target_ack_ctrl_test needs +smc_i2c_shared_bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_ACKCTRL")
        await self._wait_bus_released("bus_released_bringup")
        for idx in INSTANCES:
            await self._program_timing(idx)
            await self.csr_write(f"I2C{idx}_INTR_ENABLE_OFF", _reg("INTR_ENABLE", idx), 0)
            await self.csr_write(f"I2C{idx}_OVRD_OFF", _reg("OVRD", idx), 0)
            await self._disable(idx)
        self.monitor = SmcFwI2cWireMonitor(name="smc_i2c1_ack_ctrl_wire")
        await self._enable_target(1, "S1")
        await self._enable_controller(2, "S1")
        for idx in (1, 2):
            for i in range(2):
                await self.csr_read(
                    f"S1_I2C{idx}_NACK_COUNT_CLR{i}", _reg("TARGET_NACK_COUNT", idx)
                )
        self._stamp("BRINGUP")

    # ------------------------------------------------------------- S2/S3/S4
    async def _nbytes_leg(self, tgt: int, last: bool) -> None:
        ctl = CONTROLLER_FOR[tgt]
        label = f"S2_T{tgt}"
        await self._disable(ctl)
        await self._enable_target(tgt, label)
        await self._enable_controller(ctl, label)
        stops_base = self.monitor.stops
        nbytes_log: list[tuple[int, int]] = []
        await self._queue(ctl, _write_words(NBYTES_PAYLOAD), label)

        hold_counts = [await self._wait_hold(f"{label}_hold1", tgt, stops_base, -1, nbytes_log)]
        await self.csr_write(f"{label}_NBYTES3", _reg("TARGET_ACK_CTRL", tgt), RELOADS[0])
        hold_counts.append(
            await self._wait_hold(f"{label}_hold2", tgt, stops_base, hold_counts[0], nbytes_log)
        )
        status = await self.csr_read(f"{label}_HOLD2_STATUS", _reg("STATUS", tgt))
        intr = await self.csr_read(f"{label}_HOLD2_INTR", _reg("INTR_STATE", tgt))
        nxt = await self.csr_read(f"{label}_HOLD2_NEXT", _reg("ACQ_FIFO_NEXT_DATA", tgt))
        acked2 = hold_counts[1] - hold_counts[0]
        assert acked2 == RELOADS[0], (
            f"{label}: {acked2} bytes ACKed after NBYTES={RELOADS[0]} before the next hold "
            f"(wire frame {self._frame()})"
        )
        assert status & I2C_STATUS_ACK_CTRL_STRETCH, (
            f"{label}: STATUS.ACK_CTRL_STRETCH=0 at the second hold (0x{status:08x})"
        )
        assert not status & I2C_STATUS_ACQFULL, (
            f"{label}: STATUS.ACQFULL=1 at the second hold (0x{status:08x})"
        )
        assert intr & INTR_ACQ_STRETCH, (
            f"{label}: INTR_STATE.ACQ_STRETCH=0 at the second hold (0x{intr:08x})"
        )
        assert nxt & _ABYTE_BM == NBYTES_PAYLOAD[3], (
            f"{label}: ACQ_FIFO_NEXT_DATA=0x{nxt:08x} at the second hold, expected "
            f"0x{NBYTES_PAYLOAD[3]:02x}"
        )
        self.nbytes3_rows.append(
            f"target I2C{tgt} (controller I2C{ctl}): first hold at acked={hold_counts[0]}, "
            f"{acked2} bytes ACKed after NBYTES=3 (wire {self._frame()}), second hold "
            f"STATUS=0x{status:08x} ACK_CTRL_STRETCH=1 ACQFULL=0 INTR_STATE=0x{intr:08x} "
            f"ACQ_STRETCH=1 ACQ_FIFO_NEXT_DATA=0x{nxt & _ABYTE_BM:02x}"
        )
        if last:
            self._chk("CHK-I2C1-ACKCTRL-NBYTES3", "; ".join(self.nbytes3_rows))
            self._stamp("I2C_ACKCTRL_NBYTES3")

        await self.csr_write(f"{label}_NBYTES2", _reg("TARGET_ACK_CTRL", tgt), RELOADS[1])
        hold_counts.append(
            await self._wait_hold(f"{label}_hold3", tgt, stops_base, hold_counts[1], nbytes_log)
        )
        nxt3 = await self.csr_read(f"{label}_HOLD3_NEXT", _reg("ACQ_FIFO_NEXT_DATA", tgt))
        await self.csr_write(f"{label}_NBYTES1", _reg("TARGET_ACK_CTRL", tgt), RELOADS[2])
        await self._wait_release(f"{label}_release3", hold_counts[2])
        await self._wait_ctrl_done(ctl, tgt, label, stops_base)
        final = self._acked()
        per_reload = [
            hold_counts[1] - hold_counts[0],
            hold_counts[2] - hold_counts[1],
            final - hold_counts[2],
        ]
        assert per_reload == list(RELOADS), (
            f"{label}: ACKed bytes per reload {per_reload}, expected {list(RELOADS)}; "
            f"holds at {hold_counts}, final {final}, wire {self._frame()}"
        )
        self.decrement_rows.append(
            f"target I2C{tgt}: ACKed per reload {per_reload} for reloads {list(RELOADS)} "
            f"(holds at acked={hold_counts}, STOP at acked={final})"
        )
        self.nbytes_seq_rows.append(
            f"I2C{tgt} (acked, NBYTES)={[(a, hex(n)) for a, n in nbytes_log]}"
        )
        if last:
            self._chk(
                "CHK-I2C1-ACKCTRL-DECREMENT",
                f"{'; '.join(self.decrement_rows)} (compare held); nbytes_readbacks="
                f"{'; '.join(self.nbytes_seq_rows)} (measured, not compared; LINKED-ISSUE SF-005)",
            )
            self._stamp("I2C_ACKCTRL_DECREMENT")

        frame = self._frame()
        acq = await self._drain(tgt, label, I2C_ACQ_SIGNAL_STOP)
        wire_want = [(b, True) for b in NBYTES_PAYLOAD]
        assert frame is not None and frame.addr_acked and frame.data == wire_want, (
            f"{label}: wire frame {frame}, expected address ACK and {wire_want}"
        )
        want_sig = (
            [I2C_ACQ_SIGNAL_START]
            + [I2C_ACQ_SIGNAL_NONE] * len(NBYTES_PAYLOAD)
            + [I2C_ACQ_SIGNAL_STOP]
        )
        want_bytes = [TARGET_ADDR << 1, *NBYTES_PAYLOAD]
        assert [s for s, _ in acq] == want_sig, f"{label}: ACQ signals {acq}, expected {want_sig}"
        assert [b for _, b in acq[:-1]] == want_bytes, (
            f"{label}: ACQ bytes {[hex(b) for _, b in acq]}, expected {[hex(b) for b in want_bytes]}"
        )
        self.reload_rows.append(
            f"target I2C{tgt}: each reload released the hold and the pending byte was ACKed "
            f"(third hold pending 0x{nxt3 & _ABYTE_BM:02x}); wire {frame}; ACQ "
            f"{[(s, hex(b)) for s, b in acq]}"
        )
        if last:
            self._chk("CHK-I2C1-ACKCTRL-RELOAD", "; ".join(self.reload_rows))
            self._stamp("I2C_ACKCTRL_RELOAD")
        await self._wait_bus_released(f"{label}_bus_released")

    # -------------------------------------------------------------------- S5
    async def _range_leg(self, n: int) -> dict:
        tgt, ctl = 1, CONTROLLER_FOR[1]
        label = f"S5_N{n}"
        await self._disable(ctl)
        await self._enable_target(tgt, label)
        await self._enable_controller(ctl, label)
        stops_base = self.monitor.stops
        payload = [i & 0xFF for i in range(n + 1)]
        words = _write_words(payload)
        pushed = 0
        acq: list[tuple[int, int]] = []
        holds: list[int] = []
        readback = None
        acqfull_polls = 0
        last_hold = -1
        state = "never sampled"
        done = False
        for _ in range(RANGE_POLLS):
            if pushed < len(words):
                hfs = await self.csr_read(f"{label}_FMTLVL", _reg("HOST_FIFO_STATUS", ctl))
                room = FMT_FILL - (hfs & I2C_HOST_FIFO_STATUS_FMTLVL_BM)
                for _ in range(max(0, min(room, len(words) - pushed))):
                    await self.csr_write(f"{label}_FDATA", _reg("FDATA", ctl), words[pushed])
                    pushed += 1
            await self._pop(tgt, label, acq)
            status, acked, stable = await self._sample_hold(label, tgt)
            if status & I2C_STATUS_ACQFULL:
                acqfull_polls += 1
            if stable and status & I2C_STATUS_ACK_CTRL_STRETCH and acked > last_hold:
                holds.append(acked)
                last_hold = acked
                if len(holds) == 1:
                    await self.csr_write(f"{label}_NBYTES_N", _reg("TARGET_ACK_CTRL", tgt), n)
                    readback = await self.csr_read(
                        f"{label}_NBYTES_RB", _reg("TARGET_ACK_CTRL", tgt)
                    )
                else:
                    rest = min(len(payload) - acked, NBYTES_MAX)
                    await self.csr_write(f"{label}_NBYTES_REST", _reg("TARGET_ACK_CTRL", tgt), rest)
            state = (
                f"pushed={pushed}/{len(words)} acq={len(acq)} holds={holds} STATUS=0x{status:08x} "
                f"{self.monitor.summary()}"
            )
            if self.monitor.stops > stops_base:
                cstat = await self.csr_read(f"{label}_CTL_STATUS", _reg("STATUS", ctl))
                want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
                if cstat & want == want:
                    done = True
                    break
            await ClockCycles(cocotb.top.clk_smc_i, RANGE_STEP)
        bound = f"{RANGE_POLLS}x{RANGE_STEP} clk_smc_i plus accesses"
        if not done:
            self.waits.append((f"{label}_transfer", bound, f"EXPIRED {state}"))
            raise AssertionError(f"{label}: transfer not finished within {bound}; last {state}")
        self.waits.append((f"{label}_transfer", bound, state))
        if not acq or acq[-1][0] != I2C_ACQ_SIGNAL_STOP:
            acq += await self._drain(tgt, label, I2C_ACQ_SIGNAL_STOP)
        await self._wait_bus_released(f"{label}_bus_released")
        assert readback is not None and len(holds) >= 1, (
            f"{label}: the target never held for ACK control; {state}"
        )
        return {
            "n": n,
            "holds": holds,
            "readback": readback & I2C_TARGET_ACK_CTRL_NBYTES_BM,
            "acqfull_polls": acqfull_polls,
            "acq_entries": len(acq),
            "frame": self._frame(),
        }

    async def _range(self) -> None:
        rows = []
        for n in RANGE_NS:
            r = await self._range_leg(n)
            holds = r["holds"]
            between = holds[1] - holds[0] if len(holds) > 1 else None
            frame = r["frame"]
            total_acked = frame.data_bytes(acked_only=True) if frame else 0
            if n == NBYTES_MAX:
                assert r["readback"] == NBYTES_MAX, (
                    f"S5: NBYTES written 0x{NBYTES_MAX:x} reads back 0x{r['readback']:x}"
                )
                rows.append(
                    f"N=0x{n:x}: readback=0x{r['readback']:x} (compare held); "
                    f"acked_before_next_hold={between} holds_at_acked={holds} "
                    f"acqfull_polls={r['acqfull_polls']} total_acked={total_acked} "
                    f"acq_entries={r['acq_entries']} (measured, not compared; LINKED-ISSUE SF-005)"
                )
            else:
                assert between == n, (
                    f"S5 N={n}: {between} bytes ACKed between the first and the next ACK-control "
                    f"hold (holds at acked={holds}), expected {n}"
                )
                rows.append(
                    f"N={n}: acked_before_next_hold={between} (compare held) readback="
                    f"0x{r['readback']:x} holds_at_acked={holds} acqfull_polls={r['acqfull_polls']} "
                    f"total_acked={total_acked} acq_entries={r['acq_entries']}"
                )
        self._chk("CHK-I2C1-ACKCTRL-NBYTES-RANGE", "; ".join(rows))
        self._stamp("I2C_ACKCTRL_RANGE")

    # -------------------------------------------------------------------- S6
    async def _nack_leg(self, tgt: int, last: bool) -> None:
        ctl = CONTROLLER_FOR[tgt]
        label = f"S6_T{tgt}"
        await self._disable(ctl)
        await self._enable_target(tgt, label)
        await self._enable_controller(ctl, label)
        stops_base = self.monitor.stops
        await self._queue(ctl, _write_words(NACK_PAYLOAD), label)
        await self._wait_hold(f"{label}_hold", tgt, stops_base, -1, None)
        nxt = await self.csr_read(f"{label}_HOLD_NEXT", _reg("ACQ_FIFO_NEXT_DATA", tgt))
        await self.csr_write(
            f"{label}_NACK", _reg("TARGET_ACK_CTRL", tgt), I2C_TARGET_ACK_CTRL_NACK
        )

        events = [0]

        async def probe() -> tuple[bool, str]:
            events[0] = await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", ctl))
            return bool(events[0] & EV_NACK), f"CONTROLLER_EVENTS=0x{events[0]:08x}"

        await self._poll(f"{label}_ctl_nack", EVENT_POLLS, EVENT_STEP, probe)
        intr = await self.csr_read(f"{label}_CTL_INTR", _reg("INTR_STATE", ctl))
        frame = self._frame()
        assert (
            frame is not None and frame.addr_acked and frame.data[:1] == [(NACK_PAYLOAD[0], False)]
        ), f"{label}: wire frame {frame}, expected address ACK then 0x{NACK_PAYLOAD[0]:02x} NACKed"
        assert events[0] == EV_NACK, f"{label}: CONTROLLER_EVENTS=0x{events[0]:08x}, expected 0x1"
        assert intr & INTR_CONTROLLER_HALT, (
            f"{label}: controller INTR_STATE.CONTROLLER_HALT=0 (0x{intr:08x})"
        )
        await self.csr_write(f"{label}_CTL_OFF", _reg("CTRL", ctl), 0)

        async def stopped() -> tuple[bool, str]:
            return self.monitor.stops > stops_base, self.monitor.summary()

        await self._poll(f"{label}_disable_stop", DONE_POLLS, DONE_STEP, stopped)
        await self.csr_write(
            f"{label}_CTL_FMTRST", _reg("FIFO_CTRL", ctl), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", ctl), EV_NACK)
        ev_after = await self.csr_read(f"{label}_EVENTS_AFTER", _reg("CONTROLLER_EVENTS", ctl))
        intr_after = await self.csr_read(f"{label}_CTL_INTR_AFTER", _reg("INTR_STATE", ctl))
        assert ev_after == 0, f"{label}: CONTROLLER_EVENTS=0x{ev_after:08x} after writing 0x1"
        await self._wait_bus_released(f"{label}_bus_released")
        acq = await self._drain(tgt, label, I2C_ACQ_SIGNAL_ERROR)
        data_hits = [(s, b) for s, b in acq if s == I2C_ACQ_SIGNAL_NONE and b in NACK_PAYLOAD]
        assert not data_hits, f"{label}: NACKed bytes acquired as data: {acq}"
        nack1 = await self.csr_read(f"{label}_NACK_COUNT1", _reg("TARGET_NACK_COUNT", tgt))
        nack2 = await self.csr_read(f"{label}_NACK_COUNT2", _reg("TARGET_NACK_COUNT", tgt))
        assert acq[-1][0] == I2C_ACQ_SIGNAL_ERROR, f"{label}: ACQ stream {acq} lacks a final 0x6"
        assert (nack1 & 0xFF, nack2 & 0xFF) == (1, 0), (
            f"{label}: TARGET_NACK_COUNT read {nack1 & 0xFF} then {nack2 & 0xFF}, expected 1 then 0"
        )
        self.nack_rows.append(
            f"target I2C{tgt} (controller I2C{ctl}): NACK written at the hold with "
            f"ACQ_FIFO_NEXT_DATA=0x{nxt & _ABYTE_BM:02x}; wire {frame} (0x{NACK_PAYLOAD[0]:02x} "
            f"NACKed); CONTROLLER_EVENTS=0x{events[0]:08x} CONTROLLER_HALT=1 (INTR_STATE="
            f"0x{intr:08x}); after CTRL=0, STOP and the written 0x1: CONTROLLER_EVENTS="
            f"0x{ev_after:08x} (INTR_STATE=0x{intr_after:08x}); no SIGNAL=0x0 entry carries "
            f"0xe0..0xe3"
        )
        self.record_rows.append(
            f"target I2C{tgt}: ACQ {[(s, hex(b)) for s, b in acq]} ends SIGNAL=0x6; "
            f"TARGET_NACK_COUNT {nack1 & 0xFF} then {nack2 & 0xFF}"
        )
        if last:
            self._chk("CHK-I2C1-ACKCTRL-SW-NACK", "; ".join(self.nack_rows))
            self._chk("CHK-I2C1-ACKCTRL-NACK-RECORD", "; ".join(self.record_rows))
            self._stamp("I2C_ACKCTRL_SW_NACK")

    # ----------------------------------------------------------------- report
    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry; %s",
            len(waits),
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )
        self.chk_lines.append(("CHK-TIMEOUT-PATHS", len(self.stamps)))

    def _emit_nonvac(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed: dict[str, list[int]] = {}
        for name, at in self.chk_lines:
            printed.setdefault(name, []).append(at)
        for name, term in CHECKER_BEFORE.items():
            assert printed.get(name, []) == [order.index(term)], (
                f"{name} printed at fence positions {printed.get(name)}, expected once "
                f"between the term before {term} and {term}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        try:
            await self._bring_up()
            await self._nbytes_leg(1, last=False)
            await self._nbytes_leg(2, last=True)
            await self._range()
            await self._nack_leg(1, last=False)
            await self._nack_leg(2, last=True)
        finally:
            if self.monitor is not None:
                self.monitor.stop()
        self._emit_timeout_paths()
        self._emit_nonvac()
