#!/usr/bin/env python3
"""
Post-installation configuration for Jambonz CloudFormation deployments.

Performs:
1. DNS A record creation (DNSMadeEasy)
2. TLS certificate provisioning via certbot
3. Webapp rebuild for HTTPS

Usage:
    # Full post-install
    python post_install.py --stack-name jambonz-mini --region ap-southeast-2

    # Skip DNS (if already configured)
    python post_install.py --stack-name jambonz-mini --region ap-southeast-2 --skip-dns

    # Use Let's Encrypt staging (for testing)
    python post_install.py --stack-name jambonz-mini --region ap-southeast-2 --staging
"""

import sys
import os
import logging
import time
import click
from pathlib import Path
from dotenv import load_dotenv

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from cf_helper import (
    get_stack_outputs,
    detect_deployment_type,
    get_web_server_ip,
    get_sip_server_ip,
    CFError
)
from ssh_helper import run_ssh_command, SSHError
from dns_manager import (
    DNSManager,
    DNSError,
    extract_base_domain,
    extract_subdomain,
    wait_for_dns_propagation
)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(message)s'
    )
    return logging.getLogger("jambonz-test")


@click.command()
@click.option(
    '--stack-name',
    required=True,
    help='CloudFormation stack name'
)
@click.option(
    '--region',
    required=True,
    help='AWS region where the stack is deployed'
)
@click.option(
    '--ssh-key',
    help='Path to SSH private key (overrides .env SSH_KEY_PATH)'
)
@click.option(
    '--ssh-user',
    default=None,
    help='SSH username (default: jambonz, or from .env SSH_USER)'
)
@click.option(
    '--skip-dns',
    is_flag=True,
    help='Skip DNS record creation'
)
@click.option(
    '--skip-tls',
    is_flag=True,
    help='Skip TLS certificate provisioning'
)
@click.option(
    '--skip-webapp',
    is_flag=True,
    help='Skip webapp rebuild'
)
@click.option(
    '--staging',
    is_flag=True,
    help="Use Let's Encrypt staging server (for testing)"
)
@click.option(
    '--dns-wait',
    default=60,
    help='Seconds to wait for DNS propagation (default: 60)'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='Enable verbose output'
)
def main(stack_name, region, ssh_key, ssh_user, skip_dns, skip_tls, skip_webapp, staging, dns_wait, verbose):
    """
    Post-installation configuration for Jambonz CloudFormation deployment.

    Creates DNS records, provisions TLS certificates, and rebuilds the webapp
    for HTTPS support.
    """
    # Load environment from .env file
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    logger = setup_logging(verbose)

    # Build SSH config
    ssh_config = {
        'user': ssh_user or os.getenv('SSH_USER', 'jambonz'),
        'key_path': ssh_key or os.getenv('SSH_KEY_PATH', '~/.ssh/id_rsa'),
        'timeout': 300,
        'strict_host_key_checking': False
    }

    # Get DNS and certbot config from environment
    dns_api_key = os.getenv('DNS_API_KEY')
    dns_secret = os.getenv('DNS_SECRET')
    certbot_email = os.getenv('CERTBOT_EMAIL')

    print("=" * 60)
    print("Jambonz CloudFormation Post-Installation")
    print("=" * 60)
    print()
    print(f"Stack: {stack_name}")
    print(f"Region: {region}")
    print()

    # Step 1: Get CloudFormation outputs
    print("[Step 1] Getting CloudFormation outputs...")
    try:
        outputs = get_stack_outputs(stack_name, region)

        portal_url_raw = outputs.get('portal_url', '')
        password = outputs.get('password', '')

        # Strip protocol prefix if present (CF output may include http://)
        portal_url = portal_url_raw
        if portal_url.startswith('http://'):
            portal_url = portal_url[7:]
        elif portal_url.startswith('https://'):
            portal_url = portal_url[8:]

        if not portal_url:
            print("  ERROR: No portal URL found in stack outputs")
            print("  The URLPortal parameter must be set when deploying the stack")
            sys.exit(1)

        print(f"  Portal URL: {portal_url}")
        print()

    except CFError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 1b: Detect deployment type
    print("[Step 1b] Detecting deployment type...")
    deployment_type = detect_deployment_type(outputs)
    print(f"  Deployment type: {deployment_type}")

    # Get appropriate server IPs based on deployment type
    web_server_ip = get_web_server_ip(outputs, deployment_type)
    sip_server_ip = get_sip_server_ip(outputs, deployment_type)

    if not web_server_ip:
        print("  ERROR: No web server IP found in stack outputs")
        sys.exit(1)

    print(f"  Web server IP: {web_server_ip}")
    if sip_server_ip and sip_server_ip != web_server_ip:
        print(f"  SIP server IP: {sip_server_ip}")
    print()

    # Extract domain info
    base_domain = extract_base_domain(portal_url)
    subdomain = extract_subdomain(portal_url)

    print(f"  Base domain: {base_domain}")
    print(f"  Subdomain: {subdomain}")
    print()

    # Step 2: Create DNS records
    if not skip_dns:
        print("[Step 2] Creating DNS records...")

        if not dns_api_key or not dns_secret:
            print("  ERROR: DNS_API_KEY and DNS_SECRET must be set in .env")
            print("  Or use --skip-dns to skip DNS configuration")
            sys.exit(1)

        try:
            dns_manager = DNSManager(
                provider='dnsmadeeasy',
                config={
                    'api_key': dns_api_key,
                    'secret': dns_secret
                },
                base_domain=base_domain
            )

            # Create records for all subdomains
            # Web-related records point to web server
            web_subdomains = [
                subdomain,                    # portal (mini.jambonz.io)
                f"api.{subdomain}",           # api (api.mini.jambonz.io)
                f"grafana.{subdomain}",       # grafana (grafana.mini.jambonz.io)
                f"homer.{subdomain}",         # homer (homer.mini.jambonz.io)
            ]

            # SIP record points to SIP/SBC server
            sip_subdomains = [
                f"sip.{subdomain}",           # sip (sip.mini.jambonz.io)
            ]

            created_records = []

            # Create web-related DNS records
            for sub in web_subdomains:
                try:
                    record = dns_manager.create_a_record(sub, web_server_ip)
                    created_records.append(sub)
                    print(f"  Created: {sub}.{base_domain} -> {web_server_ip}")
                except DNSError as e:
                    print(f"  WARNING: Failed to create {sub}.{base_domain}: {e}")

            # Create SIP DNS record (may point to different server in medium/large deployments)
            for sub in sip_subdomains:
                try:
                    record = dns_manager.create_a_record(sub, sip_server_ip)
                    created_records.append(sub)
                    print(f"  Created: {sub}.{base_domain} -> {sip_server_ip}")
                except DNSError as e:
                    print(f"  WARNING: Failed to create {sub}.{base_domain}: {e}")

            if created_records:
                print()
                print(f"  Waiting {dns_wait}s for DNS propagation...")
                time.sleep(dns_wait)

                # Verify DNS propagation for portal URL
                try:
                    wait_for_dns_propagation(portal_url, web_server_ip, timeout=120)
                    print(f"  DNS propagated for {portal_url}")
                except DNSError as e:
                    print(f"  WARNING: DNS propagation check failed: {e}")
                    print("  Continuing anyway - DNS may still be propagating")

            print()

        except DNSError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)
    else:
        print("[Step 2] Skipping DNS configuration (--skip-dns)")
        print()

    # Step 3: Provision TLS certificates
    if not skip_tls:
        print("[Step 3] Provisioning TLS certificates...")

        if not certbot_email:
            print("  ERROR: CERTBOT_EMAIL must be set in .env")
            print("  Or use --skip-tls to skip TLS configuration")
            sys.exit(1)

        try:
            # Discover domains from nginx configuration on web server
            print(f"  Discovering domains from nginx configuration on {web_server_ip}...")
            stdout, stderr, exit_code = run_ssh_command(
                host=web_server_ip,
                command="sudo grep -h 'server_name' /etc/nginx/sites-enabled/* | grep -v '#' | sed 's/.*server_name//g' | sed 's/;//g' | tr -s ' ' '\\n' | grep -v '^$' | sort -u",
                ssh_config=ssh_config
            )

            if exit_code != 0 or not stdout.strip():
                print("  ERROR: Failed to discover domains from nginx")
                sys.exit(1)

            discovered_domains = [d.strip() for d in stdout.strip().split('\n') if d.strip() and d.strip() != '_']

            if not discovered_domains:
                print("  ERROR: No domains found in nginx configuration")
                sys.exit(1)

            print(f"  Found {len(discovered_domains)} domain(s):")
            for domain in discovered_domains:
                print(f"    - {domain}")
            print()

            # Build certbot command
            certbot_cmd_parts = ["sudo certbot --nginx"]

            for domain in discovered_domains:
                certbot_cmd_parts.append(f"-d {domain}")

            certbot_cmd_parts.extend([
                f"--email {certbot_email}",
                "--non-interactive",
                "--agree-tos",
                "--no-eff-email",
                "--redirect"
            ])

            if staging:
                certbot_cmd_parts.append("--staging")
                print("  Using Let's Encrypt STAGING server")

            certbot_cmd = " ".join(certbot_cmd_parts)

            print(f"  Running certbot on {web_server_ip} (this may take 1-2 minutes)...")
            stdout, stderr, exit_code = run_ssh_command(
                host=web_server_ip,
                command=certbot_cmd,
                ssh_config=ssh_config,
                timeout=180
            )

            if exit_code == 0:
                print("  TLS certificates provisioned successfully")
            else:
                print(f"  ERROR: Certbot failed (exit code {exit_code})")
                if verbose:
                    print(f"  Output: {stdout}")
                    print(f"  Stderr: {stderr}")

                # Check for common errors
                if "too many certificates" in stdout.lower() or "rate limit" in stdout.lower():
                    print()
                    print("  Rate limit hit. Consider using --staging for testing.")

                sys.exit(1)

            print()

        except SSHError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)
    else:
        print("[Step 3] Skipping TLS configuration (--skip-tls)")
        print()

    # Step 4: Rebuild webapp for HTTPS
    if not skip_webapp and not skip_tls:
        print("[Step 4] Rebuilding webapp for HTTPS...")

        try:
            # Update webapp .env for HTTPS on web server
            print(f"  Updating webapp for HTTPS on {web_server_ip}...")

            update_env_cmd = """
cd /home/jambonz/apps/webapp && \\
sed -i 's|http://|https://|g' .env && \\
npm run build
"""
            stdout, stderr, exit_code = run_ssh_command(
                host=web_server_ip,
                command=update_env_cmd,
                ssh_config=ssh_config,
                timeout=300
            )

            if exit_code == 0:
                print("  Webapp rebuilt successfully")
            else:
                print(f"  WARNING: Webapp rebuild may have failed (exit code {exit_code})")
                if verbose:
                    print(f"  Output: {stdout}")

            # Restart webapp PM2 process
            print(f"  Restarting webapp on {web_server_ip}...")
            stdout, stderr, exit_code = run_ssh_command(
                host=web_server_ip,
                command="pm2 restart webapp",
                ssh_config=ssh_config
            )

            if exit_code == 0:
                print("  Webapp restarted")
            else:
                print(f"  WARNING: Failed to restart webapp")

            print()

        except SSHError as e:
            print(f"  ERROR: {e}")
            # Don't exit - webapp rebuild is not critical

    elif skip_webapp:
        print("[Step 4] Skipping webapp rebuild (--skip-webapp)")
        print()
    else:
        print("[Step 4] Skipping webapp rebuild (TLS was skipped)")
        print()

    # Summary
    print("=" * 60)
    print("Post-Installation Complete!")
    print("=" * 60)
    print()
    print("URLs:")
    if not skip_tls:
        print(f"  Portal:  https://{portal_url}")
        print(f"  API:     https://api.{portal_url}")
        print(f"  Grafana: https://grafana.{portal_url}")
        print(f"  Homer:   https://homer.{portal_url}")
        print(f"  SIP:     sip.{portal_url}:5060")
    else:
        print(f"  Portal:  http://{portal_url}")
        print(f"  API:     http://api.{portal_url}")
    print()

    if password:
        print(f"Admin Password: {password}")
        print()

    if staging:
        print("NOTE: Using Let's Encrypt staging certificates.")
        print("      Browsers will show certificate warnings.")
        print("      Re-run without --staging for production certificates.")
        print()

    print("Next steps:")
    print("  1. Open the portal in your browser")
    print("  2. Log in with admin credentials")
    print("  3. Configure your SIP trunks and carriers")
    print()


if __name__ == '__main__':
    main()
