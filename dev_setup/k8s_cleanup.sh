#!/bin/bash

# Configuration - Match your deployment specs.  Run with DRY_RUN=1 to inspect
# every local/S3 deletion without changing Redis, scratch storage, or S3.
NAMESPACE="default"
FLASK_POD_PREFIX="mopa-laser-rasterizer"
REDIS_POD="redis-state-set-0"
UPLOAD_DIR="/tmp/uploads"
DRY_RUN="${DRY_RUN:-0}"

run_delete() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "DRY RUN: $*"
    else
        "$@"
    fi
}

delete_s3_task() {
    task_id="$1"
    if [ "$DRY_RUN" = "1" ]; then
        kubectl exec -n "$NAMESPACE" "$APP_POD" -- env S3_CLEANUP_DRY_RUN=1 \
            python /app/dev_setup/s3_cleanup.py "$task_id"
    else
        kubectl exec -n "$NAMESPACE" "$APP_POD" -- \
            python /app/dev_setup/s3_cleanup.py "$task_id"
    fi
}

APP_POD=$(kubectl get pods -n "$NAMESPACE" --no-headers -o custom-columns=":metadata.name" | grep "^$FLASK_POD_PREFIX" | head -n 1)
if [ -z "$APP_POD" ]; then
    echo "Error: No active $FLASK_POD_PREFIX pod found. Exiting."
    exit 1
fi

echo "=== Step 1: Purging Tracked Tasks from Redis, Scratch, and S3 ==="

# Fetch active status keys from Redis
STATUS_KEYS=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli --no-auth-warning keys "task:*:status" 2>/dev/null)

if [ -n "$STATUS_KEYS" ]; then
    echo "Found active Task IDs in Redis:"
    TASK_IDS=()
    for key in $STATUS_KEYS; do
        task_id=$(echo "$key" | cut -d':' -f2)
        TASK_IDS+=("$task_id")
        echo " - $task_id"
    done

    echo ""
    read -p "Permanently purge these tracked tasks from Redis, local scratch, and S3? (y/N): " CONFIRM_REDIS
    if [[ "$CONFIRM_REDIS" =~ ^[Yy]$ ]]; then
        for task_id in "${TASK_IDS[@]}"; do
            echo "Purging tracked task: $task_id ..."
            delete_s3_task "$task_id"
            run_delete kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli --no-auth-warning del "task:$task_id:status" "task:$task_id:log" "task:$task_id:downloads"
            run_delete kubectl exec -n "$NAMESPACE" "$APP_POD" -- sh -c "rm -f '$UPLOAD_DIR'/'$task_id'.* '$UPLOAD_DIR'/*'$task_id'*"
        done
        echo "Tracked task cleanup finished."
    fi
else
    echo "No active task keys found in Redis."
fi

echo ""
echo "=== Step 2: Scanning Disk for Finished/Orphaned Files ==="

# List files inside node-local job scratch via the containe
DISK_FILES=$(kubectl exec -n "$NAMESPACE" "$APP_POD" -- sh -c "ls -1 '$UPLOAD_DIR'" 2>/dev/null)

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
    task_id=$(echo "$file" | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n 1)
    if [ -z "$task_id" ]; then continue; fi
    
    # Check if this task still has an active status tracker in Redis
    REDIS_EXISTS=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli --no-auth-warning exists "task:$task_id:status")
    
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
done 

echo ""
read -p "Do you want to permanently delete these processed files to free up disk space? (y/N): " CONFIRM_DISK
if [[ "$CONFIRM_DISK" =~ ^[Yy]$ ]]; then
    for file in "${ORPHANED_FILES[@]}"; do
        echo "Deleting: $file ..."
        run_delete kubectl exec -n "$NAMESPACE" "$APP_POD" -- sh -c "rm -f '$UPLOAD_DIR/$file'"
    done
    echo "=== Storage Reclaimed Successfully ==="
else
    echo "Disk cleanup cancelled."
fi
