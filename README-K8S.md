# Kubernetes Deployment Guide

This guide covers local Kubernetes development and the production AWS K3s
deployment for MOPA Laser Rasterizer. Production separates responsive web
traffic from CPU- and memory-intensive raster jobs by running a web deployment
and a dedicated Redis-backed worker deployment.

## Prerequisites

- Kubernetes or K3s cluster
- `kubectl` installed and configured
- Docker (for building the image locally)
- AWS CLI access for production ECR, EC2, and VPC operations
- The production SSH key stored outside the repository

## Production topology

- Two EC2 K3s nodes in one VPC and Availability Zone.
- Two dedicated raster-worker pods, spread one per labeled node using required
  pod anti-affinity.
- Web pods scale independently from raster workers.
- Redis holds the waiting queue, processing queue, job status, logs, and worker
  leases.
- S3 holds durable job inputs and outputs; pod-local `/tmp/uploads` is scratch
  space only.
- Both deployments run the same immutable image tag from private ECR.
- Private workers receive ECR images through the deployment preload workflow
  and reach S3 and DynamoDB through free Gateway VPC Endpoints.

## Optional AWS Fargate worker

The dedicated worker can run as one-shot ECS/Fargate tasks without moving the web
application away from K3s. The existing Docker image is reused with
`python -u worker.py` as its command; Kubernetes manifests and deployment
scripts are not changed by this path.

Configure the workstation's Identity Center profile once:

```bash
aws configure sso --profile mopa-admin
```

Copy `.env.aws.example` to the ignored `.env.aws` and set `AWS_SSO_START_URL`,
`AWS_REGION`, `AWS_ACCOUNT_ID`, and the remaining production identifiers.
AWS deployment helpers load this file automatically. Keep the populated file
outside source control and back it up with the other operator recovery records.
Use the `AdministratorAccess` permission set. At the start of a
work session, or after the SSO session expires, authenticate with:

```bash
aws sso login --profile mopa-admin --use-device-code
aws sts get-caller-identity --profile mopa-admin
```

The workstation deployment scripts set `AWS_PROFILE` to `mopa-admin`, even if
the surrounding shell still has a root/default profile selected. Override it
only when another deployment identity is intended, for example
`DEPLOY_AWS_PROFILE=another-admin ./dev_setup/deploy_fargate_worker.sh`. They do
not use `aws login` for routine deployment authentication.

Fargate and the web pods **must use the same Redis instance** because Redis is
the job queue. A Kubernetes-only hostname such as `redis-service` is not
resolvable from ECS. Use a private VPC-reachable endpoint (normally
ElastiCache), update the K3s web deployment's `REDIS_HOST`, `REDIS_PORT`, and
`REDIS_SSL` values to match it, and verify that its security group permits the
web nodes too. Job artifacts continue to use the existing S3 bucket and job
history continues to use the existing DynamoDB table.

The minimum-change production path exposes the existing K3s Redis only inside
the VPC through `k8s/redis.fargate-service.yml` on NodePort `30379`. The EC2
security group must not expose this port publicly. The Fargate CloudFormation
stack adds a source-security-group rule so only its worker tasks can connect.
Use a K3s node's private IP as `REDIS_HOST`, port `30379`, and `REDIS_SSL=false`.
This retains the current single Redis StatefulSet availability characteristics;
move both web and worker clients to ElastiCache later if managed Redis
durability and failover are required.

The Fargate stack creates only the ECS cluster, task definition,
least-privilege task roles, CloudWatch log group, and worker security group. It
does not replace the web deployment, Redis, S3, or DynamoDB. Deploy from a
shell with AWS CLI and Docker access:

```bash
export VPC_ID=vpc-0123456789abcdef0
export SUBNET_IDS=subnet-aaa,subnet-bbb
export REDIS_HOST=primary.example.cache.amazonaws.com
export REDIS_SECURITY_GROUP_ID=sg-0123456789abcdef0
export REDIS_SSL=true
export REDIS_PASSWORD_SECRET_ARN=arn:aws:secretsmanager:us-east-2:123456789012:secret:redis-token
export S3_BUCKET_NAME=mopa-laser-rasterizer-artifacts-123456789012
export DYNAMODB_TABLE_NAME=mopa-laser-rasterizer-users
export SQS_QUEUE_ARN=arn:aws:sqs:us-east-2:123456789012:mopa-laser-raster-jobs
export SQS_DLQ_ARN=arn:aws:sqs:us-east-2:123456789012:mopa-laser-raster-jobs-dlq
export SQS_DLQ_URL=https://sqs.us-east-2.amazonaws.com/123456789012/mopa-laser-raster-jobs-dlq
./dev_setup/deploy_fargate_worker.sh
```

For the current production account, use the discovery wrapper instead of
exporting those values manually:

```bash
aws sso login --profile mopa-admin --use-device-code
bash dev_setup/start-k3s-tunnel.sh
bash dev_setup/deploy_production.sh
```

It derives the VPC, private Redis host, EC2 security group, and default subnets
from the control-plane instance configured as `K3S_INSTANCE_ID`, then calls the generic
deployment script. Override `K3S_INSTANCE_ID` during disaster recovery when the
control plane is replaced.

`REDIS_PASSWORD_SECRET_ARN` is optional and should reference a Secrets Manager
secret whose entire value is the Redis password/token. Do not put that value
in source control. Omit `REDIS_SSL=true` only for a Redis endpoint that does
not use in-transit encryption.

The default task is 1 vCPU, 4 GiB memory, and Fargate's included 20 GiB of
ephemeral scratch storage. Override compute with `FARGATE_CPU` and
`FARGATE_MEMORY`. Private subnets
need NAT or VPC endpoints for ECR, CloudWatch Logs, S3, DynamoDB, Secrets
Manager (when used), and the ECS control plane. For public subnets, explicitly
set `FARGATE_ASSIGN_PUBLIC_IP=ENABLED`.

Each accepted job has a task-addressable envelope in Redis. When
`FARGATE_DISPATCH_VIA_S3=true`, the web application writes a zero-byte
`jobs/TASK_ID/dispatch.ready` marker through the existing S3 gateway endpoint
and immediately returns the status page. S3 sends that event to SQS;
EventBridge Pipes starts a Standard Step Functions workflow, which extracts
the task ID, launches one Fargate task, and waits for its final container
result. This avoids a paid SQS interface endpoint on private K3s nodes. The
manual launcher remains available for diagnostics:

```bash
./dev_setup/run_fargate_worker.sh TASK_ID
aws logs tail /ecs/mopa-laser-raster-worker --follow
```

Without `FARGATE_DISPATCH_VIA_S3` or `SQS_QUEUE_URL`, the existing Kubernetes
worker consumes the Redis list, so recovery deployments remain backward
compatible.
`worker.py --task-id TASK_ID` claims
the persisted envelope, skips an already-completed task idempotently, processes
only that task, and exits. The workflow retries a nonzero exit up to three
times, then explicitly sends the task ID to the DLQ. Scale the Kubernetes
worker deployment to zero only after the SQS success and DLQ paths are verified.
The production `k8s/worker.aws.yaml` therefore keeps zero legacy replicas;
increase it only during an intentional Redis-queue rollback.

ECS allows a maximum 120-second container stop timeout. The worker handles
`SIGTERM` and tries to finish its current job; if a longer job is forcibly
stopped, its renewable Redis lease expires and the task can be retried safely.

## Authentication mechanisms

### Private administrator console

`/admin` is default-deny and is not linked from public navigation. It requires
an ALB-authenticated Cognito identity whose verified email exactly matches the
`ADMIN_EMAIL` value held in the `mopa-rasterizer-admin` Kubernetes Secret.
Configure or change that email from WSL while the K3s tunnel is running:

```bash
bash dev_setup/configure-k3s-admin.sh you@example.com
```

The script stores the email in Kubernetes rather than the repository, grants
the EC2 instance role read-only `cognito-idp:ListUsers` access to the configured
pool, injects the Secret into the web deployment, and waits for the rollout.
If the Secret is absent, no account can open `/admin`. The console lists jobs
from the seven-day retention window, exposes retained logs, permits only
waiting jobs to be removed from the queue, and displays the Cognito user count.

The deployment scripts do not contain or inherit one universal credential.
Each operation uses the authentication mechanism appropriate to the system it
contacts:

| Operation | Authentication source |
| --- | --- |
| Local `aws` commands | AWS CLI credentials configured in WSL, normally through `~/.aws/config` and `~/.aws/credentials` |
| Docker push to private ECR | A temporary ECR authorization token requested by the local AWS CLI during each deployment |
| SSH and file transfer to EC2 | The private PEM key selected by `K3S_SSH_KEY`; the key remains outside the repository |
| Local `kubectl` commands | The production kubeconfig plus an SSH tunnel to the K3s API on the control-plane EC2 instance |
| Application access to S3 and DynamoDB | The IAM instance profile attached to the EC2 node, currently `mopa-laser-rasterizer-ec2-profile` |
| EC2 image access to ECR | The node's IAM instance profile when using an ECR credential provider, or images preloaded by the deployment script |

The K3s tunnel only carries Kubernetes API traffic. It does not run local AWS
CLI commands on EC2 and does not lend the EC2 role to WSL. Commands such as
`aws ec2 describe-instances`, VPC endpoint creation, and ECR pushes therefore
use the AWS identity configured on the workstation. Code running in a pod uses
the EC2 node's IAM role through AWS instance metadata.

Do not commit AWS access keys, the PEM key, kubeconfig files, Flask or Cognito
secrets, generated ECR passwords, or local `.env` files. ECR passwords are
short-lived and are refreshed by the deployment workflow; permanent cloud
permissions remain in IAM rather than in the repository.

## Connect to production from WSL

Start the SSH tunnel before using `kubectl` or a deployment script:

```bash
bash dev_setup/start-k3s-tunnel.sh
export KUBECONFIG="$HOME/.kube/mopa-rasterizer-production.yaml"
kubectl get nodes -o wide
```

The tunnel maps the remote K3s API to `https://127.0.0.1:16443`. Stop only the
local tunnel when finished; this does not stop the cluster or its workloads:

```bash
bash dev_setup/stop-k3s-tunnel.sh
```

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

### AWS private-ECR workflow

Production images are built once, pushed to private ECR, and deployed under
the same immutable tag to the K3s web pods and Fargate worker task. Authenticate
the AWS CLI, start the K3s tunnel, and run:

```bash
bash dev_setup/start-k3s-tunnel.sh
bash dev_setup/deploy_production.sh
```

The optional first argument overrides the automatically generated immutable
tag:

```bash
bash dev_setup/deploy_production.sh release-2026-08-22
```

The script deploys the same image to the web and one-shot Fargate raster-worker
deployments. It also refreshes the short-lived `ecr-registry` pull secret.
Install the AWS ECR kubelet credential provider when nodes must join and pull
images independently of a recent deployment.

Private EC2 workers also require a route to S3 because queued job inputs and
outputs are stored there. Prepare each worker before scheduling pods:

```bash
bash dev_setup/ensure-ec2-aws-gateway-endpoints.sh <worker-instance-id>
bash dev_setup/add-ec2-k3s-worker.sh <worker-instance-id>
```

The add-worker script invokes the endpoint setup automatically; the separate
command is useful during disaster recovery or when validating networking.

To join a replacement or additional EC2 worker and spread two worker replicas:

```bash
bash dev_setup/add-ec2-k3s-worker.sh <worker-instance-id>
bash dev_setup/deploy-worker-to-node.sh <kubernetes-node-name>
```

The add-worker script verifies the shared VPC, IAM instance profile, security
group rules, private S3 and DynamoDB routes, HTTPS connectivity to both APIs,
K3s membership, and node labels. A private node must not receive application
pods or raster jobs until this succeeds.

### Deploy current workspace code

`deploy_production.sh` builds from the current workspace and `.dockerignore`, assigns
a unique immutable tag containing the current Git commit prefix and UTC build
time, pushes it, preloads private workers, and deploys that exact tag:

```bash
bash dev_setup/start-k3s-tunnel.sh
bash dev_setup/deploy_production.sh
```

The normal Fargate production topology leaves
`K3S_PRIVATE_WORKER_INSTANCE_IDS` empty, so the preload phase is skipped and
both web replicas run on the single K3s control-plane node.

Uncommitted workspace files included by the Docker build context are included
in the image. The Git portion of the tag identifies the checked-out commit; it
does not mean the image contains only committed files.

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
kubectl get deployment mopa-laser-rasterizer mopa-laser-raster-worker
kubectl rollout status deployment/mopa-laser-rasterizer --timeout=20m
kubectl rollout status deployment/mopa-laser-raster-worker --timeout=120m
kubectl get nodes -o wide
kubectl get pods -o wide

# Check service
kubectl get service mopa-laser-rasterizer

# View pod logs
kubectl logs -f deployment/mopa-laser-rasterizer
kubectl logs -l app=mopa-laser-rasterizer --tail=100

# Confirm both deployments reference the intended immutable image
kubectl get deployment mopa-laser-rasterizer mopa-laser-raster-worker \
  -o=jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.template.spec.containers[0].image}{"\n"}{end}'

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

### deployment.aws.yaml
- Production web deployment served by Gunicorn
- Resource limits and requests
- Liveness and readiness probes

### worker.aws.yaml
- Two dedicated Redis-backed raster workers
- One worker per labeled node through required pod anti-affinity
- A 90-second renewable job lease and 15-second stale-job recovery scan
- A two-hour graceful termination window for active raster jobs
- Pod-local scratch storage with durable artifacts transferred through S3

### service.yaml
- LoadBalancer service exposing port 80 → 8000
- Selector: `app: mopa-laser-rasterizer`

### configmap.yaml
- Configuration values (can be referenced by pods)
- Environment variables

### hpa.yaml
- Horizontal Pod Autoscaler
- Scales only the web deployment between 2 and 4 replicas
- Uses absolute average targets of `200m` CPU and `384Mi` memory
- Requires sustained pressure for 60 seconds and adds at most one pod per minute
- Uses a five-minute scale-down stabilization window

These limits prevent short job-submission spikes from causing the previous
rapid `2 -> 3 -> 6 -> 9` web-pod scaling storm. Raster-worker replicas are
managed separately and are not controlled by this HPA.

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
- `k8s/hpa.yaml`: web `minReplicas` and `maxReplicas`
- `k8s/worker.aws.yaml`: dedicated worker replicas

With required worker pod anti-affinity, two worker replicas require two Ready,
worker-labeled nodes. A second worker remains `Pending` if only one eligible
node is available.

### Resource Limits

Modify in `deployment.yaml` under `spec.template.spec.containers[0].resources`:
- `requests`: Minimum guaranteed resources
- `limits`: Maximum allowed resources

## Common Operations

### Scale Deployment
```bash
# Inspect web autoscaling and current resource targets
kubectl get hpa mopa-laser-rasterizer
kubectl describe hpa mopa-laser-rasterizer

# Apply the repository's corrected production HPA through the tunnel
bash dev_setup/apply-k3s-hpa.sh
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

# Follow every web pod, with the pod/container prefix on each line
kubectl logs -f -l app=mopa-laser-rasterizer \
  --all-containers=true --prefix=true --max-log-requests=10 --tail=100

# Follow every dedicated raster worker
kubectl logs -f -l app=mopa-laser-raster-worker \
  --all-containers=true --prefix=true --max-log-requests=10 --tail=100
```

Press `Ctrl+C` to stop following logs. This stops only the local log command;
it does not stop pods or jobs.

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

Private workers without NAT cannot pull directly from ECR or Docker Hub. The
normal `deploy_production.sh` workflow preloads the application image. For a newly
joined node, use the current deployment workflow or the targeted helpers:

```bash
bash dev_setup/preload-k3s-worker-image.sh <instance-id> <complete-image-uri>
bash dev_setup/sync-k3s-worker-images.sh <instance-id>
```

### Job stops after the worker claims it

A normal job console should advance through:

```text
Dedicated raster worker claimed the job.
Downloading the source image from durable storage.
Source image download complete.
```

If it remains at the download step, check which node owns the worker and test
that node's S3 path:

```bash
kubectl get pods -l app=mopa-laser-raster-worker -o wide
bash dev_setup/ensure-ec2-aws-gateway-endpoints.sh <instance-id>
```

The worker renews a 90-second Redis lease while it owns a job. If a genuinely
hung worker must be removed, cordon its node before deleting the pod so the
replacement cannot immediately land on the same unhealthy node. After the
lease expires, a healthy worker requeues the processing entry automatically.
Restore S3 access and verify it before uncordoning the node.

### Worker rollout remains pending

```bash
kubectl get nodes --show-labels
kubectl get pods -l app=mopa-laser-raster-worker -o wide
kubectl describe pod <pending-worker-pod>
```

Confirm two nodes are Ready and carry `rasterizer.mopa/workload=worker`. Because
the deployment requires one worker per hostname, Kubernetes intentionally will
not place both replicas on the same node.

### Site slows down after job submission

Raster work should run only in `mopa-laser-raster-worker`. Inspect web HPA
behavior and placement:

```bash
kubectl get hpa mopa-laser-rasterizer -w
kubectl top pods
kubectl get pods -o wide
```

Apply `dev_setup/apply-k3s-hpa.sh` if the live HPA differs from the repository.
The current policy caps web pods at four and prevents short submission bursts
from repeatedly doubling replicas.

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
