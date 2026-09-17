#!/usr/bin/env python3
"""
PiCrawler reggaeton twerk.

Synthesizes a dembow (reggaeton) beat with numpy the first time it runs,
saves it to musics/reggaeton_dembow.wav, then loops it while the crawler
bounces its rear legs on the beat.  Ctrl+C sits the robot down and stops
the music.

Usage:
    python3 twerk.py            # 95 BPM, default volume
    python3 twerk.py --bpm 100 --volume 40
"""
import argparse
import math
import os
import time
import wave

import numpy as np
from picrawler import Picrawler
from robot_hat import Music

HERE = os.path.dirname(os.path.abspath(__file__))
MUSIC_FILE = os.path.join(HERE, 'musics', 'reggaeton_dembow.wav')

# ---------------------------------------------------------------------------
# Beat synthesis
# ---------------------------------------------------------------------------
SR = 44100

# Dembow pattern on a 16th-note grid (one bar = 16 slots).
KICK_SLOTS = (0, 4, 8, 12)          # four on the floor
SNARE_SLOTS = (3, 6, 11, 14)        # the "boom-ch-boom-chick"
HAT_SLOTS = tuple(range(0, 16, 2))  # eighth-note hats
BASS_SLOTS = (0, 3, 6, 8, 11, 14)   # bass follows the dembow accents

# Am - F - C - G, one chord per bar, as bass root notes (Hz).
BASS_ROOTS = (55.0, 43.65, 65.41, 49.0)


def _env(n, decay):
    t = np.arange(n) / SR
    return np.exp(-t * decay)


def _kick(n):
    t = np.arange(n) / SR
    freq = 150 * np.exp(-t * 30) + 45          # pitch drop
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * _env(n, 9) * 1.0


def _snare(n):
    rng = np.random.default_rng(7)
    noise = rng.uniform(-1, 1, n) * _env(n, 30)
    tone = np.sin(2 * np.pi * 190 * np.arange(n) / SR) * _env(n, 40)
    return (0.6 * noise + 0.5 * tone) * 0.7


def _hat(n, accent):
    rng = np.random.default_rng(11)
    noise = rng.uniform(-1, 1, n)
    # crude high-pass: difference of the signal
    noise = np.diff(noise, prepend=0.0)
    return noise * _env(n, 80) * (0.35 if accent else 0.18)


def _bass(n, root):
    t = np.arange(n) / SR
    saw = 2 * ((t * root) % 1.0) - 1.0
    sub = np.sin(2 * np.pi * root * t)
    return (0.35 * saw + 0.5 * sub) * _env(n, 6) * 0.6


def _stab(n, root):
    """Short minor-chord synth stab on the off-beat, for the reggaeton flavour."""
    t = np.arange(n) / SR
    chord = 0.0
    for mult in (4.0, 4.0 * 2 ** (3 / 12), 4.0 * 2 ** (7 / 12)):
        chord = chord + np.sin(2 * np.pi * root * mult * t)
    return chord / 3 * _env(n, 18) * 0.25


def make_beat(path, bpm=95, bars=8):
    slot = 60.0 / bpm / 4.0                     # seconds per 16th
    slot_n = int(slot * SR)
    total_n = slot_n * 16 * bars + SR           # one second of tail
    out = np.zeros(total_n)

    def add(sample, start):
        end = min(start + len(sample), total_n)
        out[start:end] += sample[:end - start]

    kick = _kick(int(0.35 * SR))
    snare = _snare(int(0.25 * SR))
    hat_a = _hat(int(0.08 * SR), True)
    hat_b = _hat(int(0.06 * SR), False)

    for bar in range(bars):
        root = BASS_ROOTS[bar % len(BASS_ROOTS)]
        bass = _bass(int(0.4 * SR), root)
        stab = _stab(int(0.3 * SR), root)
        base = bar * 16 * slot_n
        for s in range(16):
            at = base + s * slot_n
            if s in KICK_SLOTS:
                add(kick, at)
            if s in SNARE_SLOTS:
                add(snare, at)
            if s in HAT_SLOTS:
                add(hat_a if s % 4 == 0 else hat_b, at)
            if s in BASS_SLOTS:
                add(bass, at)
            if s in (2, 10):
                add(stab, at)

    # Loudness: normalize, drive into a soft clipper, then re-normalize so the
    # track is dense and hot instead of leaving headroom.
    out = out / np.max(np.abs(out))
    out = np.tanh(out * 3.0)
    out = out / np.max(np.abs(out)) * 0.99
    pcm = (out * 32767).astype('<i2')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


# ---------------------------------------------------------------------------
# Choreography
# ---------------------------------------------------------------------------
# Leg order in a step is [leg1, leg2, leg3, leg4]: 1 and 2 are the front
# legs, 3 and 4 the rear.  x/y come from the stock stand pose.
FRONT_XY = ([45, 45], [45, 0])
REAR_XY = ([45, 0], [45, 45])

Z_FRONT = -50       # front stays at stand height
Z_REAR_UP = -65     # rear pushed up (booty high)
Z_REAR_DOWN = -32   # rear dropped (booty low)
Z_REAR_MID = -48


def pose(z3, z4, z_front=Z_FRONT, front_sway=0):
    """Build a step with the given rear-leg heights and optional front y sway."""
    l1 = [FRONT_XY[0][0], FRONT_XY[0][1] + front_sway, z_front]
    l2 = [FRONT_XY[1][0], FRONT_XY[1][1] - front_sway, z_front]
    l3 = [REAR_XY[0][0], REAR_XY[0][1], z3]
    l4 = [REAR_XY[1][0], REAR_XY[1][1], z4]
    return [l1, l2, l3, l4]


def bounce_bar():
    """Both rear legs drop on the beat, pop up on the off-beat (8th notes)."""
    return [pose(Z_REAR_DOWN, Z_REAR_DOWN) if i % 2 == 0 else pose(Z_REAR_UP, Z_REAR_UP)
            for i in range(8)]


def shake_bar():
    """Left/right rear alternate: the side-to-side shake."""
    out = []
    for i in range(8):
        if i % 2 == 0:
            out.append(pose(Z_REAR_DOWN, Z_REAR_UP, front_sway=4))
        else:
            out.append(pose(Z_REAR_UP, Z_REAR_DOWN, front_sway=-4))
    return out


def grind_bar():
    """Slow sinusoidal rear roll over the bar with a front-leg sway."""
    out = []
    for i in range(8):
        ph = 2 * math.pi * i / 8
        z3 = Z_REAR_MID + 16 * math.sin(ph)
        z4 = Z_REAR_MID + 16 * math.sin(ph + math.pi / 2)
        out.append(pose(z3, z4, front_sway=6 * math.cos(ph)))
    return out


def double_time_bar():
    """Fast bounce on 16ths for the drop."""
    out = []
    for i in range(16):
        out.append(pose(Z_REAR_DOWN, Z_REAR_DOWN) if i % 2 == 0
                   else pose(Z_REAR_MID, Z_REAR_MID))
    return out


# Each entry: (frames for one bar, subdivisions per bar).
ROUTINE = (
    (bounce_bar, 8), (bounce_bar, 8), (bounce_bar, 8), (bounce_bar, 8),
    (shake_bar, 8), (shake_bar, 8),
    (grind_bar, 8), (grind_bar, 8),
    (bounce_bar, 8), (bounce_bar, 8),
    (shake_bar, 8), (double_time_bar, 16),
)


def twerk(crawler, bpm, speed, duration=None):
    """Run the routine forever, or for `duration` seconds."""
    bar_len = 60.0 / bpm * 4.0
    t0 = time.monotonic()
    bar_idx = 0
    while duration is None or time.monotonic() - t0 < duration:
        make_frames, subdiv = ROUTINE[bar_idx % len(ROUTINE)]
        frames = make_frames()
        bar_start = t0 + bar_idx * bar_len
        for i, step in enumerate(frames):
            due = bar_start + i * bar_len / subdiv
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            crawler.do_step(step, speed)
        bar_idx += 1


def party(crawler, seconds=12, bpm=95, speed=70, volume=90, music=None):
    """Short twerk session for use as a voice-assistant action.
    Plays the dembow beat (if audio works) and dances for `seconds`, then sits."""
    if not os.path.exists(MUSIC_FILE):
        make_beat(MUSIC_FILE, bpm=bpm)
    own_music = music is None
    try:
        if music is None:
            music = Music()
    except Exception as e:
        print(f"(sin música: {e})")
        music = None
    try:
        crawler.do_step('stand', 50)
        time.sleep(0.5)
        crawler.do_step(pose(Z_REAR_MID, Z_REAR_MID), 50)
        if music:
            try:
                music.music_set_volume(volume)
                music.music_play(MUSIC_FILE, loops=-1)
            except Exception as e:
                print(f"(sin música: {e})")
        twerk(crawler, bpm, speed, duration=seconds)
    finally:
        if music:
            try:
                music.music_stop()
            except Exception:
                pass
        try:
            crawler.do_step('stand', 40)
            time.sleep(0.4)
            crawler.do_step('sit', 40)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description='PiCrawler reggaeton twerk')
    ap.add_argument('--bpm', type=int, default=95)
    ap.add_argument('--volume', type=int, default=100, help='0-100')
    ap.add_argument('--speed', type=int, default=90, help='servo speed 0-100')
    ap.add_argument('--regen', action='store_true', help='re-synthesize the beat file')
    args = ap.parse_args()

    if args.regen or not os.path.exists(MUSIC_FILE):
        print('Synthesizing dembow beat ->', MUSIC_FILE)
        make_beat(MUSIC_FILE, bpm=args.bpm)

    music = Music()
    crawler = Picrawler()

    try:
        crawler.do_step('stand', 50)
        time.sleep(0.8)
        crawler.do_step(pose(Z_REAR_MID, Z_REAR_MID), 50)
        time.sleep(0.5)

        music.music_set_volume(args.volume)
        music.music_play(MUSIC_FILE, loops=-1)
        print('Twerking at %d BPM. Ctrl+C to stop.' % args.bpm)
        twerk(crawler, args.bpm, args.speed)
    except KeyboardInterrupt:
        print('\nstopping')
    finally:
        try:
            music.music_stop()
        except Exception:
            pass
        try:
            crawler.do_step('stand', 40)
            time.sleep(0.5)
            crawler.do_step('sit', 40)
            time.sleep(0.8)
        except Exception:
            pass


if __name__ == '__main__':
    main()
