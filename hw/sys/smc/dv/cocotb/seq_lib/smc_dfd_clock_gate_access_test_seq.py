# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The DFD clock gate seen through register accesses, and the CLA enable and lock.

Every address, field position, width, reset value and software-access type
comes from the generated register map through :mod:`seq_lib.smc_rdl_regmap`
and :mod:`seq_lib.smc_cla_regmap`. The vendored RTL is not a source for any
value this sequence programs or compares against.

Three sentences are graded:

* `dfx_ctrl_status.rdl` `DEBUG_CTRL.cg_en`: "1 stops the clock to the debug-bus
  muxes and the CLA unless force_clk_en is 1; 0 lets it run. ... While the
  clock is stopped, CLA and DST register accesses complete with an error and
  reads return 0xBADCAB1E." With `cg_en` 1 and `force_clk_en` 0 a read of the
  CLA `Scratch` register and of the DST `Trdstimpl` register answer an error
  response carrying 0xBADCAB1E in every 32-bit lane, and a write of `Scratch`
  answers an error and leaves the word; with `force_clk_en` 1, and again with
  `cg_en` 0, the same accesses answer OKAY and the word written.
* `DEBUG_CTRL.force_clk_en`: "1 keeps the DFD clock running whatever the value
  of cg_en", together with "0 lets it run" above: with `DEBUG_CTRL` at 0 the
  CLA evaluates node 0 pair 0 and `CDbgClaTimestamp` advances, and setting
  `force_clk_en` changes neither.
* `dfd_cla.rdl` `CDbgClaCtrlStatus.EnableCla`: "Set this bit to 1 to enable the
  CLA functional clock; clear it to 0 to gate that clock ... this bit can still
  be written while the functional clock is gated", and `ClaLock`: "the
  enable_cla is latched forever". With the pair quiet and its status cleared,
  `EnableCla` 0 keeps the status at 0 while the pair's relation is made true;
  `EnableCla` 1 lets it set. After `ClaLock`, a write of `EnableCla` 0 that
  also moves `ClaChainLoopDelay` lands the delay, reads `EnableCla` back as 1,
  and the pair still sets its status.

The relation values that activate and quiet the pair are measured, as
`smc_dfd_cla_action_seq_utils` measures them. The counter and timestamp words
are sampled across the gated window and logged; the register block holds them
and the RDL states nothing about their motion under the gate.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_cla_regmap import cla_field, cla_register
from .smc_dfd_cla_action_seq_utils import SETTLE_CYCLES, SmcDfdClaActionSeq
from .smc_dfd_trace_accumulator_fill_test_seq import dfd_register, dst_register, pack_fields

CHK_GATED = "CHK-DFD-CG-EN-GATED-ACCESS"
CHK_UNFORCED = "CHK-DFD-CLOCK-RUNS-UNFORCED"
CHK_ENABLE = "CHK-CLA-ENABLE-CLA-GATES"

# dfx_ctrl_status.rdl DEBUG_CTRL.cg_en: the word every gated read returns.
_GATED_WORD = 0xBADCAB1E
_LANE = 0xFFFF_FFFF
_SLVERR = 2
_PATTERNS = (0x5A5A_0000_1234_ABCD, 0xA5A5_FFFF_0F0F_3C3C, 0x0123_4567_89AB_CDEF)
# Bounded polls of the hardware-driven timestamp and of the status bit.
_TIMESTAMP_POLLS = 64
_HOLD_POLLS = 8
_RESP = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}


class smc_dfd_clock_gate_access_test_seq(SmcDfdClaActionSeq):
    """Gate the DFD clock around CLA and DST accesses, then gate the CLA by its enable."""

    def __init__(self, name: str = "smc_dfd_clock_gate_access_test_seq") -> None:
        super().__init__(name)
        self.responses: list[str] = []
        self.timestamps: list[tuple[str, int]] = []
        self.status_trace: list[tuple[str, int]] = []
        self.value_checks = 0

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _scratch():
        return cla_register("Scratch")

    @staticmethod
    def _timestamp():
        return cla_register("CDbgClaTimestamp")

    async def _debug_ctrl(self, cg_en: int, force: int, label: str) -> None:
        clk = dfd_register("dfx_ctrl/DEBUG_CTRL")
        word = pack_fields(clk, {"cg_en": cg_en, "force_clk_en": force})
        await self.csr_write(f"DEBUG_CTRL:{label}", clk.addr, word, length=clk.width_bytes)
        readback = await self.csr_read(f"DEBUG_CTRL:{label}_rb", clk.addr, length=clk.width_bytes)
        assert readback == word, (
            f"DEBUG_CTRL @ 0x{clk.addr:08x} [{label}]: wrote 0x{word:08x}, reads 0x{readback:08x}"
        )
        self.value_checks += 1

    async def _access(self, op: SmcSysAxiOp, reg, label: str, wdata: int = 0) -> SmcSysAxiItem:
        """One access of the register's width whose response is tolerated and returned."""
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = reg.addr
        item.length = reg.width_bytes
        item.wdata = wdata
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.responses.append(f"{label}={_RESP.get(item.resp_code)}")
        return item

    def _lanes(self, word: int, width_bytes: int) -> list[int]:
        return [(word >> (32 * i)) & _LANE for i in range(width_bytes // 4)]

    async def _gated_read(self, reg, label: str) -> None:
        item = await self._access(SmcSysAxiOp.READ, reg, label)
        lanes = self._lanes(item.rdata, reg.width_bytes)
        assert item.resp_code == _SLVERR and all(lane == _GATED_WORD for lane in lanes), (
            f"{CHK_GATED} FAIL: {reg.path} @ 0x{reg.addr:08x} read with cg_en 1 and "
            f"force_clk_en 0 answers {_RESP.get(item.resp_code)} with "
            f"0x{item.rdata:0{reg.width_bytes * 2}x}, want SLVERR with 0x{_GATED_WORD:08x} in "
            f"every 32-bit lane"
        )
        self.value_checks += 1

    async def _okay_read(self, reg, want: int, label: str) -> None:
        item = await self._access(SmcSysAxiOp.READ, reg, label)
        assert item.resp_code == 0 and item.rdata == want, (
            f"{CHK_GATED} FAIL: {reg.path} @ 0x{reg.addr:08x} read [{label}] answers "
            f"{_RESP.get(item.resp_code)} with 0x{item.rdata:x}, want OKAY with 0x{want:x}"
        )
        self.value_checks += 1

    async def _okay_write(self, reg, word: int, label: str) -> None:
        item = await self._access(SmcSysAxiOp.WRITE, reg, label, word)
        assert item.resp_code == 0, (
            f"{CHK_GATED} FAIL: {reg.path} @ 0x{reg.addr:08x} write [{label}] answers "
            f"{_RESP.get(item.resp_code)}, want OKAY"
        )
        self.value_checks += 1

    async def _read_timestamp(self, label: str) -> int:
        word = await self._read(self._timestamp(), label)
        self.timestamps.append((label, word))
        return word

    async def _timestamp_advances(self, label: str) -> tuple[int, int, int]:
        """Poll the timestamp until it changes; return (first, last, polls)."""
        first = await self._read_timestamp(f"{label}_0")
        last = first
        for poll in range(1, _TIMESTAMP_POLLS + 1):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
            last = await self._read_timestamp(f"{label}_{poll}")
            if last != first:
                return first, last, poll
        return first, last, _TIMESTAMP_POLLS

    async def _status_holds(self, want: int, label: str) -> int:
        """Read the status bit `_HOLD_POLLS` times; return the first value off `want`, or `want`."""
        for poll in range(_HOLD_POLLS):
            bit = await self._status_bit(f"{label}_{poll}")
            self.status_trace.append((f"{label}_{poll}", bit))
            if bit != want:
                return bit
        return want

    async def _write_ctrl_lock(self, label: str) -> None:
        ctrl = self._ctrl()
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        await self._write(
            ctrl,
            {
                "EnableCla": 1,
                "EnableEap": 1,
                "DisableGlobalClockHalt": 1,
                "DisableLocalClockHalt": 1,
                "ClaChainLoopDelay": (ctrl.reset_word & chain.mask) >> chain.offset,
                "ClaLock": 1,
            },
            label,
        )

    # -- legs -------------------------------------------------------------

    async def _gated_access(self) -> None:
        scratch = self._scratch()
        impl = dst_register("Trdstimpl")
        await self._debug_ctrl(0, 0, "open")
        await self._okay_write(scratch, _PATTERNS[0], "open_write")
        await self._okay_read(scratch, _PATTERNS[0], "open_read")
        opened = await self._access(SmcSysAxiOp.READ, impl, "open_impl")
        assert opened.resp_code == 0, (
            f"{CHK_GATED} FAIL: Trdstimpl read with DEBUG_CTRL 0 answers "
            f"{_RESP.get(opened.resp_code)}, want OKAY"
        )
        impl_word = opened.rdata

        await self._debug_ctrl(1, 0, "gated")
        await self._gated_read(scratch, "gated_read")
        await self._gated_read(impl, "gated_impl")
        refused = await self._access(SmcSysAxiOp.WRITE, scratch, "gated_write", _PATTERNS[1])
        assert refused.resp_code == _SLVERR, (
            f"{CHK_GATED} FAIL: Scratch write with cg_en 1 and force_clk_en 0 answers "
            f"{_RESP.get(refused.resp_code)}, want SLVERR"
        )
        self.value_checks += 1

        await self._debug_ctrl(1, 1, "forced")
        await self._okay_read(scratch, _PATTERNS[0], "forced_read")
        await self._okay_read(impl, impl_word, "forced_impl")
        await self._okay_write(scratch, _PATTERNS[2], "forced_write")
        await self._okay_read(scratch, _PATTERNS[2], "forced_read_back")

        await self._debug_ctrl(0, 0, "reopened")
        await self._okay_read(scratch, _PATTERNS[2], "reopened_read")
        await self._okay_write(scratch, 0, "reopened_clear")
        cocotb.log.info(
            "%s: with cg_en 1 and force_clk_en 0 the CLA Scratch and DST Trdstimpl reads "
            "answered SLVERR with 0x%08x in every lane and the Scratch write answered SLVERR "
            "and left 0x%016x in place; with force_clk_en 1 the reads answered OKAY with the "
            "held words and a write of 0x%016x read back; with cg_en 0 the read answered OKAY "
            "with that word (%s)",
            CHK_GATED,
            _GATED_WORD,
            _PATTERNS[0],
            _PATTERNS[2],
            ", ".join(self.responses),
        )

    async def _unforced_clock(self) -> tuple[int, int]:
        await self._write(self._eap(), {}, "reset")
        await self._write_ctrl(1, 1, 1, "arm")
        activating, quiet = await self._fire(0, "unforced")
        first, last, polls = await self._timestamp_advances("unforced")
        assert last != first, (
            f"{CHK_UNFORCED} FAIL: CDbgClaTimestamp read 0x{first:x} and stayed there over "
            f"{polls} polls with DEBUG_CTRL 0 (cg_en 0, force_clk_en 0)"
        )
        self.value_checks += 1
        unforced = (activating, first, last, polls)

        await self._debug_ctrl(0, 1, "force")
        await self._quiet(0, quiet, "force_quiet")
        await self._w2c("force")
        held = await self._status_holds(0, "force_quiet")
        assert held == 0, (
            f"{CHK_UNFORCED} FAIL: CDbgEapStatus.Node0Eap0 reads 1 on quiet LogicalOp {quiet} "
            f"after the W2C with force_clk_en 1"
        )
        await self._arm(0, activating, "force_fire")
        assert await self._poll_status("force_fire"), (
            f"{CHK_UNFORCED} FAIL: CDbgEapStatus.Node0Eap0 did not read 1 on LogicalOp "
            f"{activating} with force_clk_en 1 after activating with it 0"
        )
        f_first, f_last, f_polls = await self._timestamp_advances("forced")
        assert f_last != f_first, (
            f"{CHK_UNFORCED} FAIL: CDbgClaTimestamp read 0x{f_first:x} and stayed there over "
            f"{f_polls} polls with force_clk_en 1"
        )
        self.value_checks += 2
        await self._debug_ctrl(0, 0, "unforce")
        cocotb.log.info(
            "%s: with DEBUG_CTRL 0 node 0 pair 0 activated on LogicalOp %d and "
            "CDbgClaTimestamp moved 0x%x -> 0x%x within %d polls; with force_clk_en 1 the "
            "pair activated again on the same relation and the timestamp moved 0x%x -> 0x%x "
            "within %d polls, so the force changed nothing",
            CHK_UNFORCED,
            *unforced,
            f_first,
            f_last,
            f_polls,
        )
        return activating, quiet

    async def _enable_gate(self, activating: int, quiet: int) -> None:
        await self._quiet(0, quiet, "gate_quiet")
        await self._w2c("gate")
        held = await self._status_holds(0, "gate_quiet")
        assert held == 0, (
            f"{CHK_ENABLE} FAIL: CDbgEapStatus.Node0Eap0 reads 1 on quiet LogicalOp {quiet} "
            f"after the W2C with EnableCla 1"
        )
        counter_before = await self._read(cla_register("CDbgClaCounter0Cfg"), "gate_counter_0")
        ts_before = await self._read_timestamp("gate_0")

        await self._write_ctrl(0, 1, 1, "enable_off")
        await self._arm(0, activating, "gated_fire")
        gated = await self._status_holds(0, "gated_fire")
        counter_gated = await self._read(cla_register("CDbgClaCounter0Cfg"), "gate_counter_1")
        ts_gated = await self._read_timestamp("gate_1")
        assert gated == 0, (
            f"{CHK_ENABLE} FAIL: CDbgEapStatus.Node0Eap0 reads 1 on LogicalOp {activating} "
            f"with EnableCla 0, so the CLA evaluated with its functional clock gated "
            f"(status trace {self.status_trace})"
        )
        self.value_checks += 1

        await self._write_ctrl(1, 1, 1, "enable_on")
        assert await self._poll_status("enabled_fire"), (
            f"{CHK_ENABLE} FAIL: CDbgEapStatus.Node0Eap0 did not read 1 on LogicalOp "
            f"{activating} after EnableCla returned to 1"
        )
        self.value_checks += 1

        await self._quiet(0, quiet, "lock_quiet")
        await self._w2c("lock")
        await self._write_ctrl_lock("lock")
        ctrl = self._ctrl()
        chain = cla_field(ctrl, "ClaChainLoopDelay")
        sentinel = ((ctrl.reset_word & chain.mask) >> chain.offset) ^ 1
        await self._write(
            ctrl,
            {
                "EnableCla": 0,
                "EnableEap": 1,
                "DisableGlobalClockHalt": 1,
                "DisableLocalClockHalt": 1,
                "ClaChainLoopDelay": sentinel,
            },
            "locked_enable_off",
        )
        enable = cla_field(ctrl, "EnableCla")
        lock = cla_field(ctrl, "ClaLock")
        word = await self._read(ctrl, "locked_rb")
        landed = (word & chain.mask) >> chain.offset
        assert word & lock.mask and word & enable.mask and landed == sentinel, (
            f"{CHK_ENABLE} FAIL: CDbgClaCtrlStatus reads 0x{word:x} after ClaLock 1 and a write "
            f"of EnableCla 0 with ClaChainLoopDelay 0x{sentinel:x}: "
            f"ClaLock={1 if word & lock.mask else 0} EnableCla={1 if word & enable.mask else 0} "
            f"ClaChainLoopDelay=0x{landed:x}, want 1, 1 and the sentinel"
        )
        await self._arm(0, activating, "locked_fire")
        assert await self._poll_status("locked_fire"), (
            f"{CHK_ENABLE} FAIL: CDbgEapStatus.Node0Eap0 did not read 1 on LogicalOp "
            f"{activating} after ClaLock 1 and a write of EnableCla 0"
        )
        self.value_checks += 2
        cocotb.log.info(
            "%s: with the pair quiet and cleared, EnableCla 0 kept CDbgEapStatus.Node0Eap0 at 0 "
            "over %d polls with LogicalOp %d selected; EnableCla 1 let it set; after ClaLock 1 a "
            "write of EnableCla 0 carrying ClaChainLoopDelay 0x%x read back that delay with "
            "EnableCla 1 and ClaLock 1, so the write landed and the enable held, and the pair "
            "set its status again. Measured, not graded: CDbgClaCounter0Cfg 0x%x -> 0x%x and "
            "CDbgClaTimestamp 0x%x -> 0x%x across the gated window",
            CHK_ENABLE,
            _HOLD_POLLS,
            activating,
            sentinel,
            counter_before,
            counter_gated,
            ts_before,
            ts_gated,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self._gated_access()
        activating, quiet = await self._unforced_clock()
        await self._enable_gate(activating, quiet)
