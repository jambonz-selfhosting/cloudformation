"""
SSH connection wrapper for remote command execution.

Adapted from the terraform testing framework for CloudFormation deployments.
"""

import paramiko
import logging
from typing import Tuple, Optional
from pathlib import Path


logger = logging.getLogger("jambonz-test")


class SSHError(Exception):
    """Raised when SSH operations fail."""
    pass


def run_ssh_command(
    host: str,
    command: str,
    ssh_config: dict,
    timeout: int = None
) -> Tuple[str, str, int]:
    """
    Execute a command on a remote host via SSH.

    Args:
        host: Hostname or IP address
        command: Command to execute
        ssh_config: SSH configuration dict with keys:
            - user: SSH username (default: 'jambonz')
            - key_path: Path to SSH private key
            - timeout: Command timeout in seconds (default: 300)
            - strict_host_key_checking: Whether to verify host keys (default: False)
        timeout: Command timeout in seconds (overrides ssh_config timeout)

    Returns:
        Tuple of (stdout, stderr, exit_code)

    Raises:
        SSHError: If SSH connection or command execution fails
    """
    if timeout is None:
        timeout = ssh_config.get('timeout', 300)

    user = ssh_config.get('user', 'jambonz')
    key_path = Path(ssh_config.get('key_path', '~/.ssh/id_rsa')).expanduser()
    strict_host_key_checking = ssh_config.get('strict_host_key_checking', False)

    if not key_path.exists():
        raise SSHError(f"SSH key not found: {key_path}")

    try:
        # Load SSH key
        private_key = paramiko.RSAKey.from_private_key_file(str(key_path))
    except Exception as e:
        raise SSHError(f"Failed to load SSH key from {key_path}: {e}")

    # Create SSH client
    client = paramiko.SSHClient()
    if not strict_host_key_checking:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.load_system_host_keys()

    try:
        # Direct connection
        logger.debug(f"Connecting to {host}")
        client.connect(
            hostname=host,
            username=user,
            pkey=private_key,
            timeout=30,
            banner_timeout=30
        )

        # Execute command
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        stdout_str = stdout.read().decode('utf-8')
        stderr_str = stderr.read().decode('utf-8')

        logger.debug(f"Command executed on {host}, exit code: {exit_code}")
        return stdout_str, stderr_str, exit_code

    except paramiko.AuthenticationException:
        raise SSHError(f"Authentication failed for {user}@{host}")
    except paramiko.SSHException as e:
        raise SSHError(f"SSH error connecting to {host}: {e}")
    except Exception as e:
        raise SSHError(f"Failed to execute command on {host}: {e}")
    finally:
        client.close()


def test_ssh_connectivity(host: str, ssh_config: dict) -> bool:
    """
    Test SSH connectivity to a host.

    Args:
        host: Hostname or IP address
        ssh_config: SSH configuration dict

    Returns:
        True if connection successful

    Raises:
        SSHError: If connection fails
    """
    try:
        stdout, stderr, exit_code = run_ssh_command(
            host=host,
            command="echo 'SSH connectivity test'",
            ssh_config=ssh_config,
            timeout=30
        )
        return exit_code == 0
    except SSHError:
        raise


def check_cloud_init_status(host: str, ssh_config: dict) -> Tuple[bool, str]:
    """
    Check if cloud-init has completed on the instance.

    Args:
        host: Hostname or IP address
        ssh_config: SSH configuration dict

    Returns:
        Tuple of (success, message)

    Raises:
        SSHError: If SSH connection fails
    """
    logger.debug(f"Checking cloud-init status on {host}")

    try:
        stdout, stderr, exit_code = run_ssh_command(
            host=host,
            command="sudo cloud-init status",
            ssh_config=ssh_config,
            timeout=60
        )

        if "status: done" in stdout.lower():
            return True, "cloud-init completed successfully"

        if "status: running" in stdout.lower():
            return False, "cloud-init still running"

        if "status: error" in stdout.lower():
            return False, f"cloud-init failed: {stdout.strip()}"

        return False, f"cloud-init status unknown: {stdout.strip()}"

    except SSHError as e:
        raise SSHError(f"Failed to check cloud-init status: {e}")


def check_systemd_service(
    host: str,
    service: str,
    ssh_config: dict
) -> Tuple[bool, str]:
    """
    Check if a systemd service is active.

    Args:
        host: Hostname or IP address
        service: Service name
        ssh_config: SSH configuration dict

    Returns:
        Tuple of (is_active, status_string)

    Raises:
        SSHError: If SSH connection fails
    """
    try:
        stdout, stderr, exit_code = run_ssh_command(
            host=host,
            command=f"systemctl is-active {service}",
            ssh_config=ssh_config,
            timeout=10
        )

        status = stdout.strip()
        is_active = (status == "active")

        return is_active, status

    except SSHError as e:
        raise SSHError(f"Failed to check service {service}: {e}")


def get_pm2_processes(host: str, ssh_config: dict) -> list:
    """
    Get list of PM2 processes running on the instance.

    Args:
        host: Hostname or IP address
        ssh_config: SSH configuration dict

    Returns:
        List of dicts with keys: name, status, cpu, memory

    Raises:
        SSHError: If SSH connection fails
    """
    import json as json_module

    logger.debug(f"Getting PM2 processes from {host}")

    try:
        stdout, stderr, exit_code = run_ssh_command(
            host=host,
            command="pm2 jlist",
            ssh_config=ssh_config,
            timeout=30
        )

        if exit_code != 0:
            logger.warning(f"PM2 jlist failed, trying pm2 list: {stderr}")
            # Try regular list command as fallback
            stdout, stderr, exit_code = run_ssh_command(
                host=host,
                command="pm2 list",
                ssh_config=ssh_config,
                timeout=30
            )
            return _parse_pm2_table(stdout)

        # Parse JSON output
        try:
            pm2_data = json_module.loads(stdout)
            processes = []
            for proc in pm2_data:
                processes.append({
                    'name': proc.get('name', 'unknown'),
                    'status': proc.get('pm2_env', {}).get('status', 'unknown'),
                    'cpu': f"{proc.get('monit', {}).get('cpu', 0)}%",
                    'memory': _format_memory(proc.get('monit', {}).get('memory', 0))
                })
            return processes
        except json_module.JSONDecodeError:
            return _parse_pm2_table(stdout)

    except SSHError as e:
        raise SSHError(f"Failed to get PM2 processes: {e}")


def _parse_pm2_table(output: str) -> list:
    """
    Parse PM2 list table format output.

    Args:
        output: PM2 list command output

    Returns:
        List of process dicts
    """
    processes = []
    lines = output.split('\n')

    for line in lines:
        if not line.strip():
            continue

        # Skip header and separator lines
        if '┌' in line or '├' in line or '└' in line or 'App name' in line:
            continue

        # Look for data lines with │ separator
        if '│' in line:
            parts = [p.strip() for p in line.split('│') if p.strip()]

            if len(parts) >= 2:
                processes.append({
                    'name': parts[0] if len(parts) > 0 else 'unknown',
                    'status': parts[1] if len(parts) > 1 else 'unknown',
                    'cpu': parts[4] if len(parts) > 4 else 'N/A',
                    'memory': parts[5] if len(parts) > 5 else 'N/A'
                })

    return processes


def _format_memory(bytes_value: int) -> str:
    """Format memory from bytes to human-readable format."""
    if not bytes_value:
        return "N/A"

    if bytes_value < 1024:
        return f"{bytes_value}B"
    elif bytes_value < 1024 * 1024:
        return f"{bytes_value / 1024:.1f}KB"
    elif bytes_value < 1024 * 1024 * 1024:
        return f"{bytes_value / (1024 * 1024):.1f}MB"
    else:
        return f"{bytes_value / (1024 * 1024 * 1024):.1f}GB"
