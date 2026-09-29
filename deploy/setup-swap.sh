#!/usr/bin/env bash
# Adds swap space - essential on a 1GB VM.Standard.E2.1.Micro instance,
# where Postgres + the OR-Tools solver + WeasyPrint + Node together can
# spike past physical RAM during a schedule generation. Without swap, the
# kernel OOM-killer takes out whichever container is using the most memory
# at that moment (usually postgres or backend) instead of just slowing
# down - so a client's "genera orario" click could kill the database.
#
# Run ONCE on a fresh VM, before deploy/up.sh. Safe to re-run (no-ops if
# the swapfile already exists).
set -euo pipefail

SWAP_FILE=/swapfile
SWAP_SIZE_GB=4

if swapon --show | grep -q "$SWAP_FILE"; then
  echo "Swap already active on $SWAP_FILE - nothing to do."
  swapon --show
  exit 0
fi

if [ -f "$SWAP_FILE" ]; then
  echo "$SWAP_FILE exists but isn't active as swap - re-enabling it."
  sudo swapon "$SWAP_FILE"
  exit 0
fi

echo "Creating a ${SWAP_SIZE_GB}GB swapfile at $SWAP_FILE..."
sudo fallocate -l ${SWAP_SIZE_GB}G "$SWAP_FILE" 2>/dev/null \
  || sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
sudo chmod 600 "$SWAP_FILE"
sudo mkswap "$SWAP_FILE"
sudo swapon "$SWAP_FILE"

# Persist across reboots.
if ! grep -q "^$SWAP_FILE" /etc/fstab; then
  echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab
fi

# Low swappiness: prefer RAM, only swap under real memory pressure - a 1GB
# box swapping proactively for no reason would just make everything slower
# all the time instead of only under an actual spike.
sudo sysctl -w vm.swappiness=10
if ! grep -q "^vm.swappiness" /etc/sysctl.conf 2>/dev/null; then
  echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
fi

echo "Done:"
swapon --show
free -h
