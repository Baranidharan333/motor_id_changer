# MotorBridge Scripts

Helper scripts for preparing known-good CAN adapters before running
`motor_cli`, `motorbridge-cli`, or `motorbridge-gateway`.

These scripts are Linux SocketCAN helpers. They work across Linux CPU
architectures such as x86_64, ARM64, Raspberry Pi, and Jetson, but they do not
run directly on Windows or macOS.

Current tested conclusion:

```text
PCAN-USB                         -> supported, stable control
CANable candleLight / gs_usb     -> supported as SocketCAN, test before control
Other USB-CAN adapters           -> unsupported unless they expose PCAN or candleLight/gs_usb
```

## Platform Support

| Platform | PCAN | CANable candleLight / gs_usb | Notes |
|---|---|---|---|
| Linux / Ubuntu | Supported. PEAK drivers: <https://www.peak-system.com/support/downloads/drivers/> | Supported | Use the scripts in this directory. |
| Windows | Needs PEAK driver: <https://www.peak-system.com/support/downloads/drivers/> | Needs compatible firmware and Windows tooling | These shell scripts do not run directly. |
| macOS | Needs PEAK macOS driver/runtime: <https://www.mac-can.com/> | Not covered by these scripts | Use vendor/runtime tooling, not SocketCAN scripts. |

On Linux, both supported paths must appear as SocketCAN interfaces before
MotorBridge can use `--transport socketcan --channel can0`.

## Recommended Path: PCAN

Use `can_restart.sh` for PEAK PCAN-USB adapters exposed as Linux SocketCAN
interfaces such as `can0` or `can1`.

```bash
scripts/can_restart.sh
scripts/can_restart.sh can0
scripts/can_restart.sh can1
scripts/can_restart.sh --bitrate 1000000 can0
```

Defaults:

- bitrate: `1000000`
- bus-off auto-restart: `restart-ms 100`
- loopback: `off`
- tx queue length: `2000`
- interfaces when omitted: `can0 can1`

Healthy PCAN output should contain:

```text
can state ERROR-ACTIVE (berr-counter tx 0 rx 0) restart-ms 100
bitrate 1000000
pcan_usb
```

Linux driver checks:

```bash
lsusb
lsmod | grep -E 'peak_usb|pcan|can_raw|can_dev'
ip -details link show type can
```

Expected `lsusb` examples:

```text
PEAK System PCAN-USB
PEAK-System Technik GmbH PCAN-USB
```

Expected Linux kernel modules:

```text
peak_usb
can_dev
can_raw
```

Expected interface details:

```text
can0: ... state ERROR-ACTIVE ...
pcan_usb
```

If the interface appears as `can1` instead of `can0`, use `can1` everywhere:

```bash
scripts/can_restart.sh can1
motorbridge-gateway -- --bind 127.0.0.1:9002 --vendor robstride --transport socketcan --channel can1
```

Recommended alias:

```bash
alias can_restart='/home/w0x7ce/Downloads/MOTOR_LIB/motorbridge/scripts/can_restart.sh'
```

Use PCAN for normal RobStride control and long-running Studio sessions.

Windows note for PCAN:

- Install the official PEAK PCAN driver / PCAN-Basic package.
- Windows does not use Linux SocketCAN names like `can0`.
- The scripts in this directory are not used on Windows.
- MotorBridge Windows support depends on the available backend/driver path; do
  not copy Linux `ip link` commands to Windows.

macOS note for PCAN:

- Install the required PEAK macOS runtime/driver if using PEAK hardware.
- `setup_pcbusb_macos.sh` is provided for the macOS PCBUSB runtime path.
- Linux SocketCAN scripts such as `can_restart.sh` do not apply on macOS.

## CANable

CANable is a board name, not one Linux driver. The currently supported CANable
path is candleLight/gs_usb firmware. It appears like this:

```text
lsusb: OpenMoko, Inc. Geschwister Schneider CAN adapter
ip -details link show can0: gs_usb
```

Use `canable_restart.sh` for this path:

```bash
scripts/canable_restart.sh
scripts/canable_restart.sh can0
scripts/canable_restart.sh --bitrate 1000000 can0
```

Defaults:

- bitrate: `1000000`
- loopback: `off`
- tx queue length: `2000`
- no `restart-ms` setting, because many `gs_usb` adapters reject bus-off restart

Check interfaces and drivers:

```bash
ip -details link show type can
lsusb
lsmod | grep -E 'can_raw|can_dev|gs_usb'
```

Expected `lsusb` example for the tested CANable/candleLight path:

```text
OpenMoko, Inc. Geschwister Schneider CAN adapter
ID 1d50:606f
```

Expected Linux kernel modules:

```text
gs_usb
can_dev
can_raw
```

Healthy CANable/candleLight output should contain:

```text
can state ERROR-ACTIVE
bitrate 1000000
gs_usb
```

Then use that interface in MotorBridge:

```bash
motorbridge-cli scan --vendor robstride --channel can0 --start-id 1 --end-id 127
motorbridge-gateway -- --bind 127.0.0.1:9002 --vendor robstride --transport socketcan --channel can0
```

Do not use `/dev/ttyACM*` serial CAN paths as the standard CAN path here.
For MotorBridge standard CAN, use PCAN or CANable candleLight/gs_usb.

Windows note for CANable:

- CANable firmware matters.
- candleLight/gs_usb is a Linux SocketCAN path; Windows may need WinUSB,
  candleLight-compatible tools, or a vendor-specific application.
- These Linux scripts do not run directly on Windows.

macOS note for CANable:

- These scripts do not configure CANable on macOS.
- Use firmware-specific tooling. Linux `ip link`, `gs_usb`, and SocketCAN are
  not macOS interfaces.

## Unsupported Adapters

Adapters outside PCAN and CANable candleLight/gs_usb are not documented as
supported startup paths here. If an adapter only exposes a vendor-specific serial
protocol, use the vendor toolchain or the dedicated Damiao `dm-serial` transport
when it is a Damiao serial bridge.

## CAN-FD

Use `canfd_restart.sh` only for known CAN-FD capable SocketCAN interfaces.

```bash
scripts/canfd_restart.sh can0
scripts/canfd_restart.sh --bitrate 1000000 --dbitrate 5000000 can0
```

## Other Helpers

- `setup_pcbusb_macos.sh`: install the macOS PCBUSB runtime for PCAN support.
- `release_python_package.sh`: package/release helper.
