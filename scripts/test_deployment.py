#!/usr/bin/env python3
"""
Deployment testing script for Jambonz CloudFormation deployments.

Tests deployed instances to verify cloud-init completed successfully
and all services are running.

Usage:
    # Test a deployment
    python test_deployment.py --stack-name jambonz-mini --region ap-southeast-2

    # Test with custom SSH key
    python test_deployment.py --stack-name jambonz-mini --region us-east-1 \
        --ssh-key ~/.ssh/my-key.pem
"""

import sys
import os
import logging
import time
import click
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

from cf_helper import (
    get_stack_outputs,
    detect_deployment_type,
    get_server_instances,
    CFError
)
from ssh_helper import (
    test_ssh_connectivity,
    check_cloud_init_status,
    check_systemd_service,
    get_pm2_processes,
    SSHError
)


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(message)s'
    )
    return logging.getLogger("jambonz-test")


def load_server_types() -> dict:
    """Load server type definitions from YAML."""
    server_types_path = Path(__file__).parent / "server_types.yaml"
    if server_types_path.exists():
        with open(server_types_path) as f:
            return yaml.safe_load(f)
    return {}


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
    '--verbose', '-v',
    is_flag=True,
    help='Enable verbose output'
)
@click.option(
    '--wait-for-cloud-init',
    is_flag=True,
    help='Wait for cloud-init to complete (with retries)'
)
@click.option(
    '--cloud-init-timeout',
    default=300,
    help='Cloud-init wait timeout in seconds (default: 300)'
)
def test_server(
    server_ip: str,
    role: str,
    ssh_config: dict,
    server_types_config: dict,
    wait_for_cloud_init: bool,
    cloud_init_timeout: int,
    verbose: bool
) -> dict:
    """
    Test a single server instance.

    Args:
        server_ip: IP address of the server
        role: Server role (mini, sbc, web-monitoring, etc.)
        ssh_config: SSH configuration
        server_types_config: Server types configuration
        wait_for_cloud_init: Whether to wait for cloud-init
        cloud_init_timeout: cloud-init timeout in seconds
        verbose: Enable verbose output

    Returns:
        Results dictionary with test outcomes
    """
    results = {
        'ssh_connectivity': False,
        'cloud_init': False,
        'systemd_services': {},
        'pm2_processes': [],
        'all_services_ok': True,
        'all_pm2_ok': True
    }

    # Get expected services for this role
    role_config = server_types_config.get('server_types', {}).get(role, {})
    expected_services = role_config.get('systemd_services', [])
    expected_pm2 = role_config.get('pm2_processes', [])
    optional_services = server_types_config.get('optional_services', {}).get('systemd', [])

    # Test SSH connectivity
    print(f"  Testing SSH connectivity...")
    try:
        test_ssh_connectivity(server_ip, ssh_config)
        results['ssh_connectivity'] = True
        print(f"    SSH connection successful")
    except SSHError as e:
        print(f"    ERROR: {e}")
        return results  # Can't continue without SSH

    # Check cloud-init status
    print(f"  Checking cloud-init status...")
    try:
        if wait_for_cloud_init:
            start_time = time.time()
            cloud_init_done = False

            while time.time() - start_time < cloud_init_timeout:
                success, message = check_cloud_init_status(server_ip, ssh_config)
                if success:
                    cloud_init_done = True
                    break
                elif "still running" in message:
                    elapsed = int(time.time() - start_time)
                    print(f"    cloud-init still running... ({elapsed}s elapsed)")
                    time.sleep(15)
                else:
                    print(f"    WARNING: {message}")
                    break

            if cloud_init_done:
                results['cloud_init'] = True
                print(f"    cloud-init completed successfully")
            else:
                print(f"    ERROR: cloud-init did not complete within {cloud_init_timeout}s")
        else:
            success, message = check_cloud_init_status(server_ip, ssh_config)
            results['cloud_init'] = success
            if success:
                print(f"    cloud-init completed successfully")
            else:
                print(f"    WARNING: {message}")
    except SSHError as e:
        print(f"    ERROR: {e}")

    # Check systemd services
    if expected_services:
        print(f"  Checking systemd services...")
        for service in expected_services:
            try:
                is_active, status = check_systemd_service(server_ip, service, ssh_config)
                results['systemd_services'][service] = is_active

                if is_active:
                    print(f"    {service}: active")
                else:
                    if service in optional_services:
                        print(f"    {service}: {status} (optional)")
                    else:
                        print(f"    {service}: {status} (FAILED)")
                        results['all_services_ok'] = False
            except SSHError as e:
                print(f"    {service}: ERROR - {e}")
                results['systemd_services'][service] = False
                if service not in optional_services:
                    results['all_services_ok'] = False
    else:
        print(f"  No systemd services expected for this role")

    # Check PM2 processes
    if expected_pm2:
        print(f"  Checking PM2 processes...")
        try:
            processes = get_pm2_processes(server_ip, ssh_config)
            results['pm2_processes'] = processes

            if not processes:
                print("    WARNING: No PM2 processes found")
                results['all_pm2_ok'] = False
            else:
                for proc in processes:
                    status_icon = "ONLINE" if proc['status'] == 'online' else proc['status'].upper()
                    print(f"    {proc['name']}: {status_icon}")
                    if proc['status'] != 'online':
                        results['all_pm2_ok'] = False

                # Check for missing expected processes
                process_names = [p['name'] for p in processes]
                missing = [p for p in expected_pm2 if p not in process_names]
                if missing:
                    print(f"    WARNING: Missing expected: {', '.join(missing)}")
                    results['all_pm2_ok'] = False

        except SSHError as e:
            print(f"    ERROR: {e}")
            results['all_pm2_ok'] = False
    else:
        print(f"  No PM2 processes expected for this role")

    return results


def main(stack_name, region, ssh_key, ssh_user, verbose, wait_for_cloud_init, cloud_init_timeout):
    """
    Test a Jambonz CloudFormation deployment.

    Verifies:
    1. CloudFormation stack outputs are available
    2. SSH connectivity to all servers
    3. cloud-init completed successfully on all servers
    4. Systemd services are running on appropriate servers
    5. PM2 processes are online on appropriate servers
    """
    # Load environment from .env file
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    logger = setup_logging(verbose)
    server_types_config = load_server_types()

    # Build SSH config
    ssh_config = {
        'user': ssh_user or os.getenv('SSH_USER', 'jambonz'),
        'key_path': ssh_key or os.getenv('SSH_KEY_PATH', '~/.ssh/id_rsa'),
        'timeout': 300,
        'strict_host_key_checking': False
    }

    print("=" * 60)
    print("Jambonz CloudFormation Deployment Test")
    print("=" * 60)
    print()
    print(f"Stack: {stack_name}")
    print(f"Region: {region}")
    print(f"SSH User: {ssh_config['user']}")
    print(f"SSH Key: {ssh_config['key_path']}")
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

    except CFError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 2: Detect deployment type
    print("[Step 2] Detecting deployment type...")
    deployment_type = detect_deployment_type(outputs)
    print(f"  Deployment type: {deployment_type}")
    print()

    # Step 3: Get server instances
    print("[Step 3] Discovering server instances...")
    instances = get_server_instances(outputs, deployment_type)

    if not instances:
        print("  ERROR: No server instances found in stack outputs")
        print(f"  Available outputs: {list(outputs.keys())}")
        sys.exit(1)

    print(f"  Found {len(instances)} server(s):")
    for instance in instances:
        print(f"    - {instance['role']}: {instance['ip']}")
    print()

    # Step 4: Test each server
    all_results = {}
    for instance in instances:
        role = instance['role']
        ip = instance['ip']

        print("-" * 60)
        print(f"[Testing {role} @ {ip}]")
        print("-" * 60)

        results = test_server(
            server_ip=ip,
            role=role,
            ssh_config=ssh_config,
            server_types_config=server_types_config,
            wait_for_cloud_init=wait_for_cloud_init,
            cloud_init_timeout=cloud_init_timeout,
            verbose=verbose
        )
        all_results[role] = {
            'ip': ip,
            'results': results
        }
        print()

    # Summary
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    print()

    total_passed = 0
    total_failed = 0

    for role, data in all_results.items():
        ip = data['ip']
        results = data['results']

        print(f"  [{role} @ {ip}]")

        passed = 0
        failed = 0

        # SSH connectivity
        if results['ssh_connectivity']:
            print(f"    SSH connectivity: PASS")
            passed += 1
        else:
            print(f"    SSH connectivity: FAIL")
            failed += 1

        # cloud-init
        if results['cloud_init']:
            print(f"    cloud-init: PASS")
            passed += 1
        else:
            print(f"    cloud-init: FAIL")
            failed += 1

        # Systemd services
        if results['systemd_services']:
            active_services = sum(1 for v in results['systemd_services'].values() if v)
            total_services = len(results['systemd_services'])
            if results['all_services_ok']:
                print(f"    systemd services: PASS ({active_services}/{total_services} active)")
                passed += 1
            else:
                print(f"    systemd services: FAIL ({active_services}/{total_services} active)")
                failed += 1
        else:
            print(f"    systemd services: N/A (none expected)")

        # PM2 processes
        role_config = server_types_config.get('server_types', {}).get(role, {})
        expected_pm2 = role_config.get('pm2_processes', [])
        if expected_pm2:
            online_pm2 = sum(1 for p in results['pm2_processes'] if p.get('status') == 'online')
            total_pm2 = len(results['pm2_processes'])
            if results['all_pm2_ok'] and total_pm2 > 0:
                print(f"    PM2 processes: PASS ({online_pm2}/{total_pm2} online)")
                passed += 1
            else:
                print(f"    PM2 processes: FAIL ({online_pm2}/{total_pm2} online)")
                failed += 1
        else:
            print(f"    PM2 processes: N/A (none expected)")

        total_passed += passed
        total_failed += failed
        print()

    print(f"Total: {total_passed} passed, {total_failed} failed")
    print()

    # Print connection info on success
    if total_failed == 0:
        print("=" * 60)
        print("Deployment Ready!")
        print("=" * 60)
        print()

        # Show server IPs
        for role, data in all_results.items():
            print(f"  {role}: {data['ip']}")

        if portal_url:
            print()
            print(f"Portal: http://{portal_url}")
        if password:
            print(f"Admin Password: {password}")
        print()
        print("Next steps:")
        print("  1. Run post_install.py to configure DNS and TLS")
        print("  2. Access the portal and complete setup")
        print()

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == '__main__':
    main()
