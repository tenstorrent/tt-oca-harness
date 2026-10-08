# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C-window → fabric decode smoke (real OCA I3C core).

Toggles the I3C CSR clock-gate control, restores it, proves the I3C wrapper CSR
window is decoded by reading HCI_VERSION and comparing it against the reset
declared in the I3C core's SystemRDL source (see below), then enables the core
through ``HC_CONTROL.BUS_ENABLE`` and observes the I3C0 pads while it is enabled
before restoring the register.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _SMC_BASE_CFG_H, I3C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_base_test_seq import smc_base_test_seq
from .smc_i3c_vip_utils import observe_i3c0_external_pull_low

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
# Entry-state precondition for the CLOCK_GATE_CONTROL set/restore claim: the
# generated header declares this field's reset as 0, so the toggle below is
# 0 -> 1 -> 0.
I3C_CG_EN_RESET = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_reset"
)

# --- HCI_VERSION identity and expected value: SystemRDL source, not the DUT ----
#
# Both the register's offset inside the I3C CSR window and its reset value are
# read here from the I3C core's SystemRDL register source
# ``vendor/chipsalliance/i3c-core/upstream/src/rdl/base_registers.rdl`` (reg
# ``HCI_VERSION``; the generated doc ``.../src/rdl/docs/README.md`` tables the
# same reset).
#
# The expected value is therefore independent of the RTL readback mux
# (``I3CCSR.sv``), and the register identity printed in the log derives from the
# same symbols that formed the address: the window base from the generated
# ``smc_addr.h`` plus the HCI_VERSION offset from the RDL
# ([INDEPENDENT-EXPECTED-MODEL], [ADDRESS-FROM-AUTHORITATIVE-MAP]).
_I3C_BASE_RDL = (
    Path(__file__).resolve().parents[6]
    / "vendor"
    / "chipsalliance"
    / "i3c-core"
    / "upstream"
    / "src"
    / "rdl"
    / "base_registers.rdl"
)
_RDL_REG_END_RE = re.compile(r"\}\s*(\w+)\s*@\s*(0x[0-9A-Fa-f]+)\s*;")
_RDL_RESET_RE = re.compile(r"reset\s*=\s*\d+'h([0-9A-Fa-f]+)")


def _i3c_reg_from_rdl(reg_name: str) -> tuple[int, int]:
    """Return ``(offset, reset)`` for ``reg_name`` from ``base_registers.rdl``.

    Raises rather than guessing: if the RDL is restructured or the register is
    renamed, this fails loudly at import instead of silently keeping a stale
    hand-copied literal alive.
    """
    text = _I3C_BASE_RDL.read_text(encoding="utf-8")
    for match in _RDL_REG_END_RE.finditer(text):
        if match.group(1) != reg_name:
            continue
        offset = int(match.group(2), 0)
        body_start = text.rfind("reg {", 0, match.start())
        if body_start < 0:
            break
        resets = _RDL_RESET_RE.findall(text[body_start : match.start()])
        if len(resets) != 1:
            raise RuntimeError(
                f"{reg_name} in {_I3C_BASE_RDL} does not declare exactly one "
                f"field reset (found {len(resets)}); the expected value can no "
                f"longer be derived unambiguously"
            )
        return offset, int(resets[0], 16)
    raise RuntimeError(f"register {reg_name} not found in {_I3C_BASE_RDL}")


_RDL_FIELD_RE = re.compile(
    r"field\s*\{(?P<body>[^{}]*)\}\s*(?P<name>\w+)\s*\[\s*(?P<hi>\d+)\s*:\s*"
    r"(?P<lo>\d+)\s*\]\s*;",
    re.S,
)
_RDL_ANY_RESET_RE = re.compile(r"reset\s*=\s*\d+'([hbd])([0-9A-Fa-f]+)")
_RADIX = {"h": 16, "b": 2, "d": 10}


def _i3c_multifield_reg_from_rdl(reg_name: str) -> tuple[int, int, dict[str, int]]:
    """Return ``(offset, reset_word, {field: bitmask})`` from the vendor RDL.

    Same authority and the same reason as :func:`_i3c_reg_from_rdl`, generalised
    to a register with several fields: every field's declared reset is summed
    into the whole-register reset word and every field name is exported as a
    bitmask, so both the expected entry value and the bit to write come from the
    RDL rather than from a hand-copied literal or an observed readback.
    """
    text = _I3C_BASE_RDL.read_text(encoding="utf-8")
    for match in _RDL_REG_END_RE.finditer(text):
        if match.group(1) != reg_name:
            continue
        offset = int(match.group(2), 0)
        body_start = text.rfind("reg {", 0, match.start())
        if body_start < 0:
            break
        reset_word = 0
        masks: dict[str, int] = {}
        for field in _RDL_FIELD_RE.finditer(text[body_start : match.start()]):
            hi = int(field.group("hi"))
            lo = int(field.group("lo"))
            width_mask = (1 << (hi - lo + 1)) - 1
            masks[field.group("name")] = width_mask << lo
            reset = _RDL_ANY_RESET_RE.search(field.group("body"))
            if reset is None:
                raise RuntimeError(
                    f"{reg_name}.{field.group('name')} in {_I3C_BASE_RDL} "
                    f"declares no reset; the expected entry word cannot be "
                    f"derived"
                )
            value = int(reset.group(2), _RADIX[reset.group(1)])
            reset_word |= (value & width_mask) << lo
        if not masks:
            raise RuntimeError(f"no fields parsed for {reg_name} in {_I3C_BASE_RDL}")
        return offset, reset_word, masks
    raise RuntimeError(f"register {reg_name} not found in {_I3C_BASE_RDL}")


I3C0_CSR_WINDOW = smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0)
HCI_VERSION_OFFSET, I3C_HCI_VERSION_RESET = _i3c_reg_from_rdl("HCI_VERSION")
I3C0_HCI_VERSION = I3C0_CSR_WINDOW + HCI_VERSION_OFFSET

# HC_CONTROL: the register that enables the host controller. Offset, whole-
# register reset word and the BUS_ENABLE bit all come from the same vendor RDL.
# (base_registers.rdl: ``HC_CONTROL @ 0x4``, ``BUS_ENABLE[31:31] sw=rw reset=0``,
# ``MODE_SELECTOR[6:6] reset=1`` -- so the reset word is 0x0000_0040.)
HC_CONTROL_OFFSET, I3C_HC_CONTROL_RESET, _HC_CONTROL_MASKS = _i3c_multifield_reg_from_rdl(
    "HC_CONTROL"
)
I3C0_HC_CONTROL = I3C0_CSR_WINDOW + HC_CONTROL_OFFSET
I3C_HC_CONTROL_BUS_ENABLE = _HC_CONTROL_MASKS["BUS_ENABLE"]
I3C_HC_CONTROL_ENABLED = I3C_HC_CONTROL_RESET | I3C_HC_CONTROL_BUS_ENABLE


class smc_i3c_to_fabric_test_seq(smc_base_test_seq):
    """Exercise I3C clock gate and real HCI_VERSION decode."""

    def __init__(self, name: str = "smc_i3c_to_fabric_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.reads = 0
        self.writes = 0
        self.last_resp_code: int | None = None

    async def _read(
        self,
        name: str,
        addr: int,
        expected: int | None = None,
    ) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.reads += 1
        self.last_resp_code = item.resp_code
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.writes += 1

    async def body(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        # Guarantee the set/restore token below describes a real transition: if
        # I3C_CG_EN were already set, both writes would write the same word and
        # both readbacks would compare against the same value.
        assert not (self.clock_gate_value & I3C_CG_EN), (
            f"CLOCK_GATE_CONTROL @ 0x{CLOCK_GATE_CONTROL:08x} entered this test "
            f"with I3C_CG_EN already set (read 0x{self.clock_gate_value:08x}); "
            f"the generated header declares "
            f"SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__I3C_CG_EN_reset = "
            f"0x{I3C_CG_EN_RESET:x}, so the set-then-restore claim below would "
            f"not describe an observed 0 -> 1 -> 0 toggle"
        )
        enabled = self.clock_gate_value | I3C_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.clock_gate_value)
        await self._read(
            "CLOCK_GATE_CONTROL_RESTORE",
            CLOCK_GATE_CONTROL,
            expected=self.clock_gate_value,
        )
        # Both CLOCK_GATE_CONTROL readbacks above carry an exact ``expected``,
        # so the scoreboard has already failed the run on any mismatch by the
        # time this token is emitted.
        cocotb.log.info(
            "CHK-I3C-CLOCK-GATE-RW: CLOCK_GATE_CONTROL 0x%08x I3C_CG_EN set "
            "readback==0x%08X then restored readback==0x%08X",
            CLOCK_GATE_CONTROL,
            enabled,
            self.clock_gate_value,
        )

        # Real OCA I3C core: window must complete OKAY with HCI_VERSION reset.
        rdata = await self._read("I3C0_HCI_VERSION", I3C0_HCI_VERSION)
        assert self.last_resp_code == 0, (
            f"I3C0_HCI_VERSION @ 0x{I3C0_HCI_VERSION:08x}: expected OKAY, "
            f"got resp={self.last_resp_code}"
        )
        assert (rdata & 0xFFFF_FFFF) == I3C_HCI_VERSION_RESET, (
            f"I3C HCI_VERSION mismatch: got 0x{rdata & 0xFFFF_FFFF:08X}, "
            f"expected 0x{I3C_HCI_VERSION_RESET:08X}"
        )
        # CSR-window decode only: the fabric routes the I3C0 window and the core
        # returns HCI_VERSION; nothing here is a claim about I3C bus protocol
        # behaviour.
        cocotb.log.info(
            "CHK-I3C0-HCI-VERSION: HCI_VERSION @ window 0x%08x + RDL offset "
            "0x%03x = 0x%08x resp=OKAY rdata=0x%08X == 0x%08X "
            "(expected = base_registers.rdl HCI_VERSION.VERSION reset; "
            "CSR-window decode only, no I3C protocol claim)",
            I3C0_CSR_WINDOW,
            HCI_VERSION_OFFSET,
            I3C0_HCI_VERSION,
            rdata & 0xFFFF_FFFF,
            I3C_HCI_VERSION_RESET,
        )

        # --- Enable the real I3C core, observe the pads, restore -------------
        # Pad-level idle-zero compares are unfalsifiable while the core is
        # disabled. This leg enables it through the RDL-declared
        # HC_CONTROL.BUS_ENABLE and holds it enabled across the pad observation,
        # so the helper records the pad state of a running controller. All three
        # expectations are RDL-sourced:
        #   * entry word == the sum of HC_CONTROL's declared field resets
        #     (BUS_ENABLE=0, MODE_SELECTOR=1 -> 0x00000040),
        #   * after the write == that word with BUS_ENABLE set, proving the
        #     sw=rw field is really writable in the real core, and
        #   * after the restore == the declared reset word again.
        await self._read("I3C0_HC_CONTROL", I3C0_HC_CONTROL, expected=I3C_HC_CONTROL_RESET)
        await self._write("I3C0_HC_CONTROL_BUS_ENABLE", I3C0_HC_CONTROL, I3C_HC_CONTROL_ENABLED)
        await self._read(
            "I3C0_HC_CONTROL_BUS_ENABLE",
            I3C0_HC_CONTROL,
            expected=I3C_HC_CONTROL_ENABLED,
        )
        cocotb.log.info(
            "CHK-I3C0-HC-CONTROL-BUS-ENABLE: HC_CONTROL @ window 0x%08x + RDL "
            "offset 0x%03x = 0x%08x read its RDL-declared reset 0x%08X, then "
            "BUS_ENABLE (bm 0x%08X, sw=rw in base_registers.rdl) wrote and read "
            "back 0x%08X: the real I3C core's host-controller enable is "
            "software-writable over the fabric",
            I3C0_CSR_WINDOW,
            HC_CONTROL_OFFSET,
            I3C0_HC_CONTROL,
            I3C_HC_CONTROL_RESET,
            I3C_HC_CONTROL_BUS_ENABLE,
            I3C_HC_CONTROL_ENABLED,
        )

        # Pad observation runs with the core enabled (see the helper's docstring
        # for exactly what it does and does not claim).
        await observe_i3c0_external_pull_low(core_enabled=True)

        await self._write("I3C0_HC_CONTROL_RESTORE", I3C0_HC_CONTROL, I3C_HC_CONTROL_RESET)
        await self._read(
            "I3C0_HC_CONTROL_RESTORE",
            I3C0_HC_CONTROL,
            expected=I3C_HC_CONTROL_RESET,
        )

        # Exact access count of this body. The fail-capable stimulus floor is
        # `min_csr_accesses` at the record_protocol_vip call in
        # tests/smc_i3c_to_fabric_test.py, taken from the scoreboard's own
        # access tally.
        assert (self.reads, self.writes) == (7, 4), (
            f"I3C fabric smoke issued {self.reads} reads / {self.writes} writes, expected 7 / 4"
        )
