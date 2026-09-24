# RobStride CLI Manual Test Commands

This file records copyable manual test commands for comparing the Rust/Core CLI
and the Python CLI RobStride paths.

## 0. Replace These Values First

Use values that match your hardware:

```text
CHANNEL=can0
MODEL=rs-00
MID=127
FID=0xFD
```

RobStride note: `FID` / `feedback-id` is the host ID, not the motor/device ID.
Common host IDs are `0xFD`, `0xFF`, `0xFE`, `0x00`, `0xAA`.

For write tests, prefer a safe writable runtime parameter first:

```text
PARAM_ID=0x7017
PARAM_TYPE=f32
TEST_VALUE=1.0
```

`0x7017` is `limit_spd`, `f32`, W/R. The commands below use `store=0` by
default, so they do not intentionally persist the value to flash.

Do not use read-only parameters for write tests. For example `0x7019 mechPos`
is read-only and should be used only for read checks.

## 1. Build / Import Smoke Test

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --help
```

Python CLI from an installed package:

```bash
motorbridge-cli --help
```

Python CLI from this source tree:

```bash
PYTHONPATH=bindings/python/src python -m motorbridge.cli --help
```

Windows PowerShell source-tree variant:

```powershell
$env:PYTHONPATH="bindings/python/src"; python -m motorbridge.cli --help
```

## 2. Scan

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --mode scan --start-id 1 --end-id 127 --feedback-ids 0xFD,0xFF,0xFE,0x00,0xAA
```

Python CLI:

```bash
motorbridge-cli scan --vendor robstride --channel can0 --model rs-00 --start-id 1 --end-id 127 --feedback-ids 0xFD,0xFF,0xFE,0x00,0xAA
```

Python CLI from source tree:

```bash
PYTHONPATH=bindings/python/src python -m motorbridge.cli scan --vendor robstride --channel can0 --model rs-00 --start-id 1 --end-id 127 --feedback-ids 0xFD,0xFF,0xFE,0x00,0xAA
```

Expected: at least one `vendor=robstride` hit for the real device ID.

## 3. Ping

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode ping
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode ping --loop 1
```

Expected: ping returns device/responder information, or the RobStride fallback
parameter query responds.

## 4. Read A Read-Only Parameter

Use this to prove the read path works without changing motor settings.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode read-param --param-id 0x7019
```

Python CLI, run-mode form:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode read-param --param-id 0x7019 --param-type f32 --timeout-ms 500
```

Python CLI, dedicated subcommand:

```bash
motorbridge-cli robstride-read-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7019 --type f32 --timeout-ms 500
```

Expected: value for `0x7019 mechPos`.

## 5. Read A Writable Parameter Before Changing It

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode read-param --param-id 0x7017
```

Python CLI:

```bash
motorbridge-cli robstride-read-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7017 --type f32 --timeout-ms 500
```

Expected: current `limit_spd` value.

## 6. Write A Writable Parameter And Read Back

Keep the motor in a safe/disabled state before doing parameter writes.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode write-param --param-id 0x7017 --param-value 1.0 --store 0
```

Python CLI, run-mode form:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode write-param --param-id 0x7017 --param-type f32 --param-value 1.0 --timeout-ms 500 --store 0
```

Python CLI, dedicated subcommand:

```bash
motorbridge-cli robstride-write-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7017 --type f32 --value 1.0 --verify 1 --store 0 --timeout-ms 500
```

Expected: write command succeeds and verify/readback is close to `1.0`.

## 7. Read Again After Write

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode read-param --param-id 0x7017
```

Python CLI:

```bash
motorbridge-cli robstride-read-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7017 --type f32 --timeout-ms 500
```

Expected: value is still close to the last test value while the device remains
powered.

## 8. Optional Restore Original Value

If the original value from step 5 was different, restore it manually.
Replace `ORIGINAL_VALUE` before running.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode write-param --param-id 0x7017 --param-value ORIGINAL_VALUE --store 0
```

Python CLI:

```bash
motorbridge-cli robstride-write-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7017 --type f32 --value ORIGINAL_VALUE --verify 1 --store 0 --timeout-ms 500
```

Expected: readback equals the original value.

## 9. Optional Persist Parameter

Only run this after verifying the value is correct and safe for the motor.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode write-param --param-id 0x7017 --param-value 1.0 --store 1
```

Python CLI:

```bash
motorbridge-cli robstride-write-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7017 --type f32 --value 1.0 --verify 1 --store 1 --timeout-ms 500
```

Expected: write succeeds, readback succeeds, and save/store is requested.

## 10. Save Parameters Only

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode save
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode save --loop 1
```

Expected: save/store request is sent.

## 11. Active Report Toggle

Enable active report:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode active-report --active-report 1
```

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode active-report --active-report 1 --loop 1
```

Disable active report:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode active-report --active-report 0
```

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode active-report --active-report 0 --loop 1
```

Expected: command succeeds. If firmware does not acknowledge, inspect whether
subsequent status/feedback behavior changed.

## 12. Clear Error

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode clear-error
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode clear-error --loop 1
```

Expected: clear-error request succeeds or reports an ack timeout warning only.

## 13. Enable / Disable

Enable:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode enable --loop 1
```

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode enable --loop 1
```

Disable:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode disable --loop 1
```

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode disable --loop 1
```

Expected: command succeeds or reports an ack timeout warning only.

## 14. MIT Control Smoke Test

Run only with the motor safely mounted or unloaded.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode mit --ensure-mode 1 --pos 0 --vel 0 --kp 5 --kd 0.2 --tau 0 --loop 20 --dt-ms 20
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode mit --ensure-mode 1 --pos 0 --vel 0 --kp 5 --kd 0.2 --tau 0 --loop 20 --dt-ms 20
```

Expected: mode switch succeeds and control frames are sent without fault.

## 15. Position-Velocity Control Smoke Test

Run only with the motor safely mounted or unloaded.

RobStride `pos-vel` maps to the native parameter path:

- effective: `--pos` -> `loc_ref`, `--vlim` -> `limit_spd`, `--loc-kp` -> `loc_kp`
- fallback: `--kp` is used as `loc_kp` only when `--loc-kp` is omitted
- ignored with warning: `--vel`, `--kd`, `--tau`

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode pos-vel --ensure-mode 1 --pos 0 --vlim 1.0 --loc-kp 1.0 --loop 20 --dt-ms 20
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode pos-vel --ensure-mode 1 --pos 0 --vlim 1.0 --loc-kp 1.0 --loop 20 --dt-ms 20
```

Expected: mode switch succeeds, `limit_spd` / `loc_kp` / `loc_ref` parameter
path works, and control frames are sent without fault.

## 16. Velocity Control Smoke Test

Run only with the motor safely mounted or unloaded.

Rust/Core CLI:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode vel --ensure-mode 1 --vel 0.2 --loop 20 --dt-ms 20
```

Python CLI:

```bash
motorbridge-cli run --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode vel --ensure-mode 1 --vel 0.2 --loop 20 --dt-ms 20
```

Expected: mode switch succeeds and the velocity target path works.

## 17. ID Change Dry-Run Style Check

This is not a dry-run command: it really changes the device ID. Only run when
you are prepared to recover the motor by scanning.

Change `127 -> 126`:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --mode ping --set-motor-id 126 --store 0
```

```bash
motorbridge-cli id-set --vendor robstride --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --new-motor-id 126 --store 0 --verify 1
```

Change `126 -> 127`:

```bash
cargo run -p motor_cli -- --vendor robstride --channel can0 --model rs-00 --motor-id 126 --feedback-id 0xFD --mode ping --set-motor-id 127 --store 0
```

```bash
motorbridge-cli id-set --vendor robstride --channel can0 --model rs-00 --motor-id 126 --feedback-id 0xFD --new-motor-id 127 --store 0 --verify 1
```

Expected: new ID responds to ping/scan. Use `--store 1` only after confirming
the new ID is correct.

## 18. Source-Tree Python CLI Variants

If `motorbridge-cli` is not installed, replace any Python CLI command with:

```bash
PYTHONPATH=bindings/python/src python -m motorbridge.cli ...
```

Example:

```bash
PYTHONPATH=bindings/python/src python -m motorbridge.cli robstride-read-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7019 --type f32 --timeout-ms 500
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="bindings/python/src"; python -m motorbridge.cli robstride-read-param --channel can0 --model rs-00 --motor-id 127 --feedback-id 0xFD --param-id 0x7019 --type f32 --timeout-ms 500
```

## 19. Pass / Fail Summary

Mark each pair manually:

```text
[ ] scan: Rust CLI / Python CLI
[ ] ping: Rust CLI / Python CLI
[ ] read 0x7019: Rust CLI / Python CLI
[ ] read 0x7017: Rust CLI / Python CLI
[ ] write 0x7017 store=0: Rust CLI / Python CLI
[ ] restore 0x7017: Rust CLI / Python CLI
[ ] optional store=1: Rust CLI / Python CLI
[ ] save: Rust CLI / Python CLI
[ ] active-report on/off: Rust CLI / Python CLI
[ ] clear-error: Rust CLI / Python CLI
[ ] enable/disable: Rust CLI / Python CLI
[ ] MIT smoke: Rust CLI / Python CLI
[ ] pos-vel smoke: Rust CLI / Python CLI
[ ] velocity smoke: Rust CLI / Python CLI
[ ] optional ID change/revert: Rust CLI / Python CLI
```
