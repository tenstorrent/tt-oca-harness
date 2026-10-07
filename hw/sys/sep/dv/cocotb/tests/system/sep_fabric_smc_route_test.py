# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The route demux sends the SMC aperture that the SMC supplies to the SMC port, first and unfiltered.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", output fabric, and
"Transaction Routing"; ``hw/sys/sep/doc/port_table.adoc``):

* The route demux matches the aperture on ``smc_global_base_addr_i`` /
  ``smc_region_size_i`` first in its order and sends that traffic to
  ``sep_ext_to_smc_axi_req_o`` without the outbound filter.
* Only the supplied aperture goes to the SMC port. The static SMC row of the
  memory map (``0x4000_0000`` to ``0x7FFF_FFFF``) names the SMC address space and
  does not select the port.
* A request to the SMC waits until ``SMC_FUSE_SENSE_STATUS.smc_fuse_sense_done``
  reads 1 (``sep_cpu_ctrl.adoc``).
* A request that no enabled outbound entry admits is answered DECERR
  (``hw/ip/axi_filter/doc/index.adoc``, "Blocked Transactions").

The seed draws configuration A (base ``0x4000_0000``) or configuration B (base
``0x9000_0000``, inside the reset SMU window), both with size ``0x0100_0000``.
The leaf drives the aperture through the BH-SMC hook before reset release; the
specification states no behaviour for an aperture change after reset, so a seed
runs one configuration.

Checks:

* CHK-SMC-ROUTE (configuration A): the edge words reach PR-SMC (one AW and one AR
  each) and never PR-OUT, the SMC responder returns the written marker, the
  accesses still pass with every outbound entry disabled, and an SMU-window read
  then answers DECERR with PR-OUT silent. Control: the SMU-window read with the
  pair enabled answers OKAY on PR-OUT and not on PR-SMC.
* CHK-SMC-STATIC-ROW (configuration A): the word one above the aperture top, in
  the static SMC row, gives no PR-SMC handshake on read and on write. Its response
  and its PR-OUT count are logged only: the specification gives two conflicting
  rules for an address outside every window.
* CHK-SMC-FIRST-MATCH (configuration B): the aperture words inside the SMU window
  reach PR-SMC and not PR-OUT; the SMU-window word outside the aperture reaches
  PR-OUT and not PR-SMC.

Read data with an X or Z bit fails the read in the AXI master (VCS; Verilator is
2-state).

Run mode: no_cpu, ``lsu_stub_all_live``, ``+skip_fuse_sense``. RANDCFG: the
configuration is the only draw. The configuration bins close over a merge of
regressions.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_bh_smc import drive_bh_smc
from env.sep_fabric_tap import start_taps, stop_taps
from env.sep_fcov_gate import close_graded_window, fcov_present, open_graded_window
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LCC_FEAT_CTRL
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank

TEST = "sep_fabric_smc_route_test"

RESP_OKAY = 0
RESP_DECERR = 3
RESP_NAME = {-1: "TIMEOUT", 0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

SMC_SIZE = 0x0100_0000
CFG = {"A": 0x4000_0000, "B": 0x9000_0000}
# The SMU window at its RDL reset aperture, and an SMU-window word outside both
# SMC apertures.
SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
SMU_SIZE = SEP_CPU_CTRL.reset("SMU_REGION_SIZE")
SMU_LAST = SMU_BASE + SMU_SIZE - 1
SMU_PROBE = SMU_BASE + 0x100
# Fixed, pairwise different markers: [first word, last word] per leg.
MARK_ROUTE = (0x5A3C_0001, 0xA5C3_0002)
MARK_UNFILT = (0x3C5A_0003, 0xC3A5_0004)
MARK_FIRST = (0x6B2D_0005, 0xB6D2_0006)
MARK_ABOVE = 0x1E1E_0007

SMC_FUSE_STATUS = SEP_CPU_CTRL.addr("SMC_FUSE_SENSE_STATUS")
SMC_FUSE_DONE = SEP_CPU_CTRL.field_mask("SMC_FUSE_SENSE_STATUS", "smc_fuse_sense_done")
_FUSE_POLL_MAX = 400
_FUSE_POLL_GAP = 50


class _Csr(SepAxiRegDriver):
    _DRIVER_TAG = "SMCROUTE"


@pyuvm.test()
class sep_fabric_smc_route_test(sep_base_test):
    """The supplied SMC aperture goes to the SMC port, first and unfiltered."""

    async def _lsu(
        self, op: SepAxiOp, addr: int, *, data: int = 0, expect_error: bool = False,
        ungraded: bool = False,
    ) -> SepAxiAccessSeq:
        """One 4-byte LSU access. ``ungraded`` lets the caller log a response that
        the specification does not state; a missing response still fails."""
        kw = {}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = ungraded
        else:
            kw["allow_unverified_write_resp"] = ungraded or expect_error
        seq = SepAxiAccessSeq(
            f"smc_route_{op.value}",
            op=op,
            addr=addr,
            wdata=data,
            length=4,
            size=2,
            expect_error=expect_error,
            **kw,
        )
        # The s_axi monitor fails an unannounced DECERR beat; a refused or
        # ungraded probe announces one and returns the credit it did not use.
        armed = expect_error or ungraded
        if armed:
            self.env.axi_monitor.arm_expected_decerr(1)
        await self.start_seq(seq)
        if armed and seq.resp_code != RESP_DECERR:
            self.env.axi_monitor.release_expected_decerr(1)
        return seq

    def _counts(self, mark: dict[str, int]) -> dict[str, int]:
        smc, out = self.taps["PR-SMC"], self.taps["PR-OUT"]
        return {
            "smc_aw": smc.count(mark["PR-SMC"], "aw"),
            "smc_ar": smc.count(mark["PR-SMC"], "ar"),
            "out_aw": out.count(mark["PR-OUT"], "aw"),
            "out_ar": out.count(mark["PR-OUT"], "ar"),
        }

    def _mark(self) -> dict[str, int]:
        return {n: t.mark() for n, t in self.taps.items()}

    async def _edge_word(self, chk: str, addr: int, marker: int) -> dict:
        """Write then read one aperture word; return the counts and the readback."""
        m = self._mark()
        wr = await self._lsu(SepAxiOp.WRITE, addr, data=marker)
        rd = await self._lsu(SepAxiOp.READ, addr)
        c = self._counts(m)
        smc_beats = self.taps["PR-SMC"].since(m["PR-SMC"])
        unknown = [b.fmt() for b in smc_beats if b.has_unknown()]
        assert wr.resp_code == RESP_OKAY and rd.resp_code == RESP_OKAY, (
            f"{chk} FAIL: addr=0x{addr:08x} wr_resp={RESP_NAME[wr.resp_code]} "
            f"rd_resp={RESP_NAME[rd.resp_code]}, expected OKAY from the SMC responder"
        )
        rdata = rd.rdata & 0xFFFF_FFFF
        assert rdata == marker, (
            f"{chk} FAIL: addr=0x{addr:08x} rdata=0x{rdata:08x} wr=0x{marker:08x}: "
            "the read did not return the written value"
        )
        assert not unknown, f"{chk} FAIL: addr=0x{addr:08x} X/Z on PR-SMC: {unknown}"
        self.logger.info(
            "%s LOG: addr=0x%08x smc_aw=%d smc_ar=%d out_aw=%d out_ar=%d rdata=0x%08x wr=0x%08x "
            "smc_addrs=%s",
            chk, addr, c["smc_aw"], c["smc_ar"], c["out_aw"], c["out_ar"], rdata, marker,
            [hex(a) for a in self.taps["PR-SMC"].addrs(m["PR-SMC"]) if a is not None],
        )
        return {"addr": addr, "rdata": rdata, "wr": marker, **c}

    async def _smu_read(self, *, expect_error: bool) -> dict:
        m = self._mark()
        rd = await self._lsu(SepAxiOp.READ, SMU_PROBE, expect_error=expect_error)
        c = self._counts(m)
        return {"resp": rd.resp_code, **c}

    async def _wait_smc_fuse_done(self) -> int:
        """Bounded poll of SMC_FUSE_SENSE_STATUS; returns the number of reads."""
        for n in range(1, _FUSE_POLL_MAX + 1):
            v = await self.csr._rd(SMC_FUSE_STATUS)
            if v & SMC_FUSE_DONE:
                self.logger.info(
                    "SMC-FUSE-DONE LOG: status=0x%08x reads=%d", v, n
                )
                return n
            await ClockCycles(cocotb.top.clk_i, _FUSE_POLL_GAP)
        raise AssertionError(
            f"SMC-FUSE-DONE FAIL: smc_fuse_sense_done still 0 after {_FUSE_POLL_MAX} reads"
        )

    async def _program_pair(self, start: int, end: int) -> None:
        for idx, ns in ((0, False), (1, True)):
            await self.outf.program(
                idx,
                FilterEntry(
                    start=start, end=end, enabled=True, read_allowed=True,
                    write_allowed=True, allow_ns=ns, src_id=0,
                ),
            )

    async def _config_a(self, base: int) -> None:
        last = base + SMC_SIZE - 4
        above = base + SMC_SIZE
        await self._program_pair(CFG["A"], SMU_LAST)

        open_graded_window(TEST, self.logger)
        route = [
            await self._edge_word("CHK-SMC-ROUTE", base, MARK_ROUTE[0]),
            await self._edge_word("CHK-SMC-ROUTE", last, MARK_ROUTE[1]),
        ]
        ctl = await self._smu_read(expect_error=False)
        close_graded_window(self.logger)
        assert ctl["resp"] == RESP_OKAY, (
            f"CHK-SMC-ROUTE FAIL: control read 0x{SMU_PROBE:08x} resp={RESP_NAME[ctl['resp']]}, "
            "expected OKAY through the enabled outbound pair"
        )
        control_out = ctl["out_ar"]
        control_smc = ctl["smc_ar"] + ctl["smc_aw"]

        await self.outf.disable_all()

        open_graded_window(TEST, self.logger)
        unfilt = [
            await self._edge_word("CHK-SMC-ROUTE", base, MARK_UNFILT[0]),
            await self._edge_word("CHK-SMC-ROUTE", last, MARK_UNFILT[1]),
        ]
        deny = await self._smu_read(expect_error=True)

        # Static-row leg: one word above the aperture top. Its response is not
        # stated, so it is logged; a missing response fails the check.
        m = self._mark()
        try:
            rd = await self._lsu(SepAxiOp.READ, above, ungraded=True)
            wr_m = self._mark()
            wr = await self._lsu(SepAxiOp.WRITE, above, data=MARK_ABOVE, ungraded=True)
        except Exception as exc:
            raise AssertionError(
                f"CHK-SMC-STATIC-ROW FAIL: above=0x{above:08x}: no response within the bound ({exc})"
            ) from exc
        close_graded_window(self.logger)
        above_rd = {
            "smc": self.taps["PR-SMC"].count(m["PR-SMC"], "ar"),
            "out": self.taps["PR-OUT"].count(m["PR-OUT"], "ar"),
            "resp": rd.resp_code,
        }
        above_wr = {
            "smc": self.taps["PR-SMC"].count(wr_m["PR-SMC"], "aw"),
            "out": self.taps["PR-OUT"].count(wr_m["PR-OUT"], "aw"),
            "resp": wr.resp_code,
        }

        # CHK-SMC-ROUTE grading.
        assert control_out >= 1 and control_smc == 0, (
            f"CHK-SMC-ROUTE FAIL: control 0x{SMU_PROBE:08x} out_ar={control_out} "
            f"smc={control_smc}; the control must reach PR-OUT and not PR-SMC"
        )
        for leg, cells in (("filtered", route), ("unfiltered", unfilt)):
            for c in cells:
                ok = c["smc_aw"] == 1 and c["smc_ar"] == 1 and c["out_aw"] == 0 and c["out_ar"] == 0
                assert ok, (
                    f"CHK-SMC-ROUTE FAIL: leg={leg} addr=0x{c['addr']:08x} smc_aw={c['smc_aw']} "
                    f"smc_ar={c['smc_ar']} out_aw={c['out_aw']} out_ar={c['out_ar']}; expected one "
                    "AW and one AR on PR-SMC and none on PR-OUT"
                )
        assert deny["resp"] == RESP_DECERR and deny["out_ar"] == 0, (
            f"CHK-SMC-ROUTE FAIL: SMU-window read 0x{SMU_PROBE:08x} with every outbound entry "
            f"disabled resp={RESP_NAME[deny['resp']]} out_ar={deny['out_ar']}; expected DECERR "
            "with PR-OUT silent"
        )
        for c, u in zip(route, unfilt):
            self.logger.info(
                "CHK-SMC-ROUTE PASS: addr=0x%08X smc_aw=%d smc_ar=%d out_seen=%d control_out=%d "
                "control_smc=%d rdata=0x%08X wr=0x%08X unfilt_smc=%d unfilt_rdata=0x%08X "
                "deny_resp=%s deny_out=%d fuse_done=1",
                c["addr"], c["smc_aw"], c["smc_ar"], c["out_aw"] + c["out_ar"], control_out,
                control_smc, c["rdata"], c["wr"], u["smc_aw"] + u["smc_ar"], u["rdata"],
                RESP_NAME[deny["resp"]], deny["out_ar"],
            )

        control_smc_seen = sum(c["smc_aw"] + c["smc_ar"] for c in route + unfilt)
        for d, cell in (("R", above_rd), ("W", above_wr)):
            assert cell["smc"] == 0, (
                f"CHK-SMC-STATIC-ROW FAIL: above=0x{above:08x} dir={d} smc_seen={cell['smc']}; "
                "only the supplied aperture may reach the SMC port"
            )
            assert control_smc_seen > 0, "CHK-SMC-STATIC-ROW FAIL: the aperture control drove no PR-SMC"
            self.logger.info(
                "CHK-SMC-STATIC-ROW PASS: above=0x%08X dir=%s smc_seen=0 out_seen=%d resp=%s "
                "control_smc=%d",
                above, d, cell["out"], RESP_NAME[cell["resp"]], control_smc_seen,
            )

    async def _config_b(self, base: int) -> None:
        last = base + SMC_SIZE - 4
        await self._program_pair(SMU_BASE, SMU_LAST)

        open_graded_window(TEST, self.logger)
        cells = [
            await self._edge_word("CHK-SMC-FIRST-MATCH", base, MARK_FIRST[0]),
            await self._edge_word("CHK-SMC-FIRST-MATCH", last, MARK_FIRST[1]),
        ]
        ctl = await self._smu_read(expect_error=False)
        close_graded_window(self.logger)

        for c in cells:
            ok = c["smc_aw"] == 1 and c["smc_ar"] == 1 and c["out_aw"] == 0 and c["out_ar"] == 0
            assert ok, (
                f"CHK-SMC-FIRST-MATCH FAIL: addr=0x{c['addr']:08x} smc_aw={c['smc_aw']} "
                f"smc_ar={c['smc_ar']} out_aw={c['out_aw']} out_ar={c['out_ar']}; the SMC "
                "aperture inside the SMU window must take the SMC port"
            )
        control_smc = ctl["smc_ar"] + ctl["smc_aw"]
        assert ctl["resp"] == RESP_OKAY and ctl["out_ar"] >= 1 and control_smc == 0, (
            f"CHK-SMC-FIRST-MATCH FAIL: control 0x{SMU_PROBE:08x} resp={RESP_NAME[ctl['resp']]} "
            f"out_ar={ctl['out_ar']} smc={control_smc}; expected OKAY on PR-OUT only"
        )
        self.logger.info(
            "CHK-SMC-FIRST-MATCH PASS: smc_base=0x%08X smu_base=0x%08X smc_seen=%d out_seen=0 "
            "control_out=%d control_smc=0 rdata=%s fuse_done=1",
            base, self.smu_base, sum(c["smc_aw"] + c["smc_ar"] for c in cells), ctl["out_ar"],
            ",".join(f"0x{c['rdata']:08X}" for c in cells),
        )
        for idx in (0, 1):
            await self.outf.set_enabled(idx, False)

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        cfg = rng.choice(("A", "B"))
        base = CFG[cfg]
        self.required_evidence = (
            ("CHK-SMC-ROUTE", "CHK-SMC-STATIC-ROW") if cfg == "A" else ("CHK-SMC-FIRST-MATCH",)
        )
        self.logger.info("CFG-SMC cfg=%s base=0x%08X size=0x%08X", cfg, base, SMC_SIZE)
        drive_bh_smc(base, SMC_SIZE)
        close_graded_window()

        await self.bring_up_no_cpu()
        self.csr = _Csr(self)
        self.outf = SepFilterBank(self, "out")
        self.taps = start_taps("PR-SMC", "PR-OUT")

        feat = await self.csr._rd(LCC_FEAT_CTRL) | (await self.csr._rd(LCC_FEAT_CTRL + 4) << 32)
        self.smu_base = await self.csr._rd(SEP_CPU_CTRL.addr("SMU_GLOBAL_BASE_ADDR"))
        smu_size = await self.csr._rd(SEP_CPU_CTRL.addr("SMU_REGION_SIZE"))
        self.logger.info(
            "BRINGUP LOG: feat_ctrl=0x%016x smu_base=0x%08x smu_size=0x%08x fcov=%d",
            feat, self.smu_base, smu_size, int(fcov_present()),
        )
        # Configuration B places the SMC aperture inside the SMU window, so the
        # window must sit at its RDL reset aperture.
        lo32 = 0xFFFF_FFFF
        smu_ok = (self.smu_base & lo32) == (SMU_BASE & lo32) and (smu_size & lo32) == (
            SMU_SIZE & lo32
        )
        inside = SMU_BASE <= CFG["B"] and CFG["B"] + SMC_SIZE - 1 <= SMU_LAST
        line = (
            f"smu_base=0x{self.smu_base:08x} smu_size=0x{smu_size:08x} "
            f"rdl_base=0x{SMU_BASE:08x} rdl_size=0x{SMU_SIZE:08x} cfg_b_inside={int(inside)}"
        )
        assert smu_ok and inside, f"CTL-SMC-SMU-RESET FAIL: {line}"
        self.logger.info("CTL-SMC-SMU-RESET LOG: %s", line)
        assert self.taps["PR-SMC"].count() == 0, "SMC request before smc_fuse_sense_done read 1"
        await self._wait_smc_fuse_done()

        if cfg == "A":
            await self._config_a(base)
        else:
            await self._config_b(base)

        close_graded_window(self.logger)
        await stop_taps(self.taps)
