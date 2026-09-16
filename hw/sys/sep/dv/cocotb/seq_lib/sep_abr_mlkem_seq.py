# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-KEM-1024 driver (sep_abr_mlkem_kat_test).

ML-KEM has its own register block beside ML-DSA in the Caliptra ``abr_reg.rdl``:
a separate ``MLKEM_CTRL`` / ``MLKEM_STATUS`` pair and its own key, ciphertext
and shared-key windows. Offsets come from that RDL by symbol, the same way
``sep_abr_keygen_seq`` resolves the ML-DSA ones.

Two properties of this block shape the driver, and both are false-pass hazards:

* ``MLKEM_CTRL`` is software-writable only while ``MLKEM_STATUS.READY`` is set
  (``swwe = abr_ready`` in the RDL). A command written to a busy engine is
  dropped silently, so every command here waits for READY first and a caller
  that skips it would issue nothing and still see the previous VALID.
* The ek / dk / ciphertext read ports are gated on the engine's valid register,
  so they read back as zero before a command completes. A compare against zero,
  or a read-back-what-was-written check on those windows, proves nothing.
"""

from __future__ import annotations

from env.sep_spec_tables import abr_off, mldsa_name_words, window

from seq_lib.sep_abr_keygen_seq import SepAbr

ABR_BASE = window("ABR").base

MLKEM_NAME0 = ABR_BASE + abr_off("MLKEM_NAME")
MLKEM_NAME1 = MLKEM_NAME0 + 4
MLKEM_CTRL = ABR_BASE + abr_off("MLKEM_CTRL")
MLKEM_STATUS = ABR_BASE + abr_off("MLKEM_STATUS")
MLKEM_SEED_D = ABR_BASE + abr_off("MLKEM_SEED_D")
MLKEM_SEED_Z = ABR_BASE + abr_off("MLKEM_SEED_Z")
MLKEM_SHARED_KEY = ABR_BASE + abr_off("MLKEM_SHARED_KEY")
MLKEM_MSG = ABR_BASE + abr_off("MLKEM_MSG")
MLKEM_DECAPS_KEY = ABR_BASE + abr_off("MLKEM_DECAPS_KEY")
MLKEM_ENCAPS_KEY = ABR_BASE + abr_off("MLKEM_ENCAPS_KEY")
MLKEM_CIPHERTEXT = ABR_BASE + abr_off("MLKEM_CIPHERTEXT")

# MLKEM_CTRL.CTRL, the 3-bit command field.
KEM_CMD_NONE = 0x0
KEM_CMD_KEYGEN = 0x1
KEM_CMD_ENCAPS = 0x2
KEM_CMD_DECAPS = 0x3
KEM_CMD_KEYGEN_DECAPS = 0x4
KEM_CTRL_ZEROIZE = 1 << 3

# MLKEM_STATUS
KEM_ST_READY = 1 << 0
KEM_ST_VALID = 1 << 1
KEM_ST_ERROR = 1 << 2

# ML-KEM-1024 window sizes, in 32-bit words.
KEM_SEED_WORDS = 8
KEM_MSG_WORDS = 8
KEM_K_WORDS = 8
KEM_EK_WORDS = 392
KEM_DK_WORDS = 792
KEM_CT_WORDS = 392

# Identity words. The Caliptra NAME packing is the same half-word swap for
# every core in this block, so the ML-DSA helper derives the ML-KEM pair from
# its label rather than the value being copied in.
KEM_NAME0_EXP, KEM_NAME1_EXP = mldsa_name_words("KEM-1024")


class SepAbrMlkem(SepAbr):
    """ML-KEM view of the same 32-bit ABR aperture the ML-DSA driver uses."""

    _DRIVER_TAG = "ABR-KEM"


def _selftest() -> None:
    # Pinned against the generated decoder in the vendored abr_reg.sv, so a bad
    # RDL resolution fails at import rather than as a wrong-address access in
    # the middle of a simulation.
    assert ABR_BASE == 0x1094_0000
    assert MLKEM_NAME0 - ABR_BASE == 0x9000
    assert MLKEM_CTRL - ABR_BASE == 0x9010
    assert MLKEM_STATUS - ABR_BASE == 0x9014
    assert MLKEM_SEED_D - ABR_BASE == 0x9018
    assert MLKEM_SEED_Z - ABR_BASE == 0x9038
    assert MLKEM_SHARED_KEY - ABR_BASE == 0x9058
    assert MLKEM_MSG - ABR_BASE == 0x9080
    assert MLKEM_DECAPS_KEY - ABR_BASE == 0xA000
    assert MLKEM_ENCAPS_KEY - ABR_BASE == 0xB000
    assert MLKEM_CIPHERTEXT - ABR_BASE == 0xB800
    # The three large windows a command touches must not overlap each other.
    assert MLKEM_DECAPS_KEY + 4 * KEM_DK_WORDS <= MLKEM_ENCAPS_KEY
    assert MLKEM_ENCAPS_KEY + 4 * KEM_EK_WORDS <= MLKEM_CIPHERTEXT
    # And the whole ML-KEM aperture must stay inside the ABR decode window.
    assert MLKEM_CIPHERTEXT + 4 * KEM_CT_WORDS <= window("ABR").end
    # abr_params_pkg MLKEM_CORE_NAME is 64'h32343130_4D2D4B45, low word first.
    assert KEM_NAME0_EXP == 0x4D2D4B45
    assert KEM_NAME1_EXP == 0x32343130


_selftest()
