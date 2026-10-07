# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMC CPU reads and writes the CSR window of I3C instance 5.

`fw/tests/i3c5_csr_access` runs on hart 0. It reads HCI_VERSION and HC_CONTROL
at `SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR(5)`, sets HC_CONTROL.BUS_ENABLE and
reads it back, writes the entry word back and reads that, and publishes the
four values in CPU_CTRL SCRATCH_4..7. It posts PASS only if each matches the
reset words it was built with.

The bench grades three things the PASS word does not carry:

* The four published values against the vendor RDL (`base_registers.rdl`),
  parsed by `smc_i3c_to_fabric_test_seq`, not the image's own constants.
* The accesses that reached the I3C cores. `tb_i3c_csr_read_count` and
  `tb_i3c_csr_write_count` count R and B handshakes at each core's AXI-Lite
  port after the wrapper's instance decode. Between release and PASS the bench
  issues no I3C access, so instance 5 must advance by exactly the image's four
  reads and two writes and the other five instances by none.
* HC_CONTROL read over SEP_IN after PASS: the restored reset word, and one
  more read on instance 5's counter, which shows that the counter counts.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_fw_image_boot_seq import scratch_addr, smc_fw_image_boot_seq
from .smc_i3c_to_fabric_test_seq import (
    HC_CONTROL_OFFSET,
    HCI_VERSION_OFFSET,
    I3C_HC_CONTROL_BUS_ENABLE,
    I3C_HC_CONTROL_ENABLED,
    I3C_HC_CONTROL_RESET,
    I3C_HCI_VERSION_RESET,
)

I3C_INSTANCE = 5
I3C_CSR_WINDOW = smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", I3C_INSTANCE)
I3C_CSR_NUM = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM")
I3C_HC_CONTROL = I3C_CSR_WINDOW + HC_CONTROL_OFFSET

# The image's loads and stores in the window: HCI_VERSION, HC_CONTROL at entry,
# after BUS_ENABLE and after the restore; the BUS_ENABLE and restore stores.
FW_I3C_READS = 4
FW_I3C_WRITES = 2

# SCRATCH index -> (what the image read, the RDL-derived expected word).
PUBLISHED = {
    4: ("HCI_VERSION", I3C_HCI_VERSION_RESET),
    5: ("HC_CONTROL at entry", I3C_HC_CONTROL_RESET),
    6: ("HC_CONTROL after BUS_ENABLE", I3C_HC_CONTROL_ENABLED),
    7: ("HC_CONTROL after restore", I3C_HC_CONTROL_RESET),
}


def _unpack(signal_name: str) -> list[int]:
    signal = getattr(cocotb.top, signal_name)
    width = len(signal)
    assert width == 32 * I3C_CSR_NUM, (
        f"{signal_name} is {width} bits wide, not 32 per instance for {I3C_CSR_NUM} instances"
    )
    assert signal.value.is_resolvable, f"{signal_name} is not resolvable: {signal.value}"
    packed = int(signal.value)
    return [(packed >> (32 * i)) & 0xFFFF_FFFF for i in range(I3C_CSR_NUM)]


def i3c_csr_counts() -> tuple[list[int], list[int]]:
    """Per-instance (reads, writes) completed at the I3C cores' CSR ports."""
    return _unpack("tb_i3c_csr_read_count"), _unpack("tb_i3c_csr_write_count")


class smc_fw_i3c5_csr_access_test_seq(smc_fw_image_boot_seq):
    """Boot the I3C5 CSR image; grade its values, its access count and the restore."""

    tag = "I3C5-CSR"
    poll_iterations = 2000

    def __init__(self, name: str = "smc_fw_i3c5_csr_access_test_seq") -> None:
        super().__init__(name)
        self.base_counts: tuple[list[int], list[int]] = ([], [])
        self.published: dict[int, int] = {}
        self.access_ok = False
        self.values_ok = False

    async def before_boot(self) -> None:
        for index in PUBLISHED:
            await self.csr_write(f"I3C5_SCRATCH{index}_CLEAR", scratch_addr(index), 0)
            await self.csr_read(f"I3C5_SCRATCH{index}_CLEAR_RB", scratch_addr(index), expected=0)
        self.base_counts = i3c_csr_counts()

    async def after_pass(self) -> None:
        reads, writes = i3c_csr_counts()
        base_reads, base_writes = self.base_counts
        d_reads = [now - then for now, then in zip(reads, base_reads, strict=True)]
        d_writes = [now - then for now, then in zip(writes, base_writes, strict=True)]
        expected_reads = [FW_I3C_READS if i == I3C_INSTANCE else 0 for i in range(I3C_CSR_NUM)]
        expected_writes = [FW_I3C_WRITES if i == I3C_INSTANCE else 0 for i in range(I3C_CSR_NUM)]
        assert (d_reads, d_writes) == (expected_reads, expected_writes), (
            f"I3C CSR accesses between release and PASS: reads {d_reads}, writes {d_writes} "
            f"per instance; expected reads {expected_reads}, writes {expected_writes}"
        )
        self.access_ok = True
        cocotb.log.info(
            "CHK-FW-I3C5-CSR-ACCESS-COUNT: between release and PASS the I3C cores' CSR ports "
            "completed reads %s and writes %s per instance 0..%d: instance %d took the image's "
            "%d loads and %d stores and no other instance took any",
            d_reads,
            d_writes,
            I3C_CSR_NUM - 1,
            I3C_INSTANCE,
            FW_I3C_READS,
            FW_I3C_WRITES,
        )

        for index, (what, expected) in PUBLISHED.items():
            got = await self.csr_read(f"I3C5_SCRATCH{index}", scratch_addr(index))
            self.published[index] = got
            assert got == expected, (
                f"SCRATCH_{index} = 0x{got:08x}: the image's read of I3C5 {what}; the vendor "
                f"RDL gives 0x{expected:08x}"
            )
        cocotb.log.info(
            "CHK-FW-I3C5-HCI-VERSION: the CPU read HCI_VERSION at window 0x%08x + RDL offset "
            "0x%03x as 0x%08x == base_registers.rdl reset 0x%08x",
            I3C_CSR_WINDOW,
            HCI_VERSION_OFFSET,
            self.published[4],
            I3C_HCI_VERSION_RESET,
        )

        await self.csr_read(
            "I3C5_HC_CONTROL_AFTER_PASS", I3C_HC_CONTROL, expected=I3C_HC_CONTROL_RESET
        )
        after_reads, after_writes = i3c_csr_counts()
        assert after_reads[I3C_INSTANCE] - reads[I3C_INSTANCE] == 1, (
            f"instance {I3C_INSTANCE}'s read counter went {reads[I3C_INSTANCE]} -> "
            f"{after_reads[I3C_INSTANCE]} across one SEP_IN read of HC_CONTROL"
        )
        assert after_writes == writes, f"write counters moved on a read: {writes} -> {after_writes}"
        self.values_ok = True
        cocotb.log.info(
            "CHK-FW-I3C5-HC-CONTROL-BUS-ENABLE: the CPU read HC_CONTROL at 0x%08x as 0x%08x, "
            "wrote BUS_ENABLE (bm 0x%08x) and read 0x%08x, wrote the entry word back and read "
            "0x%08x, each equal to the base_registers.rdl word; SEP_IN read the restored 0x%08x "
            "after PASS and instance %d's read counter advanced by that one read",
            I3C_HC_CONTROL,
            self.published[5],
            I3C_HC_CONTROL_BUS_ENABLE,
            self.published[6],
            self.published[7],
            I3C_HC_CONTROL_RESET,
            I3C_INSTANCE,
        )
