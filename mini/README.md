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
| `InstanceType` | EC2 instance type | c5n.large |
| `KeyName` | EC2 Key Pair name for SSH access | (required) |
| `AllowedSshCidr` | CIDR for SSH access | 0.0.0.0/0 |
| `AllowedHttpCidr` | CIDR for HTTP/HTTPS access | 0.0.0.0/0 |
| `AllowedSipCidr` | CIDR for SIP access | 0.0.0.0/0 |
| `AllowedRtpCidr` | CIDR for RTP traffic | 0.0.0.0/0 |
| `VpcCidr` | CIDR range for the VPC | 10.0.0.0/16 |
| `Cloudwatch` | Enable CloudWatch logging | true |
| `CloudwatchLogRetention` | Days to retain CloudWatch logs | 3 |
| `URLPortal` | DNS name for the portal | (required) |

## Generate and Deploy

First, generate the CloudFormation template:

```bash
cd ..  # Go to project root
./generate-cf.sh
# Follow prompts to select 'mini' and your region
# Wait for AMI copy to complete
```

Then deploy the generated template:

```bash
aws cloudformation create-stack \
  --stack-name jambonz-mini \
  --template-body file://jambonz-mini-us-west-2.yaml \
  --capabilities CAPABILITY_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=URLPortal,ParameterValue=my-domain.example.com
```

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
