# jambonz Large CloudFormation Deployment

This directory contains the base CloudFormation template for "jambonz large" - a highly scalable multi-tier architecture with separate SBC SIP, SBC RTP, Feature Server, Web Server, and Monitoring components, backed by Aurora Serverless MySQL and ElastiCache Redis. Suitable for large-scale production workloads requiring maximum scalability and separation of concerns.

**Important:** Do not deploy `_jambonz-base-template.yaml` directly. Instead, run `../generate-cf.sh` from the project root to generate a deployable template.

Use this Cloudformation deployment for production workloads requiring high availability and scalability that need to scale to over 1,500 concurrent calls.

## Architecture

The large deployment creates:

- **SBC SIP Auto Scaling Group** - Handles SIP signaling with drachtio
- **SBC RTP Auto Scaling Group** - Handles RTP media with rtpengine
- **Feature Server Auto Scaling Group** - Runs jambonz application logic with FreeSWITCH
- **Web Server** - Hosts the portal, API, and public apps. Either a single instance with an Elastic IP, or an Auto Scaling group (1-4 instances) behind an internet-facing ALB - see [Web server deployment](#web-server-deployment)
- **Monitoring Server** - Hosts Grafana, Homer, Jaeger, InfluxDB, and Cassandra
- **Aurora Serverless v2** - MySQL database cluster
- **ElastiCache** - Redis for caching and pub/sub: a primary and a replica in two availability zones,
  with automatic failover (two nodes, so twice the cost of one)
- **Recording Cluster** - Auto-scaling recording servers behind an internal ALB (always deployed)

## Prerequisites

- AWS CLI and credentials configured
- `yq` installed (YAML processor)
- An existing EC2 Key Pair in the target region
- An AWS account with permissions to create VPCs, EC2 instances, IAM roles, RDS, ElastiCache, and Elastic IPs

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `Architecture` | CPU architecture: `amd64` (x86_64) or `arm64` (Graviton). Allowed values are limited to the architectures whose AMIs were copied | amd64 |
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `URLPortal` | DNS name for the portal | (required) |
| `WebServerDeployment` | `single-instance` or `autoscaling-alb` - see [Web server deployment](#web-server-deployment) | single-instance |
| `HostedZoneId` | `autoscaling-alb`: Route 53 zone containing `URLPortal`; the stack issues the ALB certificate and creates the web DNS records | (none) |
| `WebCertificateArn` | `autoscaling-alb`: your own ACM certificate for the ALB, instead of `HostedZoneId` | (none) |
| `EnablePcaps` | Enable PCAPs for SIP traffic | (required) |
| `InstanceTypeSbcSip` | EC2 instance type for SBC SIP servers | c5n.xlarge |
| `InstanceTypeSbcRtp` | EC2 instance type for SBC RTP servers | c5n.xlarge |
| `InstanceTypeFeatureServer` | EC2 instance type for Feature servers | c5n.xlarge |
| `InstanceTypeWebserver` | EC2 instance type for Web server | c5n.xlarge |
| `InstanceTypeMonitoringServer` | EC2 instance type for Monitoring server | c5n.xlarge |
| `RecordingInstanceType` | EC2 instance type for Recording servers | t2.xlarge |
| `ElastiCacheNodeType` | ElastiCache node type, for each of the two Redis nodes | cache.t3.medium |
| `AuroraDBMinCapacity` | Aurora Serverless min ACU | 0.5 |
| `AuroraDBMaxCapacity` | Aurora Serverless max ACU | 8 |
| `AllowedSshCidr` | **Required.** CIDR allowed to SSH to the instances: your admin IP as `x.x.x.x/32`, or your VPN range | (none) |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | 0.0.0.0/0 |
| `AllowedSipCidr` | CIDR for SIP access | 0.0.0.0/0 |
| `AllowedSmppCidr` | CIDR for SMPP access | 0.0.0.0/0 |
| `AllowedRtpCidr` | CIDR for RTP traffic | 0.0.0.0/0 |
| `VpcCidr` | CIDR range for the VPC | 172.20.0.0/16 |
| `MySQLUsername` | Database username | admin |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs (1–365). Enforced on the log groups: a shorter value deletes older events. SOC 2 typically expects ≥ 90 | 90 |
| `EnableEBSEncryption` | Encrypt all EBS volumes | no |
| `KrispApiKey` | Optional Krisp API key for noise isolation and turn-taking (contact support@jambonz.org for info) | (none) |
| `EnableOpenTelemetry` | Enable OpenTelemetry tracing (Cassandra, Jaeger). Increases resource usage | false |
| `DbCachingTTS` | Seconds to cache DB query results (0=no caching) | 0 |
| `StatsSampleRate` | Sampling rate for metrics (0-1) | 1 |
| `WebMonitoringDiskSize` | Disk size in GB for Monitoring server | 200 |

> **Instance type / architecture:** the `Architecture` parameter (dropdown, default `amd64`)
> selects both the AMIs and the instance-type defaults for every role. Its allowed values are
> the architectures whose AMIs `generate-cf.sh` copied — pick "both" there to make it
> selectable at deploy time. The `InstanceType*` defaults shown above (`c5n.xlarge`) are the
> amd64 defaults; leave them blank to use the architecture- and region-optimized default.
> arm64 (Graviton) uses `c7g.xlarge` (or `t4g`/`c6g` where `c7g` is unavailable), with
> recording servers on the burstable `t4g` tier. If you set an instance type explicitly, match
> it to the selected architecture. arm64 availability is region-dependent — see the top-level
> README.

## Web server deployment

`WebServerDeployment` chooses how the web tier (portal, API, public apps) is deployed:

- **`single-instance`** (default) - one EC2 instance with an Elastic IP. nginx on the
  instance serves HTTP; add TLS after deploy with certbot (see
  [Enable HTTPS](#enable-https-for-the-portal)).
- **`autoscaling-alb`** - an Auto Scaling group of web servers (min 1, max 4, starting at 1,
  scaling on 60% average CPU) behind an internet-facing Application Load Balancer. The ALB
  terminates TLS with an ACM certificate and redirects HTTP to HTTPS, so there is no certbot
  step and the portal is configured for `https://` from the start. Instances are replaced one
  at a time on stack updates.

For `autoscaling-alb`, the load balancer needs a certificate. There are two ways to provide one:

- **Let the stack do it (recommended): set `HostedZoneId`** to the Route 53 public hosted zone
  that contains `URLPortal`. The stack requests an ACM certificate for `URLPortal` and its
  `api.`, `grafana.` and `public-apps.` subdomains, validates it through DNS in that zone, and
  creates those four records pointing at the load balancer. ACM renews the certificate
  automatically. Stack creation waits for the certificate to be issued, usually a few minutes.
  ACM's validation records (CNAMEs beginning with `_`) may stay in the zone after the stack is
  deleted.
- **Bring your own: set `WebCertificateArn`** to a certificate you requested or imported in ACM
  **in the same region**. It must cover `URLPortal` and its `api.`, `grafana.` and
  `public-apps.` subdomains, e.g. `my-domain.example.com` plus `*.my-domain.example.com`. Then
  point those names at the `WebLoadBalancerDnsName` output yourself.

If you set both, the stack uses your certificate and still creates the DNS records.
`HostedZoneId` is rejected with `single-instance`.

The initial admin password is generated into Secrets Manager
(`<stack-name>-web-admin-initial-password`) instead of being the instance ID.

## Secrets

The stack generates every secret it needs: the database master password, the JWT and
encryption secrets, and the credential the feature servers present to the recording servers.
It keeps them in Secrets Manager and copies them into SSM Parameter Store as SecureString
parameters:

| Path | Read by |
|---|---|
| `/jambonz/<stack-name>/common` | every server |
| `/jambonz/<stack-name>/fs` | feature servers |
| `/jambonz/<stack-name>/recording` | recording servers |

No secret is written to an instance's disk or to its user data. The jambonz apps, drachtio and
the recording uploader fetch their values from Parameter Store each time they start. Each tier's instance role can read only the paths for its tier.
The parameters are deleted with the stack.

To change a value, update the parameter, then restart the processes that read it. **Never
change `ENCRYPTION_SECRET` once the system holds data.** It encrypts the vendor credentials
stored in the database, and changing it makes them unreadable.

## Generate and Deploy

First, generate the CloudFormation template:

```bash
cd ..  # Go to project root
./generate-cf.sh
# Follow prompts to select 'large', the CPU architecture (amd64/arm64/both), and your region
# Wait for AMI copy to complete
```

The generated template exceeds the 51,200 byte limit for inline `--template-body`, so you must upload it to S3 first:

```bash
# Upload template to S3 (create bucket if needed)
aws s3 mb s3://my-cf-templates-bucket --region us-west-2
aws s3 cp jambonz-large-us-west-2-amd64.yaml s3://my-cf-templates-bucket/jambonz-large.yaml

# Deploy using --template-url
aws cloudformation create-stack \
  --stack-name jambonz-large \
  --template-url https://my-cf-templates-bucket.s3.us-west-2.amazonaws.com/jambonz-large.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=AllowedSshCidr,ParameterValue=203.0.113.10/32 \
    ParameterKey=URLPortal,ParameterValue=my-domain.example.com
```

## Monitor Stack Creation

Wait for the stack to complete (this may take 15-20 minutes due to Aurora and ElastiCache):

```bash
aws cloudformation wait stack-create-complete --stack-name jambonz-large --region us-west-2
```

Or check status manually:

```bash
aws cloudformation describe-stacks --stack-name jambonz-large --region us-west-2
```

## Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name jambonz-large \
  --region us-west-2 \
  --query 'Stacks[0].Outputs'
```

Outputs include:
- **WebPortalURL** - URL to access the jambonz web portal
- **WebServerIP** - Public IP address of the Web server (for DNS records; `single-instance` only)
- **WebLoadBalancerDnsName** - DNS name of the web ALB (for DNS records; `autoscaling-alb` only)
- **SipServerIP** - Public IP address of the SBC SIP server (for SIP traffic)
- **RtpServerIP** - Public IP address of the SBC RTP server (for RTP traffic)
- **WebPortalUsername** - Admin username (always `admin`)
- **WebPortalPassword** - Initial admin password (the Web server EC2 instance ID, or for `autoscaling-alb` the name of the Secrets Manager secret holding it)
- **GrafanaUsername** - Grafana username (always `admin`)
- **GrafanaPassword** - Initial Grafana password (always `admin`)

## Post-install steps

### Create DNS records

After the stack is created, create the following DNS A records:

**Pointing to WebServerIP:**
- `my-domain.example.com`
- `api.my-domain.example.com`
- `grafana.my-domain.example.com`
- `homer.my-domain.example.com`
- `public-apps.my-domain.example.com`

With `autoscaling-alb`, point the same names at **WebLoadBalancerDnsName** instead: a
Route 53 alias record for the domain itself (or a CNAME if it is a subdomain of a zone you
manage elsewhere), and CNAME records for the subdomains.

**Pointing to SipServerIP:**
- `sip.my-domain.example.com`

### Enable HTTPS for the portal

`single-instance` only - with `autoscaling-alb` the load balancer already serves HTTPS.
SSH into the Web server and install TLS certificates:

1. `ssh -i <yuour-ssh-keypair> jambonz@<WebServerIP>` - ssh into the server
2. `sudo certbot --nginx` - generate TLS certs
3. `cd ~/apps/webapp && vi .env` - edit the VITE_API_BASE_URL param to use https
4. `npm run build && pm2 restart webapp` - restart the webapp under https

### Enable SIP over TLS and WSS

SIP over TLS (port 5061) and SIP over secure WebSocket (WSS, port 8443) need a certificate for the
name your carriers and SIP clients connect to, for example `sip.<URLPortal>`. Get it from any
source (certbot, your CA), then store it in SSM Parameter Store, in the stack's region, as three
SecureString parameters:

```bash
aws ssm put-parameter --region us-west-2 --type SecureString \
  --name /jambonz/jambonz-large/sbc/TLS_PRIVKEY --value file://privkey.pem
aws ssm put-parameter --region us-west-2 --type SecureString \
  --name /jambonz/jambonz-large/sbc/TLS_CERT --value file://cert.pem
aws ssm put-parameter --region us-west-2 --type SecureString \
  --name /jambonz/jambonz-large/sbc/TLS_CHAIN --value file://chain.pem
```

The path is `/jambonz/<stack-name>/sbc`; you can create the parameters before the stack. At boot,
each SIP server installs the certificate and turns on TLS and WSS. Without the parameters, SIP runs over UDP
and TCP only. If they are incomplete, the key does not match the certificate, or the certificate
has expired, each SIP server logs the reason in `/var/log/cloud-init-output.log` and starts without TLS.
A value over 4 KB needs `--tier Advanced`.

To add or renew the certificate on a running stack, update the parameters (add `--overwrite`),
then either:

- **Replace the SIP server instances one at a time.** The Auto Scaling group lets the instance's
  calls in progress finish before terminating it, and its replacement installs the new certificate.
  While an instance drains it turns away new calls, so with a single SIP server, new calls fail until
  the replacement takes over its Elastic IP:

  ```bash
  aws autoscaling terminate-instance-in-auto-scaling-group --region us-west-2 \
    --instance-id <instance-id> --no-should-decrement-desired-capacity
  ```

- **Or apply it in place** on each SIP server. This drops the calls in progress on that server:

  ```bash
  sudo /usr/local/bin/jambonz-sip-tls.sh /jambonz/jambonz-large/sbc us-west-2 && sudo systemctl restart drachtio
  ```

The parameters are yours: deleting the stack does not delete them.

## First time login

Now log into the portal for the first time.

The user is 'admin' and the password will have been listed as part of the outputs above (it is set initially to the Web server instance ID). You will be prompted to change the password on first login.

## Acquiring a license

When you log in for the first time, you will notice a banner at the top of the portal indicating that the system is unlicensed. Click on the link in the message to go to the Admin settings panel where you can paste in a license key.

To acquire a license key go to [licensing.jambonz.org](https://licensing.jambonz.org), create an account and purchase a license or request a trial license.

## Delete the Stack

```bash
aws cloudformation delete-stack --stack-name jambonz-large --region us-west-2
```

Note that the RDS cluster has delete protection enabled, so you will need to disable that or else you will need to delete the cluster manually.

**Note:**
- The Elastic IPs have a `Retain` deletion policy and will not be deleted with the stack. You can manually release them after the stack is deleted.
- The Aurora database has deletion protection enabled. You must disable it before deleting the stack.
- CloudFormation takes a final snapshot of the Aurora cluster when the stack is deleted, and keeps
  the `<stack-name>-encryption-secret` Secrets Manager secret with it. A restored snapshot needs
  that secret to read the stored vendor credentials. Delete both once you no longer need the data.
  The secret also blocks creating a new stack with the same name until it is deleted.
- The database audit log group (`/aws/rds/cluster/<stack-name>-aurora-mysql-cluster/audit`, connections
  only) is also kept, and expires on the `CloudwatchLogRetention` schedule.

## SSH Access

Connect to any instance as the `jambonz` user:

```bash
# Web server
ssh -i /path/to/keypair.pem jambonz@<WebServerIP>

# SBC SIP server
ssh -i /path/to/keypair.pem jambonz@<SipServerIP>

# SBC RTP server
ssh -i /path/to/keypair.pem jambonz@<RtpServerIP>
```

## Ports

### SBC SIP Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 5060 | UDP/TCP | SIP |
| 5061 | TCP | SIP TLS |
| 8443 | TCP | SIP WSS |
| 2775 | TCP | SMPP |
| 3550 | TCP | SMPP TLS |

### SBC RTP Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 40000-60000 | UDP | RTP |

### Web Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 80 | TCP | HTTP (nginx) |
| 443 | TCP | HTTPS (nginx) |
| 3000 | TCP | API Server |

### Monitoring Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 3010 | TCP | Grafana |
| 9080 | TCP | Homer |
| 8086 | TCP | InfluxDB |
| 16686 | TCP | Jaeger |

## Scaling

**Each SIP and RTP server needs its own Elastic IP.** Carriers and customers allow-list these
addresses, so a server never serves from a temporary public IP. The stack creates one EIP per
tier. Before scaling a tier above one server, allocate another EIP with that tier's
`Environment` tag:

```bash
aws ec2 allocate-address --domain vpc --region us-west-2 \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Environment,Value=jambonz-large-sbc-sip}]'
```

Use `<stack-name>-sbc-sip` for a SIP server and `<stack-name>-sbc-rtp` for an RTP server, and
publish the new address to your carriers and customers. A new SIP server that finds no free EIP
waits, out of service, until one is free. A new RTP server in that state marks itself unhealthy
and is replaced, again and again, until one is free.

The SBC SIP, SBC RTP, and Feature Server Auto Scaling Groups can be scaled manually or configured with scaling policies:

```bash
# Scale SBC SIP servers
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name jambonz-large-sbc-sip-autoscaling-group \
  --desired-capacity 2 \
  --region us-west-2

# Scale SBC RTP servers
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name jambonz-large-sbc-rtp-autoscaling-group \
  --desired-capacity 2 \
  --region us-west-2

# Scale Feature servers
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name jambonz-large-feature-server-autoscaling-group \
  --desired-capacity 2 \
  --region us-west-2
```

## Redis failover

Redis runs as a primary and a replica in two availability zones. When ElastiCache fails over,
because the primary or its zone failed or during AWS maintenance, it promotes the replica and
moves the primary endpoint to it. The jambonz servers reconnect to the new primary on their own,
including when the old primary stays up as a replica.
