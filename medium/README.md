# jambonz Medium CloudFormation Deployment

This directory contains the base CloudFormation template for "jambonz medium" - a scalable multi-tier architecture with separate SBC, Feature Server, and Web/Monitoring components, backed by Aurora Serverless MySQL and ElastiCache Redis. Suitable for production workloads requiring high availability and scalability up to 1,500 concurrent calls.

**Important:** Do not deploy `_jambonz-base-template.yaml` directly. Instead, run `../generate-cf.sh` from the project root to generate a deployable template.

## Architecture

The medium deployment creates:

- **SBC Auto Scaling Group** - Handles SIP/RTP traffic with drachtio and rtpengine
- **Feature Server Auto Scaling Group** - Runs jambonz application logic with FreeSWITCH
- **Web/Monitoring Server** - Hosts the portal, API, Grafana, Homer, and Jaeger
- **Aurora Serverless v2** - MySQL database cluster
- **ElastiCache** - Redis cluster for caching and pub/sub
- **Optional Recording Cluster** - Auto-scaling recording servers behind an ALB

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
| `EnablePcaps` | Enable PCAPs for SIP traffic | (required) |
| `EnableTLS` | Enable SIP over TLS (5061) and WSS (8443) on the SBC | false |
| `SipDomain` | Required with `EnableTLS`: SIP domain for the certificate, e.g. `sip.example.com` | (blank) |
| `CertEmail` | Required with `EnableTLS`: email Let's Encrypt registers the cert against | (blank) |
| `HostedZoneId` | Required with `EnableTLS`: Route 53 hosted zone id for `SipDomain` | (blank) |
| `EnableMtls` | Present a client certificate on outbound SIP over TLS | false |
| `MtlsCaCertParam` | Required with `EnableMtls`: SSM parameter holding the private CA certificate | (blank) |
| `MtlsCaKeyParam` | Required with `EnableMtls`: SSM parameter holding the private CA key (SecureString) | (blank) |
| `MtlsCommonName` | CN placed in the client certificate. Blank uses `SipDomain` | (blank) |
| `MtlsCaFile` | Authorities allowed to sign the *carrier's* server certificate | system bundle |
| `MtlsVerifyServerName` | Require the carrier's certificate to match the hostname dialled | false |
| `InstanceTypeSbc` | EC2 instance type for SBC servers | c5n.xlarge |
| `InstanceTypeFeatureServer` | EC2 instance type for Feature servers | c5n.xlarge |
| `InstanceTypeWebMonitoring` | EC2 instance type for Web/Monitoring server | c5n.xlarge |
| `ElastiCacheNodeType` | ElastiCache node type | cache.t3.medium |
| `AuroraDBMinCapacity` | Aurora Serverless min ACU | 0.5 |
| `AuroraDBMaxCapacity` | Aurora Serverless max ACU | 4 |
| `AllowedSshCidr` | CIDR for SSH access | 0.0.0.0/0 |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | 0.0.0.0/0 |
| `AllowedSbcCidr` | CIDR for SIP/RTP access | 0.0.0.0/0 |
| `AllowedSmppCidr` | CIDR for SMPP access | 0.0.0.0/0 |
| `VpcCidr` | CIDR range of the VPC. When using an existing VPC, set this to that VPC's CIDR | 172.20.0.0/16 |
| `ExistingVpcId` | Optional. Blank creates a new VPC; set to a `vpc-...` id to deploy into a VPC you already have | (blank) |
| `ExistingSubnetIds` | Optional. Required when `ExistingVpcId` is set: exactly two public subnet ids in different AZs, comma separated with no spaces | (blank) |
| `MySQLUsername` | Database username | admin |
| `MySQLPassword` | Database password | JambonzR0ck$ |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `DeployRecordingCluster` | Deploy optional recording cluster | yes |
| `KrispApiKey` | Optional Krisp API key for noise isolation and turn-taking (contact support@jambonz.org for info) | (none) |
| `EnableEBSEncryption` | Encrypt all EBS volumes | no |
| `EnableOpenTelemetry` | Enable OpenTelemetry tracing (Cassandra, Jaeger). Increases resource usage | false |
| `DbCachingTTS` | Seconds to cache DB query results (0=no caching) | 0 |
| `RecordingInstanceType` | EC2 instance type for Recording servers | (region default) |
| `WebMonitoringDiskSize` | Disk size in GB for Web/Monitoring server | 200 |

> **Instance type / architecture:** the `Architecture` parameter (dropdown, default `amd64`)
> selects both the AMIs and the instance-type defaults for every role. Its allowed values are
> the architectures whose AMIs `generate-cf.sh` copied — pick "both" there to make it
> selectable at deploy time. The `InstanceType*` defaults shown above (`c5n.xlarge`) are the
> amd64 defaults; leave them blank to use the architecture- and region-optimized default.
> arm64 (Graviton) uses `c7g.xlarge` (or `t4g`/`c6g` where `c7g` is unavailable), with
> recording servers on the burstable `t4g` tier. If you set an instance type explicitly, match
> it to the selected architecture. arm64 availability is region-dependent — see the top-level
> README.

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
`PublicSubnetCIDR` and `PublicSubnetCIDR2` are ignored.

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
  The SBC and feature server instances request a public IP explicitly, but the web/monitoring server and the recording servers
  inherit it from the subnet setting — and AWS defaults auto-assign to **off** for subnets
  you create yourself. Without it those instances come up with no public
  address, their first-boot UserData cannot reach Secrets Manager and never completes, and
  the recording instances never pass their load balancer health check. Nothing in these
  templates signals boot success, so **CloudFormation still reports `CREATE_COMPLETE`** —
  you get a green stack and a broken cluster. Verify the setting before deploying: in the
  console, *Subnet → Actions → Edit subnet settings → Enable auto-assign public IPv4
  address*.
- **The subnets need room to scale.** An internet-facing Application Load Balancer requires
  each of its subnets to be at least a `/27` and to have 8 free addresses, and the
  auto-scaling groups here can reach 16 instances between them, plus the standalone
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
existing VPC the same rules mean **every workload in that VPC** — 20 rules in total:

| Port(s) | Service | Note |
|---------|---------|------|
| 3306 | Aurora MySQL | CDRs, account API keys, SIP credentials. `PubliclyAccessible: false` is the only other control. |
| 6379 | ElastiCache Redis | live call state. No equivalent fallback. |
| 8086, 8088 | InfluxDB + backup port | **typically unauthenticated** — call metrics |
| 9080, 9060/udp | Homer webapp + HEP | full SIP capture, i.e. call metadata |
| 4000 | Grafana | dashboards |
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
`delete-stack` reaches `DELETE_COMPLETE` and leaves 2 Elastic IPs allocated and billed. Release them
by hand after deleting the stack, or they sit in your account unattached.

## Generate and Deploy

First, generate the CloudFormation template:

```bash
cd ..  # Go to project root
./generate-cf.sh
# Follow prompts to select 'medium', the CPU architecture (amd64/arm64/both), and your region
# Wait for AMI copy to complete
```

The generated template exceeds the 51,200 byte limit for inline `--template-body`, so you must upload it to S3 first:

```bash
# Upload template to S3 (create bucket if needed)
aws s3 mb s3://my-cf-templates-bucket --region us-west-2
aws s3 cp jambonz-medium-us-west-2-amd64.yaml s3://my-cf-templates-bucket/jambonz-medium.yaml

# Deploy using --template-url
aws cloudformation create-stack \
  --stack-name jambonz-medium \
  --template-url https://my-cf-templates-bucket.s3.us-west-2.amazonaws.com/jambonz-medium.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=URLPortal,ParameterValue=my-domain.example.com
```

## Monitor Stack Creation

Wait for the stack to complete (this may take 15-20 minutes due to Aurora and ElastiCache):

```bash
aws cloudformation wait stack-create-complete --stack-name jambonz-medium --region us-west-2
```

Or check status manually:

```bash
aws cloudformation describe-stacks --stack-name jambonz-medium --region us-west-2
```

## Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name jambonz-medium \
  --region us-west-2 \
  --query 'Stacks[0].Outputs'
```

Outputs include:
- **PortalURL** - URL to access the jambonz web portal
- **WebServerIP** - Public IP address of the Web/Monitoring server (for DNS records)
- **SbcServerIP** - Public IP address of the SBC server (for SIP traffic)
- **PortalUsername** - Admin username (always `admin`)
- **PortalPassword** - Initial admin password (the Web/Monitoring EC2 instance ID)
- **GrafanaURL** - URL to access Grafana
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

**Pointing to SbcServerIP:**
- `sip.my-domain.example.com`

### Enable SIP over TLS and WSS

Set four parameters and the SBC configures itself at boot — no SSH, no manual certbot run:

| Parameter | Example |
|-----------|---------|
| `EnableTLS` | `true` |
| `SipDomain` | `sip.example.com` |
| `CertEmail` | `admin@example.com` |
| `HostedZoneId` | `Z1234567890ABC` |

This brings up SIP over TLS on `5061` and SIP over secure WebSockets on `8443` — the latter
is what browser clients (jsSIP, SIP.js) need, since browsers refuse plain `ws`. The security
group already allows both from `AllowedSbcCidr`.

Leave `EnableTLS` at `false` and nothing changes; the other three are ignored.

#### What happens on the SBC

The launch template writes `/usr/local/bin/drachtio_tls.sh` on every boot and runs it. The
script:

1. requests a certificate for `SipDomain` **and** `*.SipDomain` via certbot's Route 53
   DNS-01 plugin;
2. inserts the `<tls>` block into `/etc/drachtio.conf.xml`;
3. appends the `sips:` contacts to `/etc/systemd/system/drachtio.service`;
4. drops a renewal hook at `/etc/letsencrypt/renewal-hooks/deploy/restart-drachtio.sh` and
   enables `certbot.timer`;
5. reloads systemd and restarts drachtio.

Every step is guarded, so re-running it is a no-op. It is written out on each boot on
purpose: a replacement instance in the autoscaling group starts with an empty
`/etc/letsencrypt` and an unmodified `drachtio.conf.xml`, so it has to redo the work.

The wildcard means you can give different jambonz accounts different SIP realms
(`alice.sip.example.com`, `bob.sip.example.com`) under one certificate. Pass the bare
domain — the `*.` is added for you.

Because the whole thing lives in the launch template rather than the AMI, changing it is a
stack update, not an image rebuild.

#### Where the boot scripts live

EC2 caps user data at 16 KB and this deployment already spends most of it, so the two boot
scripts travel in Parameter Store as `/<stack-name>/drachtio/tls-script` and
`/<stack-name>/drachtio/mtls-script`; user data only carries the fetch.

They are kept as ordinary shell files — [`boot-scripts/drachtio_tls.sh`](../boot-scripts/drachtio_tls.sh)
and [`boot-scripts/drachtio_mtls.sh`](../boot-scripts/drachtio_mtls.sh) — so they can be linted,
diffed and syntax-checked like any other script, and `generate-cf.sh` folds them into the
parameters when it builds the template. The generated template is therefore self-contained:
an instance runs exactly what that stack version declared, with nothing fetched from outside
AWS at boot and no chance of drifting when a newer script lands in the repository.

The generator refuses to build if either script fails `bash -n` or exceeds the 8 KB
parameter limit, and it checks every user data block against the 16 KB EC2 limit before
writing the template. Each parameter is created only while its feature is switched on, and
uses the advanced tier for its 8 KB value limit at about $0.05 per parameter per month.

#### Renewal

Certificates last 90 days. The certbot package installs a systemd timer that renews them on
its own; the missing piece is that drachtio keeps serving the old certificate until it
restarts, so the script installs a deploy hook that restarts drachtio after each renewal.
No cron entry is needed — the packaged timer already covers it.

#### Requirements

- **The DNS zone must be in Route 53, in this account.** DNS-01 is the only challenge that
  can issue a wildcard, and the SBC has no port 80 open, so HTTP-01 was never an option. The
  template grants `route53:ChangeResourceRecordSets` scoped to `HostedZoneId` alone, plus
  `ListHostedZones` and `GetChange`, which accept no resource scope. That policy is created
  only when `EnableTLS` is true. Note that this deployment shares a single IAM role across
  the SBC, feature, web/monitoring and recording instances, so the grant reaches all of
  them — feature servers run customer-supplied webhooks. If that matters to you, use a
  hosted zone dedicated to SIP rather than one carrying production records.
- **`sip.<your-domain>` must resolve to the SBC's Elastic IP** so clients can validate the
  certificate. See the DNS records section above.
- **certbot with the route53 plugin must be in the AMI.** Images built from the packer repo
  with `install_certbot=yes` have it. If certbot is missing the boot script fails, logs the
  error, and the SBC comes up **without TLS** — and since nothing here signals boot status,
  the stack still reports `CREATE_COMPLETE`. Check `/var/log/cloud-init-output.log` on the
  SBC after the first deploy.

#### Rate limit — read this before scaling the SBC

**A certificate is requested on every SBC boot**, since an autoscaled instance starts with an
empty `/etc/letsencrypt`. Every one of those requests asks for the identical hostname set
(`SipDomain` plus its wildcard), so the limit that binds is Let's Encrypt's **duplicate
certificate** limit — **5 per week for the same set of hostnames** — not the more generous
50-per-registered-domain figure.

Five SBC boots in a rolling week is not a lot: scaling the group toward `MaxSize`, one
health-check replacement, or a few stack recreations during testing will reach it. When it
trips, certbot returns "too many certificates already issued", the boot script logs the
failure and continues, **and the SBC serves plain SIP behind a stack that reports
`CREATE_COMPLETE`**.

If you expect anything more than occasional replacement, issue the certificate once and
distribute it from Secrets Manager rather than calling ACME per instance.

### Enable mutual TLS on outbound calls

Some carriers refuse SIP over TLS unless the caller also proves who it is. Ordinary TLS
proves the carrier's identity to you; mTLS proves yours to them. There is nothing to enable
per carrier — the requirement is signalled during the handshake, and carriers that don't ask
are sent nothing.

| Parameter | Example |
|-----------|---------|
| `EnableMtls` | `true` |
| `MtlsCaCertParam` | `/proagent/sip-mtls/client-ca-pem` |
| `MtlsCaKeyParam` | `/proagent/sip-mtls/client-ca-key` |
| `MtlsCommonName` | blank, or the name the carrier asked for |

`EnableTLS` must already be true. mTLS attaches the identity to the `sips:` contact that the
inbound TLS step creates; without it drachtio ignores the configuration silently.

#### This is a second, unrelated certificate

The Let's Encrypt certificate cannot be reused, for two independent reasons. A carrier
requiring mTLS wants a certificate from an authority *it* trusts, not one anybody could
obtain. And a client certificate needs the `clientAuth` extended key usage, which the public
authorities have stopped issuing — Let's Encrypt issued its last on 2026-07-08. A certificate
carrying only `serverAuth` is rejected as `unsuitable certificate purpose`.

So this one comes from a private CA you run: a root valid for years that the carrier loads
into its trust store once, and short-lived leaf certificates signed by it. Rotating a leaf
needs nothing from the carrier, because their trust anchor has not changed.

#### What each instance does at boot

1. reads the CA certificate and key from Parameter Store into **tmpfs**;
2. generates its own key — a fresh one per instance — straight into
   `/etc/drachtio/tls/carrier-client.key`, mode 0600;
3. signs a CSR for `MtlsCommonName` with `clientAuth` declared explicitly, valid one year;
4. writes the chain (leaf, then CA) to `/etc/drachtio/tls/carrier-client.pem`;
5. refuses to go further unless `openssl verify -purpose sslclient` passes and the
   certificate really carries `clientAuth`;
6. inserts `<client>` into the existing `<tls>` block and restarts drachtio;
7. shreds the CA material on every exit path.

A weekly timer re-runs the same script. It exits immediately while the leaf has more than a
month left, so it reaches Parameter Store roughly once a year per instance.

#### The CA private key reaches every SBC — read this before enabling

`MtlsCaKeyParam` gives the SBC role read access to the key that signs certificates the
carrier accepts. If an SBC is compromised, the attacker can mint identities the carrier will
trust until the CA itself is withdrawn — which takes the carrier removing it from their trust
store, and that ends every trunk using it.

The template limits the exposure as far as it can: the key is fetched into `/dev/shm`, never
written to the root volume, shredded through a `trap` on every exit path including a kill,
and never echoed to a log. The IAM grant names the two parameters exactly, and the
`kms:Decrypt` it needs is conditioned on `kms:ViaService` being Parameter Store.

That is mitigation, not removal. **The alternative is to sign once outside AWS** and put only
the leaf key and certificate in Parameter Store, so no SBC ever sees the CA key. The cost is
one signing round a year and a single shared identity across the group. If the CA is in AWS
Private CA, a third option removes both problems — each instance calls `issue-certificate`
and no CA key exists to leak.

#### `MtlsVerifyServerName` affects every trunk

`verify-server-cert`, `verify-server-name` and `sni` apply to **all** outbound TLS from this
server, not just the mTLS carrier. Leave `MtlsVerifyServerName` at `false` if any trunk is
configured by IP address — an IP can never match a hostname in a certificate. `sni` is on by
default and the template does not touch it.

#### Confirm it took

```
sudo grep -a "tls client\|tls verify policy" /var/log/drachtio/drachtio.log | tail -4
```

```
tls client key file:   /etc/drachtio/tls/carrier-client.key
tls client cert file:  /etc/drachtio/tls/carrier-client.pem
tls client ca file:    /etc/ssl/certs/ca-certificates.crt
tls verify policy: incoming cert no, outgoing cert yes, outgoing name no
```

If those lines are absent, drachtio did not read `<client>` — usually a path it cannot read,
or the element sitting outside `<tls>`. Nothing else reports it: a stack that fails here
still reaches `CREATE_COMPLETE`, and a missing identity surfaces as calls that fail to
connect rather than a SIP rejection you can inspect, because the handshake dies before any
SIP is exchanged.

### Enable HTTPS for the portal

SSH into the Web/Monitoring server and install TLS certificates:

1. `ssh -i <yuour-ssh-keypair> jambonz@<WebServerIP>` - ssh into the server
2. `sudo certbot --nginx` - generate TLS certs
3. `cd ~/apps/webapp && vi .env` - edit the VITE_API_BASE_URL param to use https
4. `npm run build && pm2 restart webapp` - restart the webapp under https

## First time login

Now log into the portal for the first time.

The user is 'admin' and the password will have been listed as part of the outputs above (it is set initially to the Web/Monitoring instance ID). You will be prompted to change the password on first login.

## Acquiring a license

When you log in for the first time, you will notice a banner at the top of the portal indicating that the system is unlicensed. Click on the link in the message to go to the Admin settings panel where you can paste in a license key.

To acquire a license key go to [licensing.jambonz.org](https://licensing.jambonz.org), create an account and purchase a license or request a trial license.

## Delete the Stack

```bash
aws cloudformation delete-stack --stack-name jambonz-medium --region us-west-2
```

Note that the RDS cluster has delete protection enabled, so you will need to disable that or else you will need to delete the cluster manually.

**Note:**
- The Elastic IPs have a `Retain` deletion policy and will not be deleted with the stack. You can manually release them after the stack is deleted.
- The Aurora database has deletion protection enabled. You must disable it before deleting the stack.

## SSH Access

Connect to any instance as the `jambonz` user:

```bash
# Web/Monitoring server
ssh -i /path/to/keypair.pem jambonz@<WebServerIP>

# SBC server
ssh -i /path/to/keypair.pem jambonz@<SbcServerIP>
```

## Ports

### SBC Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 5060 | UDP/TCP | SIP |
| 5061 | TCP | SIP TLS |
| 8443 | TCP | SIP WSS |
| 40000-60000 | UDP | RTP |

### Web/Monitoring Server

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 80 | TCP | HTTP (nginx) |
| 443 | TCP | HTTPS (nginx) |
| 3000 | TCP | API Server |
| 9080 | TCP | Homer |

## Scaling

The SBC and Feature Server Auto Scaling Groups can be scaled manually or configured with scaling policies:

```bash
# Scale SBC servers
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name jambonz-medium-sbc-sip-autoscaling-group \
  --desired-capacity 2 \
  --region us-west-2

# Scale Feature servers
aws autoscaling set-desired-capacity \
  --auto-scaling-group-name jambonz-medium-feature-server-autoscaling-group \
  --desired-capacity 2 \
  --region us-west-2
```
