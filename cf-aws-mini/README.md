# jambonz Mini CloudFormation Deployment

This CloudFormation template deploys a single EC2 instance running all jambonz components for development, testing, or small-scale production use.

## Prerequisites

- AWS CLI installed and configured with appropriate credentials
- An existing EC2 Key Pair in the target region
- The jambonz AMI available in your target region (currently only us-west-2)

## Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `InstanceType` | EC2 instance type | c5n.large |
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `AllowedSshCidr` | CIDR for SSH access | (required) |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | (required) |
| `AllowedSipCidr` | CIDR for SIP access | (required) |
| `AllowedRtpCidr` | CIDR for RTP traffic | (required) |
| `VpcCidr` | CIDR range for the VPC | 10.0.0.0/16 |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `URLPortal` | Optional DNS name for the portal | (empty) |

## Deploy the Stack

```bash
aws cloudformation create-stack \
  --stack-name jambonz-mini \
  --template-body file://jambonz.yaml \
  --capabilities CAPABILITY_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=AllowedSshCidr,ParameterValue=203.0.113.10/32 \
    ParameterKey=AllowedHttpCidr,ParameterValue=0.0.0.0/0 \
    ParameterKey=AllowedSipCidr,ParameterValue=0.0.0.0/0 \
    ParameterKey=AllowedRtpCidr,ParameterValue=0.0.0.0/0
```

### With Custom DNS

```bash
aws cloudformation create-stack \
  --stack-name jambonz-mini \
  --template-body file://jambonz.yaml \
  --capabilities CAPABILITY_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=AllowedSshCidr,ParameterValue=203.0.113.10/32 \
    ParameterKey=AllowedHttpCidr,ParameterValue=0.0.0.0/0 \
    ParameterKey=AllowedSipCidr,ParameterValue=0.0.0.0/0 \
    ParameterKey=AllowedRtpCidr,ParameterValue=0.0.0.0/0 \
    ParameterKey=URLPortal,ParameterValue=jambonz.example.com
```

When using a custom DNS name, create A records pointing to the server IP for:
- `jambonz.example.com` (main portal)
- `api.jambonz.example.com` (API)
- `grafana.jambonz.example.com` (monitoring)
- `homer.jambonz.example.com` (SIP tracing)

## Monitor Stack Creation

```bash
aws cloudformation describe-stacks --stack-name jambonz-mini --region us-west-2

aws cloudformation describe-stack-events --stack-name jambonz-mini --region us-west-2
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

## Update the Stack

```bash
aws cloudformation update-stack \
  --stack-name jambonz-mini \
  --template-body file://jambonz.yaml \
  --capabilities CAPABILITY_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,UsePreviousValue=true \
    ParameterKey=AllowedSshCidr,UsePreviousValue=true \
    ParameterKey=AllowedHttpCidr,UsePreviousValue=true \
    ParameterKey=AllowedSipCidr,UsePreviousValue=true \
    ParameterKey=AllowedRtpCidr,UsePreviousValue=true
```

## Delete the Stack

```bash
aws cloudformation delete-stack --stack-name jambonz-mini --region us-west-2
```

Note: The Elastic IP has a `Retain` deletion policy and will not be deleted with the stack.

## SSH Access

Connect to the instance as the `jambonz` user:

```bash
ssh -i /path/to/keypair.pem jambonz@<ServerIP>
```

## Services

The instance runs the following services managed by PM2:
- jambonz-api-server
- jambonz-webapp

System services:
- drachtio (SIP server)
- rtpengine (RTP proxy)
- MySQL
- Redis
- nginx
- Cassandra, Jaeger (tracing)
- InfluxDB, Telegraf, Grafana (metrics)
- Homer, heplify-server (SIP capture)

## Ports

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
