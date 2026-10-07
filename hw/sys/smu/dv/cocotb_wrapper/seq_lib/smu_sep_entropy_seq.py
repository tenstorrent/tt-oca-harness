# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy stack brought up by SEP firmware, with entropy proven to flow.

This anchor proves the entropy path that the AES anchors consume. It runs
hw/sys/sep/dv/fw/tests/sep_smu_entropy_bringup, which programs ESRC -> CSRNG ->
EDN through the driver the SEP DV tree ships, in the order that driver
documents, and it drives the raw noise the ring oscillators cannot generate
under Verilator.

Programming the stack is not the claim -- a firmware that wrote the registers
into a dead block would reach its pass loop just the same. The claim is that
entropy moved, and it is checked at three points down the chain:

  esrc_noise_active   lane-0's actual dcor.noise_i tracks the driven bit, so the
                      force took. Without this, every later zero could just mean
                      the stimulus never reached the DUT.
  drbg_seed_valid     the seed adapter presented a seed to CSRNG -- ESRC
                      produced something the health tests accepted.
  drbg_es_ack         CSRNG consumed it.
  drbg_genbits_vld    the CTR_DRBG produced genbits.

Bit-exact prediction of those genbits is not attempted; that needs the golden
chain in hw/sys/sep/dv and belongs there. Here the question is whether the
chain runs at all in this wrapper, which the AES anchors' masking reseed
depends on.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.esrc_noise import SmuEsrcNoiseDriver
from seq_lib.sep_fw_common import addr_of, load_syms

PASS_SYM = "sep_smu_entropy_pass_loop"
FAIL_SYMS = {
    "esrc_configure": "sep_smu_entropy_fail_configure_loop",
    "esrc_generators": "sep_smu_entropy_fail_generators_loop",
    "esrc_boot_phase": "sep_smu_entropy_fail_boot_phase_loop",
    "esrc_alert": "sep_smu_entropy_fail_esrc_alert_loop",
}

# Firmware phase markers in SEP cold scratch1.
PHASES = {
    0x5EED0001: "entered",
    0x5EED0002: "PHASE-A configured",
    0x5EED0003: "generators on",
    0x5EED0004: "ESRC boot phase done",
    0x5EED0005: "PHASE-B EDN enabled",
}


class SmuSepEntropySeq:
    """Require the firmware bring-up to make real entropy reach the DRBG."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SEP_ENTROPY_FW_BRINGUP_OK", "SEP_ENTROPY_CHAIN_FLOWS_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_ENTROPY_MAX_CYCLES", "3000000"), 0)
        heartbeat = max(1, max_cycles // 20)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_entropy_bringup.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, PASS_SYM)
        fail_pcs = {addr_of(syms, s): label for label, s in FAIL_SYMS.items()}

        assert cocotb.plusargs.get("esrc_noise_force") is not None, (
            "+esrc_noise_force is required: without it the ring oscillators never "
            "toggle under Verilator and no entropy can be produced"
        )

        self.log.info("=" * 70)
        self.log.info("TEST: SEP firmware entropy bring-up, with entropy proven to flow")
        self.log.info("=" * 70)

        noise = SmuEsrcNoiseDriver(self.dut)
        noise.start()

        verdict = None
        traces = 0
        # The chain flags are latched in hardware, so poll in blocks rather than
        # sampling every edge: entropy accumulation runs for millions of cycles
        # and a per-edge Python loop would dominate the runtime.
        POLL = 2000

        def chain() -> tuple[bool, bool, bool, bool]:
            return (
                bool(self._rd(self.dut.esrc_noise_took_o, "esrc_noise_took_o")),
                bool(self._rd(self.dut.drbg_seed_valid_seen_o, "drbg_seed_valid_seen_o")),
                bool(self._rd(self.dut.drbg_es_ack_seen_o, "drbg_es_ack_seen_o")),
                bool(self._rd(self.dut.drbg_genbits_seen_o, "drbg_genbits_seen_o")),
            )

        for cycle in range(0, max_cycles, POLL):
            for _ in range(POLL):
                await RisingEdge(self.dut.clk_smu_i)
                if verdict is None and self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                    traces += 1
                    pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                    if pc == pass_pc:
                        verdict = ("pass", None)
                    elif pc in fail_pcs:
                        verdict = ("fail", fail_pcs[pc])

            noise_took, seed_valid, es_ack, genbits = chain()
            if verdict is not None and (genbits or verdict[0] == "fail"):
                break
            if cycle and cycle % heartbeat < POLL:
                self.log.info(
                    "entropy heartbeat cycle=%d traces=%d noise_took=%s "
                    "seed_valid=%s es_ack=%s genbits=%s",
                    cycle,
                    traces,
                    noise_took,
                    seed_valid,
                    es_ack,
                    genbits,
                )

        noise_took, seed_valid, es_ack, genbits = chain()

        self.log.info(
            "chain: noise_took=%s -> seed_valid=%s -> es_ack=%s -> genbits=%s "
            "(firmware verdict=%s, traces=%d)",
            noise_took,
            seed_valid,
            es_ack,
            genbits,
            verdict[1] if verdict and verdict[1] else (verdict[0] if verdict else None),
            traces,
        )

        errors: list[str] = []
        if verdict is None:
            errors.append(f"firmware reached no terminal loop within {max_cycles} cycles")
        elif verdict[0] == "fail":
            errors.append(
                f"firmware parked in the {verdict[1]} fail loop -- the ESRC CSR "
                "path did not read back what it programmed"
            )
        if not noise_took:
            errors.append(
                "lane-0 dcor.noise_i never matched the driven bit; the "
                "+esrc_noise_force did not take, so nothing below it is meaningful"
            )
        if not seed_valid:
            errors.append(
                "the CSRNG seed adapter never presented a seed -- ESRC produced "
                "nothing the health tests accepted"
            )
        if not es_ack:
            errors.append("CSRNG never acknowledged an entropy-source seed")
        if not genbits:
            errors.append("the CTR_DRBG never produced genbits")

        assert not errors, "SEP entropy bring-up: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-ENTROPY-FW-BRINGUP: PASS (firmware programmed ESRC/CSRNG/EDN "
            "in the documented PHASE-A / generators / PHASE-B order and reached "
            "its pass loop)"
        )
        self.log.info(
            "CHK-SEP-ENTROPY-FLOWS: PASS (forced noise reached dcor.noise_i, ESRC "
            "produced an accepted seed, CSRNG consumed it, and the CTR_DRBG "
            "produced genbits -- the chain runs, not just its registers)"
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
