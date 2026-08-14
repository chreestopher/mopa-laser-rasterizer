# AWS disaster-recovery runbook

This documents the production shape of MOPA Laser Rasterizer and the order to rebuild it. It deliberately contains no secrets. Keep the repository, Route 53/domain access, the Flask session secret, and Cognito client secret in a password manager or another secure store.

## Production topology

| Area | Configuration |
| --- | --- |
| Region | `us-east-2` |
| Public domain | `mopa-laser-rasterizer.com` and `www.mopa-laser-rasterizer.com` |
| Compute | One Ubuntu EC2 host, K3s, node label `mopa-laser-rasterizer-host=true` |
| App networking | NodePort `30080` to container port `8000` |
| Public edge | Internet-facing Application Load Balancer with ACM TLS termination |
| Artifacts | Private S3 bucket `mopa-laser-rasterizer-artifacts-<account-id>`; jobs expire after 7 days, saved Material Libraries persist |
| Account data | DynamoDB `mopa-laser-rasterizer-users`, on-demand; string keys `pk` and `sk` |
| Sign-in | Cognito Hosted UI, authenticated at the ALB |

The application mounts `/home/ubuntu/mopa-laser-rasterizer` from the EC2 host into `/app`. Application code changes therefore deploy with `git pull` and `sh dev_setup/restart_rollout.sh`; only dependency or Dockerfile changes require rebuilding/importing the local image.

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
- IAM role and instance profile `mopa-laser-rasterizer-ec2`.
- Least-privilege S3 and DynamoDB access used by the app.

Saved Material Libraries are deliberately outside the lifecycle filters, so they persist until explicitly deleted. Signed-in job uploads are tagged `mopa-retention=job`; guest job files remain under the `jobs/` prefix.

## 2. Rebuild EC2 and K3s

Create a small Ubuntu instance in the target VPC and attach the `mopa-laser-rasterizer-ec2` instance profile. Create or use two security groups:

| Security group | Inbound rule |
| --- | --- |
| ALB | Public TCP `80` and `443` |
| EC2 | TCP `30080` from the ALB security group only; SSH `22` from your fixed IP only |

Do not expose NodePort `30080` to the internet.

On the EC2 host:

```bash
curl -sfL https://get.k3s.io | sh -
sudo systemctl enable --now k3s
sudo kubectl label node "$(hostname)" mopa-laser-rasterizer-host=true --overwrite
cd /home/ubuntu
git clone https://github.com/chreestopher/mopa-laser-rasterizer.git
cd mopa-laser-rasterizer
sudo docker build -t mopa-laser-rasterizer:com .
sudo docker save mopa-laser-rasterizer:com | sudo k3s ctr -n k8s.io images import -
```

Generate the new session secret and deploy the workload:

```bash
SESSION_SECRET="$(openssl rand -hex 32)"
sudo kubectl create secret generic mopa-rasterizer-session \
  --from-literal=secret="$SESSION_SECRET" -n default
sudo kubectl apply -f k8s/redis.statefulset.yaml
sudo kubectl apply -f k8s/redis.service.yml
sudo kubectl apply -f k8s/service.aws.yaml
sudo kubectl apply -f k8s/deployment.aws.yaml
sudo kubectl rollout status deployment/mopa-laser-rasterizer -n default
```

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

To inspect the durable job record from a pod:

```bash
python -c 'from services import get_job_record; import json; print(json.dumps(get_job_record("TASK_ID"), indent=2))'
```

Account history is stored in DynamoDB; job inputs and outputs expire from S3 after seven days, at which point the file panel intentionally hides those expired entries. Saved Material Libraries persist independently.
