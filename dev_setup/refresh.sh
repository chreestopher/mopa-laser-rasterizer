# git pull
# sudo ./dev_setup/deploy.sh
# sudo kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=mopa-laser-rasterizer:com
# sudo kubectl rollout restart deployment/mopa-laser-rasterizer
# sudo sudo kubectl logs -f deployment/mopa-laser-rasterizer


#!/usr/bin/env bash
set -e # Exit immediately if any command returns a non-zero status

echo "===================================================="
echo "🚀 STARTING FULL CLEAN REDEPLOYMENT SEQUENCER"
echo "===================================================="

# 1. Pull latest application source code changes
echo "📥 Step 1: Pulling latest changes from Git..."
git pull

# 2. Run your underlying environment setup script
echo "🛠️ Step 2: Running environment developer configurations..."
sudo ./dev_setup/deploy.sh

echo "===================================================="
echo "🧹 PURGING EXISTING REDIS STATE LAYER COMPLETELY"
echo "===================================================="

# 3. Scale down the core application to free up scheduling RAM
echo "🛑 Scaling down application replicas to 0..."
sudo kubectl scale deployment/mopa-laser-rasterizer --replicas=0 --ignore-not-found=true

# 4. Remove all existing Redis controllers to stop active execution loops
echo "🗑️ Deleting Redis controllers..."
sudo kubectl delete statefulset redis-state-set --ignore-not-found=true --grace-period=0 --force
sudo kubectl delete deployment redis-state-deployment --ignore-not-found=true --grace-period=0 --force

# 5. HARD PURGE: Delete the storage volume claim so disk locks vanish
echo "💾 Purging Redis Persistent Volume Claim (PVC)..."
sudo kubectl delete pvc redis-data-redis-state-set-0 --ignore-not-found=true --grace-period=0 --force

# 6. Clear K3s/OS memory caching locks
echo "🧹 Flushing system storage block allocations..."
sync

echo "===================================================="
echo "🏗️ REBUILDING INFRASTRUCTURE COMPONENT LAYERS"
echo "===================================================="

# 7. Locate and re-apply your Redis infrastructure definition manifest
# If your redis definition is inside a different path, adjust this line!
if [ -f "redis.yaml" ]; then
    echo "📦 Re-applying clean Redis infrastructure specifications..."
    sudo kubectl apply -f redis.yaml
elif [ -f "dev_setup/redis.yaml" ]; then
    echo "📦 Re-applying clean Redis infrastructure specifications from dev_setup..."
    sudo kubectl apply -f dev_setup/redis.yaml
else
    echo "⚠️ Warning: Could not locate a standalone redis.yaml file. Skipping re-apply step."
fi

# 8. Re-apply the primary image tag payload to the web app
echo "🖼️ Updating application container image pointers..."
sudo kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=mopa-laser-rasterizer:com

# 9. Wait for the fresh Redis database engine to move into a Running status
echo "⏳ Waiting for fresh Redis StatefulSet to initialize..."
until [ "$(sudo kubectl get pod redis-state-set-0 -o jsonpath='{.status.phase}' 2>/dev/null)" == "Running" ]; do
    echo "   -> Redis is still pending or creating... retrying in 3 seconds..."
    sleep 3
done
echo "✅ Redis database is completely up and 1/1 READY!"

# 10. Bring the application web containers back online safely
echo "📈 Scaling application web framework up to 1 replica..."
sudo kubectl scale deployment/mopa-laser-rasterizer --replicas=1

# 11. Monitor deployment status to guarantee success
echo "📋 Verifying web node initialization..."
sudo kubectl rollout status deployment/mopa-laser-rasterizer

echo "===================================================="
echo "🎉 DEPLOYMENT COMPLETE! STREAMING LIVE POD LOGS:"
echo "===================================================="
sudo kubectl logs -f deployment/mopa-laser-rasterizer --tail=50
