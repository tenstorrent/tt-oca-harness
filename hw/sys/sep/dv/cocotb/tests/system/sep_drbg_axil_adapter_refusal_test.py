# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""drbg_axil64_lane_adapter answers an unsupported access SLVERR and forwards nothing.

no_cpu / +skip_fuse_sense. hw/ip/drbg/doc/architecture.adoc ("Bus Protocol
Adaptation") states the graded contract: the adapter forwards only aligned
single-lane accesses with WSTRB 0x0F or 0xF0, selects the 32-bit data lane by
address bit 2, and answers every other access AXI SLVERR with no downstream
request. The next supported access must then complete normally.

Graded refusals: a write whose strobe is not 0x0F or 0xF0 (a byte, a halfword,
a full 64-bit beat, a zero strobe) and a write whose address is not 4-byte
aligned. Driven only: a misaligned read, a legal strobe on the lane address
bit 2 does not select, and the other lane of a supported read. Those three
rules are in the adapter RTL header only (#2822). Their cells run on every seed
for coverage; the response, data and forward probe are logged at info level as
"not graded until #2822 specifies the rule" and do not enter the verdict.

Two halves, the same split as the port-arbitration leaf:

* The DUT's CSRNG and EDN lane adapters, reached as CSR traffic on s_axi. A
  seeded 1- or 2-byte write to INTR_ENABLE whose value differs from the
  register's (graded), then a single-byte read at a seeded misaligned offset
  into INTR_ENABLE (driven only, last on the lane so it cannot change what the
  graded checks see). "Nothing forwarded" is graded on the lane adapter's own
  AXI-Lite-32 request (drbg_csrng_fwd_o / drbg_edn_fwd_o in tb/tb_top.sv),
  which must stay low on every cycle of the refused write, and through what the
  DUT shows: the register keeps its value, and the lane's PERIPH_BUS_ERR_STATUS
  bit -- the bridge's sticky TL-UL error (hw/sys/sep/doc/crypto.adoc, "Crypto
  Register-Bridge Faults") -- stays clear. No legal access sets the CSRNG or
  EDN bit in this build: their crypto-demux windows end at the last register,
  so an unmapped offset answers DECERR before the bridge
  (seq_lib/sep_irq_aggregator_seq.py). The probe is therefore the observable
  that a control shows live; the status bit is a second consequence only.
* The TB-owned instance ``u_tbadp_vehicle``, driven pin-level, for the refusal
  conditions one AXI master transfer cannot place at a DUT port (a full 64-bit
  beat, a zero strobe, a misaligned write address, and the driven-only
  wrong-lane strobe). Its downstream side is observed directly on
  ``tbadp_fwd_o``.

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

CHK-REFUSE-VEH: every graded refused vehicle cell retires with SLVERR and the
adapter drives no AXI-Lite-32 request at any cycle of it. A cycle on which
``tbadp_fwd_o`` is X or Z fails the cell.

CHK-REFUSE-VEH-CONTROL: after each vehicle cell, graded or driven only, with no
vehicle reset, the supported access of the same kind on the same lane answers
OKAY, IS seen forwarded on ``tbadp_fwd_o`` (so the probe is live), and a read
returns the responder's word in the lane address bit 2 selects.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import axi_lane_strobe
from sep_base_test import sep_base_test
from seq_lib.sep_drbg_adapter_port_seq import AW_VALID, W_VALID
from seq_lib.sep_drbg_adapter_refusal_seq import (
    DUT_LANES,
    FWD_READ,
    FWD_WRITE,
    NOT_GRADED_NOTE,
    POST_RESP_CYCLES,
    RESP_OKAY,
    RESP_SLVERR,
    TBADP_RESPONDER_RDATA,
    VEHICLE_CELLS,
    VEHICLE_HEADER_ONLY,
    VEHICLE_REFUSED,
    RefusalVehicle,
    SepDrbgLaneRefusal,
    lane_word,
    legal_partner,
    plan_for,
)


@pyuvm.test()
class sep_drbg_axil_adapter_refusal_test(sep_base_test):
    """Unsupported accesses at the DRBG lane adapters: SLVERR, nothing forwarded."""

    required_evidence = (
        "CHK-REFUSE-ANCHOR",
        "CHK-REFUSE-STIM",
        "CHK-REFUSE-DUT-WRITE",
        "CHK-REFUSE-DUT-CONTROL",
        "CHK-REFUSE-VEH",
        "CHK-REFUSE-VEH-CONTROL",
    )

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

        for lane in DUT_LANES:
            await self._dut_lane(
                drv, lane, plan_for(lane, rng, baselines[lane.name]), baselines[lane.name]
            )

        await self._vehicle()

    async def _dut_lane(self, drv: SepDrbgLaneRefusal, lane, plan, baseline: int) -> None:
        tag = lane.name
        reg = lane.reg_addr

        # Narrow write carrying a value the register does not hold.
        resp, wstrb, fwd, port = await drv.narrow_write(lane, plan.wr_bytes, plan.pattern)
        want_strb = axi_lane_strobe(reg, plan.wr_bytes)
        assert wstrb == want_strb, (
            f"CHK-REFUSE-STIM FAIL: [{tag}] s_axi W beat strobe {wstrb}, expected "
            f"0x{want_strb:02x} for a {plan.wr_bytes}-byte write at 0x{reg:08x}"
        )
        after = await drv.read32(f"{tag}_after_refused_wr_rd", reg)
        status = await drv.periph_status()
        assert (
            resp == RESP_SLVERR
            and port.bits & (AW_VALID | W_VALID) == AW_VALID | W_VALID
            and port.unknown == 0
            and fwd.bits == 0
            and fwd.unknown == 0
            and after & lane.mask == baseline & lane.mask
            and status & lane.status_bit == 0
        ), (
            f"CHK-REFUSE-DUT-WRITE FAIL: [{tag}] {plan.wr_bytes}-byte write of "
            f"0x{plan.pattern:x} (WSTRB 0x{wstrb:02x}) answered resp={resp} (want "
            f"SLVERR={RESP_SLVERR}); drbg_{tag}_axil_chan_o {port.describe()} (want AW and W "
            f"handshakes, 0 X/Z); drbg_{tag}_fwd_o {fwd.describe()} (want 0b00, 0 X/Z); "
            f"INTR_ENABLE 0x{baseline:x} -> 0x{after:x} under mask "
            f"0x{lane.mask:x}; PERIPH_BUS_ERR_STATUS=0x{status:x} ({tag} bit "
            f"0x{lane.status_bit:x})"
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
        assert (
            ctl_resp == RESP_OKAY
            and ctl_wr_fwd.bits == FWD_WRITE
            and ctl_wr_fwd.unknown == 0
            and ctl_rd & lane.mask == plan.pattern
            and ctl_rd_fwd.bits == FWD_READ
            and ctl_rd_fwd.unknown == 0
            and rst_resp == RESP_OKAY
            and rst_rd & lane.mask == baseline & lane.mask
        ), (
            f"CHK-REFUSE-DUT-CONTROL FAIL: [{tag}] supported write of 0x{plan.pattern:x} "
            f"resp={ctl_resp}, drbg_{tag}_fwd_o {ctl_wr_fwd.describe()} (want "
            f"0b{FWD_WRITE:02b}); read back 0x{ctl_rd:x}, drbg_{tag}_fwd_o "
            f"{ctl_rd_fwd.describe()} (want 0b{FWD_READ:02b}); restore of 0x{baseline:x} "
            f"resp={rst_resp} read back 0x{rst_rd:x} (mask 0x{lane.mask:x}). Without a "
            f"forwarded, landing control access, 'probe low' and 'INTR_ENABLE unchanged' "
            f"above do not show the refused access is dropped"
        )
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

        # Misaligned single-byte read, driven only. It runs last on the lane, so
        # whatever the adapter does with it cannot change a graded check above.
        resp, ar, fwd, port = await drv.misaligned_read(lane, plan.rd_offset)
        want_ar = {"addr": reg + plan.rd_offset, "len": 0, "size": 0}
        got_ar = None if ar is None else {k: ar[k] for k in want_ar}
        assert got_ar == want_ar, (
            f"CHK-REFUSE-STIM FAIL: [{tag}] s_axi presented AR {ar}, expected {want_ar}; "
            f"the misaligned read is not the access this cell drives"
        )
        self.logger.info(
            "CHK-REFUSE-STIM PASS: [%s] W strobe=0x%02x (%d-byte write at 0x%08x); AR "
            "addr=0x%08x len=%d size=%d",
            tag,
            wstrb,
            plan.wr_bytes,
            reg,
            got_ar["addr"],
            got_ar["len"],
            got_ar["size"],
        )
        status = await drv.periph_status()
        self.logger.info(
            "REFUSE-DUT-READ observation (%s): [%s] 1-byte read at 0x%08x "
            "(ARADDR[1:0]=%d) -> resp=%d; drbg_%s_axil_chan_o %s; drbg_%s_fwd_o %s; "
            "PERIPH_BUS_ERR_STATUS=0x%x (%s bit 0x%x)",
            NOT_GRADED_NOTE,
            tag,
            reg + plan.rd_offset,
            plan.rd_offset,
            resp,
            tag,
            port.describe(),
            tag,
            fwd.describe(),
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
        for (name, op, addr, strb), graded in VEHICLE_CELLS:
            obs = await veh.access(name, op, addr, strb)
            if graded:
                veh_fwd_x += obs["fwd_x"]
            if not graded:
                self.logger.info(
                    "REFUSE-VEH observation (%s): %s", NOT_GRADED_NOTE, veh.describe(obs)
                )
            elif not (
                obs["retired"]
                and obs["resp"] == RESP_SLVERR
                and obs["fwd"] == 0
                and obs["fwd_x"] == 0
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
                ok = lane == TBADP_RESPONDER_RDATA
            if not ok:
                control_fails.append(f"{veh.describe(ctl)} (want fwd=0b{want_fwd:02b})")
                self.logger.error("CHK-REFUSE-VEH-CONTROL FAIL: %s", control_fails[-1])
            else:
                self.logger.info("CHK-REFUSE-VEH-CONTROL OK: %s", veh.describe(ctl))

        assert not control_fails, (
            f"CHK-REFUSE-VEH-CONTROL FAIL: {len(control_fails)} supported access(es) after a "
            f"vehicle cell did not complete forwarded with OKAY and the addressed-lane data: "
            f"{'; '.join(control_fails)}"
        )
        self.logger.info(
            "CHK-REFUSE-VEH-CONTROL PASS: %d supported accesses, one after each vehicle cell "
            "and with no vehicle reset, answered OKAY; tbadp_fwd_o values seen %s; "
            "addressed-lane read words seen %s (want 0x%08x)",
            len(VEHICLE_CELLS),
            sorted(f"0b{v:02b}" for v in ctl_fwd_seen),
            sorted(f"0x{v:08x}" for v in ctl_rd_lanes),
            TBADP_RESPONDER_RDATA,
        )
        self.logger.info(
            "REFUSE-VEH-CONTROL observation (%s): other-lane read words seen %s",
            NOT_GRADED_NOTE,
            sorted(f"0x{v:x}" for v in ctl_rd_others),
        )
        assert not refused_fails, (
            f"CHK-REFUSE-VEH FAIL: {len(refused_fails)} of {len(VEHICLE_REFUSED)} graded "
            f"unsupported access(es) were not answered SLVERR with nothing forwarded: "
            f"{'; '.join(refused_fails)}"
        )
        self.logger.info(
            "CHK-REFUSE-VEH PASS: %d graded unsupported accesses (%s) answered SLVERR with "
            "tbadp_fwd_o low on every cycle to %d cycles after the response "
            "(%d X/Z cycles); %d driven-only cells (%s) logged, %s",
            len(VEHICLE_REFUSED),
            ", ".join(n for n, *_r in VEHICLE_REFUSED),
            POST_RESP_CYCLES,
            veh_fwd_x,
            len(VEHICLE_HEADER_ONLY),
            ", ".join(n for n, *_r in VEHICLE_HEADER_ONLY),
            NOT_GRADED_NOTE,
        )
