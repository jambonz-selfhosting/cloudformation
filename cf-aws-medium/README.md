# jambonz Medium CloudFormation Deployment

This CloudFormation template deploys a "jambonz medium" - a scalable multi-tier architecture with separate SBC, Feature Server, and Web/Monitoring components, backed by Aurora Serverless MySQL and ElastiCache Redis. Suitable for production workloads requiring high availability and scalability up to 1,500 concurrent calls.

## Architecture

The medium deployment creates:

- **SBC Auto Scaling Group** - Handles SIP/RTP traffic with drachtio and rtpengine
- **Feature Server Auto Scaling Group** - Runs jambonz application logic with FreeSWITCH
- **Web/Monitoring Server** - Hosts the portal, API, Grafana, Homer, and Jaeger
- **Aurora Serverless v2** - MySQL database cluster
- **ElastiCache** - Redis cluster for caching and pub/sub
- **Optional Recording Cluster** - Auto-scaling recording servers behind an ALB

## Prerequisites

- An existing EC2 Key Pair in the target region
- An AWS account with permissions to create VPCs, EC2 instances, IAM roles, RDS, ElastiCache, and Elastic IPs

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `URLPortal` | DNS name for the portal | (required) |
| `EnablePcaps` | Enable PCAPs for SIP traffic | (required) |
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
| `VpcCidr` | CIDR range for the VPC | 172.20.0.0/16 |
| `MySQLUsername` | Database username | admin |
| `MySQLPassword` | Database password | JambonzR0ck$ |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `DeployRecordingCluster` | Deploy optional recording cluster | yes |

## Deploy the Stack

The template exceeds the 51,200 byte limit for inline `--template-body`, so you must upload it to S3 first.

```bash
# Upload template to S3 (create bucket if needed)
aws s3 mb s3://my-cf-templates-bucket --region us-west-1
aws s3 cp jambonz.yaml s3://my-cf-templates-bucket/jambonz-medium.yaml

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
