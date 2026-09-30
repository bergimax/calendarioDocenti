#!/usr/bin/env bash
# Weekly off-VM backup: takes a fresh dump (deploy/backup-db.sh) and uploads
# it to an Oracle Object Storage bucket, then keeps only the newest N copies
# there. Meant for cron, e.g. `30 3 * * 0 cd ~/calendarioDocenti && deploy/backup-offsite.sh`.
#
# Authenticates as the VM itself ("instance principal"): no API keys or
# passwords are stored anywhere. The one-time console setup (bucket, dynamic
# group, policy) is described in deploy/README.md.
#
# Reads from .env.production (none of these are secrets):
#   OCI_BACKUP_BUCKET   bucket name (required)
#   OCI_NAMESPACE       Object Storage namespace (optional, looked up if empty)
#   OCI_BACKUP_KEEP     how many weekly copies to keep (default 8)
set -euo pipefail
cd "$(dirname "$0")/.."

OCI="${OCI_CLI:-$HOME/oci-cli/bin/oci}"
AUTH=(--auth instance_principal)

env_get() { grep -oP "(?<=^$1=).*" .env.production 2>/dev/null || true; }
BUCKET=$(env_get OCI_BACKUP_BUCKET)
NAMESPACE=$(env_get OCI_NAMESPACE)
KEEP=$(env_get OCI_BACKUP_KEEP)
KEEP=${KEEP:-8}

[ -x "$OCI" ] || { echo "OCI CLI not found at $OCI (see deploy/README.md)." >&2; exit 1; }
[ -n "$BUCKET" ] || { echo "OCI_BACKUP_BUCKET is not set in .env.production." >&2; exit 1; }
if [ -z "$NAMESPACE" ]; then
  NAMESPACE=$("$OCI" os ns get "${AUTH[@]}" --query data --raw-output)
fi

# Fresh dump (also refreshes the local rotation in deploy/backups/).
deploy/backup-db.sh
LATEST=$(ls -1t deploy/backups/calendariodocenti-*.sql.gz | head -1)
gunzip -t "$LATEST"  # never upload a corrupt archive

NAME="weekly/$(basename "$LATEST")"
"$OCI" os object put "${AUTH[@]}" -ns "$NAMESPACE" -bn "$BUCKET" \
  --file "$LATEST" --name "$NAME" --force >/dev/null
echo "Uploaded $NAME to bucket $BUCKET"

# Retention: object names carry a UTC timestamp, so name order == age order.
"$OCI" os object list "${AUTH[@]}" -ns "$NAMESPACE" -bn "$BUCKET" \
    --prefix weekly/ --all --query 'data[].name' \
  | python3 -c 'import json,sys; print("\n".join(sorted(json.load(sys.stdin))))' \
  | head -n "-$KEEP" \
  | while read -r old; do
      [ -n "$old" ] || continue
      "$OCI" os object delete "${AUTH[@]}" -ns "$NAMESPACE" -bn "$BUCKET" --object-name "$old" --force
      echo "Deleted old copy $old"
    done
