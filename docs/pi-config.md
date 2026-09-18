# Raspberry Pi and Robot HAT configuration

Audit of the robot's Pi (`ricardo@pi.local`, SSH alias `picrawler`) taken
2026-09-18, 52 minutes after boot. Read-only: nothing on the device was changed.
Re-run the commands in [Reproducing](#reproducing) to refresh it.

## Findings

Ordered by how much they affect the robot.

1. **No servo calibration is saved.** `/root/.config/.picrawler.config` (the
   examples run under `sudo`, so `~` is `/root`) holds only the robot-hat
   header, no offsets. Either `0_calibration.py` was never saved or the file
   was reset. Gaits run on raw servo zeros. Run `sudo python3
   examples/0_calibration.py` and save.
2. **Under-voltage under load.** The kernel logged `Undervoltage detected!` at
   11:11:13, recovered 2 s later, and `vcgencmd get_throttled` reports
   `0x50000` (under-voltage and throttling have occurred since boot, neither
   active now). EXT5V read 5.21 V at idle and the battery 7.43 V (2S, ~50 %),
   so this is the Robot HAT's 5 V regulator sagging during servo motion rather
   than a flat battery. Expect it to get worse as the pack drains; charge
   before trotting or twerking.
3. **`petronilo.service` is not installed.** The checkout is at `e8f4dab`,
   which includes the installer step (`picrawler-control/install.sh` step 7),
   but the installer wasn't re-run: no unit exists under
   `/etc/systemd/system`. `examples/secret.py` is present, so running the
   installer will enable and start it.
4. **No IMU on the bus.** `i2cdetect -y 1` shows only the HAT MCU at `0x14`.
   The MPU6050 (`0x68`) needed by examples 21–23 and `balance.Leveler` isn't
   connected or isn't powered.
5. **Bootloader is behind.** Running 2025-12-08, latest default is
   2026-05-26. `sudo rpi-eeprom-update -a` then reboot.
6. **Desktop stack running on a headless robot.** Boots to
   `graphical.target` with lightdm, wayvnc, CUPS, Bluetooth, PackageKit and
   NFS client/rpcbind enabled. None are used by the robot, and they cost RAM,
   CPU and boot time. `sudo systemctl set-default multi-user.target` and
   disabling cups, rpcbind/nfs-client and packagekit is safe; keep Bluetooth
   only if a controller is paired.
7. **`examples/secret.py` is world-readable** (`0664`). The service runs as
   root, so `chmod 600` costs nothing.
8. **No firewall** (empty nftables ruleset). SSH is key-only
   (`PasswordAuthentication no`), which is the part that matters; root login is
   `without-password` (keys only).

Minor: locale is `en_GB.UTF-8` while the timezone is `America/New_York`; one
package upgrade is pending; `~/picrawler` has untracked generated media and
`picrawler.egg-info/`, all already excluded from `make sync`.

## Hardware

| Component | Detail |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.0, 4 GB |
| Storage | 128 GB microSD (`mmcblk0`), 8 % used; 2 GB zram swap |
| HAT | SunFounder Robot HAT, MCU at I2C `0x14`; no ID EEPROM (no `/proc/device-tree/hat`) |
| Speaker | HAT I2S amp, driven as `hifiberry-dac` (PCM5102A), ALSA card `sndrpihifiberry` |
| Microphone | USB PnP Sound Device (TI PCM2902, `08bb:2902`), ALSA card 2, capture only |
| Camera | OV5647 on CSI (`rpicam-hello --list-cameras`), up to 2592×1944 @ 15.6 fps |
| IMU | Not detected |
| Battery | 7.43 V at audit time; `VoiceActiveCrawler` warns below 6.9 V |
| Cooling | No fan cooling device registered; SoC at 58.7 °C at light load |

## OS and firmware

| Item | Value |
|---|---|
| OS | Raspberry Pi OS, Debian 13.7 (trixie), aarch64 |
| Kernel | `6.18.50+rpt-rpi-2712` |
| VideoCore firmware | `2226a853`, 2025-12-08 |
| Bootloader | 2025-12-08 (update available: 2026-05-26) |
| EEPROM config | `BOOT_UART=1`, `POWER_OFF_ON_HALT=0`, `BOOT_ORDER=0xf461` (SD, NVMe, USB, restart) |
| Python | 3.13.5, system interpreter, packages installed with `--break-system-packages` |
| Default target | `graphical.target` |
| Timezone / locale | America/New_York, NTP synced / `en_GB.UTF-8` |

### `/boot/firmware/config.txt`

Active lines (comments stripped). The HAT-relevant ones are I2C, SPI and the
`hifiberry-dac` overlay; the rest are Pi OS defaults.

```ini
dtparam=i2c_arm=on
dtparam=spi=on
dtparam=audio=on
camera_auto_detect=1
display_auto_detect=1
auto_initramfs=1
dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1
arm_64bit=1
disable_overscan=1
arm_boost=1

[cm4]
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[pi5]
dtoverlay=nospi10

[all]
dtoverlay=hifiberry-dac
```

`cmdline.txt` keeps the serial console on `serial0` and sets
`cfg80211.ieee80211_regdom=US`.

## Buses and devices

- I2C: `/dev/i2c-1` is the HAT header bus; `i2c-4`, `-11`, `-13`, `-14` are
  Pi 5 internal (RP1, camera, HDMI DDC).
- SPI: `/dev/spidev0.0`, `/dev/spidev0.1`.
- `ricardo` is in `gpio`, `i2c`, `spi`, `audio` and `video`, but the examples
  still need `sudo` for robot-hat's GPIO/PWM access.

## Audio

`/etc/asound.conf` (written by `i2samp.sh`) routes the ALSA default through a
softvol control onto a dmix on the HAT DAC, so several processes can play at
once and volume is set with the `robot-hat speaker Playback Volume` control:

```
default → robothat (plug) → softvol → dmixer (dmix, 44.1 kHz stereo) → hw:sndrpihifiberry
```

PipeWire (with the PulseAudio shim) also runs in the user session; its default
sink is the same DAC. HDMI audio cards 0 and 1 exist but are unused.

## Software

| Package | Version | Source (apt = `/usr/lib/python3`, pip = `/usr/local`) |
|---|---|---|
| picrawler | 2.1.4 | editable install of `~/picrawler` (`rickhlx/picrawler`, `main` @ `e8f4dab`) |
| robot_hat | 2.5.7 | `~/robot-hat` (`rickhlx/robot-hat`, `2.5.x` @ `e88f901`), regular install into `/usr/local/lib/python3.13/dist-packages` |
| sunfounder-voice-assistant | 1.1.9 | pip, pulled in by robot-hat's `install.py` |
| vilib | 0.3.19 | pip, from `~/vilib` @ `dd5b81e` |
| picamera2 | 0.3.37 | apt |
| vosk | 0.3.45 | pip |
| piper-tts | 1.8.0 | pip |
| numpy, requests | 2.2.4, 2.32.3 | apt |
| readchar | 4.2.2 | pip |
| GPIO stack | lgpio 0.2.2.0, rpi-lgpio 0.6, gpiozero 2.0.1, gpiod 2.2.0 | apt |
| I2C | smbus 1.1, smbus2 0.4.3 | apt |
| Audio I/O | PyAudio 0.2.14, sounddevice 0.5.6 | pip |

robot-hat is not editable, so changes in `~/robot-hat` need a reinstall
(`sudo pip3 install ~/robot-hat --break-system-packages`) to take effect.

Pi-local state in `~/picrawler/examples`: `secret.py` (API keys) and
`petronilo_memory.json`. Calibration lives in `/root/.config/.picrawler.config`.

## Services and access

- Petronilo: not installed (see Findings).
- Enabled: ssh, avahi (so `pi.local` resolves), NetworkManager,
  wpa_supplicant, bluetooth, lightdm, wayvnc-control, cups, rpcbind,
  nfs-client, packagekit, rpi-eeprom-update, serial getty on `ttyAMA10`.
- No user or root crontabs.
- Network: Wi-Fi on `wlan0` via NetworkManager (netplan-generated profile,
  address not pinned here); `eth0` down.
- SSH: port 22, pubkey only, no password auth.

## Reproducing

```bash
ssh ricardo@pi.local '
  cat /proc/device-tree/model; uname -r; cat /etc/os-release
  vcgencmd get_throttled; vcgencmd pmic_read_adc EXT5V_V
  sudo rpi-eeprom-update; sudo rpi-eeprom-config
  grep -v "^\s*#" /boot/firmware/config.txt | grep .
  sudo i2cdetect -y 1
  aplay -l; arecord -l; cat /etc/asound.conf
  rpicam-hello --list-cameras
  pip3 list | grep -Ei "robot|picrawler|vilib|voice|vosk|piper"
  sudo cat /root/.config/.picrawler.config
  sudo python3 -c "from robot_hat import utils; print(utils.get_battery_voltage())"
  systemctl status petronilo; systemctl list-unit-files --state=enabled
  sudo journalctl -k -b | grep -i voltage
'
```
