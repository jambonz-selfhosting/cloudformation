# jambonz Large CloudFormation Deployment

This directory contains the base CloudFormation template for "jambonz large" - a highly scalable multi-tier architecture with separate SBC SIP, SBC RTP, Feature Server, Web Server, and Monitoring components, backed by Aurora Serverless MySQL and ElastiCache Redis. Suitable for large-scale production workloads requiring maximum scalability and separation of concerns.

**Important:** Do not deploy `_jambonz-base-template.yaml` directly. Instead, run `../generate-cf.sh` from the project root to generate a deployable template.

Use this Cloudformation deployment for production workloads requiring high availability and scalability that need to scale to over 1,500 concurrent calls.

## Architecture

The large deployment creates:

- **SBC SIP Auto Scaling Group** - Handles SIP signaling with drachtio
- **SBC RTP Auto Scaling Group** - Handles RTP media with rtpengine
- **Feature Server Auto Scaling Group** - Runs jambonz application logic with FreeSWITCH
- **Web Server** - Hosts the portal, API, and public apps
- **Monitoring Server** - Hosts Grafana, Homer, Jaeger, InfluxDB, and Cassandra
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
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `URLPortal` | DNS name for the portal | (required) |
| `EnablePcaps` | Enable PCAPs for SIP traffic | (required) |
| `InstanceTypeSbcSip` | EC2 instance type for SBC SIP servers | c5n.xlarge |
| `InstanceTypeSbcRtp` | EC2 instance type for SBC RTP servers | c5n.xlarge |
| `InstanceTypeFeatureServer` | EC2 instance type for Feature servers | c5n.xlarge |
| `InstanceTypeWebserver` | EC2 instance type for Web server | c5n.xlarge |
| `InstanceTypeMonitoringServer` | EC2 instance type for Monitoring server | c5n.xlarge |
| `RecordingInstanceType` | EC2 instance type for Recording servers | t2.xlarge |
| `ElastiCacheNodeType` | ElastiCache node type | cache.t3.medium |
| `AuroraDBMinCapacity` | Aurora Serverless min ACU | 0.5 |
| `AuroraDBMaxCapacity` | Aurora Serverless max ACU | 8 |
| `AllowedSshCidr` | CIDR for SSH access | 0.0.0.0/0 |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | 0.0.0.0/0 |
| `AllowedSipCidr` | CIDR for SIP access | 0.0.0.0/0 |
| `AllowedSmppCidr` | CIDR for SMPP access | 0.0.0.0/0 |
| `AllowedRtpCidr` | CIDR for RTP traffic | 0.0.0.0/0 |
| `VpcCidr` | CIDR range for the VPC | 172.20.0.0/16 |
| `MySQLUsername` | Database username | admin |
| `MySQLPassword` | Database password | JambonzR0ck$ |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `DeployRecordingCluster` | Deploy optional recording cluster | yes |
| `EnableEBSEncryption` | Encrypt all EBS volumes | no |

## Generate and Deploy

First, generate the CloudFormation template:

```bash
cd ..  # Go to project root
./generate-cf.sh
# Follow prompts to select 'large' and your region
# Wait for AMI copy to complete
```

The generated template exceeds the 51,200 byte limit for inline `--template-body`, so you must upload it to S3 first:

```bash
# Upload template to S3 (create bucket if needed)
aws s3 mb s3://my-cf-templates-bucket --region us-west-2
aws s3 cp jambonz-large-us-west-2.yaml s3://my-cf-templates-bucket/jambonz-large.yaml

# Deploy using --template-url
aws cloudformation create-stack \
  --stack-name jambonz-large \
  --template-url https://my-cf-templates-bucket.s3.us-west-2.amazonaws.com/jambonz-large.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
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
- **WebServerIP** - Public IP address of the Web server (for DNS records)
- **SipServerIP** - Public IP address of the SBC SIP server (for SIP traffic)
- **RtpServerIP** - Public IP address of the SBC RTP server (for RTP traffic)
- **WebPortalUsername** - Admin username (always `admin`)
- **WebPortalPassword** - Initial admin password (the Web server EC2 instance ID)
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

**Pointing to SipServerIP:**
- `sip.my-domain.example.com`

### Enable HTTPS for the portal

SSH into the Web server and install TLS certificates:

1. `ssh -i <yuour-ssh-keypair> jambonz@<WebServerIP>` - ssh into the server
2. `sudo certbot --nginx` - generate TLS certs
3. `cd ~/apps/webapp && vi .env` - edit the VITE_API_BASE_URL param to use https
4. `npm run build && pm2 restart webapp` - restart the webapp under https

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