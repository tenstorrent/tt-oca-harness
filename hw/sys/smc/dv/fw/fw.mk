# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# SMC DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw TARGET=smc
FW_NAME := smc
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT ?= $(abspath $(FW_DIR)/../../../../..)

# SMC runtime driver library. DV tests supply main() and link against it. Layout
# follows the SiFive Metal include convention rooted at common/.
FW_C_SRCS   := $(wildcard $(FW_DIR)/common/*.c $(FW_DIR)/common/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/common/*.S)
FW_INCLUDES := \
  -I$(FW_DIR)/common \
  -I$(FW_DIR)/common/drivers \
  -I$(FW_DIR)/common/metal \
  -I$(FW_DIR)/common/metal/drivers \
  -I$(FW_DIR)/common/metal/smc

# Register headers via the shared engine helper (umbrella smc.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := smc

FW_TEST_SRCS := $(wildcard $(FW_DIR)/tests/*/src/main.c)
FW_TEST_NAMES := $(sort $(notdir $(patsubst %/src/main.c,%,$(FW_TEST_SRCS))))
$(foreach test,$(FW_TEST_NAMES),$(eval FW_TEST_SRC_$(test) := $(FW_DIR)/tests/$(test)/src/main.c))
$(foreach test,$(FW_TEST_NAMES),$(eval FW_TEST_SRCS_$(test) := $(wildcard $(FW_DIR)/tests/$(test)/src/*.c)))
FW_TEST_SRCS_coremark += $(FW_DIR)/tests/core_portme.c
FW_TEST_INCLUDES := -I$(FW_DIR)/tests $(addprefix -I,$(wildcard $(FW_DIR)/tests/*/inc $(FW_DIR)/tests/*/include))
# Test sources predate strict prototypes / native register headers; keep these
# relaxations so they compile unchanged.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-incompatible-pointer-types \
  -Wno-implicit-function-declaration \
  -Wno-implicit-int \
  -Wno-strict-prototypes
FW_TEST_LINKER_SCRIPT := $(FW_DIR)/common/metal/smc/scratch_pad.ld
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
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).bin" --data_width 8 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).bin" --data_width 1 --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).hex" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi" --out_file "$(FW_TEST_BUILD_DIR)/$(2)/$(2).spi_preload"
endef

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
