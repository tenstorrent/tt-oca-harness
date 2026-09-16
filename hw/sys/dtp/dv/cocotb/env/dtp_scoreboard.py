# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP UVM scoreboard.

Subscribes to the JTAG agent's completed-transaction stream and checks:
  * IDCODE reads return exactly the DTP IDCODE (full 32-bit compare, which
    subsumes the IEEE 1149.1 LSB == 1 rule).
  * JTAG2AXI writes report SUCCESS and land in the OCAH AXI RAM.
  * JTAG2AXI reads report SUCCESS and return the OCAH AXI RAM contents.

check_phase() fails on any recorded error and reports the per-category check
counts; a test whose checkable traffic produced zero comparisons is reported
so a vacuous run is visible in the log even when it cannot be failed here
(most scenarios land their evidence in the per-feature OcahChecker ledgers).
"""

from __future__ import annotations

from pyuvm import ConfigDB, uvm_subscriber

from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_tap_device import DTP_DEFAULT_IDCODE
from .dtp_types import DtpJtag2AxiStatus


class DtpScoreboard(uvm_subscriber):
    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.errors: list[str] = []
        self.checks = 0
        self.items_seen = 0
        self.checks_by_kind: dict[str, int] = {"idcode": 0, "j2a_write": 0, "j2a_read": 0}

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.logger.error("SCOREBOARD FAIL: %s", msg)

    def write(self, item: DtpJtagItem) -> None:
        self.items_seen += 1
        if item.op is DtpJtagOp.READ and item.reg == "IDCODE":
            self.checks += 1
            self.checks_by_kind["idcode"] += 1
            if (item.result & 0xFFFF_FFFF) != DTP_DEFAULT_IDCODE:
                self._fail(
                    f"IDCODE mismatch: expected 0x{DTP_DEFAULT_IDCODE:08x}, got 0x{item.result:08x}"
                )
            else:
                self.logger.info("IDCODE check OK: 0x%08x", item.result)

        elif item.op is DtpJtagOp.J2A_WRITE:
            self.checks += 1
            self.checks_by_kind["j2a_write"] += 1
            if item.status != DtpJtag2AxiStatus.SUCCESS:
                self._fail(f"J2A write status {DtpJtag2AxiStatus(item.status).name}")
            elif self.cfg.axi_ram is not None:
                byte_count = 1 << item.axi_size
                mem = self.cfg.axi_ram.read(item.axi_addr, byte_count)
                expected = item.axi_data.to_bytes(8, "little")[:byte_count]
                for idx in range(byte_count):
                    if ((item.axi_wstrb >> idx) & 0x1) and mem[idx] != expected[idx]:
                        self._fail(
                            f"J2A write byte {idx} mismatch at 0x{item.axi_addr + idx:x}: "
                            f"expected 0x{expected[idx]:02x}, got 0x{mem[idx]:02x} "
                            f"(wstrb=0x{item.axi_wstrb:02x}, size={item.axi_size})"
                        )
                        break
                else:
                    self.logger.info(
                        "J2A write OK: addr=0x%x size=%d wstrb=0x%02x data=0x%016x",
                        item.axi_addr,
                        item.axi_size,
                        item.axi_wstrb,
                        item.axi_data,
                    )

        elif item.op is DtpJtagOp.J2A_READ:
            self.checks += 1
            self.checks_by_kind["j2a_read"] += 1
            if item.status != DtpJtag2AxiStatus.SUCCESS:
                self._fail(f"J2A read status {DtpJtag2AxiStatus(item.status).name}")
            elif self.cfg.axi_ram is not None:
                byte_count = 1 << item.axi_size
                mem = int.from_bytes(self.cfg.axi_ram.read(item.axi_addr, byte_count), "little")
                mask = (1 << (8 * byte_count)) - 1
                if (item.rdata & mask) != mem:
                    self._fail(
                        f"J2A read 0x{item.rdata & mask:0{byte_count * 2}x} != "
                        f"AxiRam[0x{item.axi_addr:x}]=0x{mem:0{byte_count * 2}x} "
                        f"(size={item.axi_size})"
                    )
                else:
                    self.logger.info(
                        "J2A read OK: addr=0x%x size=%d data=0x%x",
                        item.axi_addr,
                        item.axi_size,
                        item.rdata & mask,
                    )

    def check_phase(self) -> None:
        assert not self.errors, f"DTP scoreboard found {len(self.errors)} error(s): " + "; ".join(
            self.errors
        )
        breakdown = " ".join(f"{kind}={count}" for kind, count in self.checks_by_kind.items())
        if self.items_seen and not self.checks:
            # Visible-but-not-fatal: JTAG traffic flowed and none of it was a
            # kind this scoreboard compares. The per-feature evidence ledgers
            # (TAP checker, AXI scoreboard, XTRIG checker) own those scenarios.
            self.logger.info(
                "DTP scoreboard: %d items observed, no scoreboard-checkable ops (%s)",
                self.items_seen,
                breakdown,
            )
        else:
            self.logger.info(
                "DTP scoreboard: %d checks (%s) over %d items, 0 errors",
                self.checks,
                breakdown,
                self.items_seen,
            )
