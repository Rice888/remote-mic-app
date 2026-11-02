#!/bin/bash
# Permanent user-space backend installer; no system drivers, EFI or root privileges.
set -euo pipefail
umask 077
if [[ $# -ne 1 ]]; then
  echo 'Usage: SAYALL_PYTHON=/path/to/python3.12 bash scripts/install-external-bluetooth.sh FIRMWARE_DIRECTORY'
  exit 2
fi
SAYALL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAYALL_BACKEND="${SAYALL_EXTERNAL_BLUETOOTH_DIR:-$HOME/Library/Application Support/SayAll/ExternalBluetooth}"
SAYALL_PYTHON="${SAYALL_PYTHON:-python3}"
"$SAYALL_PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
SAYALL_FIRMWARE="$1"
for name in rtl8761bu_fw rtl8761bu_config; do
  if [[ ! -s "$SAYALL_FIRMWARE/$name.bin" && ! -s "$SAYALL_FIRMWARE/$name" ]]; then
    echo "Missing required firmware: $name[.bin]"
    exit 2
  fi
done
mkdir -p "$SAYALL_BACKEND/firmware"
chmod 700 "$SAYALL_BACKEND"
"$SAYALL_PYTHON" -m venv "$SAYALL_BACKEND/.venv"
"$SAYALL_BACKEND/.venv/bin/python3" -m pip install \
  'bumble @ git+https://github.com/google/bumble.git@e1fe43c9b44be0d974a6fd533ac6d494fc50510a'
cp "$SAYALL_ROOT/Resources/ExternalBluetooth/bridge.py" "$SAYALL_BACKEND/bridge.py"
for name in rtl8761bu_fw rtl8761bu_config; do
  source_file="$SAYALL_FIRMWARE/$name.bin"
  [[ -s "$source_file" ]] || source_file="$SAYALL_FIRMWARE/$name"
  cp "$source_file" "$SAYALL_BACKEND/firmware/$name.bin"
done
# Existing bonds.json is preserved when updating the backend.
echo 'Backend installed. Select External UB500 in SayAll Connection settings.'
