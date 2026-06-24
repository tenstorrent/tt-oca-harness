# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# Example adopter register overlay.
#
# This file is intentionally inert: every assignment is commented out. Copy it
# into an adopter-controlled tree outside tt-oca, fill in the paths, and pass
# it to make with:
#
#   make regen-regs OCAH_ADOPTER_OVERLAY_MK=/path/to/overlay.mk
#
# The overlay should only register blocks that replace intentional OCAH shim
# placeholders or fill extension regions. Most OCAH IP register collateral is
# already generated and committed in the open tree.

# Root of the adopter overlay tree.
# OCAH_ADOPTER_OVERLAY_ROOT := /path/to/acme-overlay

# RDL directories supplied by the overlay. These paths usually mirror the open
# tree's dv/shims layout so canonical tops can keep bare `include names such as
# "pll_wrap.rdl" while the overlay's same-named RDL wins by search-path order.
# OCAH_ADOPTER_OVERLAY_SHIM_DIRS := \
#   $(OCAH_ADOPTER_OVERLAY_ROOT)/hw/sys/smc/dv/shims/regs \
#   $(OCAH_ADOPTER_OVERLAY_ROOT)/hw/sys/sep/dv/shims/regs \
#   $(OCAH_ADOPTER_OVERLAY_ROOT)/hw/ip/<ip>/dv/shims/regs

# Register overlay shim RDLs as standalone blocks. This generates collateral
# such as pll_wrap.h / pll_wrap_reg.sv under the overlay's containing regs/gen
# directory.
# OCAH_EXTRA_REG_RDL_FILES += $(foreach d,$(OCAH_ADOPTER_OVERLAY_SHIM_DIRS),$(wildcard $(d)/*.rdl))

# Register a subsystem-top variant. The block id below is only an example; its
# final path controls where generated top collateral lands unless GEN/BUILD
# overrides are provided.
# OCAH_EXTRA_REG_BLOCKS += acme/hw/sys/smc

# Make-safe key for acme/hw/sys/smc (slashes become underscores).
# OCAH_ACME_SMC_KEY := acme_hw_sys_smc

# Reuse the canonical top RDL, but resolve bare includes from the overlay shim
# directories first. The canonical top stays unmodified.
# OCAH_REG_RDL_OVERRIDE_$(OCAH_ACME_SMC_KEY) := $(OCAH_ROOT)/hw/sys/smc/regs/smc.rdl
# OCAH_REG_EXTRA_SEARCH_$(OCAH_ACME_SMC_KEY) := $(OCAH_ADOPTER_OVERLAY_SHIM_DIRS)

# Keep generated top collateral under the overlay tree instead of the open tree.
# OCAH_REG_GEN_OVERRIDE_$(OCAH_ACME_SMC_KEY) := $(OCAH_ADOPTER_OVERLAY_ROOT)/hw/sys/smc/regs/gen
# OCAH_REG_BUILD_OVERRIDE_$(OCAH_ACME_SMC_KEY) := $(OCAH_ADOPTER_OVERLAY_ROOT)/hw/sys/smc/regs/build
