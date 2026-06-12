#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v dnf >/dev/null 2>&1; then
  echo "dnf not found. This script is for Fedora Linux." >&2
  exit 1
fi

sudo dnf install -y --skip-unavailable \
  cargo \
  cmake \
  curl \
  gcc \
  gcc-c++ \
  git \
  glib2-devel \
  gobject-introspection-devel \
  gstreamer1-devel \
  gstreamer1-plugins-bad-free \
  gstreamer1-plugins-bad-free-devel \
  gstreamer1-plugins-base-devel \
  gstreamer1-plugins-good \
  libffi-devel \
  libnice-devel \
  libnice-gstreamer1 \
  portaudio-devel \
  openssl-devel \
  make \
  pkgconf-pkg-config \
  python3.10 \
  python3.10-devel \
  python3-gobject \
  python3-cairo

if ! command -v rustup >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi

sudo dnf install -y cargo-c

plugin_root="/opt/gst-plugins-rs"
sudo mkdir -p "$plugin_root"
sudo chown "$USER":"$USER" "$plugin_root"
if [ ! -d "$plugin_root/gst-plugins-rs" ]; then
  git clone https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs.git "$plugin_root/gst-plugins-rs"
fi
cd "$plugin_root/gst-plugins-rs"
git checkout 0.14.5
cargo cinstall -p gst-plugin-webrtc --prefix="$plugin_root" --release

case "$(uname -m)" in
  aarch64|arm64)
    plugin_path="$plugin_root/lib/aarch64-linux-gnu:$plugin_root/lib64"
    ;;
  *)
    plugin_path="$plugin_root/lib/x86_64-linux-gnu:$plugin_root/lib64"
    ;;
esac

echo
echo "Add this to your shell profile:"
echo "export GST_PLUGIN_PATH=\"$plugin_path:\$GST_PLUGIN_PATH\""
echo

env_file="$ROOT_DIR/.reachy.env"
{
  echo "# Reachy local env (sourced by reachy worker/bridge/daemon)"
  echo "export GST_PLUGIN_PATH=\"$plugin_path:\$GST_PLUGIN_PATH\""
  echo "export LD_LIBRARY_PATH=\"$plugin_root/lib64:\$LD_LIBRARY_PATH\""
} > "$env_file"
echo "Wrote $env_file"
echo
venv_dir="$ROOT_DIR/.venv-reachy"
python3.10 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip wheel setuptools
"$venv_dir/bin/python" -m pip install --no-deps reachy-mini==1.8.1 libusb_package==1.0.26.1
"$venv_dir/bin/python" -m pip install -r "$ROOT_DIR/backend/requirements-reachy.txt"

echo
echo "Reachy Python environment created at: $venv_dir"
echo "Use it with: source $venv_dir/bin/activate"
