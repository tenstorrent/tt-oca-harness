# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle posture the SMU tests compare against, transcribed from the specification.

Sources, by value:

* Raw 4-bit LC_STATE encodings: ``hw/sys/sep/doc/lifecycle_controller.adoc``,
  section "LC State Machine", table "LC State Name / Encoding".
* The 8-bit word the LCC exports to the SMC and the SMU boundary: the LC_STATE
  field of ``hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl`` --
  "differentially encoded: {~raw[3:0], raw[3:0]}". Before fuse sensing
  completes the OTP controller drives the INVALID encoding (4'b1111), same
  section of the specification.
* Which debug paths are open in each state: the specification's
  "Per-LC-state feature control profile" table, evaluated for the DV eFuse
  images (SIP_DIS = SYS_DIS = 0, SEC_DIS = 0), together with its "Debug and
  Test Port Path Gating" ladder, which places the SMC fabric JTAG2AXI path in
  Case 2 (``SIP_DBG & CHIPLET_DBG``).
* The name of the disable field that gates that path:
  ``hw/sys/dtp/doc/jtag.adoc``, section "Debug Disable"
  (``dbg_disable_i.smc_jtag2axi``).
* The word the boundary carries when no SEP, and therefore no lifecycle
  controller, is instantiated: ``doc/integrator/src/smu.adoc``, SMU port
  table section "Lifecycle State" -- ``lc_state_o`` is the "SEP lifecycle
  state when ``SEP=1``, else ``8'hf0``". ``hw/sys/smc/doc/port_table.adoc``
  states the same word for the receiving port ``lc_state_i`` ("tie to 8'hf0
  if unused (encoded TEST_DEV)") and names the state it encodes, which is the
  TEST_DEV row of the encoding table above.

The packing of ``dbg_disable_t`` into a word is not specified anywhere in the
tree, so this table carries no full-word expectation for a *disabled* posture.
A fully *open* posture is the all-clear word -- no path disabled -- which needs
no packing knowledge, and the SMC fabric JTAG2AXI field is read by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from seq_lib.smu_addr_map import c_header_u32

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEP_ADDR_H = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c" / "sep_addr.h"

#: Raw LC_STATE encodings. RMA_CHIPLET is 4'b011X; the DV image uses 0x6.
LC_RAW: dict[str, int] = {
    "TEST_DEV": 0x0,
    "PROD": 0x1,
    "PROD_END": 0x8,
    "RMA_CHIPLET": 0x6,
}
LC_INVALID_RAW = 0xF


def lc_state_word(raw: int) -> int:
    """The 8-bit differentially encoded LC_STATE word ``{~raw[3:0], raw[3:0]}``."""
    raw &= 0xF
    return ((~raw & 0xF) << 4) | raw


#: What lc_state reads before the shadow registers are loaded.
LC_STATE_PRESENSE = lc_state_word(LC_INVALID_RAW)

#: What lc_state carries at a boundary that has no lifecycle controller behind it.
LC_STATE_NO_LCC = lc_state_word(LC_RAW["TEST_DEV"])


def lc_state_name(raw: int) -> str:
    """Spec name of a raw encoding; raises for an encoding this table does not carry."""
    for name, value in LC_RAW.items():
        if value == (raw & 0xF):
            return name
    raise AssertionError(
        f"raw LC_STATE 0x{raw & 0xF:x} is not a lifecycle state this table carries"
    )


@dataclass(frozen=True)
class DebugPosture:
    """Debug posture of one lifecycle state under blank DIS vectors."""

    state: str
    #: The LC_STATE word the LCC exports for this state.
    lc_state: int
    #: Every debug path open (DBG_1 and DBG_2 both enabled): dbg_disable == 0.
    all_open: bool
    #: The SMC fabric JTAG2AXI path (gating ladder Case 2) is disabled.
    smc_jtag2axi_disabled: bool


def posture(state: str, *, demoted: bool = False) -> DebugPosture:
    """Posture of ``state`` with SIP_DIS = SYS_DIS = SEC_DIS = 0.

    ``demoted`` means firmware has set both DEMOTE_1 and DEMOTE_2. Per the
    feature-control table a demotion acts only in TEST_DEV and PROD; in PROD it
    relaxes each debug group to ``~(SIP_DIS | SYS_DIS)``, which is fully open
    for blank DIS vectors.
    """
    lc_state = lc_state_word(LC_RAW[state])
    if state == "TEST_DEV":
        debug_open = True
    elif state == "PROD":
        debug_open = demoted
    elif state == "PROD_END":
        debug_open = False
    elif state == "RMA_CHIPLET":
        debug_open = True
    else:
        raise AssertionError(f"no posture row for {state}")
    return DebugPosture(
        state=state,
        lc_state=lc_state,
        all_open=debug_open,
        smc_jtag2axi_disabled=not debug_open,
    )


def lc_raw_from_shadow_preload(path: str) -> int:
    """Raw LC_STATE programmed by a SEP eFuse shadow preload image.

    The image is one 32-bit hex word per line in map order; the LC_STATE word
    index comes from the generated SEP address map. The word must itself be a
    valid differential encoding, otherwise the image is malformed and no
    posture can be attributed to it.
    """
    lc_off = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR") - c_header_u32(
        _SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR"
    )
    words = [
        int(line.split("//", 1)[0], 16)
        for line in Path(path).read_text().splitlines()
        if line.split("//", 1)[0].strip()
    ]
    word = words[lc_off // 4] & 0xFF
    raw = word & 0xF
    assert word == lc_state_word(raw), (
        f"shadow preload {path}: LC_STATE word 0x{word:02x} is not a {{~raw, raw}} encoding"
    )
    return raw
