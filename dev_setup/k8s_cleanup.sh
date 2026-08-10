#!/bin/bash

# Configuration - Match your deployment specs
NAMESPACE="default"
FLASK_POD_PREFIX="mopa-laser-rasterizer"
REDIS_POD="redis-state-set-0"
UPLOAD_DIR="/app/uploads"

echo "=== Step 1: Cleaning Up Active Tasks from Redis ==="

# Fetch active status keys from Redis
STATUS_KEYS=$(kubectl exec -n $NAMESPACE $REDIS_POD -- redis-cli --no-auth-warning keys "task:*:status" 2>/dev/null)

if [ -n "$STATUS_KEYS" ]; then
    echo "Found active Task IDs in Redis:"
    TASK_IDS=()
    for key in $STATUS_KEYS; do
        task_id=$(echo "$key" | cut -d':' -f2)
        TASK_IDS+=("$task_id")
        echo " - $task_id"
    done

    echo ""
    read -p "Do you want to purge these active Redis tasks and their files? (y/N): " CONFIRM_REDIS
    if [[ "$CONFIRM_REDIS" =~ ^[Yy]$ ]]; then
        # Find an active app pod to execute disk commands
        APP_POD=$(kubectl get pods -n $NAMESPACE --no-headers -o custom-columns=":metadata.name" | grep "^$FLASK_POD_PREFIX" | head -n 1)
        if [ -n "$APP_POD" ]; then
            for task_id in "${TASK_IDS[@]}"; do
                echo "Purging active Task: $task_id ..."
                kubectl exec -n $NAMESPACE $REDIS_POD -- redis-cli --no-auth-warning del "task:$task_id:status" "task:$task_id:log" "task:$task_id:downloads" > /dev/null
                kubectl exec -n $NAMESPACE $APP_POD -- sh -c "rm -f $UPLOAD_DIR/$task_id.* $UPLOAD_DIR/*$task_id*" 2>/dev/null
            done
            echo "Active tasks purged."
        else
            echo "Error: No application pod found to delete active disk files."
        fi
    fi
else
    echo "No active task keys found in Redis."
fi

echo ""
echo "=== Step 2: Scanning Disk for Finished/Orphaned Files ==="

# Find an active application pod for disk scanning
APP_POD=$(kubectl get pods -n $NAMESPACE --no-headers -o custom-columns=":metadata.name" | grep "^$FLASK_POD_PREFIX" | head -n 1)

if [ -z "$APP_POD" ]; then
    echo "Error: No active $FLASK_POD_PREFIX pod found to scan the disk. Exiting."
    exit 1
fi

# List files inside /app/uploads via the container
DISK_FILES=$(kubectl exec -n $NAMESPACE $APP_POD -- sh -c "ls -1 $UPLOAD_DIR" 2>/dev/null)

if [ -z "$DISK_FILES" ]; then
    echo "The /app/uploads directory is completely empty. Disk space is optimal."
    exit 0
fi

ORPHANED_FILES=()

# Extract potential Task IDs from filenames to cross-reference with Redis
for file in $DISK_FILES; do
    # Skip hidden/system files
    if [[ "$file" == .* ]]; then continue; fi
    
    # Extract the first part of the filename before any dots or underscores
    # This matches task_id patterns (e.g., 'task123.log', 'task123.status', 'task123_output.png')
    task_id=$(echo "$file" | awk -F'[_.]' '{print $1}')
    
    # Check if this task still has an active status tracker in Redis
    REDIS_EXISTS=$(kubectl exec -n $NAMESPACE $REDIS_POD -- redis-cli --no-auth-warning exists "task:$task_id:status")
    
    # Redis 'EXISTS' returns 0 if the key does not exist (meaning it expired or completed 3 downloads)
    if [ "$REDIS_EXISTS" -eq 0 ]; then
        ORPHANED_FILES+=("$file")
    fi
done

if [ ${#ORPHANED_FILES[@]} -eq 0 ]; then
    echo "All files on disk belong to active processing tasks. No space to reclaim."
    exit 0
fi

echo "The following files on disk have already been processed (no longer tracked in Redis):"
for file in "${ORPHANED_FILES[@]}"; do
    echo " - $file"

echo ""
read -p "Do you want to permanently delete these processed files to free up disk space? (y/N): " CONFIRM_DISK
if [[ "$CONFIRM_DISK" =~ ^[Yy]$ ]]; then
    for file in "${ORPHANED_FILES[@]}"; do
        echo "Deleting: $file ..."
        kubectl exec -n $NAMESPACE $APP_POD -- sh -c "rm -f $UPLOAD_DIR/$file" 2>/dev/null
    done
    echo "=== Storage Reclaimed Successfully ==="
else
    echo "Disk cleanup cancelled."
fi
