# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One lifecycle state's export at the SMU boundary and the debug paths that state leaves open.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc ("SEP lifecycle state encodings", "Per-LC-state
feature control profile", "DTP path feature gates"), hw/sys/sep/doc/otp_fuse_controller.adoc
(shadow word ``{~raw[3:0], raw[3:0]}``, JTAG access policy per state),
hw/sys/smu/doc/port_table.adoc (lc_state_o), hw/sys/dtp/doc/jtag.adoc ("Debug Disable"),
hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc (iJTAG DR bit map) and
hw/ip/jtag/jtag_stap/doc/architecture.adoc (disabled STAP).

The eFuse shadow image named by ``+sep_shadow_reg_preload`` is the only stimulus. The sequence is
parameterised by an ``ExportSpec``; the steps a leaf runs follow from it, in this order:

S1, setup: the image is the leaf's own and ``sep_fuse_sense_done_o`` rises within its bound; the
    flag is the bench's ``+skip_fuse_sense`` substitute, a recorded precondition and not graded.
S2, export: ``lc_state_o``, ``obs_sep_lc_state_o`` and ``smc_lc_state_in_o`` sampled on one
    ``clk_smu_i`` edge each equal the state's word.
witness: the SEP OTP bridge reads back a word only that image holds.
feature control: ``lcc_feat_ctrl_o`` equals the state's word.
lane: ``lcc_dbg_disable_smc_jtag2axi_o`` equals the state's value.
control: while the fabric bridge is shut, a write of a non-zero word to SEC_DISABLE_TOKEN_I[7]
    and its read back (PROD), or an LC_STATE read (PROD_END), complete over the SEP OTP bridge.
fabric: one SMC fabric SINGLE_OP read and write launch AR, AW and B at the DTP-to-SMC debug AXI
    port, or launch nothing.
stap: with the PTAP selecting the secondary chain, the SEP STAP host TMS stays parked.
ijtag: under SELECT_IJTAG the three SIBs stay closed.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_boundary_regs import (
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_scan_chain_boundary_seq import (
    DTP_IR_SELECT_IJTAG,
    IJTAG_SELECT_PIN,
    ijtag_shift,
    ijtag_word,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import MIN_PTAP_TMS_EDGES, SEP_STAP_TMS
from seq_lib.smu_jtag_helpers import (
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    PTAP_3DCR_WIDTH,
    SMC_DBG_AXSIZE_4B,
    SMC_OTP_AXSIZE_4B,
    make_smu_jtag_tap,
    pack_otp_single_op,
    pack_single_op,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
    sep_otp_jtag2axi_single_read,
    unpack_otp_single_op,
)
from seq_lib.smu_lifecycle_table import (
    LC_RAW,
    LC_STATE_PRESENSE,
    lc_raw_from_shadow_preload,
    lc_state_word,
)
from seq_lib.smu_otp_bridges_under_dbg_disable_seq import (
    FABRIC_PROBE_ADDR,
    SEP_EFUSE_LC_STATE,
    SEP_EFUSE_SPARE0,
)
from seq_lib.smu_sep_sba_peripheral_test_seq import TOKEN_WORDS
from seq_lib.smu_sep_stap_hold_reset_test_seq import (
    SIB_BITS_FROM_SEP,
    SIB_COUNT,
    STAP_3DCR_BITS,
    TMS_WINDOW_CYCLES,
)

#: hw/sys/sep/doc/lifecycle_controller.adoc, "Per-LC-state feature control profile": with blank
#: SIP_DIS and SYS_DIS vectors TEST_DEV, RMA_SIP and RMA_CHIPLET enable every DBG_1 [23:0],
#: DBG_2 [47:24] and Function [63:48] term.
FEAT_CTRL_ALL_ENABLED = 0xFFFF_FFFF_FFFF_FFFF
#: Same table: PROD and PROD_END close DBG_1 and DBG_2 and leave Function enabled.
FEAT_CTRL_FUNCTION_ONLY = 0xFFFF_0000_0000_0000
#: hw/sys/sep/regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl, FEAT_CTRL reset value.
FEAT_CTRL_RESET = 0

#: hw/sys/dtp/doc/jtag.adoc, "Debug Disable": ``dbg_disable_i.smc_jtag2axi`` is active-high.
LANE_ENABLED = 0
LANE_DISABLED = 1

#: hw/sys/sep/doc/lifecycle_controller.adoc, "DTP path feature gates": the SMC fabric JTAG2AXI
#: path is Case 2 (SIP_DBG & CHIPLET_DBG), which TEST_DEV, RMA_SIP and RMA_CHIPLET leave enabled.
#: One SINGLE_OP read launches one AR; one SINGLE_OP write launches one AW and returns one B
#: (hw/sys/dtp/doc/jtag.adoc, SMC fabric bridge).
LAUNCHED_AR_AW_B = (1, 1, 1)
NOT_LAUNCHED = (0, 0, 0)

#: hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl, SPARE0: a writable word nothing else
#: reads. The marker image (hw/sys/smu/dv/assets/sep_efuse_shadow_lc_test_dev_marker.preload)
#: sets it at the offset sep_addr.h gives SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR.
SPARE0_MARKER = 0xA5C3_5A3C
#: SEC_DISABLE_TOKEN_I[7] from the generated sep_addr.h map. The register is sw = rw
#: (hw/ip/efuse/regs/efuse_mmr.rdl); no TOKEN_EOP write follows, so no token match is triggered.
SEP_EFUSE_SEC_DISABLE_TOKEN_I7 = TOKEN_WORDS[7]
#: Non-zero pattern written to and read back from SEC_DISABLE_TOKEN_I[7].
TOKEN_I7_PATTERN = 0x5A3C_A5C3

#: hw/ip/jtag/jtag_stap/doc/architecture.adoc, "3DCR Register": TMS-Hold resets to 0, the value a
#: disabled STAP drives on its host TMS.
STAP_TMS_PARKED = 0
#: Same page: Select resets to 0 and a capture reads it as 0 while the STAP is disabled.
STAP_SELECT_CAPTURED = 0
#: Select written to the SEP STAP 3DCR; bit 1 of the 3-bit payload.
STAP_SELECT_WRITTEN = 1

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc, "iJTAG Network": DR bit 0 is the DFD SIB,
#: bit 1 the DFT Non-Secure SIB, bit 2 the DFT Secure SIB; a SIB whose disable field is set
#: captures 0 whatever is shifted into it, and the closed DR is three bits long.
IJTAG_DR_BIT = {"dfd": 0, "dft": 1, "dft_secure": 2}
IJTAG_CLOSED_DR_BITS = 3
#: Flush patterns shifted behind the SIB bits: mixed and nonzero.
IJTAG_FLUSH_OPEN_REQUEST = 0b101
IJTAG_FLUSH_CAPTURE = 0b110
IJTAG_SCAN_BITS = 2 * IJTAG_CLOSED_DR_BITS

SENSE_DONE_BOUND_CYCLES = 60000
FABRIC_BOUND_CYCLES = 4000
OTP_POLL_BOUND = 128
FABRIC_WRITE_DATA = 0x5A5A_A5A5
FABRIC_WRITE_WSTRB = 0xF
IDLE_TCKS = 8


@dataclass(frozen=True)
class ExportSpec:
    """The parameters of one lifecycle-state leaf."""

    #: Key of ``LC_RAW``.
    state: str
    #: Suffix of the checker ids, e.g. ``PROD-END``.
    tag: str
    #: Basename of the eFuse shadow image under hw/sys/smu/dv/assets.
    image: str
    feat_ctrl: int
    #: Expected ``lcc_dbg_disable_smc_jtag2axi_o``.
    lane: int
    #: ``spare0`` (SPARE0 witness read), ``token_write_read`` (SEC_DISABLE_TOKEN_I[7] write and
    #: read back) or ``lc_state`` (LC_STATE read): the SEP OTP bridge access the leaf makes.
    witness: str = ""
    #: Check the lane on its own, apart from the fabric launch.
    lane_check: bool = False
    #: Observe the SEP STAP host TMS and the iJTAG SIBs.
    closed_paths: bool = False
    #: The leaf raises ``lc_sigint_inject_i`` and so runs with ``+lc_sigint_inject``.
    inject: bool = False

    @property
    def lc_word(self) -> int:
        return lc_state_word(LC_RAW[self.state])

    @property
    def launches(self) -> bool:
        return self.lane == LANE_ENABLED

    def steps(self) -> list[str]:
        steps = ["export"]
        if self.witness == "spare0":
            steps.append("witness")
        steps.append("feat")
        if self.lane_check:
            steps.append("lane")
        if self.witness in ("token_write_read", "lc_state"):
            steps.append("control")
        steps.append("fabric")
        if self.closed_paths:
            steps += ["stap", "ijtag"]
        return steps

    def wait_labels(self) -> list[str]:
        labels = ["sense_done"]
        if self.witness:
            labels.append("otp_read")
        if self.witness == "token_write_read":
            labels.append("otp_write")
        if self.launches:
            labels += ["fabric_ar", "fabric_b"]
        else:
            labels += ["fabric_window_read", "fabric_window_write"]
        if self.closed_paths:
            labels += [f"stap_window_{i}" for i in range(1, STAP_SCANS + 1)]
            labels += ["ijtag_window_1", "ijtag_window_2"]
        return sorted(labels)


#: Scans of the SEP STAP leg: TAP_3DCR IR, PTAP select, open SIB, write 3DCR, capture 3DCR,
#: PTAP deselect.
STAP_SCANS = 6


class _ReadCounter:
    """Counts the register reads a polling helper makes."""

    def __init__(self, tap) -> None:
        self._tap = tap
        self.reads = 0

    async def write(self, *args, **kwargs):
        return await self._tap.write(*args, **kwargs)

    async def read(self, *args, **kwargs):
        self.reads += 1
        return await self._tap.read(*args, **kwargs)


class smu_lc_export_seq:
    """One lifecycle state's export and path posture, driven by an ``ExportSpec``."""

    def __init__(self, test, spec: ExportSpec) -> None:
        self.test = test
        self.spec = spec
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.tap = None
        self.jtag: OcahJtagMasterSequence | None = None
        self.step_ts: dict[str, float] = {}
        self.step_names: list[str] = []
        self.records: list[dict] = []
        self.exports: dict[str, int] = {}
        self.sense_done_at_sample = 0
        self.witness_word: int | None = None
        self.launch_delta: tuple[int, int, int] | None = None
        self.lane_before: int | None = None
        self.lane_after: int | None = None
        self.control_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _rd(self, name: str, *, allow_xz: bool = False) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on the wrapper tb top")
        return self.test.read_int(pin, name, allow_xz=allow_xz)

    async def _mark(self, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        step = f"S{len(self.step_names) + 1}"
        self.step_names.append(step)
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _record(
        self, label: str, bound: int, used: int, unit: str, last: str, *, expired: bool = False
    ) -> None:
        self.records.append(
            {
                "label": label,
                "bound": bound,
                "used": used,
                "unit": unit,
                "last": last,
                "expired": expired,
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {label}: bound={bound} {unit} used={used} last_state={last}"
            )

    def _check(self, chk: str, text: str, observed, expected) -> None:
        self.sb.expect_eq(chk, observed, expected, evidence=chk)
        self._log(f"{chk}: {text} observed={observed} expected={expected}")

    def _chk(self, stem: str) -> str:
        return f"CHK-{stem}-{self.spec.tag}"

    # ------------------------------------------------------------------
    # Setup and the three export points.
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        spec = self.spec
        preload = str(cocotb.plusargs.get("sep_shadow_reg_preload", ""))
        assert preload.endswith(spec.image), f"wrong shadow image: {preload!r}"
        assert ("lc_sigint_inject" in cocotb.plusargs) == spec.inject, (
            f"+lc_sigint_inject must {'be present' if spec.inject else 'be absent'}"
        )
        assert lc_raw_from_shadow_preload(preload) == LC_RAW[spec.state], (
            f"{spec.image} does not program the {spec.state} LC_STATE"
        )
        assert spec.lc_word != LC_STATE_PRESENSE
        clk = self.dut.clk_smu_i
        last = "no sample"
        for cycle in range(0, SENSE_DONE_BOUND_CYCLES + 1):
            done = self._rd("sep_fuse_sense_done_o", allow_xz=True)
            last = (
                f"sep_fuse_sense_done_o={done} "
                f"smc_lc_state_in_o=0x{self._rd('smc_lc_state_in_o', allow_xz=True):02x}"
            )
            if done:
                self._record("sense_done", SENSE_DONE_BOUND_CYCLES, cycle, "cycles", last)
                self._log(f"CELL sense_done cycles={cycle} {last}")
                await RisingEdge(clk)
                return
            await RisingEdge(clk)
        self._record(
            "sense_done",
            SENSE_DONE_BOUND_CYCLES,
            SENSE_DONE_BOUND_CYCLES,
            "cycles",
            last,
            expired=True,
        )

    async def _sample_exports(self) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.sense_done_at_sample = self._rd("sep_fuse_sense_done_o")
        self.exports = {
            "WRAPPER": self._rd("lc_state_o"),
            "SEP-OBS": self._rd("obs_sep_lc_state_o"),
            "SMC-INPUT": self._rd("smc_lc_state_in_o"),
        }
        self._log(
            f"CELL lc_export lc_state_o=0x{self.exports['WRAPPER']:02x} "
            f"obs_sep=0x{self.exports['SEP-OBS']:02x} "
            f"smc_in=0x{self.exports['SMC-INPUT']:02x} "
            f"sense_done={self.sense_done_at_sample} lc_sigint_err={self._rd('lc_sigint_err_o')} "
            "(lc_sigint_err measured and logged only)"
        )

    def _check_exports(self) -> None:
        spec = self.spec
        for point, value in self.exports.items():
            observed: tuple = (value, value != LC_STATE_PRESENSE)
            expected: tuple = (spec.lc_word, True)
            text = (
                f"{point} word=0x{value:02x} want=0x{spec.lc_word:02x} "
                f"pre_sense=0x{LC_STATE_PRESENSE:02x} sense_done={self.sense_done_at_sample}"
            )
            if spec.witness == "spare0":
                observed += (self.witness_word,)
                expected += (SPARE0_MARKER,)
                text += f" spare0_witness=0x{self.witness_word:08x} want=0x{SPARE0_MARKER:08x}"
            stem = {
                "WRAPPER": "LC-EXPORT-WRAPPER",
                "SEP-OBS": "LC-EXPORT-SEP-OBS",
                "SMC-INPUT": "LC-EXPORT-SMC-INPUT",
            }[point]
            self._check(self._chk(stem), text, observed, expected)

    # ------------------------------------------------------------------
    # JTAG access.
    # ------------------------------------------------------------------

    async def _ensure_tap(self) -> None:
        if self.tap is not None:
            return
        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await raw.reset_tap()
        await raw.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(IDLE_TCKS):
            await raw.step_tms(0)
        self.tap = raw
        self.jtag = OcahJtagMasterSequence(raw)

    async def _sep_otp_write(self, addr: int, data: int, name: str) -> int:
        await self._ensure_tap()
        raw = pack_otp_single_op(J2A_OP_WRITE, addr, data, wstrb=0xF, size=SMC_OTP_AXSIZE_4B)
        await self.tap.write("SEP_OTP_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"SEP OTP J2A WR issue {name}")
        await ClockCycles(self.dut.clk_smu_i, 32)
        status, polls = J2A_STATUS_BUSY, 0
        for _ in range(OTP_POLL_BOUND):
            capt = await self.tap.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
            polls += 1
            require_jtag_tdo_resolved(f"SEP OTP J2A WR poll {name}")
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 16)
        last = f"status={status} data=0x{data:08x}"
        self._record(
            "otp_write",
            OTP_POLL_BOUND,
            polls,
            "polls",
            last,
            expired=(status == J2A_STATUS_BUSY),
        )
        self._log(f"CELL sep_otp_write {name} @0x{addr:08x} {last} polls={polls}")
        return status

    async def _sep_otp_read(self, addr: int, name: str) -> tuple[int, int]:
        await self._ensure_tap()
        counter = _ReadCounter(self.tap)
        status, rdata = await sep_otp_jtag2axi_single_read(counter, addr, poll_limit=OTP_POLL_BOUND)
        require_jtag_tdo_resolved(f"SEP OTP J2A RD {name}")
        last = f"status={status} rdata=0x{int(rdata) & 0xFFFF_FFFF:08x}"
        self._record(
            "otp_read",
            OTP_POLL_BOUND,
            counter.reads,
            "polls",
            last,
            expired=(status == J2A_STATUS_BUSY),
        )
        self._log(f"CELL sep_otp_read {name} @0x{addr:08x} {last} polls={counter.reads}")
        return status, int(rdata) & 0xFFFF_FFFF

    def _counts(self) -> tuple[int, int, int]:
        return (
            self._rd("dtp_smc_dbg_ar_count_o"),
            self._rd("dtp_smc_dbg_aw_count_o"),
            self._rd("dtp_smc_dbg_b_count_o"),
        )

    # ------------------------------------------------------------------
    # Steps.
    # ------------------------------------------------------------------

    async def _step_witness(self) -> None:
        status, word = await self._sep_otp_read(SEP_EFUSE_SPARE0, "SEP_EFUSE_SPARE0")
        assert status == J2A_STATUS_SUCCESS, f"SEP OTP read of SPARE0 status={status}"
        self.witness_word = word
        self._log(
            f"CELL spare0_witness word=0x{word:08x} nonzero={int(word != 0)} "
            f"differs_from_lc_word={int(word != self.spec.lc_word)}"
        )

    async def _step_feat(self) -> None:
        spec = self.spec
        await RisingEdge(self.dut.clk_smu_i)
        word = self._rd("lcc_feat_ctrl_o")
        done = self._rd("sep_fuse_sense_done_o")
        self._check(
            self._chk("LC-FEATCTRL"),
            f"lcc_feat_ctrl_o=0x{word:016x} want=0x{spec.feat_ctrl:016x} "
            f"reset=0x{FEAT_CTRL_RESET:016x} sense_done={done}",
            (word, word != FEAT_CTRL_RESET),
            (spec.feat_ctrl, True),
        )

    async def _step_lane(self) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.lane_before = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        if self.spec.launches:
            return
        self._check(
            self._chk("LC-LANE-SMC-JTAG2AXI"),
            f"lcc_dbg_disable_smc_jtag2axi_o={self.lane_before} want={self.spec.lane}",
            (self.lane_before,),
            (self.spec.lane,),
        )

    async def _step_control(self) -> None:
        spec = self.spec
        wr_ok = True
        if spec.witness == "token_write_read":
            addr, name = SEP_EFUSE_SEC_DISABLE_TOKEN_I7, "SEC_DISABLE_TOKEN_I7"
            wr_ok = await self._sep_otp_write(addr, TOKEN_I7_PATTERN, name) == J2A_STATUS_SUCCESS
        else:
            addr, name = SEP_EFUSE_LC_STATE, "SEP_EFUSE_LC_STATE"
        status, word = await self._sep_otp_read(addr, name)
        ok = wr_ok and status == J2A_STATUS_SUCCESS
        if spec.witness == "token_write_read":
            ok = ok and word == TOKEN_I7_PATTERN
        if spec.witness == "lc_state":
            ok = ok and (word & 0xFF) == spec.lc_word
        self.control_ok = ok
        self._log(
            f"CELL otp_control {name} status={status} word=0x{word:08x} "
            f"want_op={J2A_STATUS_SUCCESS} control_ok={int(ok)}"
        )

    async def _fabric_op(
        self, label: str, op: int, key: int, *, launches: bool | None = None, tag: str = ""
    ) -> None:
        """One SINGLE_OP issue, then ``FABRIC_BOUND_CYCLES`` of counter watching."""
        launches = self.spec.launches if launches is None else launches
        await self._ensure_tap()
        clk = self.dut.clk_smu_i
        before = self._counts()
        data, wstrb = (FABRIC_WRITE_DATA, FABRIC_WRITE_WSTRB) if op == J2A_OP_WRITE else (0, 0)
        await self.tap.write(
            "SMC_AXI_SINGLE_OP",
            pack_single_op(op, FABRIC_PROBE_ADDR, data, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B),
        )
        require_jtag_tdo_resolved(f"SMC fabric SINGLE_OP issue {label}")
        if not launches:
            await ClockCycles(clk, FABRIC_BOUND_CYCLES)
            after = self._counts()
            self._record(
                f"fabric_window_{label}{tag}",
                FABRIC_BOUND_CYCLES,
                FABRIC_BOUND_CYCLES,
                "cycles",
                f"counts ar/aw/b before={before} after={after}",
            )
            return
        for cycle in range(1, FABRIC_BOUND_CYCLES + 1):
            await RisingEdge(clk)
            now = self._counts()
            if now[key] > before[key]:
                self._record(
                    f"fabric_{'ar' if op == J2A_OP_READ else 'b'}{tag}",
                    FABRIC_BOUND_CYCLES,
                    cycle,
                    "cycles",
                    f"counts ar/aw/b before={before} after={now}",
                )
                return
        self._record(
            f"fabric_{'ar' if op == J2A_OP_READ else 'b'}{tag}",
            FABRIC_BOUND_CYCLES,
            FABRIC_BOUND_CYCLES,
            "cycles",
            f"counts ar/aw/b before={before} after={self._counts()}",
            expired=True,
        )

    async def _fabric_deltas(
        self, *, launches: bool | None = None, tag: str = ""
    ) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
        """One SINGLE_OP read then write: the AR/AW/B counts before, after and their deltas."""
        start = self._counts()
        await self._fabric_op("read", J2A_OP_READ, 0, launches=launches, tag=tag)
        await self._fabric_op("write", J2A_OP_WRITE, 2, launches=launches, tag=tag)
        end = self._counts()
        return start, end, (end[0] - start[0], end[1] - start[1], end[2] - start[2])

    async def _step_fabric(self) -> None:
        spec = self.spec
        start, end, delta = await self._fabric_deltas()
        self.launch_delta = delta
        self.lane_after = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        text = (
            f"AR/AW/B deltas={delta} lane_after={self.lane_after} "
            f"want_lane={spec.lane} counts {start}->{end}"
        )
        if spec.launches:
            self._check(
                self._chk("LC-FABRIC-LAUNCH"),
                text,
                (delta, self.lane_after),
                (LAUNCHED_AR_AW_B, spec.lane),
            )
            if spec.lane_check:
                self._check(
                    self._chk("LC-LANE-SMC-JTAG2AXI"),
                    f"lane before={self.lane_before} after={self.lane_after} "
                    f"fabric launched={int(delta == LAUNCHED_AR_AW_B)} want_lane={spec.lane}",
                    (self.lane_before, self.lane_after, delta == LAUNCHED_AR_AW_B),
                    (spec.lane, spec.lane, True),
                )
        else:
            self._check(
                self._chk("LC-FABRIC-NOLAUNCH"),
                f"{text} otp_control_ok={int(self.control_ok)}",
                (delta, self.lane_after, self.control_ok),
                (NOT_LAUNCHED, spec.lane, True),
            )

    # ------------------------------------------------------------------
    # SEP STAP host TMS and the iJTAG SIBs.
    # ------------------------------------------------------------------

    async def _scan_ir(self, value: int, width: int, label: str) -> int:
        captured = await self.jtag.shift_ir(value, width, back_to_rti=True)
        require_jtag_tdo_resolved(f"IR {label}")
        self._log(f"SCAN IR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return int(captured)

    async def _scan_dr(self, value: int, width: int, label: str) -> int:
        captured = await self.jtag.shift_dr(value, width, back_to_rti=True)
        require_jtag_tdo_resolved(f"DR {label}")
        self._log(f"SCAN DR {label} w={width} in=0x{value:x} out=0x{captured:x}")
        return int(captured)

    async def _tms_monitor(
        self, win: dict, oen, tms_path: str = SEP_STAP_TMS, bound: int = TMS_WINDOW_CYCLES
    ) -> dict:
        """Per clk_ref_i edge: host TMS levels, host TMS edges, PTAP TMS edges, TDO-enable highs."""
        sep_tms = hier(self.dut, tms_path)
        prev_ptap = sample(self.dut.jtag_tms, "jtag_tms") & 1
        prev_sep = sample(sep_tms, tms_path) & 1
        out = {"ptap_edges": 0, "sep_edges": 0, "levels": set(), "oen_highs": 0, "done": None}
        for cycle in range(1, bound + 1):
            await RisingEdge(self.dut.clk_ref_i)
            ptap = sample(self.dut.jtag_tms, "jtag_tms") & 1
            sep = sample(sep_tms, tms_path) & 1
            out["levels"].add(sep)
            out["oen_highs"] += sample(oen, f"{tms_path} STAP host TDO enable") & 1
            out["ptap_edges"] += int(ptap != prev_ptap)
            out["sep_edges"] += int(sep != prev_sep)
            prev_ptap, prev_sep = ptap, sep
            if win["scan_done"]:
                out["done"] = cycle
                break
        return out

    async def _stap_parked_probe(self) -> tuple[list[int], int, int, int, int]:
        """The SEP STAP select scans: (host TMS levels, host edges, TDO-enable highs, PTAP edges,
        captured Select)."""
        await self._ensure_tap()
        oen = hier(self.dut, "u_dut.u_smu.u_dtp.jtag_stap_sep_host_tdo_oen_o")
        sel_write = stap_3dcr_scan_word(
            "sep", config_hold=0, stap_sel=STAP_SELECT_WRITTEN, tms_hold=STAP_TMS_PARKED, sib_en=1
        )
        sel_off = stap_3dcr_scan_word(
            "sep", config_hold=0, stap_sel=0, tms_hold=STAP_TMS_PARKED, sib_en=0
        )
        scans = [
            ("TAP_3DCR IR", lambda: self._scan_ir(DTP_IR_TAP_3DCR, DTP_IR_WIDTH, "TAP_3DCR")),
            (
                "PTAP select",
                lambda: self._scan_dr(
                    ptap_3dcr_value(config_hold=1, select=1), PTAP_3DCR_WIDTH, "PTAP select"
                ),
            ),
            (
                "open SEP SIB",
                lambda: self._scan_dr(
                    *ptap_prefixed(stap_sib_pattern("sep", 1), SIB_COUNT), "open SEP SIB"
                ),
            ),
            (
                "write 3DCR select",
                lambda: self._scan_dr(*ptap_prefixed(*sel_write), "write 3DCR select"),
            ),
            (
                "capture 3DCR",
                lambda: self._scan_dr(*ptap_prefixed(*sel_write), "capture 3DCR"),
            ),
            (
                "PTAP deselect",
                lambda: self._scan_dr(
                    *ptap_prefixed(*sel_off, config_hold=0, select=0), "PTAP deselect"
                ),
            ),
        ]
        assert len(scans) == STAP_SCANS
        levels: set[int] = set()
        ptap_edges = sep_edges = oen_highs = 0
        capture = 0
        for index, (label, scan) in enumerate(scans, start=1):
            win = {"scan_done": False}
            monitor = cocotb.start_soon(self._tms_monitor(win, oen))
            captured = await scan()
            win["scan_done"] = True
            obs = await monitor
            done = obs["done"]
            self._record(
                f"stap_window_{index}",
                TMS_WINDOW_CYCLES,
                done if done is not None else TMS_WINDOW_CYCLES,
                "cycles",
                f"{label} levels={sorted(obs['levels'])} ptap_edges={obs['ptap_edges']} "
                f"sep_edges={obs['sep_edges']} oen_highs={obs['oen_highs']}",
                expired=done is None,
            )
            levels |= obs["levels"]
            ptap_edges += obs["ptap_edges"]
            sep_edges += obs["sep_edges"]
            oen_highs += obs["oen_highs"]
            if label == "capture 3DCR":
                capture = (captured >> SIB_BITS_FROM_SEP) & ((1 << STAP_3DCR_BITS) - 1)
        select_read = (capture >> 1) & 1
        self._log(
            f"CELL stap_capture payload=0b{capture:03b} (tms_hold, select, config_hold; "
            "measured and logged only except select)"
        )
        return sorted(levels), sep_edges, oen_highs, ptap_edges, select_read

    async def _step_stap(self) -> None:
        levels, sep_edges, oen_highs, ptap_edges, select_read = await self._stap_parked_probe()
        self._check(
            self._chk("LC-STAP-SEP-PARKED"),
            f"host TMS levels={levels} want=[{STAP_TMS_PARKED}] sep_edges={sep_edges} "
            f"tdo_enable_highs={oen_highs} ptap_tms_edges={ptap_edges} "
            f"(witness want >={MIN_PTAP_TMS_EDGES}) select_capture={select_read} "
            f"want={STAP_SELECT_CAPTURED}",
            (levels, sep_edges, oen_highs, ptap_edges >= MIN_PTAP_TMS_EDGES, select_read),
            ([STAP_TMS_PARKED], 0, 0, True, STAP_SELECT_CAPTURED),
        )

    async def _ijtag_scan(
        self, word: int, window: int, width: int = IJTAG_SCAN_BITS
    ) -> tuple[int, dict]:
        """One SELECT_IJTAG DR scan with the three host selects counted on every TCK."""
        pins = {name: IJTAG_SELECT_PIN[name] for name in IJTAG_DR_BIT}
        win = {"scan_done": False}

        async def watch() -> dict:
            counts = {"tck": 0, **{name: 0 for name in pins}, "done": None}
            prev = sample(self.dut.jtag_tck, "jtag_tck") & 1
            for cycle in range(1, TMS_WINDOW_CYCLES + 1):
                await RisingEdge(self.dut.clk_ref_i)
                tck = sample(self.dut.jtag_tck, "jtag_tck") & 1
                if tck and not prev:
                    counts["tck"] += 1
                    for name, pin in pins.items():
                        counts[name] += sample(getattr(self.dut, pin), pin) & 1
                prev = tck
                if win["scan_done"]:
                    counts["done"] = cycle
                    break
            return counts

        monitor = cocotb.start_soon(watch())
        captured = await self._scan_dr(word, width, f"iJTAG scan {window}")
        win["scan_done"] = True
        counts = await monitor
        done = counts["done"]
        self._record(
            f"ijtag_window_{window}",
            TMS_WINDOW_CYCLES,
            done if done is not None else TMS_WINDOW_CYCLES,
            "cycles",
            f"tck={counts['tck']} selects={ {n: counts[n] for n in pins} }",
            expired=done is None,
        )
        return captured, counts

    async def _step_ijtag(self) -> None:
        await self._ensure_tap()
        closed = frozenset()
        everything = frozenset(IJTAG_DR_BIT)
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG, back_to_rti=True)
        open_word = ijtag_word(closed, everything, IJTAG_FLUSH_OPEN_REQUEST, IJTAG_SCAN_BITS)
        cap_word = ijtag_word(closed, closed, IJTAG_FLUSH_CAPTURE, IJTAG_SCAN_BITS)
        want_open = ijtag_shift(closed, open_word, IJTAG_SCAN_BITS)[0]
        want_cap = ijtag_shift(closed, cap_word, IJTAG_SCAN_BITS)[0]
        got_open, counts_open = await self._ijtag_scan(open_word, 1)
        got_cap, counts_cap = await self._ijtag_scan(cap_word, 2)
        flush_ok = got_open == want_open and got_cap == want_cap
        self._log(
            f"CELL ijtag_flush open_request out=0x{got_open:x} want=0x{want_open:x} "
            f"capture out=0x{got_cap:x} want=0x{want_cap:x} dr_bits={IJTAG_CLOSED_DR_BITS}"
        )
        stems = {
            "dfd": "LC-SIB-DFD-CLOSED",
            "dft": "LC-SIB-DFT-NONSECURE-CLOSED",
            "dft_secure": "LC-SIB-DFT-SECURE-CLOSED",
        }
        for name, bit in IJTAG_DR_BIT.items():
            selects = counts_open[name] + counts_cap[name]
            tcks = min(counts_open["tck"], counts_cap["tck"])
            self._check(
                self._chk(stems[name]),
                f"{name} DR bit {bit} capture={(got_cap >> bit) & 1} want=0 "
                f"flush_returned={int(flush_ok)} host_selects={selects} tck_seen={tcks} "
                f"(witness want >={IJTAG_SCAN_BITS})",
                ((got_cap >> bit) & 1, flush_ok, selects, tcks >= IJTAG_SCAN_BITS),
                (0, True, 0, True),
            )

    # ------------------------------------------------------------------
    # Run.
    # ------------------------------------------------------------------

    async def run(self) -> None:
        spec = self.spec

        await self._mark(f"SETUP: {spec.state} shadow image, wait for sep_fuse_sense_done_o")
        await self._setup()

        for name in spec.steps():
            if name == "export":
                await self._mark("sample the three LC_STATE observation points on one edge")
                await self._sample_exports()
                if spec.witness != "spare0":
                    self._check_exports()
            elif name == "witness":
                await self._mark("WITNESS: SPARE0 read over the SEP OTP bridge")
                await self._step_witness()
                self._check_exports()
            elif name == "feat":
                await self._mark("sample lcc_feat_ctrl_o")
                await self._step_feat()
            elif name == "lane":
                await self._mark("sample lcc_dbg_disable_smc_jtag2axi_o")
                await self._step_lane()
            elif name == "control":
                await self._mark(
                    "POSITIVE CONTROL: SEP OTP bridge token write and read or LC_STATE read"
                )
                await self._step_control()
            elif name == "fabric":
                await self._mark(
                    "SMC fabric SINGLE_OP read then write, DTP-to-SMC AR/AW/B counters"
                )
                await self._step_fabric()
            elif name == "stap":
                await self._mark("SEP STAP select write while the PTAP TMS toggles")
                await self._step_stap()
            elif name == "ijtag":
                await self._mark("SELECT_IJTAG SIB open request and capture")
                await self._step_ijtag()

        await self._finish(spec.wait_labels())

    async def _finish(self, wait_labels: list[str]) -> None:
        """Report every bounded wait, then stamp the ordered step fence."""
        clk = self.dut.clk_smu_i
        await self._mark("TIMEOUT: bounded waits and last state")
        await RisingEdge(clk)
        for rec in self.records:
            state = "EXPIRED" if rec["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {rec['label']}: bound={rec['bound']} {rec['unit']} "
                f"used={rec['used']} {state} last={rec['last']}"
            )
        expired = sum(1 for rec in self.records if rec["expired"])
        self._log(f"CHK-TIMEOUT-PATHS: records={len(self.records)} expired={expired}")
        sb = self.sb
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait labels named by the steps, each exactly once",
            sorted(rec["label"] for rec in self.records),
            wait_labels,
            evidence="CHK-TIMEOUT-PATHS",
        )
        sb.expect_eq(
            "every record has a finite bound and a last-state diagnostic",
            all(0 < rec["bound"] < 10**9 and rec["last"] for rec in self.records),
            True,
            evidence="CHK-TIMEOUT-PATHS",
        )

        await ClockCycles(clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*self.step_names, "PASS"]
        stamps = [self.step_ts[k] for k in order]
        deltas = [b - a for a, b in zip(stamps, stamps[1:])]
        text = " ".join(f"{k}={self.step_ts[k]:.2f}ns" for k in order)
        self._log(f"CHK-NONVAC: ordered fence {'<'.join(order)} {text}")
        sb.expect_eq(
            "CHK-NONVAC ordered fence",
            all(d > 0 for d in deltas),
            True,
            evidence="CHK-NONVAC",
        )
