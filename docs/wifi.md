# Moving him to another network

The robot is headless: no screen, no keyboard, and the only way in is SSH over
Wi-Fi. So the rule is simple — **teach him the new network before you unplug
him**, while you can still reach him. Everything else in this page is recovery
for when you didn't.

## Before you go (the easy way)

From your computer, while he is still on the network he knows:

```bash
make wifi SSID="Casa de Ana"          # asks for the password, doesn't echo it
make wifi SSID="Oficina" HIDDEN=yes   # hidden network
make wifi-list                        # what he already knows
```

That writes a NetworkManager profile with `autoconnect=true`. NetworkManager
joins whichever known network is in range, so when you plug him in at the new
place he comes up on his own. Old networks stay — he will still join the home
one when he is back, and you can keep half a dozen.

The password is typed at a prompt, never passed on the command line, so it
stays out of your shell history and out of `ps` on both machines. It lands in a
`600` keyfile in your user's home on the Pi for a moment, then is installed
root-owned under `/etc/NetworkManager/system-connections/` and the temporary
copy is deleted.

The profile also sets `powersave=2`, which turns Wi-Fi power saving off for
that network. Power save parks the radio between packets and adds an
unpredictable 100–300 ms to the first packet of every API call, which is every
sentence he speaks. See [latency](latency.md).

Check it took:

```bash
make wifi-status     # the connection, SSID and signal he is on, plus his address
```

## Once you are there

Plug him in, give him a minute, then:

```bash
ssh picrawler        # the SSH alias
make deployed        # confirms you are talking to the right machine
```

If the alias stops resolving, his address changed. `picrawler.local` works when
mDNS does (same subnet, most home routers). Otherwise find him from the new
router's client list, or:

```bash
ping picrawler.local
arp -a | grep -i b8:27:eb     # Raspberry Pi MAC prefixes: b8:27:eb, dc:a6:32, e4:5f:01
```

Then point the alias at the new address in `~/.ssh/config`:

```
Host picrawler
    HostName 192.168.1.42
    User ricardo
```

## If he is already somewhere new and offline

In rough order of how annoying they are.

**Phone hotspot.** This is why you set one up in advance. Add your phone's
hotspot as a known network *once*, while you are at home:

```bash
make wifi SSID="iPhone de Ricardo"
```

From then on, anywhere in the world, turn the hotspot on and he joins it. SSH
to him over the hotspot and add the real network with `make wifi`. This turns
every future move into a two-minute job, and it is worth doing today.

**Ethernet.** Plug a cable from the Pi to the router, or straight into your
laptop. With a direct cable both ends get link-local addresses and
`ssh picrawler.local` usually still works. Then add the Wi-Fi as above.

**Keyboard and monitor.** Micro-HDMI and a USB keyboard on the Pi, log in, and:

```bash
sudo nmcli device wifi list
sudo nmcli device wifi connect "Casa de Ana" password "..."
```

**The SD card.** Last resort, and awkward from a Mac: the Wi-Fi profiles live
in `/etc/NetworkManager/system-connections/*.nmconnection` on the ext4 root
partition, which macOS cannot mount without extra software. A Linux machine can
drop a keyfile in (same format `make wifi` writes), `chmod 600`, done. The
`/boot/firmware` partition is FAT and *is* readable from a Mac, but its
`firstrun.sh` hook only runs on a first boot, so it will not help an
already-configured system.

## On the Pi directly

The same operations, if you are logged in:

```bash
nmcli connection show                          # known networks
nmcli device wifi list                         # what is in range
sudo nmcli device wifi connect "SSID" password "..."   # join one in range now
sudo nmcli connection delete "Old Cafe"        # forget one
sudo nmcli connection modify "Casa" connection.autoconnect-priority 10
```

Priority breaks ties when two known networks are in range — higher wins. Worth
setting if his home network and a neighbour's guest network both reach him.

## Things that bite

- **He joins, but you cannot SSH in.** Check you are on the same subnet. Guest
  networks on most routers isolate clients from each other by design, so a
  robot on the guest network is unreachable even though it has internet.
- **2.4 vs 5 GHz.** The Pi's radio handles both, but if the new network has one
  SSID for each band, seed the 2.4 GHz one: it is slower and reaches further,
  and this robot walks away from the router.
- **Captive portals.** Hotel and café Wi-Fi needs a browser to accept terms. He
  has no browser. Use the phone hotspot instead.
- **Nothing reaches the internet, so Petronilo goes quiet.** His voice,
  transcription and brain are all cloud calls. `journalctl -u petronilo -f`
  shows the failures; the wake word still works, because Vosk is local, and he
  will tell you the signal is gone in his own words.
- **A changed address breaks `make deploy`.** It is the same SSH alias for
  everything, so fix `~/.ssh/config` once and all the targets follow.
