# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMC supplementary fuse window over JTAG2AXI against the sense stream and the image.

Spec: smc.rdl smc_external supplementary region, the fuse slot at 0xC0407000; smu-smc.adoc
(Supplementary Fuse Region: the window serves the supplementary shadow words after the boot
sense); smc_efuse_map.rdl SUPPLEMENTARY_LOCKS at 0xC0007008; interface.adoc fuse_command_resp_t
{data, status, valid}.

The stream is captured at the SMU boundary during the shared bring-up. After the rise of
smc_fuse_sense_done_o, 35 words of the supplementary fuse window (every fourth word plus the first
and last word of each lock region) are read over JTAG2AXI in index order, and each window word is
compared with the stream word of the same index and with the word of that index in the
+smc_efuse_hex image the run loads; all 128 supplementary stream words are compared with the
image. SUPPLEMENTARY_LOCKS reads its image words. The harness map words are the business of
smu_smc_efuse_shadow_map_readback_test and are not read here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_smc_efuse_shadow_map_readback_test_seq import (
    MAP_WORDS,
    STREAM_WORDS,
    SUPPLEMENTARY_WORDS,
    load_efuse_image,
)

SUPP_WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_FUSE_BASE_ADDR")
SUPP_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_WRAP_SMC_EFUSE_MAP_SUPPLEMENTARY_LOCKS_BASE_ADDR")
SUPP_LOCKS_WORD = (SUPP_LOCKS - smc_addr("SMC_TOP_SMC_EFUSE_WRAP_SMC_EFUSE_MAP_BASE_ADDR")) // 4
#: Supplementary words read over JTAG2AXI: every fourth word plus the first and last word of each
#: lock region ("entries are 64, 96 and 128", hw/ip/efuse/doc/architecture.adoc, Supplementary
#: Locks); a JTAG2AXI read is slow, so the window is sampled and the stream carries all 128.
REGION_END = (64, 96, 128)
SAMPLED = tuple(
    sorted(
        set(range(0, SUPPLEMENTARY_WORDS, 4))
        | {end - 1 for end in REGION_END}
        | {end for end in REGION_END[:-1]}
    )
)
J2A_POLL_LIMIT = 128
EXPECTED_WAIT_SITES = 3


def _site(bound: int) -> dict:
    return {"bound": bound, "count": 0, "last": "none", "expired": 0}


class smu_smc_efuse_supplementary_shadow_test_seq:
    """35 sampled supplementary window words over JTAG2AXI against the stream and the image."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.capture = test.efuse_capture
        self.j2a = 0
        self.sites = {**self.capture.sites, "j2a": _site(J2A_POLL_LIMIT)}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, text: str) -> None:
        self._log(f"CELL {name} {text}")

    async def _rd32(self, addr: int, label: str) -> int:
        rec = self.sites["j2a"]
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, int(rdata))

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        cap = self.capture
        image = load_efuse_image()

        self._mark("S1", "SETUP: stream capture, done rise, TAP reset, IDCODE, J2A gate open")
        await self.cfg.reset_done.wait()
        await cap.done.wait()
        if cap.done_expired:
            raise AssertionError(
                f"TIMEOUT S1_done_rise: bound {cap.sites['S1_done_rise']['bound']} clk_smu, "
                f"last {cap.sites['S1_done_rise']['last']}"
            )
        stream = cap.words
        if len(stream) != STREAM_WORDS:
            raise AssertionError(
                f"eFuse response stream has {len(stream)} words, want {STREAM_WORDS}"
            )
        self._cell(
            "stream",
            f"words={len(stream)} supplementary first=0x{stream[MAP_WORDS]:08x} "
            f"last=0x{stream[-1]:08x} status_errors={sum(cap.status_bits)}",
        )
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")

        self._mark(
            "S2", f"read {len(SAMPLED)} supplementary window words and compare with the stream"
        )
        supplementary = range(MAP_WORDS, STREAM_WORDS)
        reads: dict[int, int] = {}
        for word in SAMPLED:
            idx = MAP_WORDS + word
            addr = SUPP_WINDOW + 4 * word
            reads[idx] = await self._rd32(addr, f"supplementary word {word}")
            self._cell(
                "window_word_vs_stream",
                f"addr=0x{addr:08x} idx={idx} read=0x{reads[idx]:08x} "
                f"stream=0x{stream[idx]:08x} image=0x{image[idx]:08x}",
            )
        sampled = [MAP_WORDS + word for word in SAMPLED]
        sb.expect_eq(
            f"the {len(SAMPLED)} sampled supplementary window words at 0x{SUPP_WINDOW:08x} "
            f"(words {list(SAMPLED)}), read over JTAG2AXI, and the stream words of the same "
            "index equal the eFuse image words of that index",
            [(idx, reads[idx], stream[idx]) for idx in sampled],
            [(idx, image[idx], image[idx]) for idx in sampled],
            evidence="SUPP_SHADOW_WINDOW",
        )
        sb.expect_eq(
            f"all {SUPPLEMENTARY_WORDS} supplementary stream words ({supplementary.start}.."
            f"{supplementary.stop - 1}) equal the eFuse image words of the same index",
            [(idx, stream[idx]) for idx in supplementary],
            [(idx, image[idx]) for idx in supplementary],
            evidence="SUPP_SHADOW_WINDOW",
        )

        self._mark("S3", "SUPPLEMENTARY_LOCKS from the harness map")
        lo = await self._rd32(SUPP_LOCKS, "SUPPLEMENTARY_LOCKS low")
        hi = await self._rd32(SUPP_LOCKS + 4, "SUPPLEMENTARY_LOCKS high")
        self._cell("supplementary_locks", f"addr=0x{SUPP_LOCKS:08x} lo=0x{lo:08x} hi=0x{hi:08x}")
        sb.expect_eq(
            "SUPPLEMENTARY_LOCKS is reachable after the boot sense and reads its two image words "
            "(both 0 in the asset: no supplementary lock set)",
            (lo, hi),
            (image[SUPP_LOCKS_WORD], image[SUPP_LOCKS_WORD + 1]),
            evidence="SUPP_LOCKS_WORD",
        )

        self._mark("S4", "TIMEOUT: bounded waits and last state")
        await RisingEdge(dut.clk_smu_i)
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq("bounded wait sites named by the test steps", len(lines), EXPECTED_WAIT_SITES)
