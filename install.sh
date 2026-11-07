#!/bin/sh
set -e
cd "$(dirname "$0")"
install -Dm755 edge-slide.py "$HOME/.local/bin/edge-slide"
install -Dm644 edge-slide.service "$HOME/.config/systemd/user/edge-slide.service"
EXT=edge-slide-osd@local
mkdir -p "$HOME/.local/share/gnome-shell/extensions"
rm -rf "$HOME/.local/share/gnome-shell/extensions/$EXT"
cp -r "gnome-extension/$EXT" "$HOME/.local/share/gnome-shell/extensions/"
# Mark enabled now; on Wayland GNOME only picks up new extensions after re-login.
gnome-extensions enable "$EXT" 2>/dev/null || python3 - "$EXT" <<'PY'
import ast, subprocess, sys
key = ["org.gnome.shell", "enabled-extensions"]
cur = subprocess.run(["gsettings", "get", *key], capture_output=True, text=True).stdout.strip()
lst = ast.literal_eval(cur.replace("@as ", "")) if cur else []
if sys.argv[1] not in lst:
    subprocess.run(["gsettings", "set", *key, str(lst + [sys.argv[1]])], check=True)
PY
systemctl --user daemon-reload
systemctl --user enable --now edge-slide.service
echo "Installed. Logs: journalctl --user -u edge-slide -f"
if ! id -nG | grep -qw input; then
  echo "NOTE: you are not in the 'input' group yet. Run:"
  echo "  sudo usermod -aG input $USER"
  echo "then log out and back in."
fi
