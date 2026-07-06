# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw-libs TARGET=smc
FW_NAME := smc
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# SMC runtime driver library. DV tests supply main() and link against it. Layout
# follows the SiFive Metal include convention rooted at include/metal.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := \
  -I$(FW_DIR)/include \
  -I$(FW_DIR)/include/metal \
  -I$(FW_DIR)/include/metal/drivers \
  -I$(FW_DIR)/include/metal/smc

# Register headers via the shared engine helper (umbrella smc.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := smc

# Test discovery is unified in compile.mk; declare only the SMC deltas. coremark
# pulls in the shared core_portme.c harness alongside its own source.
FW_TEST_EXTRA_SRCS_coremark := $(FW_DIR)/tests/core_portme.c
FW_TEST_INCLUDES := -I$(FW_DIR)/tests
# Test sources predate strict prototypes / native register headers; keep these
# relaxations so they compile unchanged.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-incompatible-pointer-types \
  -Wno-implicit-function-declaration \
  -Wno-implicit-int \
  -Wno-strict-prototypes
FW_TEST_LINKER_SCRIPT := $(FW_DIR)/link/scratch_pad.ld
# Link against picolibc like the SEP/KM flows: test images keep their own entry
# (-Wl,-e,main) and skip crt0 (-nostartfiles), resolving libc/libm from picolibc.
FW_TEST_LDFLAGS = \
  $(FW_OPT) -Wl,--gc-sections -Wl,--as-needed \
  -Wl,--defsym=__stack_size=4K -Wl,--defsym=__heap_size=2K \
  -Wl,--no-relax -Wl,-e,main -nostartfiles \
  -march=$(FW_ARCH) -mabi=$(FW_ABI) --specs=$(FW_PICOLIBC_SPECS) -lgcc
FW_TEST_ARCHIVE_LINK = "$(FW_ARCHIVE)"

define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O binary $(1) "$(FW_TEST_BUILD_DIR)/$(2)/$(2).bin"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).bin" --data_width 64 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).bin" --data_width 1 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).hex" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi_preload"
endef

# ROM boot images (tests_rom/<name>/<name>.c). These keep the crt0/_enter startup
# and link at the ROM origin (smc_rom.ld) instead of the SRAM scratch-pad script.
# Each image emits test.rom.* so the DV testbench can preload
# $FW_ROM_BUILD_ROOT/<name>/test.rom.preload.hex (FW_ROM_BUILD_ROOT = build/tests_rom).
FW_ROM_LINKER_SCRIPT := $(FW_DIR)/link/smc_rom.ld

define FW_ROM_TEST_POSTPROCESS
	$(OBJCOPY) -O binary $(1) "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin" --data_width 64 --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin" --data_width 1 --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.hex" --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi" --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi_preload"
endef

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
