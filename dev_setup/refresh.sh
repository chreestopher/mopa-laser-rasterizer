

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
sudo kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=mopa-laser-rasterizer:com
sudo kubectl rollout restart deployment/mopa-laser-rasterizer
sudo sudo kubectl logs -f deployment/mopa-laser-rasterizer


echo "===================================================="
echo "🏗️ REBUILDING INFRASTRUCTURE COMPONENT LAYERS"
echo "===================================================="


# 8. Re-apply the primary image tag payload to the web app
echo "🖼️ Updating application container image pointers..."
sudo kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=mopa-laser-rasterizer:com

# 9. Wait for the fresh Redis database engine to move into a Running status
echo "⏳ Waiting for fresh Redis StatefulSet to initialize..."
until [ "$(sudo kubectl get pod redis-state-set-0 -o jsonpath='{.status.phase}' 2>/dev/null)" = "Running" ]; do
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
