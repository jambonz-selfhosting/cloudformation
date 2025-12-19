# jambonz AWS CloudFormation Templates

This repository contains AWS CloudFormation templates for self-hosting jambonz. For more information on jambonz, please refer to [our docs](https://docs.jambonz.org).

## Deployment Options

| Deployment | Description | Concurrent Calls | Use Case |
|------------|-------------|------------------|----------|
| [Mini](mini/) | Single EC2 instance with all components | Up to 50 | Development, testing, small-scale production |
| [Medium](medium/) | Multi-tier with SBC, Feature Server, and Web/Monitoring ASGs | Up to 1,500 | Production workloads requiring HA |
| [Large](large/) | Fully separated SBC SIP, SBC RTP, Feature Server, Web, and Monitoring | 1,500+ | Large-scale production with maximum scalability |

## Quick Start

1. Choose a deployment size based on your requirements
2. Navigate to the corresponding directory
3. Follow the README instructions to deploy

Example (mini deployment):

```bash
aws cloudformation create-stack \
  --stack-name jambonz-mini \
  --template-body file://mini/jambonz.yaml \
  --capabilities CAPABILITY_IAM \
  --region us-west-2 \
  --parameters \
    ParameterKey=KeyName,ParameterValue=my-keypair \
    ParameterKey=URLPortal,ParameterValue=my-domain.example.com
```

## Prerequisites

- An AWS account with appropriate permissions
- An EC2 Key Pair in your target region
- A domain name for the portal (DNS records created post-deployment)

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

## Documentation

- [jambonz Documentation](https://docs.jambonz.org)
- [Licensing Portal](https://licensing.jambonz.org)
