# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hand-written register header in the shape ``tools/regs/rdlpyhdr.py`` emits.

One register space with every field class and every reset / write reason arm:
a 32-bit control block, a wide block (64- and 256-bit registers), an array of
two blocks each holding a regfile, a memory, and one register directly under
the top addrmap.
"""

FIX_TOP_REG_MAP_BASE_ADDR = 0x00001000
FIX_TOP_REG_MAP_SIZE = 0x00003000

CTRL_REG_MAP_BASE_ADDR = 0x00001000
CTRL_REG_MAP_SIZE = 0x00000030
CTRL_MODE_REG_OFFSET = 0x00000000
CTRL_MODE_REG_ADDR = 0x00001000
CTRL_MODE_REG_TYPE = "CTRL_MODE"
CTRL_ID_REG_OFFSET = 0x00000004
CTRL_ID_REG_ADDR = 0x00001004
CTRL_ID_REG_TYPE = "CTRL_ID"
CTRL_TRIG_REG_OFFSET = 0x00000008
CTRL_TRIG_REG_ADDR = 0x00001008
CTRL_TRIG_REG_TYPE = "CTRL_TRIG"
CTRL_IRQ_REG_OFFSET = 0x0000000C
CTRL_IRQ_REG_ADDR = 0x0000100C
CTRL_IRQ_REG_TYPE = "CTRL_IRQ"
CTRL_LOCK_REG_OFFSET = 0x00000010
CTRL_LOCK_REG_ADDR = 0x00001010
CTRL_LOCK_REG_TYPE = "CTRL_LOCK"
CTRL_FLAGS_REG_OFFSET = 0x00000014
CTRL_FLAGS_REG_ADDR = 0x00001014
CTRL_FLAGS_REG_TYPE = "CTRL_FLAGS"
CTRL_SEED_REG_OFFSET = 0x00000018
CTRL_SEED_REG_ADDR = 0x00001018
CTRL_SEED_REG_TYPE = "CTRL_SEED"
CTRL_DMA_0__REG_OFFSET = 0x00000020
CTRL_DMA_0__REG_ADDR = 0x00001020
CTRL_DMA_0__REG_TYPE = "CTRL_DMA"
CTRL_DMA_1__REG_OFFSET = 0x00000024
CTRL_DMA_1__REG_ADDR = 0x00001024
CTRL_DMA_1__REG_TYPE = "CTRL_DMA"
CTRL_STATUS_REG_OFFSET = 0x00000028
CTRL_STATUS_REG_ADDR = 0x00001028
CTRL_STATUS_REG_TYPE = "CTRL_STATUS"

WIDE_REG_MAP_BASE_ADDR = 0x00002000
WIDE_REG_MAP_SIZE = 0x00000028
WIDE_KEY_REG_OFFSET = 0x00000000
WIDE_KEY_REG_ADDR = 0x00002000
WIDE_KEY_REG_TYPE = "WIDE_KEY"
WIDE_CFG_REG_OFFSET = 0x00000020
WIDE_CFG_REG_ADDR = 0x00002020
WIDE_CFG_REG_TYPE = "WIDE_CFG"

BANK_0__REG_MAP_BASE_ADDR = 0x00003000
BANK_0__REG_MAP_SIZE = 0x00000020
BANK_0__REGION_REG_FILE_BASE_ADDR = 0x00003000
BANK_0__REGION_REG_FILE_SIZE = 0x00000010
BANK_0__REGION_ATTRS_REG_OFFSET = 0x00000000
BANK_0__REGION_ATTRS_REG_ADDR = 0x00003000
BANK_0__REGION_ATTRS_REG_TYPE = "BANK_REGION_ATTRS"
BANK_1__REG_MAP_BASE_ADDR = 0x00003020
BANK_1__REG_MAP_SIZE = 0x00000020
BANK_1__REGION_REG_FILE_BASE_ADDR = 0x00003020
BANK_1__REGION_REG_FILE_SIZE = 0x00000010
BANK_1__REGION_ATTRS_REG_OFFSET = 0x00000000
BANK_1__REGION_ATTRS_REG_ADDR = 0x00003020
BANK_1__REGION_ATTRS_REG_TYPE = "BANK_REGION_ATTRS"

BUF_MEM_BASE_ADDR = 0x00003800
BUF_MEM_SIZE = 0x00000800

VERSION_REG_OFFSET = 0x00002FF0
VERSION_REG_ADDR = 0x00003FF0
VERSION_REG_TYPE = "FIX_TOP_VERSION"

CTRL_MODE_REG_DEFAULT = 0x00000001
CTRL_MODE_REG_WIDTH = 32
CTRL_MODE_REG_FIELDS = (
    ("en", 0, 0, "rw", "r", "", "", False, False, 1),
    ("sel", 1, 3, "rw", "r", "", "", False, False, 0),
    ("rsvd0", 4, 7, "r", "r", "", "", False, False, 0),
    ("reserved_1", 8, 11, "rw", "r", "", "", False, False, 0),
    ("busy", 16, 16, "r", "w", "", "", False, True, 0),
)

CTRL_ID_REG_DEFAULT = 0x00000000
CTRL_ID_REG_WIDTH = 32
CTRL_ID_REG_FIELDS = (("id", 0, 31, "r", "na", "", "", False, False, None),)

CTRL_TRIG_REG_DEFAULT = 0x00000000
CTRL_TRIG_REG_WIDTH = 32
CTRL_TRIG_REG_FIELDS = (("go", 0, 0, "w", "r", "", "", True, False, 0),)

CTRL_IRQ_REG_DEFAULT = 0x00000000
CTRL_IRQ_REG_WIDTH = 32
CTRL_IRQ_REG_FIELDS = (
    ("pending", 0, 3, "rw", "w", "woclr", "", False, True, 0),
    ("enable", 4, 7, "rw", "r", "", "", False, False, 0),
)

CTRL_LOCK_REG_DEFAULT = 0x00000000
CTRL_LOCK_REG_WIDTH = 32
CTRL_LOCK_REG_FIELDS = (("lock", 0, 0, "rw", "r", "woset", "", False, False, 0),)

CTRL_FLAGS_REG_DEFAULT = 0x00000000
CTRL_FLAGS_REG_WIDTH = 32
CTRL_FLAGS_REG_FIELDS = (
    ("err", 0, 1, "rw", "w", "wzc", "", False, True, 0),
    ("evt", 2, 3, "rw", "w", "", "rclr", False, True, 0),
    ("tok", 4, 5, "r", "w", "", "rset", False, True, 0),
    ("once", 6, 6, "rw1", "r", "", "", False, False, 0),
    ("arm", 7, 7, "w1", "r", "", "", False, False, 0),
    ("all", 8, 8, "rw", "r", "wset", "", False, False, 0),
    ("none", 9, 9, "rw", "r", "wclr", "", False, False, 0),
    ("tgl", 10, 10, "rw", "r", "wot", "", False, False, 0),
    ("ztg", 11, 11, "rw", "r", "wzt", "", False, False, 0),
    ("zst", 12, 12, "rw", "r", "wzs", "", False, False, 0),
    ("usr", 13, 13, "rw", "r", "wuser", "ruser", False, False, 0),
    ("hid", 14, 14, "na", "rw", "", "", False, True, 0),
)

CTRL_SEED_REG_DEFAULT = 0x00000000
CTRL_SEED_REG_WIDTH = 32
CTRL_SEED_REG_FIELDS = (
    ("seed", 0, 7, "rw", "r", "", "", False, False, None),
    ("key", 8, 15, "w", "r", "", "", False, False, None),
)

CTRL_DMA_REG_DEFAULT = 0x00000000
CTRL_DMA_REG_WIDTH = 32
CTRL_DMA_REG_FIELDS = (("addr", 0, 31, "rw", "r", "", "", False, False, 0),)

CTRL_STATUS_REG_DEFAULT = 0x00000005
CTRL_STATUS_REG_WIDTH = 32
CTRL_STATUS_REG_FIELDS = (
    ("state", 0, 2, "r", "w", "", "", False, True, 5),
    ("count", 8, 15, "r", "w", "", "", False, True, None),
)

WIDE_KEY_REG_WIDTH = 256
WIDE_KEY_REG_FIELDS = (("key", 0, 255, "r", "rw", "", "", False, True, 0),)

WIDE_CFG_REG_DEFAULT = 0x0000000000000005
WIDE_CFG_REG_WIDTH = 64
WIDE_CFG_REG_FIELDS = (
    ("lo", 0, 31, "rw", "r", "", "", False, False, 5),
    ("hi", 32, 63, "rw", "r", "", "", False, False, None),
)

BANK_REGION_ATTRS_REG_DEFAULT = 0x8000000000000010
BANK_REGION_ATTRS_REG_WIDTH = 64
BANK_REGION_ATTRS_REG_FIELDS = (
    ("base", 0, 31, "rw", "r", "", "", False, False, 16),
    ("valid", 63, 63, "rw", "r", "", "", False, False, 1),
)

FIX_TOP_VERSION_REG_DEFAULT = 0xDEADBEEF
FIX_TOP_VERSION_REG_WIDTH = 32
FIX_TOP_VERSION_REG_FIELDS = (("version", 0, 31, "r", "na", "", "", False, False, 0xDEADBEEF),)
