# DM Device SDK Third-Party Runtime

This directory vendors the DaMiao DM_Device SDK binaries used by the
`dm-device` transport.

It exists so motorbridge can build, run, and package the USB/CAN adapter
support without depending on a developer's local copy of
`dm-device-sdk/C&C++/lib/v1.1.0`.

## Hardware Scope In Motorbridge

DaMiao DM_Device_SDK is a software development kit for controlling CAN/CAN FD
adapter devices. The SDK exposes these device families, and motorbridge maps
them as follows:

| SDK Device Type | SDK Enum | Physical Channels | motorbridge `--dm-device-type` | motorbridge `--dm-channel` |
|---|---|---:|---|---|
| USB2CANFD | `USB2CANFD` | 1 CAN FD channel | `usb2canfd` | `0` or SDK channel `0` |
| USB2CANFD_DUAL | `USB2CANFD_DUAL` | 2 CAN FD channels | `usb2canfd-dual` | `0` / `1` |
| LINKX4C | `LINKX4C` | 4 CAN channels | `linkx4c` | SDK channels `0` / `1` / `2` / `3` |

Important scope notes:

- motorbridge's `dm-device` transport is currently intended for Damiao motors
  only. The SDK can send generic CAN/CAN FD frames, but the motorbridge vendor
  controller layered on this transport is the Damiao protocol path.
- The adapter must be configured/connected in USB mode. Non-USB operating modes
  of a multi-interface adapter are outside this transport path.
- In scan mode, omitting `--dm-channel` scans every channel for the selected
  device type: one channel for `usb2canfd`, two channels for
  `usb2canfd-dual`, and four channels for `linkx4c`.

## Contents

`v1.1.0/dmcan.h`

- C/C++ SDK header from DaMiao.
- Used at build time by `motor_core/src/dm_device_shim.cpp`.

`v1.1.0/linux/*/libdm_device.so`

- Linux runtime libraries for the supported CPU architectures.

`v1.1.0/macos/*/libdm_device.dylib`

- macOS runtime libraries for the supported CPU architectures.

`v1.1.0/windows/*`

- Windows runtime/import libraries for MSVC and MinGW builds.

## User Runtime Setup

Python wheels do not embed these vendor runtime libraries. When a user runs
`Controller.from_dm_device(...)`, `motorbridge-cli --transport dm-device`, or
`motorbridge-gateway --transport dm-device`, motorbridge first tries to find the
matching runtime in these places:

1. `MOTOR_DM_DEVICE_LIB=/absolute/path/to/<runtime>`
2. A source checkout path:
   `third_party/dm_device/v1.1.0/<platform>/<arch>/<runtime>`
3. A user cache path:
   `~/.cache/motorbridge/dm_device/v1.1.0/<platform>/<arch>/<runtime>`
   or `$XDG_CACHE_HOME/motorbridge/dm_device/v1.1.0/...`

If the file is missing, motorbridge prints the required runtime path and a
download URL. The canonical download page is:

```text
https://github.com/motorbridge/motorbridge/tree/main/third_party/dm_device
```

Example for Linux x86_64:

```bash
mkdir -p ~/.cache/motorbridge/dm_device/v1.1.0/linux/x86_64
curl -L \
  -o ~/.cache/motorbridge/dm_device/v1.1.0/linux/x86_64/libdm_device.so \
  https://raw.githubusercontent.com/motorbridge/motorbridge/main/third_party/dm_device/v1.1.0/linux/x86_64/libdm_device.so

# Or point directly at a manually downloaded SDK file:
export MOTOR_DM_DEVICE_LIB=/absolute/path/to/libdm_device.so
```

The helper command prints the same guidance:

```bash
motorbridge-install-dm-device
```

It downloads only when explicitly requested:

```bash
motorbridge-install-dm-device --download
```

## Platform Support Rule

`dm-device` support is intentionally tied to the SDK runtime libraries that are
actually present in this directory. During `motor_core` build, `build.rs` maps
the Rust target platform to one expected SDK runtime path:

| Rust target | SDK runtime path |
|---|---|
| `x86_64-unknown-linux-*` | `linux/x86_64/libdm_device.so` |
| `aarch64-unknown-linux-*` | `linux/arm64/libdm_device.so` |
| `aarch64-apple-darwin` | `macos/arm64/libdm_device.dylib` |
| `x86_64-apple-darwin` | `macos/x86_64/libdm_device.dylib` |
| `x86_64-pc-windows-msvc` | `windows/msvc/dm_device.dll` |
| `x86_64-pc-windows-gnu` | `windows/mingw/libdm_device.dll` |

If the mapped file exists, motorbridge compiles the C++ shim and enables the
real `DmDeviceBus`. If the mapped file is missing, motorbridge still builds for
that target, but `--transport dm-device` reports that DM_Device SDK is not
bundled for the platform. In other words, adding/removing SDK runtime files here
is what controls which architectures support `dm-device`.

## Support Matrix

| Platform / Architecture | Runtime Path | Python Wheel | `dm-device` Runtime | OS/runtime ABI notes | Hardware Verified |
|---|---|---|---|---|---|
| Linux x86_64 | `v1.1.0/linux/x86_64/libdm_device.so` | yes | supported | needs `libusb-1.0.so.0`, `libstdc++.so.6` with `GLIBCXX_3.4.32`, `GLIBC_2.14+` | yes, USB2CANFD_DUAL channel 0/1 and LINKX4C channel `0..3` scan |
| Linux aarch64 / arm64 | `v1.1.0/linux/arm64/libdm_device.so` | yes | supported | needs `libusb-1.0.so.0`, `GLIBC_2.17+`, `GLIBCXX_3.4.22+` | pending host validation |
| Windows x86_64 MSVC | `v1.1.0/windows/msvc/dm_device.dll` | yes | supported | needs libusb runtime/driver and Microsoft Visual C++ runtime (`MSVCP140*.dll`, `VCRUNTIME140*.dll`) | pending host validation |
| Windows x86_64 MinGW | `v1.1.0/windows/mingw/libdm_device.dll` | ABI/CLI build support | supported | needs `libusb-1.0.dll`, `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, Universal CRT | pending host validation |
| macOS arm64 | `v1.1.0/macos/arm64/libdm_device.dylib` | yes | supported | links system `libc++`, `libSystem`, `libobjc`; final OS floor pending macOS host validation | pending host validation |
| macOS x86_64 | `v1.1.0/macos/x86_64/libdm_device.dylib` | no official wheel | source/manual install only | links system `libc++`, `libSystem`, `libobjc`; final OS floor pending macOS host validation | pending host validation |
| Other OS/arch | none | no | unsupported | unsupported | unsupported |

Linux dependency checks:

```bash
# Check the vendor library's declared dynamic dependencies.
readelf -d third_party/dm_device/v1.1.0/linux/x86_64/libdm_device.so

# Check whether the host libstdc++ provides the required GLIBCXX symbol.
strings /usr/lib/x86_64-linux-gnu/libstdc++.so.6 | grep GLIBCXX_3.4.32

# Check libusb runtime availability.
ldconfig -p | grep libusb-1.0.so.0
```

The Linux x86_64 `GLIBCXX_3.4.32` requirement is the reason Python manylinux
wheels do not embed `libdm_device.so`: `auditwheel` rejects wheels carrying a
vendor library that depends on newer libstdc++ symbols than the manylinux
policy allows.

## Relationship To Motorbridge

The integration has three layers:

1. `third_party/dm_device`

   Stores the vendor SDK header and platform runtime libraries.

2. `motor_core/src/dm_device_shim.cpp`

   A small C++ shim that talks directly to the DaMiao SDK. It dynamically
   loads `libdm_device.so`/`.dylib`/`.dll`, opens the adapter, configures
   channels, sends CAN frames, receives SDK callbacks, and exposes a small C
   ABI (`mb_dm_open`, `mb_dm_send`, `mb_dm_recv`, `mb_dm_shutdown`).

3. `motor_core/src/dm_device.rs`

   The Rust transport wrapper. It calls the shim C ABI and implements
   motorbridge's `CanBus` trait, so vendor controllers can use DM_Device in
   the same style as SocketCAN, CAN-FD, or `dm-serial`.

After that, vendor code such as the Damiao controller can simply open:

```text
--transport dm-device
--dm-device-type usb2canfd
--dm-channel 0
```

or:

```text
--transport dm-device
--dm-device-type usb2canfd-dual
--dm-channel 0
```

or:

```text
--dm-channel 1
```

or:

```text
--transport dm-device
--dm-device-type linkx4c
--dm-channel 0
```

For `motor_cli --mode scan`, omit `--dm-channel` to scan every physical channel
for the selected adapter. Pass a number only when you want one physical channel.

## Why A C++ Shim Exists

The DaMiao SDK header exposes C++-shaped types and callback structs. In
particular, the receive frame layout uses SDK-defined structs/bitfields. That
layout is fragile to reproduce directly in Rust FFI.

The C++ shim keeps the SDK boundary in C++, where `dmcan.h` is native and the
frame layout is interpreted by the compiler that sees the real SDK header.
Rust then talks only to a small, stable C ABI with plain types:

- integers
- byte arrays
- pointers
- fixed-size frame structs

This makes the Rust side simpler and safer.

The shim also mirrors the known-good C++ diagnostic tool behavior. On Linux,
the SDK/libusb teardown path was observed to leave the USB adapter in a bad
state or print repeated `libusb_transfer_cancelled` messages. For that reason,
`mb_dm_shutdown` unregisters motorbridge's callback/queue state but deliberately
does not call the SDK close/destroy functions.

## Current Scope

Currently supported through motorbridge:

- `usb2canfd`
- `usb2canfd-dual`
- `linkx4c`
- `0` / `1` channel selection for CAN FD adapters
- SDK channel `0..3` selection for `linkx4c`
- classic CAN frames up to 8 bytes
- standard and extended CAN identifiers

Known current limits:

- The active implementation sends classic CAN frames, not 64-byte CAN-FD
  payloads.
- Multi-channel adapters open/configure all physical channels, then filter
  RX/TX to the selected `--dm-channel`.
- The first matching DM_Device adapter is opened; there is not yet a serial
  number/device-index selector.
- The SDK appears to be exclusive per USB adapter. Do not open the same
  DM_Device USB adapter from two motorbridge processes at the same time.

## Packaging

Python packaging intentionally does not copy `libdm_device.so`/`.dylib`/`.dll`
into wheels. This avoids manylinux `auditwheel` failures caused by the vendor
Linux library's newer `GLIBCXX` dependency, and keeps the vendor runtime setup
explicit.

For development or diagnostics, `MOTOR_DM_DEVICE_LIB` can be set manually to
override the library path. Source-tree runs also resolve files placed under
`third_party/dm_device/v1.1.0/...`.

## Updating The SDK

When updating DaMiao DM_Device SDK:

1. Add the new SDK files under a new version directory, for example
   `third_party/dm_device/v1.2.0`.
2. Update `motor_core/build.rs` include path if the header version changes.
3. Update `motor_core/src/dm_device.rs` runtime search paths.
4. Rebuild `motor_core`, `motor_abi`, and `motor_cli`.
5. Test all supported adapter/channel mappings available on your bench:

```text
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type usb2canfd --model 4310 --mode scan --start-id 1 --end-id 16
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type usb2canfd-dual --model 4310 --mode scan --start-id 1 --end-id 16
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type usb2canfd-dual --dm-channel 0 --model 4310 --mode scan --start-id 1 --end-id 16
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type usb2canfd-dual --dm-channel 1 --model 4310 --mode scan --start-id 1 --end-id 16
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type linkx4c --model 4310 --mode scan --start-id 1 --end-id 16
cargo run -p motor_cli -- --vendor damiao --transport dm-device --dm-device-type linkx4c --dm-channel 0 --model 4310 --mode scan --start-id 1 --end-id 16
```
