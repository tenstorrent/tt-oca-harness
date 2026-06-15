# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_fw_common_mk
ocah_fw_common_mk := 1

# Shared DV-firmware build engine + RISC-V bare-metal toolchain contract.
#
# A subsystem fw.mk sets a handful of variables, includes its own toolchain.mk
# (ISA/ABI/libc flags), then includes this file to get the build rules and the
# standard `all` / `clean` targets. Nothing here is subsystem specific.
#
# Inputs a subsystem is expected to define BEFORE including this file:
#   FW_NAME          - short subsystem name (e.g. km, sep, smc)
#   FW_DIR           - absolute path to the subsystem dv/fw directory
#   FW_C_SRCS        - library C sources (no entry/main)
#   FW_ASM_SRCS      - library .s/.S startup/helper sources
#   FW_INCLUDES      - -I include flags
#   FW_CFLAGS        - C compile flags (from toolchain.mk + subsystem)
#   FW_ASFLAGS       - assembler flags (from toolchain.mk + subsystem)
#   FW_LDFLAGS       - link flags (from toolchain.mk + subsystem)
# Optional (enable a linked image instead of just an archive):
#   FW_LINKER_SCRIPT - linker script path
#   FW_ENTRY_SRCS    - entry/main C/asm sources providing the image entry point

# --- Toolchain resolution -------------------------------------------------
#
# RISCV_TOOLCHAIN is intentionally empty by default: do NOT commit site-specific
# or proprietary toolchain paths. Provide it on the command line / environment to
# point at a directory containing the riscv64-unknown-elf-* tools, e.g.
#   make dv-fw TARGET=km RISCV_TOOLCHAIN=/opt/riscv/bin
# Leave it empty to use a toolchain already on PATH. The toolchain (including
# picolibc for SEP) is expected to be provisioned via the project Docker image,
# so nothing here fetches or vendors a toolchain or C library.
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= riscv64-unknown-elf-

ifeq ($(strip $(RISCV_TOOLCHAIN)),)
OCAH_FW_TOOL_PREFIX := $(RISCV_PREFIX)
else
OCAH_FW_TOOL_PREFIX := $(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(RISCV_PREFIX)
endif

# Use ':=' (not '?='): CC/AR are predefined by Make (cc/ar), so '?=' would not
# take effect. A command-line override (e.g. CC=...) still wins over ':='.
CC      := $(OCAH_FW_TOOL_PREFIX)gcc
AR      := $(OCAH_FW_TOOL_PREFIX)ar
OBJCOPY := $(OCAH_FW_TOOL_PREFIX)objcopy
OBJDUMP := $(OCAH_FW_TOOL_PREFIX)objdump
SIZE    := $(OCAH_FW_TOOL_PREFIX)size

# --- Derived build variables ---------------------------------------------
FW_BUILD_DIR ?= $(FW_DIR)/build

FW_C_OBJS   := $(addprefix $(FW_BUILD_DIR)/,$(notdir $(FW_C_SRCS:.c=.o)))
FW_ASM_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ASM_SRCS)))))
FW_LIB_OBJS := $(FW_C_OBJS) $(FW_ASM_OBJS)

FW_ENTRY_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ENTRY_SRCS:.c=.o)))))

FW_ARCHIVE := $(FW_BUILD_DIR)/lib$(FW_NAME)_fw.a
FW_ELF     := $(FW_BUILD_DIR)/$(FW_NAME).elf

# Let the single pattern rules below find sources regardless of subdirectory.
vpath %.c $(sort $(dir $(FW_C_SRCS) $(FW_ENTRY_SRCS)))
vpath %.S $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))
vpath %.s $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))

DEPFLAGS := -MMD -MP

$(FW_BUILD_DIR):
	@mkdir -p "$@"

$(FW_BUILD_DIR)/%.o: %.c | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_CFLAGS) $(FW_INCLUDES) $(DEPFLAGS) -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.S | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.s | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

# Runtime library archive: the portable proof that the ported sources compile
# and assemble with the subsystem toolchain. DV tests / production entries link
# against this archive.
$(FW_ARCHIVE): $(FW_LIB_OBJS)
	@rm -f "$@"
	$(AR) rcs "$@" $(FW_LIB_OBJS)
	$(SIZE) -t $(FW_LIB_OBJS) | tail -n 1

.PHONY: ocah-fw-lib
ocah-fw-lib: $(FW_ARCHIVE)

# Linked image (only when the subsystem provides a linker script + entry).
ifneq ($(strip $(FW_LINKER_SCRIPT)),)
ifneq ($(strip $(FW_ENTRY_SRCS)),)
$(FW_ELF): $(FW_ENTRY_OBJS) $(FW_ARCHIVE) $(FW_LINKER_SCRIPT)
	$(CC) $(FW_LDFLAGS) -T "$(FW_LINKER_SCRIPT)" $(FW_ENTRY_OBJS) $(FW_ARCHIVE) -o "$@"
	$(OBJCOPY) -O verilog --verilog-data-width 8 "$@" "$(FW_BUILD_DIR)/$(FW_NAME).hex"
	$(OBJDUMP) -DCSsx "$@" > "$(FW_BUILD_DIR)/$(FW_NAME).dis"
	$(SIZE) "$@"

.PHONY: ocah-fw-elf
ocah-fw-elf: $(FW_ELF)
FW_DEFAULT_GOAL := ocah-fw-elf
endif
endif

FW_DEFAULT_GOAL ?= ocah-fw-lib

.PHONY: all
all: $(FW_DEFAULT_GOAL)

.PHONY: clean
clean:
	@rm -rf "$(FW_BUILD_DIR)"

# Verify the cross compiler resolves; emit an actionable error otherwise.
.PHONY: ocah-fw-check-toolchain
ocah-fw-check-toolchain:
	@command -v "$(CC)" >/dev/null 2>&1 || { \
		echo "error: RISC-V toolchain not found (looking for '$(CC)')."; \
		echo "set RISCV_TOOLCHAIN=/path/to/bin (a directory with $(RISCV_PREFIX)* tools),"; \
		echo "or put the toolchain on PATH."; \
		exit 1; \
	}

-include $(FW_LIB_OBJS:.o=.d) $(FW_ENTRY_OBJS:.o=.d)

endif
