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
- `irq_en`   — gate `irq_o`. When 0, a detected hang is suppressed (counter still runs).
- `irq_test` — force `irq_o` high without a real stall. Software self-test only; the
  detector does **not** need this to catch a real hang.

`HANG_DET_<master>_TIMEOUT_THRESHOLD`

- `value` — number of consecutive stalled cycles before firing. **0 disables the
  detector.** Default `0x1000`. 20 bits → up to ~1M cycles (~1 ms at 1 GHz).

## Programming order (firmware)

1. Write `TIMEOUT_THRESHOLD.value` to a non-zero count appropriate for the bus
   (smaller = faster detection, but must exceed the longest legitimate stall).
2. Write `CTRL` with `enable = 1` and `irq_en = 1` to arm the detector.

The threshold is latched when a stall window begins, so reprogramming it mid-stall
takes effect on the next window. To disable a detector, clear `CTRL.enable` (or set
`TIMEOUT_THRESHOLD.value = 0`). Use `CTRL.irq_test = 1` only to verify the interrupt
path during bring-up.
