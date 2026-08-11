# 1. Force remove all stopped or dead container instances
sudo k3s crictl rm $(sudo k3s crictl ps -a -q) 2>/dev/null || true

# 2. Force prune all orphaned image blob layers and snapshots
sudo k3s crictl rmi --prune
sync
df -h /
sudo kubectl taint nodes --all node.kubernetes.io/disk-pressure:NoSchedule-

# 1. Force prune Docker's modern BuildKit builder layer cache (The 29GB snapshotter hog)
sudo docker builder prune -a -f

# 2. Force delete all unused or dangling docker system volumes and containers
sudo docker system prune -a --volumes -f