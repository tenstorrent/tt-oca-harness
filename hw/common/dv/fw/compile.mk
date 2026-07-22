# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_fw_common_mk
ocah_fw_common_mk := 1

# Shared DV firmware build engine. A subsystem fw.mk sets the FW_* inputs below,
# includes its toolchain.mk, then includes this for the build rules + all/clean.
#
# Inputs a subsystem defines before including this file:
#   FW_NAME          - short subsystem name (e.g. key_manager, sep, smc)
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
# Optional (enable per-test linked images through `dv-fw-tests`):
#   FW_TEST_LINKER_SCRIPT - linker script used for test images
#   FW_TEST_LDFLAGS       - extra/override test link flags (defaults to FW_LDFLAGS)
#   FW_TEST_INCLUDES      - extra test-only include flags
#   FW_TEST_EXTRA_CFLAGS  - extra test-only C flags
#   FW_TEST_EXTRA_ARCHIVES - optional extra archives linked after lib<name>.a
#   FW_TEST_POSTPROCESS   - make macro called as $(call ...,elf_path,test_name)
# Test discovery is unified below (canonical tests/<name>/<name>.c); a subsystem
# declares only deltas:
#   FW_TEST_EXCLUDE_NAMES   - test dir names to skip
#   FW_TEST_EXTRA_SRCS_<t>  - extra .c compiled into test <t> (e.g. coremark)
# A bespoke layout opts out by pre-setting FW_TEST_NAMES (+ FW_TEST_SRCS_<t>).

# Parallelize object compiles / test links by default (same pattern as
# regen-regs). Explicit -j / --jobs on the command line wins.
OCAH_DV_FW_JOBS ?= 8
ifeq ($(filter -j% --jobs%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(OCAH_DV_FW_JOBS)
endif

# Toolchain resolution. RISCV_TOOLCHAIN = dir of riscv64-unknown-elf-* tools, or
# empty to use the toolchain on PATH (provisioned via Docker).
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= riscv64-unknown-elf-

ifeq ($(strip $(RISCV_TOOLCHAIN)),)
OCAH_FW_TOOL_PREFIX := $(RISCV_PREFIX)
else
OCAH_FW_TOOL_PREFIX := $(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(RISCV_PREFIX)
endif

# ':=' because CC/AR are Make built-ins ('?=' wouldn't take); cmdline still wins.
# AR/RANLIB use gcc-* wrappers so the LTO plugin indexes -flto archives.
CC      := $(OCAH_FW_TOOL_PREFIX)gcc
AR      := $(OCAH_FW_TOOL_PREFIX)gcc-ar
RANLIB  := $(OCAH_FW_TOOL_PREFIX)gcc-ranlib
OBJCOPY := $(OCAH_FW_TOOL_PREFIX)objcopy
OBJDUMP := $(OCAH_FW_TOOL_PREFIX)objdump
NM      := $(OCAH_FW_TOOL_PREFIX)nm
SIZE    := $(OCAH_FW_TOOL_PREFIX)size

# picolibc spec file shared by every subsystem toolchain; default here so the
# per-subsystem toolchain.mk files do not repeat it.
FW_PICOLIBC_SPECS ?= picolibc.specs

# Register -I flags for a sys subsystem (umbrella + generated headers + shim/ip
# trees). A sys sets FW_REG_SYS; leaf IP subsystems leave it unset.
ocah_fw_reg_includes = $(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_$(1)) \
  -I$(OCAH_ROOT)/hw/common/dv/fw \
  -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c/blocks \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/sys/$(1)/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/common/axi/*/regs/gen/c))
FW_INCLUDES += $(if $(strip $(FW_REG_SYS)),$(call ocah_fw_reg_includes,$(FW_REG_SYS)))

# Derived build variables.
FW_BUILD_DIR ?= $(FW_DIR)/build

FW_C_OBJS   := $(addprefix $(FW_BUILD_DIR)/,$(notdir $(FW_C_SRCS:.c=.o)))
FW_ASM_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ASM_SRCS)))))
FW_LIB_OBJS := $(FW_C_OBJS) $(FW_ASM_OBJS)

FW_ENTRY_OBJS := $(addprefix $(FW_BUILD_DIR)/,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(notdir $(FW_ENTRY_SRCS:.c=.o)))))

FW_ARCHIVE := $(FW_BUILD_DIR)/lib$(FW_NAME).a
FW_ELF     := $(FW_BUILD_DIR)/$(FW_NAME).elf

FW_TEST_BUILD_DIR ?= $(FW_BUILD_DIR)/tests
FW_TEST_LDFLAGS ?= $(FW_LDFLAGS)
FW_TEST_INCLUDES ?=
FW_TEST_EXTRA_CFLAGS ?=
FW_TEST_EXTRA_ARCHIVES ?=
FW_TEST_COMMON_SRCS ?=
FW_TEST_ARCHIVE_LINK ?= -Wl,--whole-archive "$(FW_ARCHIVE)" $(FW_TEST_EXTRA_ARCHIVES) -Wl,--no-whole-archive

# Unified DV test discovery: one testcase per tests/<name>/ (plus sibling .c),
# tests/common/ reserved for shared helpers. Opt out by pre-setting FW_TEST_NAMES.
ifndef FW_TEST_NAMES
FW_TEST_SRCS := $(filter-out \
  $(FW_DIR)/tests/common/% \
  $(foreach t,$(FW_TEST_EXCLUDE_NAMES),$(FW_DIR)/tests/$(t)/%), \
  $(wildcard $(FW_DIR)/tests/*/*.c))
FW_TEST_NAMES := $(sort $(notdir $(patsubst %/,%,$(dir $(FW_TEST_SRCS)))))
$(foreach t,$(FW_TEST_NAMES),$(eval FW_TEST_SRC_$(t) := $(firstword $(wildcard $(FW_DIR)/tests/$(t)/*.c))))
$(foreach t,$(FW_TEST_NAMES),$(eval FW_TEST_SRCS_$(t) := $(wildcard $(FW_DIR)/tests/$(t)/*.c) $(FW_TEST_EXTRA_SRCS_$(t))))
endif

FW_TEST_SELECTED := $(if $(strip $(TEST)),$(strip $(TEST)),$(FW_TEST_NAMES))
FW_TEST_ELFS := $(foreach t,$(FW_TEST_SELECTED),$(FW_TEST_BUILD_DIR)/$(t)/$(t).elf)

# Let the pattern rules below find sources regardless of subdirectory.
vpath %.c $(sort $(dir $(FW_C_SRCS) $(FW_ENTRY_SRCS)))
vpath %.S $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))
vpath %.s $(sort $(dir $(FW_ASM_SRCS) $(FW_ENTRY_SRCS)))

DEPFLAGS := -MMD -MP

# Optional extra compile flags from the make command line (e.g. a register stub).
FW_EXTRA_CFLAGS ?=

$(FW_BUILD_DIR):
	@mkdir -p "$@"

$(FW_BUILD_DIR)/%.o: %.c | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_CFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.S | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

$(FW_BUILD_DIR)/%.o: %.s | $(FW_BUILD_DIR) ocah-fw-check-toolchain
	$(CC) $(FW_ASFLAGS) $(FW_INCLUDES) $(FW_EXTRA_CFLAGS) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

# Runtime library archive; DV tests / production entries link against it.
$(FW_ARCHIVE): $(FW_LIB_OBJS)
	@rm -f "$@"
	$(AR) rcs "$@" $(FW_LIB_OBJS)
	$(SIZE) -t $(FW_LIB_OBJS) | tail -n 1

.PHONY: ocah-fw-lib
ocah-fw-lib: $(FW_ARCHIVE)

$(FW_TEST_BUILD_DIR)/%/.dir:
	@mkdir -p "$(@D)"
	@touch "$@"

ifndef FW_TEST_POSTPROCESS
define FW_TEST_POSTPROCESS
endef
endif

define ocah_fw_test_obj_rule
$(FW_TEST_BUILD_DIR)/$(1)/$(notdir $(2:.c=.o)): $(2) | $(FW_TEST_BUILD_DIR)/$(1)/.dir ocah-fw-check-toolchain
	$$(CC) $$(FW_CFLAGS) $$(FW_INCLUDES) $$(FW_TEST_INCLUDES) $$(FW_EXTRA_CFLAGS) $$(FW_TEST_EXTRA_CFLAGS) $$(DEPFLAGS) -c "$$<" -o "$$@"
endef

define ocah_fw_test_rules
FW_TEST_SRCS_FOR_$(1) := $$(if $$(strip $$(FW_TEST_SRCS_$(1))),$$(FW_TEST_SRCS_$(1)),$$(FW_TEST_SRC_$(1))) $$(FW_TEST_COMMON_SRCS)
FW_TEST_OBJS_$(1) := $$(addprefix $(FW_TEST_BUILD_DIR)/$(1)/,$$(notdir $$(FW_TEST_SRCS_FOR_$(1):.c=.o)))
$$(foreach src,$$(FW_TEST_SRCS_FOR_$(1)),$$(eval $$(call ocah_fw_test_obj_rule,$(1),$$(src))))

$(FW_TEST_BUILD_DIR)/$(1)/$(1).elf: $$(FW_TEST_OBJS_$(1)) $$(FW_ARCHIVE) $$(FW_TEST_EXTRA_ARCHIVES) $$(FW_TEST_LINKER_SCRIPT) | $(FW_TEST_BUILD_DIR)/$(1)/.dir ocah-fw-check-toolchain
	$$(CC) $$(FW_TEST_LDFLAGS) -Wl,-Map="$(FW_TEST_BUILD_DIR)/$(1)/$(1).map" -T "$$(FW_TEST_LINKER_SCRIPT)" $$(FW_TEST_OBJS_$(1)) $$(FW_TEST_ARCHIVE_LINK) -o "$$@"
	$$(OBJDUMP) -DCSsx "$$@" > "$(FW_TEST_BUILD_DIR)/$(1)/$(1).dis"
	$$(NM) -B -n "$$@" > "$(FW_TEST_BUILD_DIR)/$(1)/$(1).sym"
	$$(SIZE) "$$@"
	$$(call FW_TEST_POSTPROCESS,$$@,$(1))
endef

$(foreach test,$(FW_TEST_NAMES),$(eval $(call ocah_fw_test_rules,$(test))))

# Validate the test selection at parse time, but only for dv-fw-tests (TEST may
# be set for other goals and must not break all/clean).
ifneq ($(filter dv-fw-tests,$(MAKECMDGOALS)),)
ifeq ($(strip $(FW_TEST_NAMES)),)
$(error no FW C tests configured for $(FW_NAME))
endif
ifneq ($(strip $(TEST)),)
ifeq ($(strip $(FW_TEST_SRC_$(strip $(TEST)))$(FW_TEST_SRCS_$(strip $(TEST)))),)
$(error unknown $(FW_NAME) FW C test '$(strip $(TEST))'; known tests: $(FW_TEST_NAMES))
endif
endif
endif

.PHONY: dv-fw-tests
dv-fw-tests: $(FW_TEST_ELFS)

.PHONY: dv-fw-test-list
dv-fw-test-list:
	@printf '%s\n' $(FW_TEST_NAMES)

# Linked image: only when the subsystem provides a linker script + entry.
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
		echo "put the toolchain on PATH, or run via the toolchain container:"; \
		echo "  ./scripts/docker-run.sh run make dv-fw-libs TARGET=<subsystem>"; \
		exit 1; \
	}

FW_TEST_DEPFILES := $(foreach t,$(FW_TEST_NAMES),$(FW_TEST_OBJS_$(t):.o=.d))

-include $(FW_LIB_OBJS:.o=.d) $(FW_ENTRY_OBJS:.o=.d) $(FW_TEST_DEPFILES)

endif
