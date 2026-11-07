#!/usr/bin/env python3
"""
edge-slide: touchpad edge sliders for Linux.

  * Slide one finger up/down along the LEFT  edge  -> screen brightness
  * Slide one finger up/down along the RIGHT edge  -> volume

Reads raw evdev events from the touchpad (needs membership in the `input`
group), sets volume with `wpctl` (PipeWire) and brightness through
systemd-logind (no root needed). Pure standard library, no dependencies.
"""

import argparse
import fcntl
import os
import re
import struct
import subprocess
import sys

# --- evdev constants -------------------------------------------------------
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0x00
ABS_X, ABS_Y = 0x00, 0x01
BTN_TOUCH = 0x14A
BTN_TOOL_FINGER = 0x145
MULTI_FINGER_TOOLS = {0x14D, 0x14E, 0x14F, 0x148}  # DOUBLETAP, TRIPLETAP, QUADTAP, QUINTTAP

EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)


def eviocgabs(code):
    # _IOR('E', 0x40 + code, struct input_absinfo)  (6 x s32 = 24 bytes)
    return (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code)


def abs_range(fd, code):
    buf = fcntl.ioctl(fd, eviocgabs(code), b"\0" * 24)
    _value, minimum, maximum, *_ = struct.unpack("6i", buf)
    return minimum, maximum


def find_touchpad():
    with open("/proc/bus/input/devices") as f:
        blocks = f.read().split("\n\n")
    for block in blocks:
        name = re.search(r'N: Name="(.*)"', block)
        handlers = re.search(r"H: Handlers=(.*)", block)
        if name and handlers and "touchpad" in name.group(1).lower():
            ev = re.search(r"\b(event\d+)\b", handlers.group(1))
            if ev:
                return "/dev/input/" + ev.group(1), name.group(1)
    return None, None


# --- actions ---------------------------------------------------------------
def show_osd(icon, level):
    """Show GNOME's native popup via the edge-slide-osd@local shell extension."""
    subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.gnome.Shell",
         "--object-path", "/org/gnome/Shell/Extensions/EdgeSlide",
         "--method", "org.gnome.Shell.Extensions.EdgeSlide.ShowOSD", icon, f"{level:.4f}"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1,
    )


def change_volume(step_pct):
    sign = "+" if step_pct > 0 else "-"
    subprocess.run(
        ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(step_pct)}%{sign}"],
        check=False,
    )
    out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                         capture_output=True, text=True).stdout
    m = re.search(r"Volume:\s*([\d.]+)", out)
    if not m:
        return
    level = float(m.group(1))
    if "MUTED" in out or level == 0:
        icon = "audio-volume-muted-symbolic"
    elif level < 0.34:
        icon = "audio-volume-low-symbolic"
    elif level < 0.67:
        icon = "audio-volume-medium-symbolic"
    else:
        icon = "audio-volume-high-symbolic"
    show_osd(icon, level)


class Backlight:
    def __init__(self, name=None):
        base = "/sys/class/backlight"
        devs = sorted(os.listdir(base)) if os.path.isdir(base) else []
        if not devs:
            self.name = None
            return
        self.name = name or devs[0]
        self.path = os.path.join(base, self.name)
        with open(os.path.join(self.path, "max_brightness")) as f:
            self.max = int(f.read())

    def change(self, step_pct):
        if not self.name:
            return
        with open(os.path.join(self.path, "brightness")) as f:
            cur = int(f.read())
        delta = max(1, round(self.max * abs(step_pct) / 100))
        new = cur + delta if step_pct > 0 else cur - delta
        new = min(self.max, max(round(self.max * 0.01), new))  # never go fully black
        subprocess.run(
            ["busctl", "call", "org.freedesktop.login1",
             "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session",
             "SetBrightness", "ssu", "backlight", self.name, str(new)],
            check=False, stdout=subprocess.DEVNULL,
        )
        show_osd("display-brightness-symbolic", new / self.max)


# --- gesture tracking ------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Touchpad edge sliders for brightness & volume")
    ap.add_argument("--device", help="evdev path (default: auto-detect touchpad)")
    ap.add_argument("--edge", type=float, default=0.07,
                    help="edge zone width as fraction of touchpad width (default 0.07)")
    ap.add_argument("--travel", type=float, default=0.06,
                    help="vertical finger travel per step, fraction of height (default 0.06)")
    ap.add_argument("--volume-step", type=int, default=4, help="volume %% per step (default 4)")
    ap.add_argument("--brightness-step", type=int, default=5, help="brightness %% per step (default 5)")
    ap.add_argument("--swap", action="store_true", help="volume on left, brightness on right")
    ap.add_argument("--backlight", help="backlight device name (default: first found)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    path, name = (args.device, args.device) if args.device else find_touchpad()
    if not path:
        sys.exit("No touchpad found in /proc/bus/input/devices (use --device)")
    try:
        fd = os.open(path, os.O_RDONLY)
    except PermissionError:
        sys.exit(f"Permission denied on {path}.\n"
                 f"Fix: sudo usermod -aG input $USER   then log out and back in.")

    xmin, xmax = abs_range(fd, ABS_X)
    ymin, ymax = abs_range(fd, ABS_Y)
    width, height = xmax - xmin, ymax - ymin
    left_lim = xmin + width * args.edge
    right_lim = xmax - width * args.edge
    step_dist = height * args.travel
    drift_lim = width * 0.20  # leaving the edge this far cancels (it's a normal swipe)

    backlight = Backlight(args.backlight)
    left_action = ("volume", change_volume, args.volume_step)
    right_action = ("brightness", backlight.change, args.brightness_step)
    if not args.swap:
        left_action, right_action = right_action, left_action

    print(f"edge-slide: {name} ({path}) x[{xmin},{xmax}] y[{ymin},{ymax}]; "
          f"left={left_action[0]} right={right_action[0]}", flush=True)

    x = y = None
    touching = False
    multi = False
    new_touch = False
    mode = None          # (label, fn, step) while a slide is active
    start_x = anchor_y = None

    while True:
        data = os.read(fd, EVENT_SIZE * 64)
        for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            _s, _us, etype, code, value = struct.unpack_from(EVENT_FMT, data, off)

            if etype == EV_ABS:
                if code == ABS_X:
                    x = value
                elif code == ABS_Y:
                    y = value
            elif etype == EV_KEY:
                if code == BTN_TOUCH:
                    touching = bool(value)
                    if value:
                        new_touch = True
                    else:
                        mode = None
                        multi = False
                elif code in MULTI_FINGER_TOOLS and value:
                    multi = True
                    mode = None
            elif etype == EV_SYN and code == SYN_REPORT:
                if not touching or x is None or y is None:
                    continue
                if new_touch:
                    new_touch = False
                    if multi:
                        continue
                    if x <= left_lim:
                        mode = left_action
                    elif x >= right_lim:
                        mode = right_action
                    else:
                        mode = None
                    start_x, anchor_y = x, y
                    if mode and args.verbose:
                        print(f"start {mode[0]} slide", flush=True)
                    continue
                if not mode or multi:
                    continue
                if abs(x - start_x) > drift_lim:
                    mode = None
                    continue
                dy = anchor_y - y  # finger moving up -> positive
                while abs(dy) >= step_dist:
                    direction = 1 if dy > 0 else -1
                    label, fn, step = mode
                    fn(direction * step)
                    if args.verbose:
                        print(f"{label} {'+' if direction > 0 else '-'}{step}%", flush=True)
                    anchor_y -= direction * step_dist
                    dy = anchor_y - y


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
