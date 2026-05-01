# CloudFormation Deployment Scripts

Testing and post-installation scripts for jambonz CloudFormation deployments.

## Overview

These scripts help you:
1. **Verify** your deployment completed successfully (cloud-init, services)
2. **Configure** DNS records, TLS certificates, and HTTPS

## Prerequisites

- Python 3.8+
- AWS CLI configured with credentials
- SSH key used when deploying the stack

Install Python dependencies:
```bash
cd scripts
pip install -r requirements.txt
```

## Configuration

Copy the example environment file and edit it:
```bash
cp .env.example .env
```

Edit `.env` with your settings:
```bash
# AWS Configuration
AWS_REGION=us-east-1
CF_STACK_NAME=jambonz-mini

# SSH Configuration
SSH_KEY_PATH=~/.ssh/your-key.pem
SSH_USER=jambonz

# DNS Configuration (DNSMadeEasy) - optional, for post_install.py
DNS_API_KEY=your-api-key
DNS_SECRET=your-secret

# Email for Let's Encrypt - optional, for post_install.py
CERTBOT_EMAIL=admin@example.com
```

## Step 1: Test Deployment

After your CloudFormation stack reaches `CREATE_COMPLETE`, verify everything is working:

```bash
python test_deployment.py --stack-name jambonz-mini --region us-east-1
```

This checks:
- CloudFormation outputs are available
- SSH connectivity to the server
- cloud-init completed successfully
- Systemd services are running (drachtio, rtpengine, freeswitch, mysql, redis)
- PM2 processes are online (api-server, webapp, feature-server, etc.)

### Options

```bash
# Use a specific SSH key (overrides .env)
python test_deployment.py --stack-name jambonz-mini --region us-east-1 \
    --ssh-key ~/.ssh/my-key.pem

# Wait for cloud-init to complete (useful immediately after stack creation)
python test_deployment.py --stack-name jambonz-mini --region us-east-1 \
    --wait-for-cloud-init

# Verbose output
python test_deployment.py --stack-name jambonz-mini --region us-east-1 -v
```

### Example Output

```
============================================================
Jambonz CloudFormation Deployment Test
============================================================

Stack: jambonz-mini
Region: us-east-1
SSH User: jambonz
SSH Key: ~/.ssh/my-key.pem

[Step 1] Getting CloudFormation outputs...
  Server IP: 54.123.45.67
  Portal URL: mini.example.com

[Step 2] Testing SSH connectivity...
  SSH connection to 54.123.45.67 successful

[Step 3] Checking cloud-init status...
  cloud-init completed successfully

[Step 4] Checking systemd services...
  drachtio: active
  rtpengine: active
  freeswitch: active
  mysql: active
  redis: active
  grafana-server: active

[Step 5] Checking PM2 processes...
  inbound: ONLINE
  outbound: ONLINE
  sbc-call-router: ONLINE
  feature-server: ONLINE
  webapp: ONLINE
  api-server: ONLINE

============================================================
Test Summary
============================================================

  CloudFormation outputs: PASS
  SSH connectivity: PASS
  cloud-init: PASS
  systemd services: PASS (6/6 active)
  PM2 processes: PASS (6/6 online)

Total: 5 passed, 0 failed
```

## Step 2: Post-Installation (Optional)

If you want to configure DNS and TLS certificates:

```bash
python post_install.py --stack-name jambonz-mini --region us-east-1
```

This performs:
1. Creates DNS A records (requires DNSMadeEasy credentials in `.env`)
2. Provisions TLS certificates via Let's Encrypt
3. Rebuilds the webapp for HTTPS

### Options

```bash
# Skip DNS (if you manage DNS elsewhere)
python post_install.py --stack-name jambonz-mini --region us-east-1 --skip-dns

# Skip TLS (HTTP only)
python post_install.py --stack-name jambonz-mini --region us-east-1 --skip-tls

# Use Let's Encrypt staging (for testing - avoids rate limits)
python post_install.py --stack-name jambonz-mini --region us-east-1 --staging

# Skip webapp rebuild
python post_install.py --stack-name jambonz-mini --region us-east-1 --skip-webapp
```

### DNS Records Created

When using DNSMadeEasy, these A records are created pointing to your server IP:
- `{subdomain}.{domain}` - Portal
- `api.{subdomain}.{domain}` - API
- `grafana.{subdomain}.{domain}` - Grafana monitoring
- `homer.{subdomain}.{domain}` - Homer SIP capture
- `sip.{subdomain}.{domain}` - SIP endpoint

## Troubleshooting

### SSH Connection Failed

- Verify your SSH key path is correct
- Check that the security group allows SSH (port 22) from your IP
- Ensure the instance has finished booting (wait 2-3 minutes after stack creation)

### cloud-init Not Complete

- Use `--wait-for-cloud-init` flag to wait for completion
- SSH into the instance and check: `sudo cloud-init status`
- View logs: `sudo cat /var/log/cloud-init-output.log`

### Services Not Running

SSH into the instance and check:
```bash
# Check systemd services
sudo systemctl status drachtio rtpengine freeswitch

# Check PM2 processes
pm2 list
pm2 logs
```

### Certbot Failed

- Ensure DNS records are propagated before running certbot
- Check that ports 80 and 443 are open in the security group
- Use `--staging` flag first to test without hitting rate limits
