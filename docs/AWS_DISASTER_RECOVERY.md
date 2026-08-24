# AWS disaster-recovery runbook

This documents the production shape of MOPA Laser Rasterizer and the order to rebuild it. It deliberately contains no secrets. Keep the repository, Route 53/domain access, the Flask session secret, and Cognito client secret in a password manager or another secure store.

Production-specific, non-secret identifiers live in the ignored `.env.aws` on
the operator workstation. Restore it from the secured operator backup or copy
`.env.aws.example` and populate it before running any deployment helper. The
scripts load it automatically. Credentials, private keys, passwords, and
application secrets do not belong in this file.

## Production topology

| Area | Configuration |
| --- | --- |
| Region | `us-east-2` |
| Public domain | `mopa-laser-rasterizer.com` and `www.mopa-laser-rasterizer.com` |
| Compute | One Ubuntu EC2 K3s control-plane node runs two web pods, Redis, and K3s system pods; raster work runs in one-shot Fargate tasks |
| Private AWS access | S3 and DynamoDB Gateway VPC Endpoints are associated with every cluster-node subnet route table |
| App networking | NodePort `30080` to container port `8000` |
| Public edge | Internet-facing Application Load Balancer with ACM TLS termination |
| Artifacts | Private S3 bucket `mopa-laser-rasterizer-artifacts-<account-id>`; jobs expire after 7 days, saved Material Libraries persist |
| Account data | DynamoDB `mopa-laser-rasterizer-users`, on-demand; string keys `pk` and `sk` |
| Container images | Private ECR repository `mopa-laser-rasterizer` in `us-east-2`; immutable tags, scan-on-push, newest 20 images retained |
| Raster task queue | Encrypted standard SQS queue `mopa-laser-raster-jobs`; 7-day retention, 2-hour visibility, three receives before redrive |
| Failed raster tasks | Encrypted SQS DLQ `mopa-laser-raster-jobs-dlq`; 14-day retention and restricted to the raster task queue |
| Sign-in | Cognito Hosted UI, authenticated at the ALB |

The application runs entirely from an immutable image in ECR. `/tmp/uploads` is pod-local scratch space; job inputs and outputs move through S3. A deployment must build and push a new image even for source-only changes.

## 1. Restore account-level resources

Open AWS CloudShell in Ohio, copy in [aws_bootstrap_cloudshell.sh](../dev_setup/aws_bootstrap_cloudshell.sh), then run:

```bash
chmod +x aws_bootstrap_cloudshell.sh
./aws_bootstrap_cloudshell.sh
```

The script safely repeats and configures:

- A private, AES-256 encrypted S3 bucket.
- Seven-day lifecycle rules for guest and signed-in job artifacts, including incomplete-multipart abort after one day.
- DynamoDB in `PAY_PER_REQUEST` mode, primary key `pk` plus sort key `sk`.
- A private, AES-256 encrypted ECR repository with immutable tags, scan-on-push, and a newest-20-images lifecycle policy.
- SQS standard queues `mopa-laser-raster-jobs` and
  `mopa-laser-raster-jobs-dlq`, encrypted with SQS-managed keys. The source
  queue uses long polling, a two-hour visibility timeout, seven-day retention,
  and retains its native redrive policy as a transport-level fallback.
- IAM role and instance profile `mopa-laser-rasterizer-ec2`.
- Least-privilege S3, DynamoDB, ECR-pull, and SQS producer access used by the
  app and K3s nodes. Queue consumers require a separate launcher role with
  receive/delete/change-visibility access; the web role intentionally does not
  receive or delete messages.

To create or reconcile only the queues without touching the other account
resources, run `dev_setup/ensure-sqs-raster-queues.sh` instead.

Saved Material Libraries are deliberately outside the lifecycle filters, so they persist until explicitly deleted. Signed-in job uploads are tagged `mopa-retention=job`; guest job files remain under the `jobs/` prefix.

The final bootstrap output includes `SQS_QUEUE_NAME`, `SQS_QUEUE_URL`,
`SQS_QUEUE_ARN`, `SQS_DLQ_NAME`, `SQS_DLQ_URL`, and `SQS_DLQ_ARN`. Record these
non-secret identifiers with the recovered environment configuration. Override
the default names with `SQS_QUEUE_NAME` and `SQS_DLQ_NAME`; override the retry
threshold with `SQS_MAX_RECEIVE_COUNT` before running the bootstrap.

Verify the restored redrive relationship:

```bash
aws sqs get-queue-attributes --region us-east-2 \
  --queue-url "$SQS_QUEUE_URL" \
  --attribute-names QueueArn RedrivePolicy VisibilityTimeout MessageRetentionPeriod SqsManagedSseEnabled
aws sqs get-queue-attributes --region us-east-2 \
  --queue-url "$SQS_DLQ_URL" \
  --attribute-names QueueArn RedriveAllowPolicy MessageRetentionPeriod SqsManagedSseEnabled
```

### Restore administrative human access

Use an organization instance of IAM Identity Center for human administration;
reserve the root user for root-only recovery tasks. Organization-instance
activation is completed once in the AWS console because AWS does not expose
that operation through the public `CreateInstance` API:

1. Open IAM Identity Center in `us-east-2` from the Organization management
   account.
2. Enable with AWS Organizations, permission sets enabled, AWS-owned
   encryption, and `us-east-2` as the primary Region.
3. Reconcile the administrator identity and assignment:

```bash
bash dev_setup/configure-identity-center-admin.sh \
  "$IDENTITY_CENTER_ADMIN_EMAIL" "$IDENTITY_CENTER_ADMIN_USERNAME"
```

The script is idempotent. It enables Organizations trusted access for Identity
Center, discovers the instance and identity store, creates or reuses the user,
`Admin team` group, and four-hour `AdministratorAccess` permission set, ensures
group membership, attaches AWS's managed `AdministratorAccess` policy, and
waits for the management-account assignment to complete. Override the profile
name fields with `IDENTITY_CENTER_ADMIN_GIVEN_NAME` and
`IDENTITY_CENTER_ADMIN_FAMILY_NAME` when restoring a different administrator.

Identity Center authentication policy is configured in the console. Under
**Settings → Authentication → Multi-factor authentication → Configure**, keep
MFA enabled, enable authenticator apps and/or security keys, and set **If a
user does not yet have a registered MFA device** to **Require them to register
an MFA device at sign in**. Do not select **Block their sign-in** for a newly
restored directory because API/CLI-created users begin without an MFA device.
Under standard authentication, enable **Send email OTP** so users created by
the API/CLI can establish their initial password through their verified email.

Do not delete root credentials until the administrator has signed in through
the AWS access portal, configured an AWS CLI SSO profile, and successfully run
`aws sts get-caller-identity` through that profile.

Configure the workstation profile once and authenticate it when each SSO
session begins or expires:

```bash
aws configure sso --profile mopa-admin
aws sso login --profile mopa-admin --use-device-code
aws sts get-caller-identity --profile mopa-admin
export AWS_PROFILE=mopa-admin
```

Routine deployment helpers explicitly select `mopa-admin`, even when the
surrounding shell has another `AWS_PROFILE`. Set `DEPLOY_AWS_PROFILE` only when
another deployment identity is intentional. `aws login` is reserved for
IAM/root sign-in workflows and is not the Identity Center deployment command.

## 2. Rebuild EC2 and K3s

Create a small Ubuntu instance in the target VPC and attach the `mopa-laser-rasterizer-ec2` instance profile. Create or use two security groups:

| Security group | Inbound rule |
| --- | --- |
| ALB | Public TCP `80` and `443` |
| EC2 | TCP `30080` from the ALB security group only; SSH `22` from your fixed IP only |

Do not expose NodePort `30080` to the internet.

Before scheduling application pods on a private node, give its route table
private access to S3. From WSL, with the AWS CLI authenticated, run:

```bash
bash dev_setup/ensure-ec2-aws-gateway-endpoints.sh <ec2-instance-id>
```

The script creates or reuses the regional S3 and DynamoDB Gateway VPC
Endpoints and associates the instance subnet's effective route table. These
Gateway endpoints do not require a NAT gateway or public IPv4 address. The
instance profile must still contain the S3 and DynamoDB permissions created in
section 1.

On the EC2 host:

```bash
curl -sfL https://get.k3s.io | sh -
sudo systemctl enable --now k3s
cd /home/ubuntu
git clone "$GITHUB_REPOSITORY_URL"
cd mopa-laser-rasterizer
```

Generate the new session secret and deploy the workload:

```bash
SESSION_SECRET="$(openssl rand -hex 32)"
sudo kubectl create secret generic mopa-rasterizer-session \
  --from-literal=secret="$SESSION_SECRET" -n default
sudo kubectl apply -f k8s/redis.statefulset.yaml
sudo kubectl apply -f k8s/redis.service.yml
sudo kubectl apply -f k8s/redis.fargate-service.yml
sudo kubectl apply -f k8s/service.aws.yaml
bash dev_setup/start-k3s-tunnel.sh
bash dev_setup/deploy_production.sh
```

`redis.fargate-service.yml` exposes Redis on NodePort `30379` for the one-shot
Fargate workers. Do not add a public CIDR ingress rule for this port. The
Fargate stack creates a worker security group and permits only that group on
the K3s node security group. The Fargate deployment uses a K3s node private IP
as `REDIS_HOST` and `30379` as `REDIS_PORT`.

Deploy or reconcile the Fargate task after the K3s control plane exists:

```bash
aws sso login --profile mopa-admin --use-device-code
K3S_INSTANCE_ID=<replacement-control-plane-id> \
  bash dev_setup/deploy_fargate_worker_production.sh
```

The wrapper discovers non-secret VPC settings from that instance. The verified
2026-08-24 deployment created CloudFormation stacks `mopa-rasterizer-worker`
and `mopa-rasterizer-orchestration`, ECS
cluster `mopa-laser-rasterizer`, task family `mopa-laser-raster-worker`, log
group `/ecs/mopa-laser-raster-worker`, and the worker security group recorded
as `FARGATE_WORKER_SECURITY_GROUP_ID` in the ignored `.env.aws`. The EC2 node
security group permits NodePort `30379`
only from that worker security group; never replace it with a public CIDR rule.
CloudFormation outputs remain authoritative if the stack is recreated.

The orchestration stack creates EventBridge Pipe
`mopa-rasterizer-jobs-to-fargate` and Standard workflow
`mopa-rasterizer-fargate-job`. The web application writes a zero-byte
`jobs/TASK_ID/dispatch.ready` S3 marker; the bucket notification sends the
object-created event to SQS, and the pipe starts one workflow per marker. This
uses the existing free S3 gateway endpoint instead of requiring a paid SQS
interface endpoint for private K3s nodes. The workflow waits for each ECS task
to stop, tries Fargate Spot twice, falls back to one regular Fargate task, and
explicitly sends the task ID to the 14-day DLQ only if all three executions
fail. Override the number of Spot attempts with
`FARGATE_SPOT_WORKER_ATTEMPTS`; the on-demand fallback is always retained.
Set `FARGATE_DISPATCH_VIA_S3=true` on the web deployment only after the bucket
notification and orchestration stack are healthy.

The normal production topology does not require a second EC2 node. To restore
one temporarily for capacity or a Kubernetes-worker rollback after the control plane is available and the
local K3s tunnel is running:

```bash
bash dev_setup/add-ec2-k3s-worker.sh <worker-instance-id>
bash dev_setup/deploy-worker-to-node.sh <worker-instance-id>
```

`add-ec2-k3s-worker.sh` now ensures both Gateway endpoints before joining and
labeling the node. Do not label or uncordon a replacement worker until its S3
and DynamoDB HTTPS connectivity succeeds; workers retrieve inputs from S3 and
persist durable job status in DynamoDB.

`deploy_production.sh` builds and pushes one unique immutable image, updates the
Fargate task and orchestration stacks, preloads private K3s nodes, refreshes the
`ecr-registry` Kubernetes pull secret, renders and applies both workload
manifests, and verifies that the web image matches while the legacy K3s worker
remains at zero replicas. Reusing the same tag resumes a partial rollout from
the existing immutable ECR image.

The pull secret contains a short-lived ECR authorization token and is refreshed by every deployment. For replacement nodes that must start pods without a recent deployment, configure the AWS ECR kubelet credential provider on every K3s node. The EC2 instance profile created by the bootstrap script includes the required read-only ECR actions. Do not store ECR passwords in this repository.

Before applying `deployment.aws.yaml`, set its S3 bucket, DynamoDB table, Cognito domain/client ID, and public URL for the recovered environment. These are identifiers, not secret values.

## 3. ACM, Cognito, ALB, and DNS

The bootstrap script can create a replacement Cognito pool and generated-secret app client with `CREATE_COGNITO=1`. It prints the new secret exactly once, so save it immediately in a secure secret store. It can also configure the ALB, target group, listener rules, and root/`www` Route 53 aliases when invoked with `CONFIGURE_EDGE=1`. Edge setup intentionally requires VPC, subnet, security-group, instance, certificate, Route 53, and Cognito values as runtime environment variables; no secret is written to the script or repository.

1. Request an ACM public certificate in `us-east-2` for the root domain and `www`; complete its Route 53 DNS validation.
2. Create a Cognito User Pool using email sign-in and verification. Create an app client with a generated secret, OAuth code flow, scopes `openid email profile`, callback URL `https://mopa-laser-rasterizer.com/oauth2/idpresponse`, and logout URL `https://mopa-laser-rasterizer.com/`. Create a Cognito hosted-UI domain.
3. Create an internet-facing **Application Load Balancer** in two public subnets. Its target group is type `instance`, protocol HTTP, port `30080`, health-check path `/auth-status`, and includes the EC2 instance.
4. Add ALB listener `:80` to redirect permanently to HTTPS while preserving host/path/query.
5. Add HTTPS listener `:443` using the ACM certificate. Configure rules in this order:

   1. `/logout*`: forward directly to the target group.
   2. `/login*`: Cognito authenticate with unauthenticated action `authenticate`, then forward.
   3. Default: Cognito authenticate with unauthenticated action `allow`, then forward.

   Every Cognito action uses the same pool, app-client ID/secret, and hosted-UI domain. The direct logout rule is required so Flask can clear the ALB session and redirect to Cognito logout.

6. In Route 53, create root and `www` A Alias records to the ALB. Verify HTTP redirects and HTTPS presents the ACM certificate.

## 4. Validate the restoration

```bash
sudo kubectl get pods -n default
sudo kubectl get svc mopa-laser-rasterizer -n default
curl -I http://mopa-laser-rasterizer.com/
curl -I https://mopa-laser-rasterizer.com/
```

Confirm the ALB target is healthy, guests receive three daily jobs, `/login` reaches Cognito, sign-out works, and a signed-in job writes S3 objects below `users/<cognito-sub>/jobs/<task-id>/`.

Restore the private administrator binding after the K3s API tunnel is available:

```bash
bash dev_setup/configure-k3s-admin.sh you@example.com
```

This recreates the `mopa-rasterizer-admin` Secret without placing the email in
source control, restores the Cognito directory permission, and rolls the web
deployment. Verify that the configured account can open `/admin` and that a
different signed-in account receives a 404 response.

Confirm both workloads use the same ECR image and that each node can pull it:

```bash
sudo kubectl get deployment mopa-laser-rasterizer mopa-laser-raster-worker \
  -n default -o=jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.template.spec.containers[0].image}{"\n"}{end}'
sudo kubectl get pods -n default -o wide
```

Also launch a small SVG-only test job on each worker node. Its console should
show `Downloading the source image from durable storage` followed by `Source
image download complete` before raster processing begins. If it remains at the
download message, cordon that node and verify its S3 endpoint route and IAM
profile before returning it to service.

To inspect the durable job record from a pod:

```bash
python -c 'from services import get_job_record; import json; print(json.dumps(get_job_record("TASK_ID"), indent=2))'
```

Account history is stored in DynamoDB; job inputs and outputs expire from S3 after seven days, at which point the file panel intentionally hides those expired entries. Saved Material Libraries persist independently.
