# Kubernetes Deployment Guide

This guide explains how to deploy the CGI server to Kubernetes using kubectl.

## Prerequisites

- Kubernetes cluster (v1.20+)
- `kubectl` installed and configured
- Docker (for building the image locally)
- Container registry access (for storing the image)

## Quick Start

### 1. Build and Push Docker Image

```bash
# Build the Docker image
docker build -t mopa-laser-rasterizer:1 .

# Tag for your registry (replace with your registry URL)
docker tag mopa-laser-rasterizer:1 your-registry.com/mopa-laser-rasterizer:1

# Push to registry
docker push your-registry.com/mopa-laser-rasterizer:1
```

For local development with Docker Desktop or Minikube:
```bash
# Build directly (no push needed)
docker build -t mopa-laser-rasterizer:1 .
```

For local k3s development, use the helper script:
```powershell
# Windows PowerShell
.\load-k3s-image.ps1 -ImageName mopa-laser-rasterizer -ImageTag local
```

```bash
# WSL or Linux shell
./load-k3s-image.sh mopa-laser-rasterizer local
```

To deploy from WSL with the current checkout bind-mounted into `/app`:

```bash
sh ./deploy-local.sh
```

The script resolves the repository's WSL path at runtime, writes the ignored
`k8s/deployment.local.yaml`, applies it, and restarts the deployment. After
the image has been loaded once, edit files in the checkout and rerun this
command; a source-only change does not need an image rebuild.

### Local environment sync

The repo root contains the authoritative `.env.local` file for local path configuration.
Before applying Kustomize, sync it into the `k8s/` folder:
```bash
./sync-env.sh
```

For PowerShell:
```powershell
.\sync-env.ps1
```

A single script is also available to rebuild, load, clean, and apply:
```powershell
.\deploy-k8s.ps1
```

Example:
```powershell
.\deploy-k8s.ps1 -ImageName mopa-laser-rasterizer -ImageTag local -KubeConfigPath /etc/rancher/k3s/k3s.yaml
```

### AWS host-mounted source workflow

The AWS deployment bind-mounts the repository checkout on its selected EC2
node at `/app`. Source files are therefore read directly from the host; they
are not copied into a pod volume. Before applying the deployment, label the
one node that contains `/home/ubuntu/mopa-laser-rasterizer`:

```bash
kubectl label node <node-name> mopa-laser-rasterizer-host=true
```

Set `HOST_APP_PATH` in `.env.local` to the absolute path of that checkout (or
use the provided default in `.env.example`). After pulling code on that EC2
host, restart the deployment—no image build is needed for source-only changes:

```bash
cd /home/ubuntu/mopa-laser-rasterizer
git pull
kubectl rollout restart deployment/mopa-laser-rasterizer -n default
kubectl rollout status deployment/mopa-laser-rasterizer -n default
```

`hostPath` is node-local storage. Do not add the label to more than one node
unless each node has the same repository path and checkout. The image remains
the source of Python and OS dependencies, so rebuild it when dependencies or
the Dockerfile change.

Then apply from WSL:
```bash
wsl -e sh -lc 'cd projectdir && ./sync-env.sh && kubectl apply -k k8s/'
```

Then update your deployment to use that tag and restart it:
```bash
kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=mopa-laser-rasterizer:local
kubectl rollout restart deployment.mopa-laser-rasterizer
```

### 2. Deploy to Kubernetes

**Option A: Using individual YAML files**
```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/hpa.yaml
```

**Option B: Using Kustomize (recommended)**
```bash
kubectl apply -k k8s/
```

> Warning: do not use `kubectl apply -f k8s/kustomization.yaml`.
> That file is a Kustomize configuration, not a Kubernetes manifest.

**Option C: Using a single combined manifest**
```bash
kubectl apply -f k8s/
```

### 3. Verify Deployment

```bash
# Check deployment status
kubectl get deployment mopa-laser-rasterizer
kubectl get pods -l app=mopa-laser-rasterizer

# Check service
kubectl get service mopa-laser-rasterizer

# View pod logs
kubectl logs -f deployment/mopa-laser-rasterizer
kubectl logs -l app=mopa-laser-rasterizer --tail=100

# Describe deployment for details
kubectl describe deployment mopa-laser-rasterizer
```

### 4. Access the Server

**Using Port Forwarding:**
```bash
kubectl port-forward service/mopa-laser-rasterizer 8000:80
# Access at: http://localhost:8000
```

**Using LoadBalancer / Traefik:**
```bash
kubectl get service mopa-laser-rasterizer
# If the service is reachable, use the external IP on port 80
```

**Using Ingress via Traefik:**
1. Add a host entry on Windows for the Traefik external IP:
   - `172.30.216.123 mopa-laser-rasterizer.local`
2. Open the browser at:
   - `http://mopa-laser-rasterizer.local`

This is the preferred way to access the app without `kubectl port-forward`.

> Note: `http://localhost:31243/` may not work from Windows because k3s is running inside WSL and the Kubernetes NodePort is not automatically forwarded to Windows localhost.

## Kubernetes Files Overview

### deployment.yaml
- 3 replicas of the CGI server
- Resource limits and requests
- Liveness and readiness probes
- Volume mounts for static and templates directories

### service.yaml
- LoadBalancer service exposing port 80 → 8000
- Selector: `app: mopa-laser-rasterizer`

### configmap.yaml
- Configuration values (can be referenced by pods)
- Environment variables

### hpa.yaml
- Horizontal Pod Autoscaler
- Scales between 2-10 replicas
- Based on CPU (70%) and memory (80%) utilization

### ingress.yaml
- Traefik ingress controller integration
- TLS/SSL support (requires cert-manager)
- Routes `mopa-laser-rasterizer.local` to the service

### kustomization.yaml
- Kustomize configuration for managing multiple resources
- Common labels and annotations
- Image and replica management

## Configuration

### Environment Variables

Edit `k8s/configmap.yaml` to modify:
- `SERVER_PORT`: Port the server listens on (default: 8000)
- `PYTHONUNBUFFERED`: Python output buffering (default: 1)
- `LOG_LEVEL`: Logging level (default: INFO)

### Replicas

Modify the replicas in:
- `deployment.yaml`: `spec.replicas`
- `hpa.yaml`: `spec.minReplicas` and `spec.maxReplicas`

### Resource Limits

Modify in `deployment.yaml` under `spec.template.spec.containers[0].resources`:
- `requests`: Minimum guaranteed resources
- `limits`: Maximum allowed resources

## Common Operations

### Scale Deployment
```bash
# Set specific number of replicas
kubectl scale deployment mopa-laser-rasterizer --replicas=5

# Check HPA status
kubectl get hpa mopa-laser-rasterizer
```

### Update Image
```bash
# Set new image
kubectl set image deployment/mopa-laser-rasterizer \
  mopa-laser-rasterizer=mopa-laser-rasterizer:v2.0
```

### View Logs
```bash
# Recent logs
kubectl logs deployment/mopa-laser-rasterizer

# Follow logs
kubectl logs -f deployment/mopa-laser-rasterizer

# Previous pod logs
kubectl logs deployment/mopa-laser-rasterizer --previous
```

### Execute Commands in Pod
```bash
# Get pod name
kubectl get pods -l app=mopa-laser-rasterizer

# Execute command
kubectl exec -it <pod-name> -- /bin/bash
```

### Delete Deployment
```bash
# Delete using kustomize
kubectl delete -k k8s/

# Or delete individual resources
kubectl delete deployment mopa-laser-rasterizer
kubectl delete service mopa-laser-rasterizer
```

## Production Considerations

1. **Image Registry**: Use a private registry for sensitive code
2. **Namespace**: Consider using a dedicated namespace (see `k8s/namespace.yaml`)
3. **Network Policies**: Add network policies to restrict traffic
4. **RBAC**: Implement Role-Based Access Control
5. **Monitoring**: Add Prometheus metrics and alerting
6. **Logging**: Integrate with centralized logging (ELK, Loki, etc.)
7. **Security**: Run as non-root user, use security contexts
8. **Persistence**: Use PersistentVolumes for data storage if needed

## Troubleshooting

### Pods not starting
```bash
kubectl describe pod <pod-name>
kubectl logs <pod-name>
```

### Service not accessible
```bash
kubectl get endpoints mopa-laser-rasterizer
kubectl get svc mopa-laser-rasterizer
```

### Image pull errors
```bash
# Check image availability
kubectl describe pod <pod-name> | grep -A 5 "Pull"
```

### CrashLoopBackOff
```bash
# Check logs
kubectl logs <pod-name>
# Check previous logs
kubectl logs <pod-name> --previous
```

## Advanced: Custom Namespace

To deploy in a custom namespace:

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Deploy with namespace
kubectl apply -f k8s/ -n mopa-laser-rasterizer
```

Update the namespace in YAML files as needed.

## Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [kubectl Reference](https://kubernetes.io/docs/reference/kubectl/)
- [Deployment API Reference](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#deployment-v1-apps)
- [Service API Reference](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.28/#service-v1-core)
