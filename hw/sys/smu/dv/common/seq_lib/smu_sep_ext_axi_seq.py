# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ext_in-driven SEP + SMC routing test under the OSS SMU wrapper.

This is the three-party test the sys-inbound path exists for. Two real firmware
images run against an external AXI master that this sequence plays:

  * SEP: hw/sys/sep/dv/fw/tests/sep_smu_ext_axi
  * SMC: hw/sys/smc/dv/fw/tests/smu_sep_ext_axi
  * ext_in: this sequence, on the flat ext_in_* pins that tb_wrapper_top.sv
    exposes for cocotbext.axi.

Protocol, and every address, comes from the firmwares' own shared header
hw/sys/sep/dv/fw/tests/common/smu_sep_ext_axi_protocol.h -- nothing here is
invented, and the globals are the local addresses seen through each subsystem's
aperture (SEP base 0x0400_0000, SMC base 0x0200_0000).

Ordering is carried by the handshake, not by delays. The master writes GO only
after BOTH firmwares have published READY, which is also the point at which
their apertures and inbound filter windows are known to be programmed -- so no
ext_in access is ever made against a route that does not yet exist. ROUTE_DONE
is written only after all four legal legs plus the DECERR leg and its recovery
have been proven, so a firmware that sees ROUTE_DONE knows the routing worked.

The verdict for the SEP half is its own terminal loop, classified by PC like the
rest of the real-firmware suite. The SMC half publishes PASS to its scratch10,
which this master reads back through the same aperture it used throughout.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from ocah_axi_vip import OcahAxiMasterDriver

from seq_lib.sep_fw_common import addr_of, load_syms
from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq
from seq_lib.smc_cpu_revector import revector_smc_cores
from seq_lib.wrapper_jtag import make_wrapper_ptap

# --- protocol constants (smu_sep_ext_axi_protocol.h) -------------------------
SMC_READY = 0x1605_0001
SMC_GO = 0x1606_0001
SEP_READY = 0x1605_0002
SEP_GO = 0x1606_0002
ROUTE_DONE_SMC = 0x160D_0001
ROUTE_DONE_SEP = 0x160D_0002
SMC_PASS = 0x160C_0001
SEP_PASS = 0x160A_0001

SMC_SCRATCH8_DATA = 0x1122_3344
SEP_COLD0_DATA = 0x5566_7788

# Globals: SMC local 0xC00xxxxx via base 0x0200_0000, SEP local 0x108xxxxx via
# base 0x0400_0000.
SMC_SCRATCH6_G = 0x0203_90B0  # SMC_READY       (SMC   -> ext_in)
SMC_SCRATCH7_G = 0x0203_90B8  # SMC_GO          (ext_in -> SMC)
SMC_SCRATCH8_G = 0x0203_90C0  # route data
SMC_SCRATCH9_G = 0x0203_90C8  # ROUTE_DONE_SMC  (ext_in -> SMC)
SMC_SCRATCH10_G = 0x0203_90D0  # SMC_PASS        (SMC   -> ext_in)

SEP_COLD0_G = 0x1480_2000  # route data
SEP_COLD4_G = 0x1480_2020  # SEP_READY       (SEP   -> ext_in)
SEP_COLD5_G = 0x1480_2028  # SEP_GO          (ext_in -> SEP)
SEP_COLD6_G = 0x1480_2030  # SEP_PASS        (SEP   -> ext_in)
SEP_COLD7_G = 0x1480_2038  # ROUTE_DONE_SEP  (ext_in -> SEP)

# Outside BOTH apertures: the crossbar must answer with an error and the master
# must stay usable afterwards.
DECERR_ADDR = 0x8000_2000

AXI_RESP_OKAY = 0

# EXTAXI_SMC_ENTRY, where the SMC cores are re-vectored to start the scratch-RAM
# half. Taken from the built image's symbol table rather than the literal the
# protocol header carries, which that header itself marks "RECONCILE vs built
# image": a relink that moves the entry has to fail here rather than drop the
# cores into the middle of an instruction.
SMC_ENTRY_SYM = "smu_sep_ext_axi_smc_entry"


class SmuSepExtAxiSeq(SepTerminalLoopSeq):
    NAME = "sep_ext_axi"
    PASS_SYM = "smu_sep_ext_axi_sep_pass_loop"
    FAIL_SYMS = {"sep": "smu_sep_ext_axi_sep_fail_loop"}
    SYM_DEFAULT = "sep_smu_ext_axi.tcm.sym"
    MAX_CYCLES_ENV = "SMU_SEP_EXT_AXI_MAX_CYCLES"
    # Three parties have to reach a barrier before any routing happens, and both
    # firmwares poll with their own bounded limits; give the whole handshake room.
    MAX_CYCLES_DEFAULT = 800_000
    EVIDENCE = ("SEP_REAL_FW_EXT_AXI_OK", "SMU_EXT_IN_ROUTING_OK")

    #: Bound on any single ext_in poll, in clk_smu cycles.
    POLL_CYCLES = 200_000

    def __init__(self, test) -> None:
        super().__init__(test)
        self.master: OcahAxiMasterDriver | None = None
        self.stage = "not started"
        self.error: str | None = None
        self.decerr_resp: int | None = None
        self.smc_pass_word: int | None = None

    # --- ext_in primitives --------------------------------------------------
    async def _wr32(self, addr: int, value: int) -> int:
        ev = self.master.init_write(addr, value.to_bytes(4, "little"), size=2)
        await ev.wait()
        return int(ev.data.resp)

    async def _rd32(self, addr: int) -> tuple[int, int]:
        ev = self.master.init_read(addr, 4, size=2)
        await ev.wait()
        return int.from_bytes(ev.data.data[:4], "little"), int(ev.data.resp)

    async def _wr32_ok(self, addr: int, value: int, what: str) -> None:
        resp = await self._wr32(addr, value)
        assert resp == AXI_RESP_OKAY, (
            f"{what}: ext_in write of 0x{value:08x} to 0x{addr:08x} answered "
            f"resp={resp} (expected OKAY); the aperture or inbound filter for "
            "that target is not open"
        )

    async def _await_word(self, addr: int, expect: int, what: str) -> None:
        """Poll a target until it reads `expect`, or fail naming what it held."""
        last = None
        for _ in range(self.POLL_CYCLES // 64):
            word, resp = await self._rd32(addr)
            if resp == AXI_RESP_OKAY and word == expect:
                return
            last = (word, resp)
        got = f"0x{last[0]:08x} resp={last[1]}" if last else "no completed read"
        raise AssertionError(
            f"{what}: 0x{addr:08x} never reached 0x{expect:08x} within "
            f"{self.POLL_CYCLES} cycles (last {got})"
        )

    # --- the ext_in half ----------------------------------------------------
    async def _drive(self) -> None:
        try:
            self.master = OcahAxiMasterDriver.from_prefix(
                cocotb.top,
                "ext_in",
                cocotb.top.clk_smu_i,
                cocotb.top.rst_cold_n_o,
                name="ExtInMaster",
                addr_width=56,
                data_width=64,
            )
            await self.master.wait_for_reset()

            # Barrier. Both READYs first: they are what proves each side has
            # programmed its aperture, so nothing below races the route.
            self.stage = "awaiting SMC_READY"
            await self._await_word(SMC_SCRATCH6_G, SMC_READY, "SMC READY")
            self.stage = "awaiting SEP_READY"
            await self._await_word(SEP_COLD4_G, SEP_READY, "SEP READY")

            self.stage = "releasing GO"
            await self._wr32_ok(SMC_SCRATCH7_G, SMC_GO, "SMC GO")
            await self._wr32_ok(SEP_COLD5_G, SEP_GO, "SEP GO")

            # Four legal legs: a write and a read-back into each subsystem.
            self.stage = "ext_in -> SMC scratch8"
            await self._wr32_ok(SMC_SCRATCH8_G, SMC_SCRATCH8_DATA, "SMC route leg")
            word, resp = await self._rd32(SMC_SCRATCH8_G)
            assert resp == AXI_RESP_OKAY and word == SMC_SCRATCH8_DATA, (
                f"SMC route leg read-back gave 0x{word:08x} resp={resp}, expected "
                f"0x{SMC_SCRATCH8_DATA:08x}"
            )

            self.stage = "ext_in -> SEP cold0"
            await self._wr32_ok(SEP_COLD0_G, SEP_COLD0_DATA, "SEP route leg")
            word, resp = await self._rd32(SEP_COLD0_G)
            assert resp == AXI_RESP_OKAY and word == SEP_COLD0_DATA, (
                f"SEP route leg read-back gave 0x{word:08x} resp={resp}, expected "
                f"0x{SEP_COLD0_DATA:08x}"
            )

            # DECERR leg: an address inside no aperture must be answered with an
            # error rather than swallowed, and the master must still work after.
            self.stage = "DECERR leg"
            self.decerr_resp = await self._wr32(DECERR_ADDR, 0xDEADBEEF)
            assert self.decerr_resp != AXI_RESP_OKAY, (
                f"write to 0x{DECERR_ADDR:08x} (outside every aperture) was "
                "answered OKAY -- an unmapped access must not look successful"
            )

            self.stage = "post-DECERR recovery"
            await self._wr32_ok(SMC_SCRATCH8_G, SMC_SCRATCH8_DATA, "recovery leg")

            # Only now is routing proven, so only now may ROUTE_DONE be published.
            self.stage = "publishing ROUTE_DONE"
            await self._wr32_ok(SMC_SCRATCH9_G, ROUTE_DONE_SMC, "SMC ROUTE_DONE")
            await self._wr32_ok(SEP_COLD7_G, ROUTE_DONE_SEP, "SEP ROUTE_DONE")

            self.stage = "awaiting SMC PASS"
            await self._await_word(SMC_SCRATCH10_G, SMC_PASS, "SMC PASS")
            self.smc_pass_word = SMC_PASS

            self.stage = "awaiting SEP PASS"
            await self._await_word(SEP_COLD6_G, SEP_PASS, "SEP PASS")
            self.stage = "complete"
        except Exception as exc:  # recorded, re-raised by run() with context
            self.error = f"{type(exc).__name__}: {exc}"

    def _smc_liveness(self) -> str:
        """Is the SMC core running the scratch-RAM half at all?

        The ROM marker says the ROM ran; the scratch fetch counter says control
        actually reached the preloaded scratch image after the re-vector.
        Without both, an aperture that never opens is unattributable.
        """
        rd = self._rd(cocotb.top.smc_scratch_read_count_o, "smc_scratch_rd")
        wr = self._rd(cocotb.top.smc_scratch_write_count_dv_o, "smc_scratch_wr")
        mark = self._rd(cocotb.top.smc_scratch_0_o, "smc_scratch_0")
        s6 = self._rd(cocotb.top.smc_scratch_6_o, "smc_scratch_6")
        s7 = self._rd(cocotb.top.smc_scratch_7_o, "smc_scratch_7")
        s10 = self._rd(cocotb.top.smc_scratch_10_o, "smc_scratch_10")
        return (
            f"SMC rom marker=0x{mark:08x} (0xacafaca1 = ROM ran), "
            f"scratch reads={rd} writes={wr}; "
            f"CPU_CTRL scratch6=0x{s6:08x} (READY) scratch7=0x{s7:08x} (GO) "
            f"scratch10=0x{s10:08x} (PASS) -- scratch6 still 0 means the "
            "scratch-RAM image never reached its S3, so the aperture it opens "
            "in S2 was never opened either"
        )

    def _smc_entry(self) -> int:
        """Entry of the preloaded SMC image, taken from its symbol table."""
        sym_path = str(cocotb.plusargs.get("smc_sym", ""))
        assert sym_path, (
            "+smc_sym is required: the cores are re-vectored to "
            f"{SMC_ENTRY_SYM}, and a hardcoded address would silently survive a "
            "relink that moved it"
        )
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        entry = addr_of(syms, SMC_ENTRY_SYM)
        self.log.info("SMC entry %s = 0x%08x (from %s)", SMC_ENTRY_SYM, entry, sym_path)
        return entry

    async def run(self) -> None:
        self.log.info("=" * 70)
        self.log.info("TEST: ext_in-driven SEP+SMC routing in the OSS SMU wrapper")
        self.log.info("=" * 70)
        # Start the SMC half. Its image is in scratch RAM; only a tile reset
        # makes the Rocket frontend latch a new vector, so re-vector rather than
        # hand over from the ROM.
        smc_entry = self._smc_entry()
        jtag = make_wrapper_ptap()
        await self.test.jtag_tap_reset()
        await revector_smc_cores(self.test, jtag, smc_entry)
        # Liveness snapshot after the re-vector: the ROM marker and the scratch
        # counters are the baseline the failure message compares against.
        self.log.info("SMC liveness after re-vector: %s", self._smc_liveness())

        driver = cocotb.start_soon(self._drive())
        try:
            await super().run()
        except AssertionError as exc:
            raise AssertionError(
                f"{exc}; ext_in master stage='{self.stage}'"
                + (f", master error: {self.error}" if self.error else "")
                + f"; {self._smc_liveness()}"
            ) from exc
        finally:
            # Let the master finish its last poll rather than cutting it off,
            # then surface whatever it recorded.
            for _ in range(64):
                if driver.done():
                    break
                await RisingEdge(self.dut.clk_smu_i)

        assert self.error is None, f"ext_in master failed at '{self.stage}': {self.error}"
        assert self.stage == "complete", (
            f"ext_in master did not finish the protocol (stopped at '{self.stage}') "
            "even though the SEP reached its pass loop -- the SEP verdict alone "
            "does not cover the ext_in legs"
        )
        self.log.info(
            "CHK-EXT-IN-ROUTING: PASS (GO after both READYs, four legal legs "
            "read back, unmapped 0x%08x answered resp=%d, recovery leg OK, "
            "ROUTE_DONE published, SMC PASS 0x%08x read back)",
            DECERR_ADDR,
            self.decerr_resp,
            self.smc_pass_word,
        )
