# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Without Adams Bridge, the ABR aperture and the KM ABR key bus answer DECERR.

RAND-NONE. no_cpu, ``+skip_fuse_sense``: no check reads fuse data. Runs only
on the ``lsu_stub_abr_absent`` model, the ``lsu_stub_all_live`` model built
without ``SEP_ABR_EN``.

Contract (``doc/integrator/src/defines.adoc``, Adams Bridge defines): without
``SEP_ABR_EN``, ``sep_crypto`` terminates the ABR AXI aperture and the Key
Manager's ABR key bus with DECERR subordinates.

Host side, on the CPU-LSU master:

* CHK-ABR-ABSENT-OPEN     the ABR reset is released, the host ABR path is
                          not isolated during the host legs, and the KM ABR
                          path is not isolated before the KM legs, so a
                          DECERR below is not the isolation answer.
* CHK-ABR-ABSENT-CONTROL  an HMAC register read on the same crypto
                          interconnect answers OKAY.
* CHK-ABR-ABSENT-HOST-RD  a read of ``MLDSA_NAME`` answers DECERR.
* CHK-ABR-ABSENT-HOST-WR  a write of ``MLDSA_CTRL`` answers DECERR.

Key Manager side, from the KM image ``km_rom_abr_absent.parhex``. The ABR
key bus is private to the KM, so only the KM CPU can reach it. The image
reports the IRQ_STATUS AXI error bits each access set:

* CHK-KM-ABR-ABSENT-PRECOND  every leg started with both error bits clear.
* CHK-KM-ABR-ABSENT-CONTROL  a store to the HMAC wrapper key aperture sets
                             neither bit.
* CHK-KM-ABR-ABSENT-WR       a store to the ABR wrapper key aperture sets
                             AXI_DECERR and not AXI_SLVERR.
* CHK-KM-ABR-ABSENT-RD       a load from the same address does the same.

The image also loads the first address after the generated KMCSR block
(``KEY_MANAGER_KMCSR_BASE_ADDR + KEY_MANAGER_KMCSR_SIZE``). No specification
states what that address answers, so the test logs the error bits and data
and grades nothing on them.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import ABR_CTRL, ABR_NAME0
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import HMAC_STATUS
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

RESP_OKAY = 0
RESP_DECERR = 3
RESULT_MAGIC = 0xB3
# 2-bit code the image reports per leg: bit 0 AXI_SLVERR, bit 1 AXI_DECERR.
CODE_CLEAN = 0
CODE_DECERR = 2
CODE_NAME = {0: "none", 1: "AXI_SLVERR", 2: "AXI_DECERR", 3: "AXI_SLVERR|AXI_DECERR"}

_MAX_KM_CYCLES = 60_000
_MAX_OPEN_CYCLES = 2_000


@pyuvm.test()
class sep_abr_absent_decerr_test(sep_base_test):
    """Host and KM accesses to the compiled-out Adams Bridge answer DECERR."""

    required_evidence = (
        "CHK-ABR-ABSENT-OPEN",
        "CHK-ABR-ABSENT-CONTROL",
        "CHK-ABR-ABSENT-HOST-RD",
        "CHK-ABR-ABSENT-HOST-WR",
        "CHK-KM-ABR-ABSENT-PRECOND",
        "CHK-KM-ABR-ABSENT-CONTROL",
        "CHK-KM-ABR-ABSENT-WR",
        "CHK-KM-ABR-ABSENT-RD",
    )

    async def _post_mbox(self, tag: str, word: int) -> None:
        """One inbound mailbox word: separator then data, as the KM images expect."""
        for name, offset, data in (
            ("sep", KM_MBOX_WRITE_SEPARATOR, 1),
            ("data", KM_MBOX_WRITE_DATA, word),
        ):
            seq = SepAxiAccessSeq(
                f"abr_absent_{tag}_{name}",
                op=SepAxiOp.WRITE,
                addr=KM_MBOX_BASE + offset,
                wdata=data,
                size=2,
            )
            await self.start_seq(seq)
            assert seq.resp_ok, f"KM mailbox {name} write not OKAY for phase {tag}"

    async def _await_phase(self, phase: int) -> int:
        """Poll KM SRAM word0 until the image publishes this phase marker."""
        dut = cocotb.top
        word = 0
        polled = 0
        for polled in range(1, _MAX_KM_CYCLES + 1):
            await RisingEdge(dut.clk_i)
            # The word can be unknown before the image's first store; the poll
            # tolerates that, and the returned word is re-read as fully known.
            word = self.rd(dut.km_sram_word0_o, allow_unknown=True)
            if (word >> 24) == RESULT_MAGIC and (word & 0xF) == phase:
                return self.rd(dut.km_sram_word0_o)
        raise AssertionError(
            f"KM image liveness FAIL: KM SRAM word0=0x{word:08x} after {polled} cycles "
            f"(phase {phase} never published)"
        )

    async def _host(self, name: str, op: SepAxiOp, addr: int) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(name, op=op, addr=addr, wdata=0, size=2, expect_error=True)
        self.env.axi_monitor.arm_expected_decerr(1)
        await self.start_seq(seq)
        if seq.resp_code != RESP_DECERR:
            self.env.axi_monitor.release_expected_decerr(1)
        return seq

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        gated = self.rd_known(dut.abr_gated_rst_n_probe_o)
        host_iso = self.rd_known(dut.abr_host_isolated_probe_o)
        assert (gated, host_iso) == (1, 0), (
            f"CHK-ABR-ABSENT-OPEN FAIL: abr_gated_rst_n={gated} host_isolated={host_iso}, "
            "want 1/0 before the host legs"
        )

        ctl = SepAxiAccessSeq("abr_absent_hmac_status", op=SepAxiOp.READ, addr=HMAC_STATUS, size=2)
        await self.start_seq(ctl)
        assert ctl.resp_code == RESP_OKAY, (
            f"CHK-ABR-ABSENT-CONTROL FAIL: HMAC STATUS @0x{HMAC_STATUS:08x} "
            f"resp={ctl.resp_code}, want OKAY"
        )
        self.logger.info(
            "CHK-ABR-ABSENT-CONTROL PASS: HMAC STATUS @0x%08x answered OKAY on the crypto "
            "interconnect",
            HMAC_STATUS,
        )

        rd = await self._host("abr_absent_name_rd", SepAxiOp.READ, ABR_NAME0)
        assert rd.resp_code == RESP_DECERR and not rd.timed_out, (
            f"CHK-ABR-ABSENT-HOST-RD FAIL: MLDSA_NAME @0x{ABR_NAME0:08x} "
            f"resp={rd.resp_code} timed_out={int(rd.timed_out)}, want DECERR"
        )
        self.logger.info(
            "CHK-ABR-ABSENT-HOST-RD PASS: read of MLDSA_NAME @0x%08x answered DECERR", ABR_NAME0
        )
        wr = await self._host("abr_absent_ctrl_wr", SepAxiOp.WRITE, ABR_CTRL)
        assert wr.resp_code == RESP_DECERR and not wr.timed_out, (
            f"CHK-ABR-ABSENT-HOST-WR FAIL: MLDSA_CTRL @0x{ABR_CTRL:08x} "
            f"resp={wr.resp_code} timed_out={int(wr.timed_out)}, want DECERR"
        )
        self.logger.info(
            "CHK-ABR-ABSENT-HOST-WR PASS: write of MLDSA_CTRL @0x%08x answered DECERR", ABR_CTRL
        )

        # The KM ABR path is isolated while the KM is in reset, so it opens only
        # after the KM release.
        await self.start_seq(sep_km_release_seq("abr_absent_km_release"))
        km_iso = 1
        for _ in range(_MAX_OPEN_CYCLES):
            await RisingEdge(dut.clk_i)
            km_iso = self.rd_known(dut.abr_km_isolated_probe_o)
            if km_iso == 0:
                break
        gated = self.rd_known(dut.abr_gated_rst_n_probe_o)
        host_iso = self.rd_known(dut.abr_host_isolated_probe_o)
        assert (gated, host_iso, km_iso) == (1, 0, 0), (
            f"CHK-ABR-ABSENT-OPEN FAIL: after the KM release abr_gated_rst_n={gated} "
            f"host_isolated={host_iso} km_isolated={km_iso}, want 1/0/0"
        )
        self.logger.info(
            "CHK-ABR-ABSENT-OPEN PASS: ABR reset released; the host ABR path was not "
            "isolated during the host legs, and the KM ABR path is not isolated before "
            "the KM legs"
        )
        await self._post_mbox("go", 1)
        word = await self._await_phase(1)
        payload = (word >> 4) & 0xFFFFF
        codes = [(payload >> (2 * leg)) & 0x3 for leg in range(4)]
        precond = (payload >> 8) & 0x1
        self.logger.info(
            "KM image codes: hmac_wr=%s abr_wr=%s abr_rd=%s kmcsr_past_end_rd=%s precond=%d "
            "(word0=0x%08x)",
            *(CODE_NAME[c] for c in codes),
            precond,
            word,
        )

        assert precond == 1, (
            f"CHK-KM-ABR-ABSENT-PRECOND FAIL: word0=0x{word:08x}, a leg started with an "
            "AXI error bit already set"
        )
        self.logger.info(
            "CHK-KM-ABR-ABSENT-PRECOND PASS: every leg began with both AXI error bits clear"
        )
        assert codes[0] == CODE_CLEAN, (
            f"CHK-KM-ABR-ABSENT-CONTROL FAIL: HMAC key store set {CODE_NAME[codes[0]]}"
        )
        self.logger.info(
            "CHK-KM-ABR-ABSENT-CONTROL PASS: KM store to the HMAC wrapper key aperture set "
            "no AXI error bit"
        )
        assert codes[1] == CODE_DECERR, (
            f"CHK-KM-ABR-ABSENT-WR FAIL: ABR key store set {CODE_NAME[codes[1]]}, "
            "want AXI_DECERR only"
        )
        self.logger.info(
            "CHK-KM-ABR-ABSENT-WR PASS: KM store to the ABR wrapper key aperture set "
            "AXI_DECERR and not AXI_SLVERR"
        )
        assert codes[2] == CODE_DECERR, (
            f"CHK-KM-ABR-ABSENT-RD FAIL: ABR key load set {CODE_NAME[codes[2]]}, "
            "want AXI_DECERR only"
        )
        self.logger.info(
            "CHK-KM-ABR-ABSENT-RD PASS: KM load from the ABR wrapper key aperture set "
            "AXI_DECERR and not AXI_SLVERR"
        )

        await self._post_mbox("lo", 2)
        lo = (await self._await_phase(2) >> 4) & 0xFFFF
        await self._post_mbox("hi", 3)
        hi = (await self._await_phase(3) >> 4) & 0xFFFF
        self.logger.info(
            "KMCSR extent observation (not graded): KM load of KMCSR base + generated "
            "size set %s, data 0x%08x",
            CODE_NAME[codes[3]],
            (hi << 16) | lo,
        )
