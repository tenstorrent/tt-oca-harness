# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pattern walk over the Adams Bridge register groups no test programs.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `abr_reg` holds 283 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`, and the annotated source puts nearly
all of them on the software-write legs (`next_c = (field_storage.X.value &
~decoded_wr_biten) | ...`) of register groups no leaf addresses:
`MLDSA_CTX` (64 words), `MLDSA_MSG` (16), `MLDSA_SIGN_RND` (8),
`MLDSA_MSG_STROBE`, `MLDSA_CTX_CONFIG`, the interrupt block file
`intr_block_rf`, and the key-vault control registers
`kv_mldsa_seed_rd_ctrl`, `kv_mlkem_seed_rd_ctrl`, `kv_mlkem_msg_rd_ctrl` and
`kv_mlkem_sharedkey_wr_ctrl`. The ML-DSA KAT leaves drive the seed, entropy
and external-mu paths; they never touch these.

Stimulus: the shared `WALK_PATTERNS` set -- all-ones, both alternating halves,
then zero -- written to every 32-bit word of each group over the CPU-LSU
master, followed by a read of each group's first word. Addresses come from
`sep_reg_meta.sym` over the generated SystemRDL export, so a register move
cannot leave this sweep on a stale offset.

`MLDSA_CTRL` is not in the walk: a pattern would set its command field and
launch an engine operation from walk data. The key-vault control registers are
walked with bit 0 masked clear, because that bit is the read/write enable
(`ABR_KV_RD_SEED_READ_EN`, `seq_lib/sep_abr_keygen_seq.py:38`) and setting it
with a pattern-derived entry index starts a key-vault transaction this leaf
does not sequence.

These registers are `swwe`-gated on `abr_ready`, which the core drops while an
operation or a key-vault transaction is in flight; a gated write is dropped
silently and still answered OKAY. The walk runs on an idle core so the writes
land. `MLDSA_MSG_STROBE` is the exception: its gate is `stream_msg_rdy`, not
`abr_ready`, so its write leg only commits in streaming mode. It stays in the
walk because the decode in front of it is addressed either way.

Not covered here: the `hwif_in.MLDSA_MSG[*].MSG.next` and
`hwif_in.MLDSA_EXTERNAL_MU[*].next` hardware write-back legs. Those are driven
by the key-vault shim loading message material, not by a register write.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import WALK_PATTERNS, SepCovStim

# Register-array groups: (label, first-word address, word count).
ARRAY_GROUPS = (
    ("MLDSA_SIGN_RND", sym("ABR_MLDSA_SIGN_RND_0__REG_ADDR"), 8),
    ("MLDSA_MSG", sym("ABR_MLDSA_MSG_0__REG_ADDR"), 16),
    ("MLDSA_EXTERNAL_MU", sym("ABR_MLDSA_EXTERNAL_MU_0__REG_ADDR"), 16),
    ("MLDSA_CTX", sym("ABR_MLDSA_CTX_0__REG_ADDR"), 64),
)

# Single-word registers of the ML-DSA block and the interrupt block file.
SINGLE_REGS = (
    ("MLDSA_MSG_STROBE", sym("ABR_MLDSA_MSG_STROBE_REG_ADDR")),
    ("MLDSA_CTX_CONFIG", sym("ABR_MLDSA_CTX_CONFIG_REG_ADDR")),
    ("global_intr_en_r", sym("ABR_INTR_BLOCK_RF_GLOBAL_INTR_EN_R_REG_ADDR")),
    ("error_intr_en_r", sym("ABR_INTR_BLOCK_RF_ERROR_INTR_EN_R_REG_ADDR")),
    ("notif_intr_en_r", sym("ABR_INTR_BLOCK_RF_NOTIF_INTR_EN_R_REG_ADDR")),
    ("error_internal_intr_r", sym("ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_R_REG_ADDR")),
    ("notif_internal_intr_r", sym("ABR_INTR_BLOCK_RF_NOTIF_INTERNAL_INTR_R_REG_ADDR")),
    ("error_intr_trig_r", sym("ABR_INTR_BLOCK_RF_ERROR_INTR_TRIG_R_REG_ADDR")),
    ("notif_intr_trig_r", sym("ABR_INTR_BLOCK_RF_NOTIF_INTR_TRIG_R_REG_ADDR")),
    (
        "error_internal_intr_count_incr_r",
        sym("ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_COUNT_INCR_R_REG_ADDR"),
    ),
    (
        "notif_cmd_done_intr_count_incr_r",
        sym("ABR_INTR_BLOCK_RF_NOTIF_CMD_DONE_INTR_COUNT_INCR_R_REG_ADDR"),
    ),
    ("error_internal_intr_count_r", sym("ABR_INTR_BLOCK_RF_ERROR_INTERNAL_INTR_COUNT_R_REG_ADDR")),
    ("notif_cmd_done_intr_count_r", sym("ABR_INTR_BLOCK_RF_NOTIF_CMD_DONE_INTR_COUNT_R_REG_ADDR")),
)

# Key-vault control registers. Bit 0 of each is the read/write enable and is
# held clear for every pattern.
KV_CTRL_REGS = (
    ("kv_mldsa_seed_rd_ctrl", sym("ABR_KV_MLDSA_SEED_RD_CTRL_REG_ADDR")),
    ("kv_mlkem_seed_rd_ctrl", sym("ABR_KV_MLKEM_SEED_RD_CTRL_REG_ADDR")),
    ("kv_mlkem_msg_rd_ctrl", sym("ABR_KV_MLKEM_MSG_RD_CTRL_REG_ADDR")),
    ("kv_mlkem_sharedkey_wr_ctrl", sym("ABR_KV_MLKEM_SHAREDKEY_WR_CTRL_REG_ADDR")),
)

KV_ENABLE_BIT = 1 << 0


@pyuvm.test()
class sep_cov_abr_reg_walk_test(sep_base_test):
    """Adams Bridge register-group pattern walk. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        words = 0
        for label, base, count in ARRAY_GROUPS:
            for idx in range(count):
                await stim.word_walk(base + 4 * idx)
            words += count
            self.logger.info("cov stimulus: walked %s over %d words", label, count)

        for _label, addr in SINGLE_REGS:
            await stim.word_walk(addr)
            words += 1

        for _label, addr in KV_CTRL_REGS:
            for pattern in WALK_PATTERNS:
                await stim._wr(addr, pattern & ~KV_ENABLE_BIT)
            words += 1

        # One read of each group's first word so the readback mux of every
        # group is addressed as well as its write leg.
        for _, base, _count in ARRAY_GROUPS:
            await stim._rd(base)
        for _, addr in SINGLE_REGS + KV_CTRL_REGS:
            await stim._rd(addr)

        self.logger.info(
            "cov stimulus: ABR register walk drove %d words with %d patterns each",
            words,
            len(WALK_PATTERNS),
        )
