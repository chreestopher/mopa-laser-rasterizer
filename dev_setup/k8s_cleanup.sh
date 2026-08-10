#!/bin/bash

# Configuration - Match your deployment specs
NAMESPACE="default"
FLASK_POD_PREFIX="mopa-laser-rasterizer"
REDIS_POD="redis-state-set-0"
UPLOAD_DIR="/app/uploads"

echo "=== Searching for Task Keys in Redis ==="

# 1. Fetch all matching status keys from Redis using standard patterns
STATUS_KEYS=$(kubectl exec -n $NAMESPACE $REDIS_POD -- redis-cli --no-auth-warning keys "task:*:status")

if [ -z "$STATUS_KEYS" ]; then
    echo "No matching Redis task keys found. Exiting."
    exit 0
fi

# 2. Extract and display clean Task IDs to the user
echo "Found the following active Task IDs:"
TASK_IDS=()
for key in $STATUS_KEYS; do
    # Extract task_id from "task:task_id:status"
    task_id=$(echo "$key" | cut -d':' -f2)
    TASK_IDS+=("$task_id")
    echo " - $task_id"
done

echo ""
read -p "Are you sure you want to delete these tasks from Redis and Disk? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Cleanup cancelled."
    exit 0
fi

# 3. Find an active application pod to execute disk commands
APP_POD=$(kubectl get pods -n $NAMESPACE --no-headers -o custom-columns=":metadata.name" | grep "^$FLASK_POD_PREFIX" | head -n 1)

if [ -z "$APP_POD" ]; then
    echo "Error: Could not find an active $FLASK_POD_PREFIX pod to run disk deletion."
    exit 1
fi

echo "Using application pod $APP_POD for disk access..."

# 4. Loop through and purge each task
for task_id in "${TASK_IDS[@]}"; do
    echo "Purging Task: $task_id ..."
    
    # Delete from Redis
    kubectl exec -n $NAMESPACE $REDIS_POD -- redis-cli --no-auth-warning del "task:$task_id:status" "task:$task_id:log" "task:$task_id:downloads" > /dev/null
    echo " -> Redis keys deleted."
    
    # Delete matching files from the shared /app/uploads volume (handles logs, status files, and variables)
    kubectl exec -n $NAMESPACE $APP_POD -- sh -c "rm -f $UPLOAD_DIR/$task_id.* $UPLOAD_DIR/*$task_id*" 2>/dev/null
    echo " -> Disk files deleted."
done

echo "=== Cleanup Complete ==="
