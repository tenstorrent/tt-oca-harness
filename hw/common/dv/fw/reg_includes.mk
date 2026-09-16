# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Register -I flags for a sys subsystem (umbrella + generated headers + shim/ip
# trees). Separate from compile.mk because the SEP boot ROM drives its own build
# but has to see exactly the same headers.

ifndef ocah_fw_reg_includes_mk
ocah_fw_reg_includes_mk := 1

# The overlay dirs come first: where a vendor variant of a header exists, it is
# the one that resolves the proprietary shims and must shadow the open copy.
ocah_fw_reg_includes = $(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_$(1)) \
  -I$(OCAH_ROOT)/hw/common/dv/fw \
  -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c -I$(OCAH_ROOT)/hw/sys/$(1)/regs/gen/c/blocks \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/sys/$(1)/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/models/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/rdl/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/regs/*/regs/gen/c))

# A standalone build (no nonfree sub-make to export the overlay) still gets the
# vendor view when it knows where the nonfree tree is.
ocah_fw_nonfree_reg_includes = $(if $(NONFREE_ROOT), \
  -I$(NONFREE_ROOT)/hw/sys/$(1)/regs/gen/c \
  -I$(NONFREE_ROOT)/hw/sys/$(1)/regs/gen/c/blocks \
  $(addprefix -I,$(wildcard $(NONFREE_ROOT)/hw/sys/$(1)/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(NONFREE_ROOT)/hw/sys/$(1)/dv/shims/regs/vendor/*/*/gen/c)) \
  $(addprefix -I,$(wildcard $(NONFREE_ROOT)/hw/ip/*/dv/shims/vendor/*/regs/gen/c)))

endif
