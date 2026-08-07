#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -euo pipefail

# Ensure the script is run with root/sudo privileges
if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run as root or with sudo." >&2
   exit 1
fi

# Ensure a username was provided as an argument
if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <username>" >&2
    exit 1
fi

TARGET_USER="$1"

# Check if the target user actually exists on the system
if ! id "$TARGET_USER" &>/dev/null; then
    echo "Error: User '$TARGET_USER' does not exist." >&2
    exit 1
fi

SUDOERS_FILE="/etc/sudoers.d/90-passwordless-${TARGET_USER}"

echo "Granting passwordless sudo to user: ${TARGET_USER}"

# Write the rule to a temporary file first to validate it
TEMP_FILE=$(mktemp)
echo "${TARGET_USER} ALL=(ALL:ALL) NOPASSWD: ALL" > "$TEMP_FILE"

# Validate the syntax using visudo before putting it into production
if visudo -cf "$TEMP_FILE" &>/dev/null; then
    # Move the validated file to the sudoers.d directory
    mv "$TEMP_FILE" "$SUDOERS_FILE"
    # Set the strict file permissions required by sudo (0440)
    chmod 0440 "$SUDOERS_FILE"
    echo "Success! ${TARGET_USER} can now run all sudo commands without a password."
else
    echo "Error: Generated sudoers syntax is invalid. Aborting." >&2
    rm -f "$TEMP_FILE"
    exit 1
fi

cat <<EOF >> /etc/wsl.conf
[automount]
enabled = true
options = "metadata,uid=1000,gid=1000,umask=022,fmask=111"
EOF
