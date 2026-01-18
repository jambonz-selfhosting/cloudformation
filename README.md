# jambonz AWS CloudFormation Templates

This repository contains AWS CloudFormation templates for self-hosting jambonz. For more information on jambonz, please refer to [our docs](https://docs.jambonz.org).

## Deployment Options

| Deployment | Description | Concurrent Calls | Use Case |
|------------|-------------|------------------|----------|
| [Mini](mini/) | Single EC2 instance with all components | Up to 50 | Development, testing, small-scale production |
| [Medium](medium/) | Multi-tier with SBC, Feature Server, and Web/Monitoring ASGs | Up to 1,500 | Production workloads requiring HA |
| [Large](large/) | Fully separated SBC SIP, SBC RTP, Feature Server, Web, and Monitoring | 1,500+ | Large-scale production with maximum scalability |

## Prerequisites

Before deploying jambonz, you'll need:

1. **Bash environment**
   - macOS/Linux: Built-in terminal
   - Windows: **WSL2 (Windows Subsystem for Linux)** recommended - [Installation Guide](https://learn.microsoft.com/en-us/windows/wsl/install)
     - Run `wsl --install` in PowerShell as Administrator
     - After WSL2 is installed, run all commands in the WSL2 terminal

2. **AWS CLI** - [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
   - macOS: `brew install awscli`
   - Linux/WSL2: `curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip awscliv2.zip && sudo ./aws/install`
   - Windows (native): Use MSI installer (but note: you'll still need WSL2 to run the bash script)

3. **yq** - YAML processor ([Installation Guide](https://github.com/mikefarah/yq#install))
   - macOS: `brew install yq`
   - Linux/WSL2: `wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/local/bin/yq && chmod +x /usr/local/bin/yq`
   - Windows: Install in WSL2 using the Linux instructions above

4. **AWS Credentials** - Configure using `aws configure`
   - You'll need your AWS Access Key ID and Secret Access Key
   - Required IAM permissions: `ec2:CopyImage`, `ec2:DescribeImages`, `ec2:CreateTags`, `cloudformation:*`

5. **AWS Resources**:
   - An EC2 Key Pair in your target region
   - A domain name for the portal (DNS records created post-deployment)

## Quick Start

### Step 1: Generate CloudFormation Template

Run the generation script to copy AMIs to your account and create a region-specific CloudFormation template:

```bash
./generate-cf.sh
```

The script will:
1. Verify AWS CLI is installed and credentials are configured
2. Prompt you to select:
   - Deployment size (mini/medium/large)
   - AWS region
3. Copy the required public jambonz AMIs to your AWS account (typically takes 5-15 minutes)
4. Show progress updates every 30 seconds
5. Generate a CloudFormation template in the project root (e.g., `jambonz-mini-us-east-1.yaml`)

**Why copy AMIs?**
- You own the AMIs in your account (no dependency on public AMIs)
- You can customize AMIs if needed
- Protection against public AMI lifecycle changes

### Step 2: Deploy CloudFormation Stack

After the script completes, deploy using the generated template:

```bash
# Example for mini deployment in us-east-1
aws cloudformation create-stack \
  --stack-name jambonz-mini \
  --template-body file://jambonz-mini-us-east-1.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=AllowedSshCidr,ParameterValue=203.0.113.0/32 \
    ParameterKey=URLPortal,ParameterValue=my-domain.example.com
```

Or deploy via AWS Console:
1. Navigate to CloudFormation service
2. Click "Create stack"
3. Upload the generated template (e.g., `jambonz-mini-us-east-1.yaml`)
4. Follow the wizard to configure parameters

## Architecture Comparison

### Mini
- Single EC2 instance running all components
- Local MySQL and Redis
- Simplest setup, lowest cost

### Medium
- Separate SBC (SIP+RTP combined) Auto Scaling Group
- Feature Server Auto Scaling Group
- Combined Web/Monitoring server
- Aurora Serverless MySQL + ElastiCache Redis

### Large
- Separate SBC SIP Auto Scaling Group
- Separate SBC RTP Auto Scaling Group
- Feature Server Auto Scaling Group
- Dedicated Web Server
- Dedicated Monitoring Server
- Aurora Serverless MySQL + ElastiCache Redis

## Post-Deployment

After deploying any stack:

1. Create DNS A records pointing to the output IP addresses
2. SSH into the web server and run `sudo certbot --nginx` for HTTPS
3. Log into the portal (user: `admin`, password: instance ID)
4. Obtain a license at [licensing.jambonz.org](https://licensing.jambonz.org)

## FAQ

### Why do I need to copy AMIs to my account?

Copying AMIs to your AWS account gives you ownership and control:
- No dependency on public AMIs remaining available indefinitely
- Freedom to customize AMIs for your specific needs
- Protection against public AMI lifecycle changes
- Clear version tracking (AMIs are named with the jambonz version)

### Can I generate templates for multiple regions?

Yes! The generated templates are named `jambonz-{size}-{region}.yaml`, so you can have multiple regions simultaneously:

```bash
./generate-cf.sh  # Generate for us-east-1
# Creates: jambonz-mini-us-east-1.yaml

./generate-cf.sh  # Generate for eu-west-1
# Creates: jambonz-mini-eu-west-1.yaml

# Both files coexist in the project root
```

### Can I delete the copied AMIs?

Yes, but you'll need to re-run the script if you want to deploy again. AMIs incur storage costs (~$0.05 per GB-month), so you may want to delete them when not actively using them.

To delete: AWS Console > EC2 > AMIs > Select AMI > Actions > Deregister AMI

### What are the AMI storage costs?

Typical costs are minimal:
- Mini AMI: ~10-15 GB = $0.50-0.75/month
- Medium AMIs (4 total): ~40-60 GB = $2-3/month
- Large AMIs (6 total): ~60-90 GB = $3-4.50/month

### The AMI copy is taking too long. Is something wrong?

Same-region AMI copies typically take 5-15 minutes depending on AMI size and AWS region load. The script polls every 30 seconds and shows:
- Current elapsed time
- Status of each AMI (pending → available)
- Progress counter (e.g., "2/4 AMIs ready")

If the copy exceeds 1 hour, the script will timeout with an error. You can also check progress manually in the AWS Console or with:
```bash
aws ec2 describe-images --region <region> --owners self --filters "Name=name,Values=jambonz-*" --query 'Images[*].[Name,State]' --output table
```

## Documentation

- [jambonz Documentation](https://docs.jambonz.org)
- [Licensing Portal](https://licensing.jambonz.org)
