# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run an OTBN program that retires the base-ISA arms no other program uses.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `otbn_decoder` (254 uncovered lines), `otbn_predecode` (167) and
`otbn_alu_bignum` (97) in the merged VCS run
`build/runs/20260919_225443__vcs__all`. Those decoders only light up for
instructions OTBN actually executes, and the two existing OTBN programs
(`seq_lib/sep_otbn_seq.py` OTBN_KEYDUMP_PROG / OTBN_RND_PROG and
`seq_lib/sep_otbn_compute_seq.py` otbn_compute_prog) between them retire only
`lui`, `addi`, `lw`, `sw`, `add`, `xor`, `and`, `csrrs`, `bn.wsrr`, `bn.xor`,
`bn.sid` and `ecall`.

This program adds the rest of the base ISA OTBN accepts:

* `xori` / `ori` / `andi` and `slli` / `srli` / `srai` -- the OP-IMM funct3
  arms at `vendor/lowRISC/opentitan/upstream/hw/ip/otbn/rtl/otbn_decoder.sv:383-406`.
* `sub` / `or` / `sll` / `srl` / `sra` -- the register-register arms at
  otbn_decoder.sv:416-426.
* `beq` and `bne`, each once taken and once not taken -- otbn_decoder.sv:465-472
  and the `ImmBaseBB` selector at :223.
* `jal` and `jalr` as a balanced call/return pair through `x1` --
  otbn_decoder.sv:477-491 and the `ImmBaseBJ` selector at :224.

The instruction words are hand-assembled, as the two existing OTBN programs
in this tree are. Each is annotated with the instruction it encodes.

Frontdoor only: the program is written word by word into the OTBN IMEM
aperture over the CPU-LSU master, started with a CMD.EXECUTE write, and
polled through STATUS. IMEM takes plain 32-bit words -- the SECDED bits are
computed in hardware from the bus data at
`hw/common/axi/axi_lite_to_tlul.sv:270-271`, which is what
`hw/sys/sep/rtl/sep_crypto_otbn_wrapper.sv:54-61` puts in front of OTBN -- so
no host-side integrity work is needed.

Two DMEM operand words are written before the run and five result words are
read after it. Both the operands and the results are logged, never compared:
this leaf does not claim OTBN computed anything. ERR_BITS is read and logged
for the same reason.

OTBN performs a secure wipe out of reset that consumes URND from the EDN, so
the run brings up the real entropy stack first, in the stimulus-only order
`tests/system/sep_cov_entropy_pool_burst_test.py` uses.

Not driven here: the BN.* arithmetic, MAC and vector families
(otbn_decoder.sv:550-638, 791-806 and the `otbn_alu_bignum` operator arms),
which are the larger remaining share. Those need 256-bit operand staging and
encodings that the vendored OTBN assembler should produce rather than a hand
table; see the coverage plan.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_otbn_seq import SepOtbn

# DMEM layout: [0] = a, [4] = b, [8] / [12] / [16] = results. The base is held
# in x6, which the first two instructions build.
DMEM_A = 0x00
DMEM_B = 0x04
DMEM_RESULTS = (0x08, 0x0C, 0x10)

OTBN_BASE_ISA_PROG = (
    0x00000337,  # lui   x6, 0
    0x00030313,  # addi  x6, x6, 0        DMEM base
    0x00032503,  # lw    x10, 0(x6)       a
    0x00432583,  # lw    x11, 4(x6)       b
    0x5A554613,  # xori  x12, x10, 0x5a5
    0x0F066613,  # ori   x12, x12, 0xf0
    0x3FF67613,  # andi  x12, x12, 0x3ff
    0x00751693,  # slli  x13, x10, 7
    0x0036D693,  # srli  x13, x13, 3
    0x4026D693,  # srai  x13, x13, 2
    0x40B50733,  # sub   x14, x10, x11
    0x00C76733,  # or    x14, x14, x12
    0x00B71733,  # sll   x14, x14, x11
    0x00B75733,  # srl   x14, x14, x11
    0x40B75733,  # sra   x14, x14, x11
    0x00D70733,  # add   x14, x14, x13
    0x00E32423,  # sw    x14, 8(x6)
    0x00100893,  # addi  x17, x0, 1       branch predicate
    0x00000793,  # addi  x15, x0, 0
    0x00000463,  # beq   x0, x0, +8       taken
    0x00178793,  # addi  x15, x15, 1      skipped
    0x00088463,  # beq   x17, x0, +8      not taken
    0x00278793,  # addi  x15, x15, 2
    0x00089463,  # bne   x17, x0, +8      taken
    0x00478793,  # addi  x15, x15, 4      skipped
    0x00001463,  # bne   x0, x0, +8       not taken
    0x00878793,  # addi  x15, x15, 8
    0x00F32623,  # sw    x15, 12(x6)
    0x008000EF,  # jal   x1, +8           call, pushes the return address
    0x00C0006F,  # jal   x0, +12          the return lands here
    0x02A00813,  # addi  x16, x0, 42      subroutine body
    0x00008067,  # jalr  x0, 0(x1)        return, pops the call stack
    0x01032823,  # sw    x16, 16(x6)
    0x00000073,  # ecall
)


@pyuvm.test()
class sep_cov_otbn_base_isa_walk_test(sep_base_test):
    """OTBN base-ISA decode walk. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac"))
        noise = self.start_esrc_noise_driver()
        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            otbn = SepOtbn(self)
            # The post-reset secure wipe holds OTBN busy and consumes URND;
            # IMEM writes are rejected until it finishes.
            await otbn.wait_idle("post-wipe", timeout=8_000)

            rng = SepSeededRng(self.random_seed())
            a = rng.getrandbits(32)
            b = rng.getrandbits(32) | 1  # keep the shift amounts off zero
            await otbn.write_dmem(DMEM_A, a)
            await otbn.write_dmem(DMEM_B, b)

            await otbn.load_program(OTBN_BASE_ISA_PROG)
            await otbn.execute()

            err = await otbn.read_errbits()
            results = [await otbn.read_dmem(off) for off in DMEM_RESULTS]
            self.logger.info(
                "cov stimulus: OTBN base-ISA program retired %d instructions "
                "(a=0x%08x b=0x%08x); ERR_BITS=0x%08x results=%s -- logged, not graded",
                len(OTBN_BASE_ISA_PROG),
                a,
                b,
                err,
                " ".join(f"0x{w:08x}" for w in results),
            )
        finally:
            noise.kill()
