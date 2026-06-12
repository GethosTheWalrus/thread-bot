#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found. This script is for Debian/Ubuntu Linux." >&2
  exit 1
fi

if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "22.04" ]; then
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:savoury1/multimedia
  fi
fi

sudo apt-get update
sudo apt-get install -y \
  build-essential \
  cmake \
  curl \
  g++ \
  gcc \
  git \
  libasound2-dev \
  libcairo2-dev \
  libglib2.0-dev \
  libgirepository1.0-dev \
  libgstreamer-plugins-bad1.0-dev \
  libgstreamer-plugins-base1.0-dev \
  libgstreamer-plugins-good1.0-dev \
  libgstreamer1.0-dev \
  libnice-dev \
  libportaudio2 \
  libssl-dev \
  gstreamer1.0-alsa \
  gstreamer1.0-nice \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-good \
  make \
  pkg-config \
  python3 \
  python3-dev \
  python3-gi \
  python3-gi-cairo \
  python3-pip \
  rustc \
  cargo

if ! python3 - <<'PY' >/dev/null 2>&1
import gi  # noqa: F401
PY
then
  echo "python3-gi is not importable yet; install your distro's python3-gobject package if needed." >&2
fi

if ! command -v rustup >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi

cargo install cargo-c

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
python3 -m pip install --upgrade pip wheel setuptools
python3 -m pip install --no-deps reachy-mini==1.8.1 libusb_package==1.0.26.1
python3 -m pip install -r "$ROOT_DIR/backend/requirements-reachy.txt"
