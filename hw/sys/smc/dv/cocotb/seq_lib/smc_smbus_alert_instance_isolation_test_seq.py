# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R5_003 ANCHOR: smc_smbus_alert_instance_isolation_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 890c309bea536ec51786567fbbd950887e9fdf997098b896590d0c6b680db254
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R5_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Per-instance SMBUS_EN and LLPBK masking of SMBALERT, I2C_CTRL writes and the wrapper window.

Sources: hw/ip/i2c/regs/i2c_ctrl.rdl (I2C_CTRL array), hw/ip/i2c/regs/i2c.rdl (SMBUS_STATUS,
CTRL.LLPBK, SMBUS_CTRL), hw/ip/i2c/doc/index.adoc (OCAH Modifications),
hw/ip/i2c/regs/gen/adoc/i2c_ctrl.adoc, hw/ip/i2c/regs/gen/adoc/i2c.adoc,
hw/sys/smc/regs/gen/adoc/memory_map.adoc (I2C wrapper decoded extent).
The specification does not state the padring reach.

* Gate rounds: with the three alert pads driven low, clearing SMBUS_EN on one
  instance leaves SMBUS_STATUS.SMBALERT of the other two at 1 and masks its own
  SMBUS_STATUS.SMBALERT to 0.
* SMBUS_EN mask, k = 1, 2: with SMBUS_EN 0 on all three and the pads low, both
  SMBALERT bits read 0; setting SMBUS_EN on k alone raises k's and leaves the other
  two at 0; clearing it again masks k's after a written 1 to INTR_STATE.
* Controller line loopback, k = 0, 1, 2: CTRL.LLPBK 1 hides the low alert pad from
  SMBUS_STATUS and INTR_STATE; LLPBK 0 sees it again.
* I2C_CTRL[1] and [2] take reserved-bit-only and all-ones writes, byte- and
  half-word-strobed writes and one-entry-at-a-time writes; the defined fields are
  compared, the reserved readback and every BRESP are logged (SF-004, SF-005).
* The wrapper window past its decoded extent answers DECERR 0xBADCAB1E / DECERR.
* The I2C1 alert pad is an input with I2C_CONTROLLER_MODE_EN 1 and follows
  SMBUS_CTRL.SMBALERT as an output with it 0; I2C2 is checked as an input.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    I2C_CG_EN,
    LOCAL_BASE_RESET,
    _field_mask,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    _I2C_H,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_INTR_STATE_SMBALERT,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_SMBUS_STATUS_SMBALERT,
    I2C_WRAP_CONTROLLER_MODE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_HOST_SMBUS,
    I2C_WRAP_EN,
    I2C_WRAP_SMBUS_EN,
)
from .smc_pad_table import pad_index

INSTANCES = (0, 1, 2)
ALERT_PADS = tuple(pad_index(f"I2C[{i}] SMB_A") for i in INSTANCES)
MASK_INSTANCES = (1, 2)
CTRL_INSTANCES = (1, 2)

POLLS = 500
POLL_US = 10
OBSERVE_POLLS = 16

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C_CTRL_LLPBK = _field_mask(_I2C_H, "I2C__CTRL__LLPBK_bm")

# I2C_CTRL words the contract writes (i2c_ctrl.adoc: I2C_EN bit 0,
# I2C_CONTROLLER_MODE_EN bit 4, SMBUS_EN bit 8, every other bit reserved).
WRAP_FIELDS = I2C_WRAP_SMBUS_EN | I2C_WRAP_CONTROLLER_MODE | I2C_WRAP_EN
WRAP_ALL = 0x111
WRAP_NO_SMBUS = 0x011
WRAP_SMBUS_ONLY = 0x100
WRAP_MODE_ONLY = 0x010
WRAP_TARGET_SMBUS = 0x101
WRAP_RSVD_ONLY = 0xFFFF_FFFF & ~WRAP_FIELDS
assert WRAP_FIELDS == WRAP_ALL == I2C_WRAP_CTRL_HOST_SMBUS, f"I2C_CTRL fields {WRAP_FIELDS:#x}"
assert I2C_WRAP_CTRL_HOST == WRAP_NO_SMBUS and I2C_WRAP_SMBUS_EN == WRAP_SMBUS_ONLY
assert I2C_WRAP_CONTROLLER_MODE == WRAP_MODE_ONLY
assert WRAP_SMBUS_ONLY | I2C_WRAP_EN == WRAP_TARGET_SMBUS
assert WRAP_RSVD_ONLY == 0xFFFF_FEEE, f"reserved-only word {WRAP_RSVD_ONLY:#x}"

DECERR = 3
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
PROBE_WORD = 0xA5A5_A5A5
I2C_WRAP_UNIT = "smc_i2c_wrap"
I2C_WRAP_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_BASE_ADDR")
# The block-end word: I2C_CTRL block base plus its size, both from the generated header.
I2C_CTRL_BLOCK_END = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR") + smc_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_SIZE"
)

FENCE_ORDER = [
    "SETUP",
    "GATE_ROUNDS",
    "SMBUS_EN_MASK",
    "LLPBK",
    "RSVD",
    "PARTIAL",
    "ENTRY",
    "WINDOW",
    "PAD_DIR",
    "TEARDOWN",
]
CHECKER_AFTER = {
    "CHK-GATE-ALL-SEE-ALERT": "GATE_ROUNDS",
    "CHK-GATE-OTHERS-UNMASKED": "GATE_ROUNDS",
    "CHK-SMBUS-EN-MASK-I2C12": "SMBUS_EN_MASK",
    "CHK-SMBUS-EN-ISOLATE": "SMBUS_EN_MASK",
    "CHK-LLPBK-ALERT-MASK": "LLPBK",
    "CHK-I2C-CTRL-RSVD-WRITE": "RSVD",
    "CHK-I2C-CTRL-PARTIAL-WRITE": "PARTIAL",
    "CHK-I2C-CTRL-ENTRY-ISOLATE": "ENTRY",
    "CHK-I2C-WRAP-PAST-EXTENT": "WINDOW",
    "CHK-I2C-ALERT-PAD-DIR": "PAD_DIR",
    "CHK-TIMEOUT-PATHS": "TEARDOWN",
}
NEW_TERMS = FENCE_ORDER[2:9]


def _reg(name: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", idx)


def _wrap_ctrl(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


class smc_smbus_alert_instance_isolation_test_seq(SmcCsrSeq):
    """Gate rounds, SMBUS_EN / LLPBK masking, I2C_CTRL writes, window decode, pad direction."""

    def __init__(self, name: str = "smc_smbus_alert_instance_isolation_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.gate: dict[int, dict[str, object]] = {}
        self.reads = 0
        self.writes = 0
        self.term_counts: list[tuple[int, int]] = []

    async def finish_item(self, item) -> None:
        await super().finish_item(item)
        if item.op is SmcSysAxiOp.READ:
            self.reads += 1
        else:
            self.writes += 1

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        self.term_counts.append((self.reads, self.writes))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    def _drive_pads_low(self, pads: tuple[int, ...], low: bool) -> None:
        dut = cocotb.top
        mask = 0
        for pad in pads:
            mask |= 1 << pad
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        if low:
            en |= mask
            val &= ~mask
        else:
            en &= ~mask
            val |= mask
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    def _drive_alert_low(self, low: bool) -> None:
        self._drive_pads_low(ALERT_PADS, low)

    async def _status(self, label: str, idx: int) -> int:
        word = await self.csr_read(label, _reg("SMBUS_STATUS", idx))
        return 1 if word & I2C_SMBUS_STATUS_SMBALERT else 0

    async def _intr(self, label: str, idx: int) -> int:
        word = await self.csr_read(label, _reg("INTR_STATE", idx))
        return 1 if word & I2C_INTR_STATE_SMBALERT else 0

    async def _poll_all(self, name: str, want: int) -> int:
        """Bounded poll until SMBUS_STATUS.SMBALERT of all three instances equals ``want``."""
        last = "never sampled"
        for polls in range(POLLS):
            got = [await self._status(f"{name}_{i}", i) for i in INSTANCES]
            last = f"SMBUS_STATUS.SMBALERT={got}"
            if got == [want] * 3:
                self.waits.append((name, f"{POLLS}x{POLL_US}us", last))
                return polls + 1
            await Timer(POLL_US, unit="us")
        self.waits.append((name, f"{POLLS}x{POLL_US}us", f"EXPIRED {last}"))
        raise AssertionError(f"{name}: not all {want} in {POLLS} polls; {last}")

    async def _poll_one(self, name: str, idx: int, want: int) -> int:
        """Bounded poll until SMBUS_STATUS.SMBALERT of instance ``idx`` equals ``want``."""
        last = "never sampled"
        for polls in range(POLLS):
            got = await self._status(f"{name}_p{polls}", idx)
            last = f"i2c{idx} SMBUS_STATUS.SMBALERT={got}"
            if got == want:
                self.waits.append((name, f"{POLLS}x{POLL_US}us", last))
                return polls + 1
            await Timer(POLL_US, unit="us")
        self.waits.append((name, f"{POLLS}x{POLL_US}us", f"EXPIRED {last}"))
        raise AssertionError(f"{name}: i2c{idx} SMBALERT not {want} in {POLLS} polls; {last}")

    @staticmethod
    def _bit(sig, pad: int) -> str:
        s = getattr(sig.value, "binstr", None) or str(sig.value)
        bits = "".join(c for c in s if c not in " _").lower()
        return bits[-1 - pad]

    async def _poll_pad(self, name: str, pad: int, want: int) -> int:
        """Bounded poll of the pad direction at ``tb_core2pad_en_o`` / ``tb_core2pad_o``.

        The pad reads 0 while the DUT drives it low (en and not data) and sits at its
        pull-up level, 1, while the DUT releases it (not en). Observation only.
        """
        top = cocotb.top
        last = "never sampled"
        for polls in range(POLLS):
            en = self._bit(top.tb_core2pad_en_o, pad)
            data = self._bit(top.tb_core2pad_o, pad)
            last = f"tb_core2pad_en_o[{pad}]={en} tb_core2pad_o[{pad}]={data}"
            if en not in "01" or (en == "1" and data not in "01"):
                self.waits.append((name, f"{POLLS}x{POLL_US}us", f"FAILED {last}"))
                raise AssertionError(f"{name}: pad direction nets not 0/1: {last}")
            level = 0 if (en == "1" and data == "0") else 1 if en == "0" else None
            if level == want:
                self.waits.append((name, f"{POLLS}x{POLL_US}us", last))
                return polls + 1
            await Timer(POLL_US, unit="us")
        self.waits.append((name, f"{POLLS}x{POLL_US}us", f"EXPIRED {last}"))
        raise AssertionError(f"{name}: pad {pad} not {want} in {POLLS} polls; {last}")

    async def _observe(self, label: str, idx: int, want: int) -> int:
        """Read SMBUS_STATUS and INTR_STATE of ``idx`` OBSERVE_POLLS times; both must be ``want``."""
        hits = 0
        for poll in range(OBSERVE_POLLS):
            status = await self._status(f"{label}_status_p{poll}", idx)
            intr = await self._intr(f"{label}_intr_p{poll}", idx)
            assert (status, intr) == (want, want), (
                f"{label}: i2c{idx} read {poll}: SMBUS_STATUS.SMBALERT={status} "
                f"INTR_STATE.SMBALERT={intr}, expected {want}/{want}"
            )
            hits += 1
        assert hits == OBSERVE_POLLS, f"{label}: {hits} of {OBSERVE_POLLS} reads"
        return hits

    async def _write_logged(self, name: str, addr: int, data: int, wstrb: int | None = None) -> str:
        """Write whose BRESP the contract only logs (SF-004 / SF-005); returns the response name."""
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.wstrb = wstrb
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"{name} @ 0x{addr:08x}: write got no response"
        return RESP_NAMES.get(item.resp_code, f"resp={item.resp_code}")

    async def _read_logged(self, name: str, addr: int) -> tuple[str, int]:
        """Read whose RRESP and data the contract only logs; returns (response, data)."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"{name} @ 0x{addr:08x}: read got no response"
        return RESP_NAMES.get(item.resp_code, f"resp={item.resp_code}"), item.rdata

    async def _ctrl_word(self, label: str, idx: int) -> int:
        return (await self.csr_read(label, _wrap_ctrl(idx))) & 0xFFFF_FFFF

    async def _setup(self) -> int:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for i in INSTANCES:
            await self.csr_write(f"I2C{i}_WRAP_HOST_SMBUS", _wrap_ctrl(i), I2C_WRAP_CTRL_HOST_SMBUS)
            await self.csr_write(f"I2C{i}_CTRL_HOST", _reg("CTRL", i), I2C_CTRL_ENABLEHOST)
            await self.csr_write(
                f"I2C{i}_INTR_STATE_W1C", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
        self._drive_alert_low(False)
        self._stamp("SETUP")
        return cg

    async def _gate_round(self, k: int) -> None:
        self._drive_alert_low(True)
        see_polls = await self._poll_all(f"gate{k}_all_see_alert", 1)
        await self.csr_write(
            f"I2C{k}_SMBUS_EN_CLR", _wrap_ctrl(k), I2C_WRAP_CTRL_HOST_SMBUS & ~I2C_WRAP_SMBUS_EN
        )
        others = [i for i in INSTANCES if i != k]
        for poll in range(OBSERVE_POLLS):
            for i in others:
                got = await self._status(f"gate{k}_other{i}_p{poll}", i)
                assert got == 1, (
                    f"k={k}: SMBUS_STATUS.SMBALERT of instance {i} read {got} in poll {poll} "
                    f"with SMBUS_EN cleared on instance {k} only"
                )
        own_status = await self._status(f"gate{k}_own_status", k)
        assert own_status == 0, (
            f"k={k}: SMBUS_STATUS.SMBALERT of the cleared instance reads {own_status}; "
            f"SMBUS_EN low masks smbalert_ni (index.adoc)"
        )
        own_intr = (
            await self.csr_read(f"gate{k}_own_intr", _reg("INTR_STATE", k))
        ) & I2C_INTR_STATE_SMBALERT
        await self.csr_write(f"I2C{k}_WRAP_RESTORE", _wrap_ctrl(k), I2C_WRAP_CTRL_HOST_SMBUS)
        self._drive_alert_low(False)
        clear_polls = await self._poll_all(f"gate{k}_released_all_zero", 0)
        self.gate[k] = {
            "see": see_polls,
            "others": others,
            "own_status": own_status,
            "own_intr": 1 if own_intr else 0,
            "clear": clear_polls,
        }

    async def _gate_rounds(self) -> None:
        for k in INSTANCES:
            await self._gate_round(k)
        self._stamp("GATE_ROUNDS")
        self._chk(
            "CHK-GATE-ALL-SEE-ALERT",
            "set: three alert pads driven low; observed: "
            + "; ".join(
                f"round k={k}: SMBUS_STATUS.SMBALERT=1 on instances 0,1,2 after "
                f"{self.gate[k]['see']} polls with SMBUS_EN set on all three"
                for k in INSTANCES
            )
            + "; cleared: pads released at the end of each round; checked_cleared: all three "
            "SMBUS_STATUS.SMBALERT read 0 after "
            + ",".join(str(self.gate[k]["clear"]) for k in INSTANCES)
            + " polls (rounds k=0,1,2)",
        )
        self._chk(
            "CHK-GATE-OTHERS-UNMASKED",
            "set: SMBUS_EN cleared on instance k only; observed: "
            + "; ".join(
                f"k={k}: instances {self.gate[k]['others']} read SMBUS_STATUS.SMBALERT=1 in "
                f"{OBSERVE_POLLS} of {OBSERVE_POLLS} polls, own instance SMBUS_STATUS.SMBALERT="
                f"{self.gate[k]['own_status']} (masked, compared) "
                f"INTR_STATE.SMBALERT={self.gate[k]['own_intr']} "
                f"logged only (not specified, measured)"
                for k in INSTANCES
            )
            + "; cleared: pads released and SMBUS_EN restored; checked_cleared: all three read 0 "
            "after the release in every round",
        )

    async def _smbus_en_mask_round(self, k: int) -> dict[str, object]:
        others = [i for i in INSTANCES if i != k]
        self._drive_alert_low(True)
        for i in INSTANCES:
            await self.csr_write(f"en{k}_I2C{i}_WRAP_NO_SMBUS", _wrap_ctrl(i), WRAP_NO_SMBUS)
        for i in INSTANCES:
            await self.csr_write(
                f"en{k}_I2C{i}_INTR_W1C", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
        masked = {i: await self._observe(f"en{k}_masked_i2c{i}", i, 0) for i in INSTANCES}
        await self.csr_write(f"en{k}_I2C{k}_WRAP_SMBUS", _wrap_ctrl(k), WRAP_ALL)
        await self._poll_one(f"en{k}_unmask_status", k, 1)
        unmasked_status = await self._status(f"en{k}_unmasked_status", k)
        unmasked_intr = await self._intr(f"en{k}_unmasked_intr", k)
        assert (unmasked_status, unmasked_intr) == (1, 1), (
            f"i2c{k} SMBUS_EN 1, pad low: SMBUS_STATUS.SMBALERT={unmasked_status} "
            f"INTR_STATE.SMBALERT={unmasked_intr}, expected 1/1"
        )
        isolated = {i: await self._observe(f"en{k}_isolate_i2c{i}", i, 0) for i in others}
        await self.csr_write(f"en{k}_I2C{k}_WRAP_REMASK", _wrap_ctrl(k), WRAP_NO_SMBUS)
        await self.csr_write(
            f"en{k}_I2C{k}_INTR_W1C_REMASK", _reg("INTR_STATE", k), I2C_INTR_STATE_SMBALERT
        )
        remasked = await self._observe(f"en{k}_remasked_i2c{k}", k, 0)
        self._drive_alert_low(False)
        for i in INSTANCES:
            await self.csr_write(f"en{k}_I2C{i}_WRAP_RESTORE", _wrap_ctrl(i), WRAP_ALL)
        await self._poll_all(f"en{k}_released_all_zero", 0)
        return {"masked": masked, "isolated": isolated, "remasked": remasked}

    async def _smbus_en_mask(self) -> None:
        res = {k: await self._smbus_en_mask_round(k) for k in MASK_INSTANCES}
        assert sorted(res) == list(MASK_INSTANCES), f"SMBUS_EN mask rounds {sorted(res)}"
        self._stamp("SMBUS_EN_MASK")
        self._chk(
            "CHK-SMBUS-EN-MASK-I2C12",
            "; ".join(
                f"i2c{k} masked {res[k]['masked'][k]}/{OBSERVE_POLLS} status=0 intr=0, "
                f"unmasked status=1 intr=1, re-masked {res[k]['remasked']}/{OBSERVE_POLLS} "
                "status=0 intr=0"
                for k in MASK_INSTANCES
            )
            + " (SMBUS_EN 0 on all three with the three pads low: every instance "
            + ", ".join(
                f"k={k}: " + "/".join(str(res[k]["masked"][i]) for i in INSTANCES)
                for k in MASK_INSTANCES
            )
            + f" of {OBSERVE_POLLS} reads 0/0; rounds {len(res)}/{len(MASK_INSTANCES)})",
        )
        self._chk(
            "CHK-SMBUS-EN-ISOLATE",
            "; ".join(
                f"en=i2c{k} only -> "
                + " ".join(
                    f"i2c{i} {res[k]['isolated'][i]}/{OBSERVE_POLLS}=0" for i in INSTANCES if i != k
                )
                for k in MASK_INSTANCES
            )
            + " (status=0 and intr=0 on every read while the enabled instance read 1/1)",
        )

    async def _llpbk_round(self, k: int) -> dict[str, int]:
        pad = (ALERT_PADS[k],)
        await self.csr_write(f"lb{k}_I2C{k}_WRAP", _wrap_ctrl(k), WRAP_ALL)
        await self.csr_write(f"lb{k}_I2C{k}_CTRL_HOST", _reg("CTRL", k), I2C_CTRL_ENABLEHOST)
        self._drive_pads_low(pad, True)
        await self._poll_one(f"lb{k}_llpbk0_status", k, 1)
        intr0 = await self._intr(f"lb{k}_llpbk0_intr", k)
        assert intr0 == 1, f"i2c{k} LLPBK 0, pad low: INTR_STATE.SMBALERT={intr0}, expected 1"
        await self.csr_write(
            f"lb{k}_I2C{k}_CTRL_LLPBK", _reg("CTRL", k), I2C_CTRL_ENABLEHOST | I2C_CTRL_LLPBK
        )
        await self.csr_write(
            f"lb{k}_I2C{k}_INTR_W1C", _reg("INTR_STATE", k), I2C_INTR_STATE_SMBALERT
        )
        hidden = await self._observe(f"lb{k}_llpbk1", k, 0)
        await self.csr_write(f"lb{k}_I2C{k}_CTRL_NO_LLPBK", _reg("CTRL", k), I2C_CTRL_ENABLEHOST)
        await self._poll_one(f"lb{k}_llpbk0_again_status", k, 1)
        await self.csr_write(
            f"lb{k}_I2C{k}_INTR_W1C_END", _reg("INTR_STATE", k), I2C_INTR_STATE_SMBALERT
        )
        self._drive_pads_low(pad, False)
        await self._poll_one(f"lb{k}_released_status", k, 0)
        return {"hidden": hidden}

    async def _llpbk(self) -> None:
        res = {k: await self._llpbk_round(k) for k in INSTANCES}
        assert sorted(res) == list(INSTANCES), f"LLPBK rounds {sorted(res)}"
        self._stamp("LLPBK")
        self._chk(
            "CHK-LLPBK-ALERT-MASK",
            "i2c0/i2c1/i2c2 llpbk0 status=1 intr=1; llpbk1 "
            + "/".join(f"{res[k]['hidden']}/{OBSERVE_POLLS}" for k in INSTANCES)
            + " status=0 intr=0; llpbk0-again status=1 "
            f"(instances {len(res)}/{len(INSTANCES)}, own alert pad low, CTRL.ENABLEHOST 1)",
        )

    async def _rsvd(self) -> None:
        parts = []
        for k in CTRL_INSTANCES:
            await self.csr_write(f"rsvd{k}_I2C{k}_CTRL_OFF", _reg("CTRL", k), 0)
            bresp_rsvd = await self._write_logged(f"rsvd{k}_ONLY", _wrap_ctrl(k), WRAP_RSVD_ONLY)
            rb_rsvd = await self._ctrl_word(f"rsvd{k}_ONLY_RB", k)
            assert rb_rsvd & WRAP_FIELDS == 0, (
                f"I2C_CTRL[{k}] after {WRAP_RSVD_ONLY:#010x}: defined fields "
                f"{rb_rsvd & WRAP_FIELDS:#05x}, expected 0x000"
            )
            await self.csr_write(f"rsvd{k}_FIELDS", _wrap_ctrl(k), WRAP_ALL)
            bresp_keep = await self._write_logged(f"rsvd{k}_ALL_ONES", _wrap_ctrl(k), 0xFFFF_FFFF)
            rb_keep = await self._ctrl_word(f"rsvd{k}_ALL_ONES_RB", k)
            assert rb_keep & WRAP_FIELDS == WRAP_ALL, (
                f"I2C_CTRL[{k}] after 0xffffffff: defined fields "
                f"{rb_keep & WRAP_FIELDS:#05x}, expected {WRAP_ALL:#05x}"
            )
            await self.csr_write(f"rsvd{k}_RESTORE", _wrap_ctrl(k), WRAP_ALL)
            await self.csr_write(f"rsvd{k}_I2C{k}_CTRL_HOST", _reg("CTRL", k), I2C_CTRL_ENABLEHOST)
            parts.append(
                f"ctrl{k} rsvd-only defined={rb_rsvd & WRAP_FIELDS:#05x} "
                f"rsvd_rb={rb_rsvd & ~WRAP_FIELDS & 0xFFFF_FFFF:#010x} bresp={bresp_rsvd}; "
                f"keep defined={rb_keep & WRAP_FIELDS:#05x} "
                f"rsvd_rb={rb_keep & ~WRAP_FIELDS & 0xFFFF_FFFF:#010x} bresp={bresp_keep}"
            )
        assert len(parts) == len(CTRL_INSTANCES), f"reserved legs {len(parts)}"
        self._stamp("RSVD")
        self._chk(
            "CHK-I2C-CTRL-RSVD-WRITE",
            "; ".join(parts) + " (reserved readback: LINKED-ISSUE SF-005)",
        )

    async def _strobed(
        self, label: str, k: int, data: int, wstrb: int, want: int, fields_only: bool = False
    ) -> tuple[str, int]:
        bresp = await self._write_logged(label, _wrap_ctrl(k), data, wstrb)
        rb = await self._ctrl_word(f"{label}_RB", k)
        got = rb & WRAP_FIELDS if fields_only else rb
        assert got == want, (
            f"I2C_CTRL[{k}] after data {data:#010x} wstrb {wstrb:#06b}: read {rb:#010x}, "
            f"expected {'fields ' if fields_only else ''}{want:#05x} (bresp {bresp})"
        )
        return bresp, rb

    async def _partial(self) -> None:
        bresps: list[str] = []
        vals: dict[int, dict[str, int]] = {}
        for k in CTRL_INSTANCES:
            await self.csr_write(f"part{k}_FROM", _wrap_ctrl(k), WRAP_NO_SMBUS)
            b, set_rb = await self._strobed(
                f"part{k}_LANE1_SET", k, WRAP_SMBUS_ONLY, 0b0010, WRAP_ALL
            )
            bresps.append(b)
            b, clr_rb = await self._strobed(f"part{k}_LANE1_CLR", k, 0, 0b0010, WRAP_NO_SMBUS)
            bresps.append(b)
            vals[k] = {"set": set_rb, "clr": clr_rb}
        await self.csr_write("part1_FROM_ALL", _wrap_ctrl(1), WRAP_ALL)
        b, lane0 = await self._strobed("part1_LANE0", 1, 0, 0b0001, WRAP_SMBUS_ONLY)
        bresps.append(b)
        b, half_lo = await self._strobed("part1_HALF_LO", 1, WRAP_ALL, 0b0011, WRAP_ALL)
        bresps.append(b)
        b, half_hi = await self._strobed(
            "part1_HALF_HI", 1, 0xFFFF_0000, 0b1100, WRAP_ALL, fields_only=True
        )
        bresps.append(b)
        for k in CTRL_INSTANCES:
            await self.csr_write(f"part{k}_RESTORE", _wrap_ctrl(k), WRAP_ALL)
        assert len(bresps) == 2 * len(CTRL_INSTANCES) + 3, f"partial writes {len(bresps)}"
        self._stamp("PARTIAL")
        self._chk(
            "CHK-I2C-CTRL-PARTIAL-WRITE",
            f"ctrl1 lane1 set={vals[1]['set']:#05x} clr={vals[1]['clr']:#05x} "
            f"lane0={lane0:#05x} half_lo={half_lo:#05x} half_hi={half_hi & WRAP_FIELDS:#05x} "
            f"(raw {half_hi:#010x}); ctrl2 lane1 set={vals[2]['set']:#05x} "
            f"clr={vals[2]['clr']:#05x}; bresp={','.join(bresps)} (SF-004)",
        )

    async def _entries(self, label: str, want: tuple[int, int, int]) -> list[int]:
        got = [await self._ctrl_word(f"{label}_ctrl{i}", i) for i in INSTANCES]
        assert tuple(got) == want, (
            f"{label}: I2C_CTRL[0..2] read {[hex(v) for v in got]}, "
            f"expected {[hex(v) for v in want]}"
        )
        return got

    async def _entry_isolation(self) -> None:
        await self._entries("entry_start", (WRAP_ALL, WRAP_ALL, WRAP_ALL))
        await self.csr_write("entry_CTRL1", _wrap_ctrl(1), WRAP_SMBUS_ONLY)
        after1 = await self._entries("entry_after1", (WRAP_ALL, WRAP_SMBUS_ONLY, WRAP_ALL))
        await self.csr_write("entry_CTRL2", _wrap_ctrl(2), WRAP_MODE_ONLY)
        after2 = await self._entries("entry_after2", (WRAP_ALL, WRAP_SMBUS_ONLY, WRAP_MODE_ONLY))
        for k in CTRL_INSTANCES:
            await self.csr_write(f"entry_RESTORE{k}", _wrap_ctrl(k), WRAP_ALL)
        self._stamp("ENTRY")
        self._chk(
            "CHK-I2C-CTRL-ENTRY-ISOLATE",
            f"after ctrl1={WRAP_SMBUS_ONLY:#05x} -> "
            + "/".join(f"{v:#05x}" for v in after1)
            + f"; after ctrl2={WRAP_MODE_ONLY:#05x} -> "
            + "/".join(f"{v:#05x}" for v in after2),
        )

    async def _window(self) -> None:
        extent = generated_decoded_extent(I2C_WRAP_UNIT)
        first, last = generated_window(I2C_WRAP_UNIT)
        assert LOCAL_BASE_RESET + first == I2C_WRAP_BASE, "I2C wrapper window base mismatch"
        offsets = (extent, last - first + 1 - 4)
        assert offsets == (0xE0C, 0xFFC), f"I2C wrapper probe offsets {[hex(o) for o in offsets]}"
        rresp, bresp = generated_past_extent_resp(I2C_WRAP_UNIT)
        assert (rresp, bresp) == ("DECERR", "DECERR"), f"past-extent response {rresp}/{bresp}"
        before_smbus = {
            k: await self.csr_read(f"win_smbus_ctrl{k}_before", _reg("SMBUS_CTRL", k))
            for k in CTRL_INSTANCES
        }
        parts = []
        for off in offsets:
            addr = I2C_WRAP_BASE + off
            rd = await self.csr_read_err_signature(f"win_{off:x}_RD", addr, resp=DECERR)
            wr = await self.csr_write_expect_error(f"win_{off:x}_WR", addr, PROBE_WORD, resp=DECERR)
            parts.append(
                f"0x{off:03X} R={RESP_NAMES[DECERR]}/0x{rd & 0xFFFF_FFFF:08X} W={RESP_NAMES[wr]}"
            )
        gap_off = I2C_CTRL_BLOCK_END - I2C_WRAP_BASE
        gap_r, gap_d = await self._read_logged(f"win_gap_{gap_off:x}_RD", I2C_CTRL_BLOCK_END)
        gap_w = await self._write_logged(f"win_gap_{gap_off:x}_WR", I2C_CTRL_BLOCK_END, PROBE_WORD)
        await self._entries("win_after", (WRAP_ALL, WRAP_ALL, WRAP_ALL))
        for k in CTRL_INSTANCES:
            after = await self.csr_read(f"win_smbus_ctrl{k}_after", _reg("SMBUS_CTRL", k))
            assert after == before_smbus[k], (
                f"SMBUS_CTRL of i2c{k} {before_smbus[k]:#x} -> {after:#x} across the probes"
            )
        self._stamp("WINDOW")
        self._chk(
            "CHK-I2C-WRAP-PAST-EXTENT",
            "; ".join(parts)
            + f"; neighbours unchanged (I2C_CTRL[0..2]={WRAP_ALL:#05x}, SMBUS_CTRL i2c1/i2c2="
            + "/".join(f"{before_smbus[k]:#x}" for k in CTRL_INSTANCES)
            + f"); gap {gap_off:#05x} R={gap_r}/{gap_d & 0xFFFF_FFFF:#010x} W={gap_w}"
            + (" (block end coincides with the decoded extent)" if gap_off == extent else "")
            + " (LINKED-ISSUE SF-001/SF-002)",
        )

    async def _pad_input(self, k: int) -> None:
        pad = (ALERT_PADS[k],)
        await self.csr_write(f"dir{k}_WRAP_IN", _wrap_ctrl(k), WRAP_ALL)
        await self.csr_write(f"dir{k}_CTRL_HOST", _reg("CTRL", k), I2C_CTRL_ENABLEHOST)
        self._drive_pads_low(pad, True)
        await self._poll_one(f"dir{k}_input_low", k, 1)
        self._drive_pads_low(pad, False)
        await self._poll_one(f"dir{k}_input_released", k, 0)

    async def _pad_dir(self) -> None:
        await self._pad_input(1)
        pad1 = ALERT_PADS[1]
        self._drive_pads_low((pad1,), False)
        await self.csr_write("dir1_WRAP_OUT", _wrap_ctrl(1), WRAP_TARGET_SMBUS)
        await self.csr_write("dir1_CTRL_TARGET", _reg("CTRL", 1), I2C_CTRL_ENABLETARGET)
        await self.csr_write("dir1_SMBALERT_SET", _reg("SMBUS_CTRL", 1), I2C_SMBUS_CTRL_SMBALERT)
        await self._poll_pad("dir1_output_pad_low", pad1, 0)
        await self.csr_write("dir1_SMBALERT_CLR", _reg("SMBUS_CTRL", 1), 0)
        await self._poll_pad("dir1_output_pad_high", pad1, 1)
        await self.csr_write("dir1_WRAP_RESTORE", _wrap_ctrl(1), WRAP_ALL)
        await self.csr_write("dir1_CTRL_RESTORE", _reg("CTRL", 1), I2C_CTRL_ENABLEHOST)
        await self._pad_input(2)
        self._stamp("PAD_DIR")
        self._chk(
            "CHK-I2C-ALERT-PAD-DIR",
            "i2c1 input low->1 rel->0; i2c2 input low->1 rel->0; i2c1 output smbalert=1 pad=0, "
            f"smbalert=0 pad=1 (observed at tb_core2pad_en_o/tb_core2pad_o[{pad1}])",
        )

    async def _teardown(self, cg: int) -> None:
        for i in INSTANCES:
            await self.csr_write(f"I2C{i}_SMBUS_CTRL_OFF", _reg("SMBUS_CTRL", i), 0)
            await self.csr_write(f"I2C{i}_WRAP_OFF", _wrap_ctrl(i), 0)
            await self.csr_write(f"I2C{i}_CTRL_OFF", _reg("CTRL", i), 0)
        self._drive_alert_low(False)
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        self._stamp("TEARDOWN")

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        expired = sum(1 for _, _, s in waits if s.startswith(("EXPIRED", "FAILED")))
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired; each "
            "raising AssertionError with its last state on expiry; %s",
            len(waits),
            expired,
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )
        self.chk_lines.append(("CHK-TIMEOUT-PATHS", len(self.stamps)))

    def _emit_nonvac(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = dict(self.chk_lines)
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never printed"
            assert printed[name] > order.index(term), f"{name} printed before {term}"
        prev = (0, 0)
        terms = []
        for (term, ps), (r, w) in zip(self.stamps, self.term_counts):
            dr, dw = r - prev[0], w - prev[1]
            prev = (r, w)
            assert dr + dw > 0, f"fence term {term} has no accesses"
            if term in NEW_TERMS:
                assert dr > 0 and dw > 0, f"fence term {term}: {dr} reads, {dw} writes"
            terms.append(f"{term}={ps}ps(r={dr},w={dw})")
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(terms),
            ",".join(name for name, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        cg = await self._setup()
        await self._gate_rounds()
        await self._smbus_en_mask()
        await self._llpbk()
        await self._rsvd()
        await self._partial()
        await self._entry_isolation()
        await self._window()
        await self._pad_dir()
        await self._teardown(cg)
        self._emit_timeout_paths()
        self._emit_nonvac()
