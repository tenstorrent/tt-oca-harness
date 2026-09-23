# AXI Hang Detector

Works with `prim_axi_snoop` to flag a hung AXI bus: it watches a (non-intrusive)
snoop of one AXI master and raises `irq_o` when transactions stay outstanding for
a programmable number of cycles with no completion. In the SMC there is one
detector per independent master (sys_axi, sep_axi, data_accel); their `irq_o`s are
OR'd into a single fault line for the safety island.

`irq_o` is a direct combinational **level**: high while the bus is
hung, dropping on its own once the bus makes progress (no software clear needed).

## Registers (per detector, in `cpu_ctrl`)

`HANG_DET_<master>_CTRL`

- `enable`   — run the detector. When 0, the counter is held and `irq_o` is forced low.
- `irq_en`   — gate `irq_o`. When 0, both a detected hang and `irq_test` are suppressed
  (the counter still runs).
- `irq_test` — assert `irq_o` without a real stall, subject to `enable` and `irq_en`.
  Software self-test only; the detector does **not** need this to catch a real hang.

`HANG_DET_<master>_TIMEOUT_THRESHOLD`

- `value` — number of consecutive stalled cycles before firing. Default `0x1000`.
  20 bits → up to ~1M cycles (~1 ms at 1 GHz). **0 disables timeout detection**: a
  stalled bus never fires, though `irq_test` still asserts `irq_o`.

## Programming order (firmware)

1. Write `TIMEOUT_THRESHOLD.value` to a non-zero count appropriate for the bus
   (smaller = faster detection, but must exceed the longest legitimate stall).
2. Write `CTRL` with `enable = 1` and `irq_en = 1` to arm the detector.

The stall count restarts whenever a transaction completes, the bus goes idle, or
`CTRL.enable` is cleared, and picks up the current threshold at that restart. A write
therefore lands on the next stall rather than the one being timed: raising the
threshold does not extend a stall in progress, and lowering it — or writing `0` —
neither cuts that stall short nor clears an `irq_o` that is already asserted.

To disable a detector, clear `CTRL.enable`; that takes effect at once and silences
`irq_test` too. `TIMEOUT_THRESHOLD.value = 0` is not equivalent: it takes effect at
the next stall count restart and leaves `CTRL.irq_test` able to assert `irq_o`. Use
`CTRL.irq_test = 1` only to verify the interrupt path during bring-up.

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut axi_hang_detector`).

The SMC integration — the three detectors' `cpu_ctrl` configuration, real bus
stalls, the OR into the safety-island fault line, and the PLIC route — is covered
by the `smc_hang_detector_*` tests in `hw/sys/smc/dv/testlists/irq.toml`.
