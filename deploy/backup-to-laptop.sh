#!/usr/bin/env bash
# Run on the laptop. No plaintext dump is written to either filesystem.
set -euo pipefail
umask 077

: "${BACKUP_HOST:?Set BACKUP_HOST, for example deploy@209.38.252.91}"
: "${BACKUP_SSH_KEY:?Set BACKUP_SSH_KEY to your SSH identity path}"
: "${BACKUP_RECIPIENT_FILE:?Set BACKUP_RECIPIENT_FILE to the public age recipient file}"
: "${BACKUP_IDENTITY_FILE:?Set BACKUP_IDENTITY_FILE to the separate private age identity}"
: "${BACKUP_DIRECTORY:?Set BACKUP_DIRECTORY to the laptop archive directory}"

for executable in ssh age pg_restore mktemp; do
    command -v "$executable" >/dev/null
done
mkdir -p "$BACKUP_DIRECTORY"
chmod 700 "$BACKUP_DIRECTORY"
archive="$BACKUP_DIRECTORY/finance-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
temporary=$(mktemp "$BACKUP_DIRECTORY/.incomplete.XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT

# Exact command must match the narrow sudoers rule in backup documentation.
ssh -F /dev/null -T -i "$BACKUP_SSH_KEY" \
    -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3 "$BACKUP_HOST" \
    'sudo -n -u finance /usr/bin/pg_dump --dbname=finance_dashboard --format=custom --no-owner --no-privileges' \
    | age -R "$BACKUP_RECIPIENT_FILE" > "$temporary"

# Authentication and archive structure must pass before publishing the backup.
# Consume the full archive so age verifies every encrypted chunk.
# A complete database restore drill remains required as well.
age -d -i "$BACKUP_IDENTITY_FILE" "$temporary" | pg_restore --file=/dev/null
test ! -e "$archive"
mv -- "$temporary" "$archive"
printf 'Verified encrypted archive: %s\n' "$archive"
