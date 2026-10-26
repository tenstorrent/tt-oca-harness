# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""drbg_axil64_lane_adapter refuses an unsupported access and zeroes the other lane.

Run mode: no_cpu with +skip_fuse_sense. hw/ip/drbg/doc/architecture.adoc:81-84
(table "DRBG lane adapter forwarded accesses") and :87 state the graded
contract: the adapter forwards a write only at a 4-byte aligned address with
WSTRB 0x0F at address bit 2 = 0 or 0xF0 at bit 2 = 1, and a read only at a
4-byte aligned address. A forwarded read returns the addressed word in the lane
address bit 2 selects and zero in the other lane. Any other access returns
SLVERR and sends no downstream request, and a rejected read returns zero data.
The next supported access must then complete normally.

Two halves, the same split as the port-arbitration leaf:

* The DUT's CSRNG and EDN lane adapters, reached as CSR traffic on s_axi. Per
  lane: a seeded 1- or 2-byte write to INTR_ENABLE whose value differs from the
  register's, two AxSIZE 2 reads of a seeded 8-byte granule (the bit 2 = 0 and
  the bit 2 = 1 word), and a single-byte read at a seeded misaligned offset into
  INTR_ENABLE. "Nothing forwarded" is graded on the lane adapter's own
  AXI-Lite-32 request (drbg_csrng_fwd_o / drbg_edn_fwd_o in tb/tb_top.sv),
  which must stay low on every cycle of the refused access, and through what
  the DUT shows: the register keeps its value, and the lane's
  PERIPH_BUS_ERR_STATUS bit -- the bridge's sticky TL-UL error
  (hw/sys/sep/doc/crypto.adoc, table "SEP crypto alert and fault routing") --
  stays clear. No legal access sets the CSRNG or EDN bit in this build: their
  crypto-demux windows end at the last register, so an unmapped offset answers
  DECERR before the bridge (the same decode sep_irq_ip_to_aggregator_test relies
  on, in seq_lib/sep_irq_aggregator_seq.py). The probe is therefore the
  observable that a control shows live; the status bit is a second consequence
  only. Read data is graded on the whole 64-bit s_axi R beat.
* The TB-owned instance ``u_tbadp_vehicle``, driven pin-level, for the refusal
  conditions one AXI master transfer cannot place at a DUT port (a full 64-bit
  beat, a zero strobe, the strobe of the other lane, a misaligned write
  address) and the misaligned reads at every byte offset of both lanes. Its
  downstream side is observed directly on ``tbadp_fwd_o``.

CHK-REFUSE-ANCHOR: both lanes' PERIPH_BUS_ERR_STATUS bits are clear before any
refused access, and INTR_ENABLE reads OKAY. A bit already set would make the
"stays clear" half of every DUT check vacuous.

CHK-REFUSE-STIM: s_axi presented the access the cell names -- the W beat with
the narrow strobe AMBA assigns to that transfer, and the AR address at the
misaligned byte with ARLEN 0. A cell that presented something else is a
stimulus miss, not a DUT verdict.

CHK-REFUSE-DUT-WRITE: BRESP is SLVERR, the lane adapter accepted the refused
beat at its AXI-Lite-64 input (AW and W handshakes on drbg_<lane>_axil_chan_o
with no X/Z cycle), so the SLVERR is the adapter's and not an upstream refusal;
the lane adapter's forward probe is low and known on every cycle, the lane's
status bit stays clear, and INTR_ENABLE still holds its value.

CHK-REFUSE-DUT-CONTROL: on the same lane, right after the refused write, a
supported 32-bit write of the same value answers OKAY, is seen as a write on
the forward probe, and reads back through a read the probe sees as a read. This
is what makes the "probe low" and "register unchanged" halves able to fail: the
probe sees a forwarded access, and the value the refused write carried lands
when the adapter does forward it. The register is then restored and read back.

CHK-REFUSE-DUT-LANE: an AxSIZE 2 read of the bit 2 = 0 word of the granule
answers OKAY with the whole R beat equal to {32'h0, word}, and one of the bit
2 = 1 word answers OKAY with the whole R beat equal to {word, 32'h0}
(architecture.adoc:83-84). Each read is the one AR on s_axi over its access
at the word's address and is seen as a read on the forward probe. ``word`` is
the value two earlier 32-bit reads of that word returned, both equal; the
neighbour word in the same granule reads non-zero and stable the same way, so a
lane that leaks the neighbour cannot read as zero (CTRL-MISSING otherwise).

CHK-REFUSE-DUT-READ: the misaligned single-byte read answers SLVERR with the
whole R beat 0 (architecture.adoc:87), the lane adapter accepted its AR at the
AXI-Lite-64 input (AR handshake on drbg_<lane>_axil_chan_o, no X/Z cycle), the
forward probe is low and known on every cycle, and the lane's status bit stays
clear.

CHK-REFUSE-VEH: every refused vehicle cell retires with SLVERR, the adapter
drives no AXI-Lite-32 request at any cycle of it, and a refused read returns
RDATA 0 on the whole 64-bit beat. A cycle on which ``tbadp_fwd_o`` is X or Z
fails the cell.

CHK-REFUSE-VEH-CONTROL: after each vehicle cell, with no vehicle reset, the
supported access of the same kind on the same lane answers OKAY, IS seen
forwarded on ``tbadp_fwd_o`` (so the probe is live), and a read returns the
responder's word in the lane address bit 2 selects and zero in the other lane.

FCOV: ``sep_crypto_bus_access_cg`` bins ``x_drbg_lane`` and ``cp_lane_refuse``
sample only in the owner window of this leaf, and only for a cell whose pass
bit of ``crypto_bus_pass`` the leaf sets after the check that grades that
access passes. Per DUT lane there are three windows: the refused write with
CHK-REFUSE-DUT-WRITE and CHK-REFUSE-DUT-CONTROL, the two lane reads with
CHK-REFUSE-DUT-LANE, and the misaligned read with CHK-REFUSE-DUT-READ. The
neighbour reads run with the window closed. A FAIL closes the window before it
raises, so the cell of a failing access never samples. The vehicle has no bins.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import (
    CRYPTO_BUS_PASS_DRBG_LANE,
    CRYPTO_BUS_PASS_LANE_REFUSE,
    close_graded_window,
    open_graded_window,
    set_crypto_bus_pass,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import axi_lane_strobe
from sep_base_test import sep_base_test
from seq_lib.sep_drbg_adapter_port_seq import AR_VALID, AW_VALID, W_VALID
from seq_lib.sep_drbg_adapter_refusal_seq import (
    DUT_LANES,
    FWD_READ,
    FWD_WRITE,
    POST_RESP_CYCLES,
    RESP_OKAY,
    RESP_SLVERR,
    TBADP_RESPONDER_RDATA,
    VEHICLE_REFUSED,
    RefusalVehicle,
    SepDrbgLaneRefusal,
    granule_for,
    lane_beat,
    lane_word,
    legal_partner,
    plan_for,
)

TEST = "sep_drbg_axil_adapter_refusal_test"

# Pass bits of crypto_bus_pass for this leaf's cells (cov/sv/sep_fcov.sv,
# CxbPassDl and CxbPassLr): x_drbg_lane value v = {edn, kind} on bit
# PASS_DL + v (kind 0 bit 2 = 0 read, 1 bit 2 = 1 read, 2 misaligned read);
# cp_lane_refuse value edn on bit PASS_LR + edn.
PASS_DL = CRYPTO_BUS_PASS_DRBG_LANE
PASS_LR = CRYPTO_BUS_PASS_LANE_REFUSE
DL_RD_LANE0, DL_RD_LANE1, DL_MISALIGNED = 0, 1, 2

# clk_i edges the window stays open after the pass bits are written: the edge
# that registers the write plus one on which the sampler compares it.
PASS_HOLD_CYCLES = 2


def _dl_bit(lane_index: int, kind: int) -> int:
    return 1 << (PASS_DL + (lane_index << 2 | kind))


def _lr_bit(lane_index: int) -> int:
    return 1 << (PASS_LR + lane_index)


@pyuvm.test()
class sep_drbg_axil_adapter_refusal_test(sep_base_test):
    """Unsupported accesses at the DRBG lane adapters: SLVERR, nothing forwarded."""

    required_evidence = (
        "CHK-REFUSE-ANCHOR",
        "CHK-REFUSE-STIM",
        "CHK-REFUSE-DUT-WRITE",
        "CHK-REFUSE-DUT-CONTROL",
        "CHK-REFUSE-DUT-LANE",
        "CHK-REFUSE-DUT-READ",
        "CHK-REFUSE-VEH",
        "CHK-REFUSE-VEH-CONTROL",
    )

    def _open(self) -> None:
        """Clear the pass bits, then open the owner window."""
        set_crypto_bus_pass(0, self.logger)
        open_graded_window(TEST, self.logger)

    async def _pass(self, cells: int) -> None:
        """Set the pass bits of the cells a passed check graded, then close the window.

        The window stays open ``PASS_HOLD_CYCLES`` clk_i edges after the write,
        so the sampler sees the bits rise inside it.
        """
        set_crypto_bus_pass(cells, self.logger)
        await ClockCycles(cocotb.top.clk_i, PASS_HOLD_CYCLES)
        close_graded_window(self.logger)
        set_crypto_bus_pass(0, self.logger)

    def _grade(self, ok: bool, msg: str) -> None:
        """On a FAIL, close the window first, then raise."""
        if not ok:
            close_graded_window(self.logger)
            set_crypto_bus_pass(0, self.logger)
            raise AssertionError(msg)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        drv = SepDrbgLaneRefusal(self)

        status0 = await drv.periph_status()
        lane_bits = sum(lane.status_bit for lane in DUT_LANES)
        assert status0 & lane_bits == 0, (
            f"CHK-REFUSE-ANCHOR FAIL: PERIPH_BUS_ERR_STATUS=0x{status0:x} already has a "
            f"CSRNG/EDN bridge-error bit (mask 0x{lane_bits:x}) set before any refused "
            f"access, so a 'stays clear' check would prove nothing"
        )
        baselines = {}
        for lane in DUT_LANES:
            baselines[lane.name] = await drv.read32(f"{lane.name}_baseline_rd", lane.reg_addr)
        self.logger.info(
            "CHK-REFUSE-ANCHOR PASS: PERIPH_BUS_ERR_STATUS=0x%x (csrng/edn bits 0x%x clear); "
            "INTR_ENABLE baselines %s",
            status0,
            lane_bits,
            ", ".join(f"{k}=0x{v:x}" for k, v in baselines.items()),
        )

        plans = [plan_for(lane, rng, baselines[lane.name]) for lane in DUT_LANES]
        granules = [granule_for(lane, rng) for lane in DUT_LANES]
        try:
            for idx, lane in enumerate(DUT_LANES):
                await self._dut_lane(
                    drv, idx, lane, plans[idx], granules[idx], baselines[lane.name]
                )
        finally:
            close_graded_window(self.logger)

        await self._vehicle()

    async def _dut_lane(
        self, drv: SepDrbgLaneRefusal, idx: int, lane, plan, granule, baseline: int
    ) -> None:
        await self._dut_refused_write(drv, idx, lane, plan, baseline)
        await self._dut_lane_read(drv, idx, lane, granule)
        await self._dut_misaligned_read(drv, idx, lane, plan)

    async def _dut_refused_write(
        self, drv: SepDrbgLaneRefusal, idx: int, lane, plan, baseline: int
    ) -> None:
        tag = lane.name
        reg = lane.reg_addr

        # Narrow write carrying a value the register does not hold.
        self._open()
        resp, wstrb, fwd, port = await drv.narrow_write(lane, plan.wr_bytes, plan.pattern)
        want_strb = axi_lane_strobe(reg, plan.wr_bytes)
        self._grade(
            wstrb == want_strb,
            f"CHK-REFUSE-STIM FAIL: [{tag}] s_axi W beat strobe {wstrb}, expected "
            f"0x{want_strb:02x} for a {plan.wr_bytes}-byte write at 0x{reg:08x}",
        )
        after = await drv.read32(f"{tag}_after_refused_wr_rd", reg)
        status = await drv.periph_status()
        self._grade(
            resp == RESP_SLVERR
            and port.bits & (AW_VALID | W_VALID) == AW_VALID | W_VALID
            and port.unknown == 0
            and fwd.bits == 0
            and fwd.unknown == 0
            and after & lane.mask == baseline & lane.mask
            and status & lane.status_bit == 0,
            f"CHK-REFUSE-DUT-WRITE FAIL: [{tag}] {plan.wr_bytes}-byte write of "
            f"0x{plan.pattern:x} (WSTRB 0x{wstrb:02x}) answered resp={resp} (want "
            f"SLVERR={RESP_SLVERR}); drbg_{tag}_axil_chan_o {port.describe()} (want AW and W "
            f"handshakes, 0 X/Z); drbg_{tag}_fwd_o {fwd.describe()} (want 0b00, 0 X/Z); "
            f"INTR_ENABLE 0x{baseline:x} -> 0x{after:x} under mask "
            f"0x{lane.mask:x}; PERIPH_BUS_ERR_STATUS=0x{status:x} ({tag} bit "
            f"0x{lane.status_bit:x})",
        )
        self.logger.info(
            "CHK-REFUSE-DUT-WRITE PASS: [%s] %d-byte write of 0x%x (WSTRB 0x%02x) -> resp=%d "
            "SLVERR; drbg_%s_axil_chan_o %s; drbg_%s_fwd_o %s; INTR_ENABLE still 0x%x "
            "(baseline 0x%x, mask 0x%x); PERIPH_BUS_ERR_STATUS=0x%x",
            tag,
            plan.wr_bytes,
            plan.pattern,
            wstrb,
            resp,
            tag,
            port.describe(),
            tag,
            fwd.describe(),
            after,
            baseline,
            lane.mask,
            status,
        )

        # Positive control: the same value through a supported access lands.
        ctl_resp, ctl_wr_fwd = await drv.watched_write32(f"{tag}_ctl_wr", lane, plan.pattern)
        ctl_rd, ctl_rd_fwd = await drv.watched_read32(f"{tag}_ctl_rd", lane)
        rst_resp = await drv.write32(f"{tag}_restore_wr", reg, baseline)
        rst_rd = await drv.read32(f"{tag}_restore_rd", reg)
        self._grade(
            ctl_resp == RESP_OKAY
            and ctl_wr_fwd.bits == FWD_WRITE
            and ctl_wr_fwd.unknown == 0
            and ctl_rd & lane.mask == plan.pattern
            and ctl_rd_fwd.bits == FWD_READ
            and ctl_rd_fwd.unknown == 0
            and rst_resp == RESP_OKAY
            and rst_rd & lane.mask == baseline & lane.mask,
            f"CHK-REFUSE-DUT-CONTROL FAIL: [{tag}] supported write of 0x{plan.pattern:x} "
            f"resp={ctl_resp}, drbg_{tag}_fwd_o {ctl_wr_fwd.describe()} (want "
            f"0b{FWD_WRITE:02b}); read back 0x{ctl_rd:x}, drbg_{tag}_fwd_o "
            f"{ctl_rd_fwd.describe()} (want 0b{FWD_READ:02b}); restore of 0x{baseline:x} "
            f"resp={rst_resp} read back 0x{rst_rd:x} (mask 0x{lane.mask:x}). Without a "
            f"forwarded, landing control access, 'probe low' and 'INTR_ENABLE unchanged' "
            f"above do not show the refused access is dropped",
        )
        await self._pass(_lr_bit(idx))
        self.logger.info(
            "CHK-REFUSE-DUT-CONTROL PASS: [%s] supported 32-bit write of 0x%x -> resp=%d, "
            "drbg_%s_fwd_o %s; read back 0x%x (differs from the 0x%x the refused write "
            "left), drbg_%s_fwd_o %s; restored 0x%x -> read back 0x%x",
            tag,
            plan.pattern,
            ctl_resp,
            tag,
            ctl_wr_fwd.describe(),
            ctl_rd,
            after,
            tag,
            ctl_rd_fwd.describe(),
            baseline,
            rst_rd,
        )

    async def _dut_lane_read(self, drv: SepDrbgLaneRefusal, idx: int, lane, granule) -> None:
        tag = lane.name
        words = ((granule.lo_name, granule.lo_addr), (granule.hi_name, granule.hi_addr))

        # Window closed: the neighbour values, read twice through 32-bit reads.
        first = [await drv.read32(f"{tag}_{n}_nb_rd0", a) for n, a in words]
        second = [await drv.read32(f"{tag}_{n}_nb_rd1", a) for n, a in words]
        self._grade(
            first == second and all(first),
            f"CTRL-MISSING CHK-REFUSE-DUT-LANE: [{tag}] granule "
            + ", ".join(
                f"{n}@0x{a:08x} read 0x{f:08x} then 0x{s:08x}"
                for (n, a), f, s in zip(words, first, second, strict=True)
            )
            + "; both words must read non-zero and stable, or a lane that leaks its "
            "neighbour could still read as zero",
        )
        self.logger.info(
            "CTRL-REFUSE-DUT-LANE-NEIGHBOUR OK: [%s] %s",
            tag,
            ", ".join(
                f"{n}@0x{a:08x}=0x{v:08x} (twice)" for (n, a), v in zip(words, first, strict=True)
            ),
        )

        self._open()
        reads = [await drv.raw_read(f"{tag}_{n}_lane_rd", lane, a) for n, a in words]
        fails = []
        for (name, addr), word, rd in zip(words, first, reads, strict=True):
            want = lane_beat(word, addr)
            if not (
                rd.resp == RESP_OKAY
                and [a for _c, _i, a in rd.ar] == [addr]
                and rd.beat == want
                and rd.fwd.bits == FWD_READ
                and rd.fwd.unknown == 0
            ):
                fails.append(
                    f"{name}@0x{addr:08x} (bit 2 = {addr >> 2 & 1}): {rd.describe()}; want "
                    f"resp={RESP_OKAY}, one AR at 0x{addr:08x}, R beat 0x{want:016x}, "
                    f"fwd=0b{FWD_READ:02b} with 0 X/Z"
                )
        self._grade(
            not fails,
            f"CHK-REFUSE-DUT-LANE FAIL: [{tag}] {'; '.join(fails)} "
            f"(architecture.adoc:83-84: the other lane reads as zero)",
        )
        await self._pass(_dl_bit(idx, DL_RD_LANE0) | _dl_bit(idx, DL_RD_LANE1))
        self.logger.info(
            "CHK-REFUSE-DUT-LANE PASS: [%s] %s",
            tag,
            "; ".join(
                f"{n}@0x{a:08x} -> resp={rd.resp} R beat 0x{rd.beat:016x} == 0x{lane_beat(w, a):016x}"
                f" (word 0x{w:08x}, neighbour 0x{nb:08x}), AR [0x{a:08x}], {rd.fwd.describe()}"
                for (n, a), w, nb, rd in zip(words, first, first[::-1], reads, strict=True)
            ),
        )

    async def _dut_misaligned_read(self, drv: SepDrbgLaneRefusal, idx: int, lane, plan) -> None:
        tag = lane.name
        reg = lane.reg_addr
        self._open()
        rd, ar, port = await drv.misaligned_read(lane, plan.rd_offset)
        want_ar = {"addr": reg + plan.rd_offset, "len": 0, "size": 0}
        got_ar = None if ar is None else {k: ar[k] for k in want_ar}
        self._grade(
            got_ar == want_ar,
            f"CHK-REFUSE-STIM FAIL: [{tag}] s_axi presented AR {ar}, expected {want_ar}; "
            f"the misaligned read is not the access this cell drives",
        )
        self.logger.info(
            "CHK-REFUSE-STIM PASS: [%s] AR addr=0x%08x len=%d size=%d",
            tag,
            got_ar["addr"],
            got_ar["len"],
            got_ar["size"],
        )
        status = await drv.periph_status()
        self._grade(
            rd.resp == RESP_SLVERR
            and rd.beat == 0
            and port.bits & AR_VALID == AR_VALID
            and port.unknown == 0
            and rd.fwd.bits == 0
            and rd.fwd.unknown == 0
            and status & lane.status_bit == 0,
            f"CHK-REFUSE-DUT-READ FAIL: [{tag}] 1-byte read at 0x{reg + plan.rd_offset:08x} "
            f"(ARADDR[1:0]={plan.rd_offset}): {rd.describe()} (want resp={RESP_SLVERR} "
            f"SLVERR, one R beat 0x{0:016x}, fwd=0b00 with 0 X/Z, architecture.adoc:87); "
            f"drbg_{tag}_axil_chan_o {port.describe()} (want an AR handshake, 0 X/Z); "
            f"PERIPH_BUS_ERR_STATUS=0x{status:x} ({tag} bit 0x{lane.status_bit:x} must be clear)",
        )
        await self._pass(_dl_bit(idx, DL_MISALIGNED))
        self.logger.info(
            "CHK-REFUSE-DUT-READ PASS: [%s] 1-byte read at 0x%08x (ARADDR[1:0]=%d) -> %s; "
            "drbg_%s_axil_chan_o %s; PERIPH_BUS_ERR_STATUS=0x%x (%s bit 0x%x clear)",
            tag,
            reg + plan.rd_offset,
            plan.rd_offset,
            rd.describe(),
            tag,
            port.describe(),
            status,
            tag,
            lane.status_bit,
        )

    async def _vehicle(self) -> None:
        veh = RefusalVehicle()
        await veh.reset()
        refused_fails: list[str] = []
        control_fails: list[str] = []
        veh_fwd_x = 0
        ctl_fwd_seen: set[int] = set()
        ctl_rd_lanes: set[int] = set()
        ctl_rd_others: set[int] = set()
        for name, op, addr, strb in VEHICLE_REFUSED:
            obs = await veh.access(name, op, addr, strb)
            veh_fwd_x += obs["fwd_x"]
            if not (
                obs["retired"]
                and obs["resp"] == RESP_SLVERR
                and obs["fwd"] == 0
                and obs["fwd_x"] == 0
                and (op is not SepAxiOp.READ or obs["rdata"] == 0)
            ):
                refused_fails.append(veh.describe(obs))
                self.logger.error("CHK-REFUSE-VEH FAIL: %s", refused_fails[-1])
            else:
                self.logger.info("CHK-REFUSE-VEH OK: %s", veh.describe(obs))

            # No reset between: the cell must leave the adapter able to serve.
            lop, laddr, lstrb = legal_partner(op, addr)
            ctl = await veh.access(f"{name}/legal", lop, laddr, lstrb)
            want_fwd = FWD_WRITE if lop is SepAxiOp.WRITE else FWD_READ
            ok = (
                ctl["retired"]
                and ctl["resp"] == RESP_OKAY
                and ctl["fwd"] == want_fwd
                and ctl["fwd_x"] == 0
            )
            ctl_fwd_seen.add(ctl["fwd"])
            if ok and lop is SepAxiOp.READ:
                lane, other = lane_word(ctl["rdata"], laddr)
                ctl_rd_lanes.add(lane)
                ctl_rd_others.add(other)
                ok = lane == TBADP_RESPONDER_RDATA and other == 0
            if not ok:
                control_fails.append(
                    f"{veh.describe(ctl)} (want fwd=0b{want_fwd:02b}; a read wants "
                    f"0x{TBADP_RESPONDER_RDATA:08x} in the addressed lane and 0 in the other)"
                )
                self.logger.error("CHK-REFUSE-VEH-CONTROL FAIL: %s", control_fails[-1])
            else:
                self.logger.info("CHK-REFUSE-VEH-CONTROL OK: %s", veh.describe(ctl))

        assert not control_fails, (
            f"CHK-REFUSE-VEH-CONTROL FAIL: {len(control_fails)} supported access(es) after a "
            f"vehicle cell did not complete forwarded with OKAY, the addressed-lane word and a "
            f"zero other lane: {'; '.join(control_fails)}"
        )
        self.logger.info(
            "CHK-REFUSE-VEH-CONTROL PASS: %d supported accesses, one after each vehicle cell "
            "and with no vehicle reset, answered OKAY; tbadp_fwd_o values seen %s; "
            "addressed-lane read words seen %s (want 0x%08x); other-lane read words seen %s "
            "(want 0x0)",
            len(VEHICLE_REFUSED),
            sorted(f"0b{v:02b}" for v in ctl_fwd_seen),
            sorted(f"0x{v:08x}" for v in ctl_rd_lanes),
            TBADP_RESPONDER_RDATA,
            sorted(f"0x{v:x}" for v in ctl_rd_others),
        )
        assert not refused_fails, (
            f"CHK-REFUSE-VEH FAIL: {len(refused_fails)} of {len(VEHICLE_REFUSED)} "
            f"unsupported access(es) were not answered SLVERR with nothing forwarded and, for "
            f"a read, RDATA 0: {'; '.join(refused_fails)}"
        )
        self.logger.info(
            "CHK-REFUSE-VEH PASS: %d unsupported accesses (%s) answered SLVERR with "
            "tbadp_fwd_o low on every cycle to %d cycles after the response "
            "(%d X/Z cycles); every refused read returned RDATA 0x0",
            len(VEHICLE_REFUSED),
            ", ".join(n for n, *_r in VEHICLE_REFUSED),
            POST_RESP_CYCLES,
            veh_fwd_x,
        )
