/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Firmware Linker Script - all-in-ROM images (no VROM) */
/* For testbenches that load only the physical KM ROM and side-load nothing:
 * main, .text, .rodata and the .data load image must all reside in ROM. The
 * layout is the production one, so these images are linked against the same
 * geometry the production ROM is validated for. */

INCLUDE km_production.ld
