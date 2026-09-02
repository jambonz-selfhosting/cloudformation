# jambonz Mini CloudFormation Deployment

This directory contains the base CloudFormation template for "jambonz mini" - a single EC2 instance running all jambonz components for development, testing, or small-scale production use.

**Important:** Do not deploy `_jambonz-base-template.yaml` directly. Instead, run `../generate-cf.sh` from the project root to generate a deployable template.

## Prerequisites

- AWS CLI and credentials configured
- `yq` installed (YAML processor)
- An existing EC2 Key Pair in the target region
- An AWS account with permissions to create VPCs, EC2 instances, IAM roles, and Elastic IPs

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `Architecture` | CPU architecture: `amd64` (x86_64) or `arm64` (Graviton). Allowed values are limited to the architectures whose AMIs were copied | amd64 |
| `InstanceType` | EC2 instance type | c5n.large |
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `AllowedSshCidr` | CIDR for SSH access | 0.0.0.0/0 |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | 0.0.0.0/0 |
| `AllowedSipCidr` | CIDR for SIP access | 0.0.0.0/0 |
| `AllowedRtpCidr` | CIDR for RTP traffic | 0.0.0.0/0 |
| `VpcCidr` | CIDR range of the VPC. When using an existing VPC, set this to that VPC's CIDR | 10.0.0.0/16 |
| `ExistingVpcId` | Optional. Blank creates a new VPC; set to a `vpc-...` id to deploy into a VPC you already have | (blank) |
| `ExistingSubnetIds` | Optional. Required when `ExistingVpcId` is set: the id of one public subnet in that VPC | (blank) |
| `EnableTLS` | Enable SIP over TLS (5061) and WSS (8443) | false |
| `SipDomain` | Required with `EnableTLS`: SIP domain for the certificate | (blank) |
| `CertEmail` | Required with `EnableTLS`: email Let's Encrypt registers the cert against | (blank) |
| `HostedZoneId` | Required with `EnableTLS`: Route 53 hosted zone id for `SipDomain` | (blank) |
| `EnableMtls` | Present a client certificate on outbound SIP over TLS | false |
| `MtlsCaCertParam` | Required with `EnableMtls`: SSM parameter holding the private CA certificate | (blank) |
| `MtlsCaKeyParam` | Required with `EnableMtls`: SSM parameter holding the private CA key | (blank) |
| `MtlsCommonName` | CN placed in the client certificate. Blank uses `SipDomain` | (blank) |
| `MtlsCaFile` | Authorities allowed to sign the *carrier's* server certificate | system bundle |
| `MtlsVerifyServerCert` | Verify the carrier's certificate at all | false |
| `MtlsVerifyServerName` | Require the carrier's certificate to match the hostname dialled | false |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `URLPortal` | DNS name for the portal | (required) |
| `KrispApiKey` | Optional Krisp API key for noise isolation and turn-taking (contact support@jambonz.org for info) | (none) |
| `EnableEBSEncryption` | Encrypt all EBS volumes | true |
| `EnableOpenTelemetry` | Enable OpenTelemetry tracing (Cassandra, Jaeger). Increases resource usage | false |

> **Instance type / architecture:** the `Architecture` parameter (dropdown, default `amd64`)
> selects both the AMI and the instance-type default. Its allowed values are the
> architectures whose AMIs `generate-cf.sh` copied — pick "both" there to make it selectable
> at deploy time. Leave `InstanceType` blank to use the architecture- and region-optimized
> default: amd64 is `c5n.large` (or `c5`/`t3` where `c5n` is unavailable), arm64 (Graviton) is
> `c7g.large` (or `t4g`/`c6g` where `c7g` is unavailable). If you set `InstanceType`
> explicitly, match it to the selected architecture. arm64 availability is region-dependent —
> see the top-level README.

## Deploying into an existing VPC

By default the stack creates its own VPC, subnet, internet gateway and route table, and
nothing else is required. To deploy into a VPC you already have, set these parameters:

| Parameter | Example |
|-----------|---------|
| `ExistingVpcId` | `vpc-0abc123def456789` |
| `ExistingSubnetIds` | `subnet-0abc123def456789` — exactly one public subnet id |
| `VpcCidr` | `10.0.0.0/16` — the CIDR of that VPC, **not** a new range |

Leave `ExistingVpcId` blank and the stack behaves exactly as it always has.

Both new parameters are validated before any resource is created, so a typo, a stray space,
or setting one without the other is rejected in seconds instead of failing part-way through
a create and rolling back.

### `ExistingVpcId` cannot be changed after the stack is created

Treat it as a create-time-only decision. Switching a live stack from its own VPC to an
existing one (or back) cannot succeed: the security groups, DB subnet group and cache
subnet group all carry fixed physical names, so the required replacement collides with
itself, and the old VPC cannot be deleted while its ENIs remain. The stack ends in
`UPDATE_ROLLBACK_FAILED`.

The dangerous direction is accidental. **CloudFormation substitutes the template default
for any parameter you omit on an update — it does not keep the previous value.** So an
update that forgets `ExistingVpcId` silently flips back to "create a new VPC", and because
`SubnetId` is a replacement property, the single instance — which holds MySQL and Redis,
and therefore every account, application and CDR — is **replaced and its data lost**,
while the stack reports `UPDATE_COMPLETE`. Always pass
it explicitly, or use `--parameters ParameterKey=ExistingVpcId,UsePreviousValue=true`, on
every update. `aws cloudformation deploy` and console updates that start from the existing
parameter set are not affected.

### Requirements for the VPC and subnet you supply

- **The subnet must be public.** It needs a default route (`0.0.0.0/0`) to an internet
  gateway. jambonz needs a public IP for SIP, RTP and the portal, and the instance
  downloads packages from the internet on first boot. A private subnet behind a NAT
  gateway will not work.
- **`VpcCidr` must match the existing VPC's CIDR.** CloudFormation cannot look up the CIDR
  of an existing VPC, so you have to tell it. It drives the security group rules that allow
  internal RTP and SMPP traffic. Nothing checks it, and nothing fails at deploy time if it
  is wrong — the stack reaches `CREATE_COMPLETE` and traffic is silently misrouted.
- **The subnet needs free addresses** and must be in the region the template was generated
  for.
- **Check the subnet's Network ACL.** A fresh VPC gets an allow-all NACL, so this never
  mattered before. A locked-down enterprise subnet that only permits 80/443 will
  statelessly drop SIP (5060/5061/8443) and RTP (UDP 40000-60000) while every security
  group still looks correct — calls connect with no audio.
- **DNS resolution and DNS hostnames should be enabled** on the VPC. The stack enables both
  on the VPC it creates. Note that `enableDnsHostnames` is **off** by default for a VPC you
  created yourself, so check rather than assume.

### Security: what `VpcCidr` opens up in a shared VPC

Two of mini's ingress rules are written against `VpcCidr` rather than against a specific
source: RTP (UDP 40000-60000) and SMPP (TCP 3020). When the stack created its own VPC, that
CIDR meant "jambonz only". In a VPC you share with other workloads it means any instance,
VPC-attached Lambda or container in that VPC can reach those two ports.

Mini is all-in-one, so this is milder than it is for the medium and large deployments —
MySQL and Redis run on the instance itself and are never exposed to the network at all. But
if the two rules above are not acceptable in your VPC, narrow `AllowedRtpCidr` and deploy
into a VPC dedicated to jambonz.

### What the stack does and does not touch

It still creates its own security groups and Elastic IP, inside your VPC. It does not add,
remove or modify any subnet, route table, route or gateway in your VPC.

One exception on teardown: the Elastic IP carries `DeletionPolicy: Retain`, so
`delete-stack` reaches `DELETE_COMPLETE` and leaves it allocated and billed — and mini's
Elastic IP is untagged, so months later it is an unattached address with nothing to say
which stack created it. Release it by hand after deleting the stack.

## Generate and Deploy

First, generate the CloudFormation template:

```bash
cd ..  # Go to project root
./generate-cf.sh
# Follow prompts to select 'mini', the CPU architecture (amd64/arm64/both), and your region
# Wait for AMI copy to complete
```

Then deploy the generated template. Mini's template is around 42 KB, comfortably under the
51,200-byte limit that `--template-body` accepts, so it deploys straight from disk — the
generator prints the same command when it finishes. (Medium and large are far larger and do
need the S3 route.)

```bash
aws cloudformation create-stack \
  --region us-west-2 \
  --stack-name jambonz-mini \
  --template-body file://jambonz-mini-us-west-2-arm64.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=KeyName,ParameterValue=<your-key-name> \
    ParameterKey=URLPortal,ParameterValue=<your-domain>
```

Uploading via the console works too: *Create stack → Upload a template file* has no such
limit, since the console puts it in S3 for you.

## Monitor Stack Creation

Wait for the stack to complete:

```bash
aws cloudformation wait stack-create-complete --stack-name jambonz-mini --region us-west-2
```

Or check status manually:

```bash
aws cloudformation describe-stacks --stack-name jambonz-mini --region us-west-2
```

## Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name jambonz-mini \
  --region us-west-2 \
  --query 'Stacks[0].Outputs'
```

Outputs include:
- **PortalURL** - URL to access the jambonz web portal
- **ServerIP** - Public IP address of the instance
- **User** - Admin username (always `admin`)
- **Password** - Initial admin password (the EC2 instance ID)

## Post-install steps

### Create DNS records

After the stack is created, create the following A records, all pointing to the ServerIP:
- `my-domain.example.com`
- `api.my-domain.example.com`
- `grafana.my-domain.example.com`
- `homer.my-domain.example.com`
- `sip.my-domain.example.com`

### Enable SIP over TLS and WSS

Set four parameters and the instance configures itself at boot — no SSH, no manual certbot run:

| Parameter | Example |
|-----------|---------|
| `EnableTLS` | `true` |
| `SipDomain` | `sip.example.com` |
| `CertEmail` | `admin@example.com` |
| `HostedZoneId` | `Z1234567890ABC` |

This brings up SIP over TLS on `5061` and SIP over secure WebSockets on `8443` — the latter
is what browser clients (jsSIP, SIP.js) need, since browsers refuse plain `ws`. The security
group already allows both from `AllowedSipCidr`.

Leave `EnableTLS` at `false` and nothing changes; the other three are ignored.

#### What happens on the SBC

The launch template runs `/usr/local/bin/drachtio_tls.sh`, which the AMI already carries.
The script:

1. requests a certificate for `SipDomain` **and** `*.SipDomain` via certbot's Route 53
   DNS-01 plugin;
2. inserts the `<tls>` block into `/etc/drachtio.conf.xml`;
3. appends the `sips:` contacts to `/etc/systemd/system/drachtio.service`;
4. drops a renewal hook at `/etc/letsencrypt/renewal-hooks/deploy/drachtio-tls.sh` and
   enables `certbot.timer`;
5. reloads systemd and restarts drachtio.

Every step is guarded, so re-running it is a no-op. It runs on each boot on purpose: a
replacement instance starts with an empty `/etc/letsencrypt` and an unmodified
`drachtio.conf.xml`, so it has to redo the work.

The wildcard means you can give different jambonz accounts different SIP realms
(`alice.sip.example.com`, `bob.sip.example.com`) under one certificate. Pass the bare
domain — the `*.` is added for you.

The script lives in the AMI, so changing it means rebuilding the image and repointing
`mappings/ami-mappings.yaml` — not a stack update.

#### Where the boot scripts live

Both scripts ship inside the AMI at `/usr/local/bin/drachtio_tls.sh` and
`/usr/local/bin/drachtio_mtls.sh`, installed by the packer build. User data only invokes
them, which is what keeps it under the 16 KB EC2 limit. The certbot `dns-route53` plugin
they depend on is installed at image build time as well, so nothing is fetched from apt or
Parameter Store while the instance boots.

The scripts live in the [packer repository](https://github.com/jambonz-selfhosting/packer)
under `files/`, and are installed by `scripts/install_certbot.sh` for the `mini`, `sip` and
`sip-rtp` variants. That is the only copy — edit them there.

**This couples the feature to the image.** `EnableTLS` and `EnableMtls` only work on an AMI
built with those scripts present. On an older image user data prints
`ERROR: drachtio_tls.sh not in this AMI` and the instance comes up without TLS rather than
failing the stack. If you see that, rebuild the image or point `ami-mappings.yaml` at a
newer one.

#### The certificate is cached in Parameter Store

Let's Encrypt allows **5 duplicate certificates per registered domain per week**, and the
boot script runs on every replacement. mini is a single instance rather than an autoscaling
group, so this bites when you rebuild the stack, move to a new AMI, or run more than one
mini on the same SIP domain — without a cache a handful of rebuilds exhausts the allowance
and the next one comes up with no TLS until the window rolls.

The issued certificate and its key are therefore stored under
`<TlsCertParamPrefix>/<SipDomain>/fullchain` and `.../privkey` (a SecureString). A booting
SBC reuses the cached copy when it still parses, pairs with its key, covers the domain and
has more than 30 days left; only when none of that holds does it ask Let's Encrypt, and it
writes the result back for the next instance. Renewal refreshes the cached copy too.

`TlsCertParamPrefix` defaults to `/jambonz/tls`. Stacks that serve the same `SipDomain`
should share it — the rate limit is per domain, not per stack, so sharing the prefix is what
keeps them from competing for the same five requests. The SBC's IAM policy grants read and
write on exactly `<prefix>/<SipDomain>/*`, nothing wider.

Two caveats. These parameters are written by the instance, not by CloudFormation, so they
**outlive the stack** — delete them by hand when you tear a deployment down for good, since
one of them holds a private key. And two instances that boot at the same moment both miss
the cache and both ask Let's Encrypt, so a large simultaneous scale-out can still spend more
than one request.

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
  only when `EnableTLS` is true. Note that this deployment is a single instance, so the grant
  reaches nothing else.
- **`sip.<your-domain>` must resolve to the instance's Elastic IP** so clients can validate the
  certificate. See the DNS records section above.
- **certbot with the route53 plugin must be in the AMI.** Images built from the packer repo
  with `install_certbot=yes` have it. If certbot is missing the boot script fails, logs the
  error, and the SBC comes up **without TLS** — and since nothing here signals boot status,
  the stack still reports `CREATE_COMPLETE`. Check `/var/log/cloud-init-output.log` on the
  instance after the first deploy.

#### Rate limit — read this before scaling the SBC

**A certificate is requested on every boot**, since an autoscaled instance starts with an
empty `/etc/letsencrypt`. Every one of those requests asks for the identical hostname set
(`SipDomain` plus its wildcard), so the limit that binds is Let's Encrypt's **duplicate
certificate** limit — **5 per week for the same set of hostnames** — not the more generous
50-per-registered-domain figure.

Five SBC boots in a rolling week is not a lot: scaling the group toward `MaxSize`, one
health-check replacement, or a few stack recreations during testing will reach it. When it
trips, certbot returns "too many certificates already issued", the boot script logs the
failure and continues, **and the SBC serves plain SIP behind a stack that reports
`CREATE_COMPLETE`**.

A single instance is replaced far less often than an autoscaling group, so this is
unlikely to bite outside repeated testing.

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

#### The CA private key reaches the instance — read this before enabling

`MtlsCaKeyParam` gives the instance role read access to the key that signs certificates the
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
server, not just the mTLS carrier — which is why both are parameters defaulting to `false`,
so switching mTLS on changes nothing for trunks you already have.

`MtlsVerifyServerCert` turns on validation of the carrier's own certificate against
`MtlsCaFile`. It is worth enabling, but check first that every TLS carrier you use presents a
certificate chaining to that file; one using a private hierarchy will start failing.
`MtlsVerifyServerName` additionally requires the certificate to match the hostname dialled,
so leave it off if any trunk is configured by IP address — an IP can never match a hostname.
`sni` is on by default and the template does not touch it.

#### Confirm it took

```
sudo grep -a "tls client" /var/log/drachtio/drachtio.log | tail -3
```

```
tls client key file:   /etc/drachtio/tls/carrier-client.key
tls client cert file:  /etc/drachtio/tls/carrier-client.pem
tls client ca file:    /etc/ssl/certs/ca-certificates.crt
```

Those three lines are the check. If they are absent, drachtio did not read `<client>` —
usually a path it cannot read, or the element sitting outside `<tls>`. Nothing else reports
it: a stack that fails here still reaches `CREATE_COMPLETE`, and a missing identity surfaces
as calls that fail to connect rather than a SIP rejection you can inspect, because the
handshake dies before any SIP is exchanged.

drachtio logs a fourth line, `tls verify policy: …`, only when at least one of the verify
switches is on. With both at their default of `false` it never appears, so its absence says
nothing about whether mTLS is working — do not use it as the test. Turning
`MtlsVerifyServerCert` on produces:

```
tls verify policy: incoming cert no, outgoing cert yes, outgoing name no
```

### Enable HTTPS for the portal

ssh into the ServerIP and install TLS certificates and then restart the portal under https.

1. `ssh jambonz@<ServerIP>` - ssh into the server
2. `sudo certbot --nginx` - generate TLS certs
3. `cd ~/apps/webapp && vi .env` - edit the webapp url to use https
4. edit the http url and change it to use https, save the file
5. `npm run build && pm2 restart webapp-app` - restart the webapp under https

## First time login

Now log into the portal for the first time.  

The user is 'admin' and the password will have been listed as part of the outputs above (it is set initially to the instance id).  You will be prompted to change the password on first login.

## Acquiring a license

When you log in for the first time, you will notice a banner at the top of the portal indicating that the system is unlicensed.  Click on the link in the message to go to the Admin settings panel where you can paste in a license key.  

To acquire a license key go to [licensing.jambonz.org](https://licensing.jambonz.org), create an account and purchase a license or request a trial license.

## Delete the Stack

```bash
aws cloudformation delete-stack --stack-name jambonz-mini --region us-west-2
```

Note: The Elastic IP has a `Retain` deletion policy and will not be deleted with the stack.  You can manually deregister it after the stack is deleted if you do not wish to use it any more.

## SSH Access

Connect to the instance as the `jambonz` user:

```bash
ssh -i /path/to/keypair.pem jambonz@<ServerIP>
```

## Ports

The following ports will be open on the server.

| Port | Protocol | Service |
|------|----------|---------|
| 22 | TCP | SSH |
| 80 | TCP | HTTP (nginx) |
| 443 | TCP | HTTPS (nginx) |
| 5060 | UDP/TCP | SIP |
| 5061 | TCP | SIP TLS |
| 8443 | TCP | SIP WSS |
| 3000 | TCP | Grafana |
| 9080 | TCP | Homer |
| 40000-60000 | UDP | RTP |
