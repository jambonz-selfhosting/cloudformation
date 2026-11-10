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
| `VpcCidr` | CIDR range of the VPC. When using an existing VPC, set this to that VPC's CIDR | 172.20.0.0/16 |
| `ExistingVpcId` | Optional. Blank creates a new VPC; set to a `vpc-...` id to deploy into a VPC you already have | (blank) |
| `ExistingSubnetIds` | Optional. Required when `ExistingVpcId` is set: exactly two public subnet ids in different AZs, comma separated with no spaces | (blank) |
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

The initial admin password is the same in both modes: the stack's unique ID, shown in the
`WebPortalPassword` output.

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

## Deploying into an existing VPC

By default the stack creates its own VPC, two public subnets, internet gateway and route
tables, and nothing else is required. To deploy into a VPC you already have, set these
parameters:

| Parameter | Example |
|-----------|---------|
| `ExistingVpcId` | `vpc-0abc123def456789` |
| `ExistingSubnetIds` | `subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb` — exactly two, comma separated, **no spaces** |
| `VpcCidr` | `172.20.0.0/16` — the CIDR of that VPC, **not** a new range |

Leave `ExistingVpcId` blank and the stack behaves exactly as it always has. When it is set,
`PublicSubnet1CIDR` and `PublicSubnet2CIDR` are ignored.

The *shape* of both new parameters is validated before any resource is created, so the wrong
number of subnets, a stray space, a malformed id, or setting one parameter without the other
is rejected in seconds instead of failing 20 minutes into a create and rolling back.

What is **not** checked, and you must verify yourself: that the subnets actually exist, that
they are two *different* subnets in two *different* AZs, that they belong to
`ExistingVpcId`, and that `VpcCidr` matches the real VPC. The `VpcCidr` pattern only checks
the shape - it accepts `999.999.999.999/99`.

> **Passing two subnets on the CLI.** The `--parameters ParameterKey=...,ParameterValue=...`
> shorthand splits on *every* comma, so the AWS CLI reads the second subnet as a new key and
> the command fails to parse before it ever reaches CloudFormation. The comma needs escaping
> **and** the argument needs shell quoting, or the shell eats the backslash and you get the
> same failure:
>
> ```bash
> # correct - single quotes keep the backslash intact
> --parameters 'ParameterKey=ExistingSubnetIds,ParameterValue=subnet-0aaa\,subnet-0bbb'
> ```
>
> A JSON parameter file avoids the problem entirely and is what the Terraform harness in
> `cloudformation_terraform` emits: `--parameters file://params.json`.

### `ExistingVpcId` cannot be changed after the stack is created

Treat it as a create-time-only decision. Switching a live stack from its own VPC to an
existing one (or back) cannot succeed: the security groups, DB subnet group and cache
subnet group all carry fixed physical names, so the required replacement collides with
itself, and the old VPC cannot be deleted while its ENIs remain. The stack ends in
`UPDATE_ROLLBACK_FAILED`.

The dangerous direction is accidental. **CloudFormation substitutes the template default
for any parameter you omit on an update — it does not keep the previous value.** So an
update that forgets `ExistingVpcId` silently flips back to "create a new VPC". Always pass
it explicitly, or use `--parameters ParameterKey=ExistingVpcId,UsePreviousValue=true`, on
every update. `aws cloudformation deploy` and console updates that start from the existing
parameter set are not affected.

### Requirements for the VPC and subnets you supply

- **Two subnets, in two different availability zones.** The Aurora database, the ElastiCache
  cluster and the recording load balancer all require two AZs. The parameter pattern
  enforces that you pass exactly two ids, but it cannot tell whether they are in different
  AZs or whether you pasted the same id twice — either produces
  `DBSubnetGroupDoesNotCoverEnoughAZs` or "At least two subnets in two different
  Availability Zones must be specified" part-way into the create.
- **Both subnets must be public** — each needs a default route (`0.0.0.0/0`) to an internet
  gateway. jambonz needs public IPs for SIP, RTP and the portal, and instances download
  packages from the internet on first boot. Private subnets behind a NAT gateway will not
  work.
- **Auto-assign public IPv4 must be enabled on both subnets, and this failure is silent.**
  The SBC and feature server instances request a public IP explicitly, but the web server, the monitoring server and the recording servers
  inherit it from the subnet setting — and AWS defaults auto-assign to **off** for subnets
  you create yourself. Without it those instances come up with no public
  address, their first-boot UserData cannot reach Parameter Store and never completes, and
  the recording instances never pass their load balancer health check. Nothing in these
  templates signals boot success, so **CloudFormation still reports `CREATE_COMPLETE`** —
  you get a green stack and a broken cluster. Verify the setting before deploying: in the
  console, *Subnet → Actions → Edit subnet settings → Enable auto-assign public IPv4
  address*.
- **The subnets need room to scale.** An internet-facing Application Load Balancer requires
  each of its subnets to be at least a `/27` and to have 8 free addresses, and the
  auto-scaling groups here can reach 24 instances between them, plus the standalone
  instances and the RDS/ElastiCache ENIs. Subnets smaller than `/27` fail load balancer
  creation outright; `/24`s that already hold your own workloads instead stall scale-out with
  `InsufficientFreeAddressesInSubnet` during a call surge, which raises no stack event. The
  created-VPC path never hit this because it always carves fresh `/24`s.
- **Check the subnets' Network ACLs.** A fresh VPC gets an allow-all NACL, so this never
  mattered before. A locked-down enterprise subnet that only permits 80/443 will
  statelessly drop SIP (5060/5061/8443) and RTP (UDP 40000-60000) while every security group
  still looks correct — calls connect with no audio and there is nothing in the stack events
  to point at.
- **`VpcCidr` must match the existing VPC's CIDR.** CloudFormation cannot look up the CIDR
  of an existing VPC, so you have to tell it, and nothing verifies your answer. It does two
  jobs: it drives the security group rules that let jambonz components reach each other, and
  it is passed to the feature servers as `JAMBONES_NETWORK_CIDR`, which is how jambonz tells
  internal traffic from external. Get it wrong — for instance by leaving the default while
  your VPC is `10.42.0.0/16` — and the database, cache and inter-component ports are closed
  to the very instances that need them while SIP is misclassified. Nothing fails at deploy
  time; the stack reaches `CREATE_COMPLETE` and calls die with no obvious cause.
- **DNS resolution and DNS hostnames should be enabled** on the VPC. The stack enables both
  on the VPC it creates, and the database and cache endpoints are resolved by name. Note
  that `enableDnsHostnames` is **off** by default for a VPC you created yourself, so check
  rather than assume.
- The subnets must be in the region the template was generated for.

### Security: what `VpcCidr` opens up in a shared VPC

Read this before deploying into a VPC that hosts anything else. jambonz components reach
each other through security group rules written against `VpcCidr`, not against each other's
security groups. When the stack created its own VPC that CIDR meant "jambonz only". In an
existing VPC the same rules mean **every workload in that VPC** — 21 rules in total:

| Port(s) | Service | Note |
|---------|---------|------|
| 3306 | Aurora MySQL | CDRs, account API keys, SIP credentials. `PubliclyAccessible: false` is the only other control. |
| 6379 | ElastiCache Redis | live call state. No equivalent fallback. |
| 8086, 8088 | InfluxDB + backup port | **typically unauthenticated** — call metrics |
| 9080, 9060/udp | Homer webapp + HEP | full SIP capture, i.e. call metadata |
| 16686, 14268-14269 | Jaeger query + collector | traces |
| 3000-3009 | internal HTTP between api/sbc/feature servers | |
| 5060/udp, 5060/tcp | SIP between components | |
| 8080, 9090, 22222-22223/udp, 22224-22233/udp | rtpengine ng/ws, Prometheus scrape, DTMF events | |
| 16000-32000/udp, 40000-60000/udp | RTP media | |

Any EC2 instance, VPC-attached Lambda or container anywhere in that VPC can reach all of it.
InfluxDB and Homer are the ones worth pausing on: they are usually unauthenticated and they
hold call metadata.

If that is not acceptable, deploy into a VPC dedicated to jambonz (or its own account), or
convert these rules to `SourceSecurityGroupId` — the templates already use that form in a
few places, and doing so would remove the dependence on `VpcCidr` entirely.

### What the stack does and does not touch

It still creates its own security groups, Elastic IPs, database subnet group, cache subnet
group and load balancer, inside your VPC. It does not add, remove or modify any subnet,
route table, route or gateway in your VPC.

One exception on teardown: every Elastic IP carries `DeletionPolicy: Retain`, so
`delete-stack` reaches `DELETE_COMPLETE` and leaves 3 Elastic IPs allocated and billed. Release them
by hand after deleting the stack, or they sit in your account unattached.

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
- **WebPortalPassword** - Initial admin password (the stack's unique ID, the last part of its stack ID)
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

#### Or let each SBC get a Let's Encrypt certificate (`EnableTLS`)

If the SIP domain's DNS zone is in Route 53 in this account, set `EnableTLS=true` with `SipDomain`,
`CertEmail` and `SipHostedZoneId`. At boot each SBC runs `drachtio_tls.sh` from the AMI: certbot
gets a certificate for `SipDomain` and `*.SipDomain` through a Route 53 DNS-01 challenge, then
renews it automatically. The certificate is cached under `TlsCertParamPrefix/<SipDomain>/` in
Parameter Store, so replacement SBCs reuse it instead of using up Let's Encrypt's limit of 5
duplicate certificates per week. When `EnableTLS` is true, the `/jambonz/<stack-name>/sbc`
parameters above are ignored. `SipDomain` is also written to the database as the SIP domain.

#### Mutual TLS on outbound calls (`EnableMtls`)

Some carriers require the SBC to present a client certificate. Store a private CA in Parameter
Store (the certificate as a String, the key as a SecureString) and set `EnableMtls=true` with
`MtlsCaCertParam` and `MtlsCaKeyParam`. `EnableTLS` must also be true. At boot, each SBC runs
`drachtio_mtls.sh`: it signs a one-year client certificate with its own key, adds it to drachtio,
and renews it weekly. Give the carrier the CA certificate, never the key. Every SBC can read the
CA key, and anyone who has it can issue certificates the carrier will accept.

#### Turning `EnableTLS` or `EnableMtls` on or off for a running stack

Both scripts run only when an instance first boots, so a stack update changes nothing on the SBCs
that are already running. Replace them after the update: on medium and large, terminate each
SBC in its Auto Scaling group, one at a time. On mini, run the two commands from the user data by
hand, because replacing the instance would delete its database. When turning a feature off on mini,
also stop its renewal timer: `sudo systemctl disable --now drachtio-tls-renew.timer` (or
`drachtio-mtls-renew.timer`). A replaced SBC never has them.

## First time login

Now log into the portal for the first time.

The user is 'admin' and the password will have been listed as part of the outputs above (it is set initially to the stack's unique ID, the last part of its stack ID). You will be prompted to change the password on first login.

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
