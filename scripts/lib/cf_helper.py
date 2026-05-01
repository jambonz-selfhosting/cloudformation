"""
CloudFormation helper for parsing stack outputs.

Provides utilities to retrieve and parse CloudFormation stack outputs
for deployed jambonz instances.
"""

import json
import subprocess
import logging
from typing import Dict, List, Optional


logger = logging.getLogger("jambonz-test")


class CFError(Exception):
    """Raised when CloudFormation operations fail."""
    pass


def get_stack_outputs(stack_name: str, region: str) -> Dict[str, str]:
    """
    Get outputs from a CloudFormation stack.

    Args:
        stack_name: Name of the CloudFormation stack
        region: AWS region where the stack is deployed

    Returns:
        Dictionary with output keys and values:
        {
            'server_ip': '1.2.3.4',
            'portal_url': 'mini.jambonz.io',
            'password': 'abc123',
            'grafana_url': 'grafana.mini.jambonz.io',
            'homer_url': 'homer.mini.jambonz.io'
        }

    Raises:
        CFError: If stack outputs cannot be retrieved
    """
    logger.debug(f"Getting outputs for stack '{stack_name}' in region '{region}'")

    try:
        result = subprocess.run(
            [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].Outputs",
                "--output", "json"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            if "does not exist" in error_msg:
                raise CFError(f"Stack '{stack_name}' not found in region '{region}'")
            raise CFError(f"Failed to get stack outputs: {error_msg}")

        # Parse JSON output
        outputs_raw = json.loads(result.stdout)

        if outputs_raw is None:
            raise CFError(f"Stack '{stack_name}' has no outputs")

        # Convert to simple key-value dict
        outputs = {}
        for output in outputs_raw:
            key = output.get('OutputKey', '')
            value = output.get('OutputValue', '')

            # Normalize common output keys
            normalized_key = _normalize_output_key(key)
            outputs[normalized_key] = value

            # Also keep original key for compatibility
            if normalized_key != key:
                outputs[key] = value

        logger.debug(f"Retrieved {len(outputs)} outputs from stack")
        return outputs

    except subprocess.TimeoutExpired:
        raise CFError("AWS CLI command timed out")
    except json.JSONDecodeError as e:
        raise CFError(f"Failed to parse CloudFormation output: {e}")
    except FileNotFoundError:
        raise CFError("AWS CLI not found. Please install the AWS CLI.")


def _normalize_output_key(key: str) -> str:
    """
    Normalize CloudFormation output key names to standard format.

    CloudFormation outputs may use various naming conventions.
    This normalizes them to a consistent format.

    Args:
        key: Original output key

    Returns:
        Normalized key name
    """
    # Convert to lowercase for comparison
    key_lower = key.lower()

    # Map common CloudFormation output names to standard names
    mappings = {
        # Mini deployment - all-in-one server
        'serverip': 'server_ip',
        'server_ip': 'server_ip',
        'publicip': 'server_ip',
        'public_ip': 'server_ip',
        'instanceip': 'server_ip',
        'instance_ip': 'server_ip',
        'elasticip': 'server_ip',
        'elastic_ip': 'server_ip',

        # Medium deployment - SBC and Web servers
        'sbcserverip': 'sbc_server_ip',
        'sbc_server_ip': 'sbc_server_ip',
        'sbcip': 'sbc_server_ip',
        'sbc_ip': 'sbc_server_ip',

        'webserverip': 'web_server_ip',
        'web_server_ip': 'web_server_ip',
        'webip': 'web_server_ip',
        'web_ip': 'web_server_ip',

        # Large deployment - SIP, RTP, Web, Monitoring servers
        'sipserverip': 'sip_server_ip',
        'sip_server_ip': 'sip_server_ip',
        'sipip': 'sip_server_ip',
        'sip_ip': 'sip_server_ip',

        'rtpserverip': 'rtp_server_ip',
        'rtp_server_ip': 'rtp_server_ip',
        'rtpip': 'rtp_server_ip',
        'rtp_ip': 'rtp_server_ip',

        'monitoringserverip': 'monitoring_server_ip',
        'monitoring_server_ip': 'monitoring_server_ip',
        'monitoringip': 'monitoring_server_ip',
        'monitoring_ip': 'monitoring_server_ip',

        # Feature server (medium/large deployments)
        'featureserverip': 'feature_server_ip',
        'feature_server_ip': 'feature_server_ip',
        'fsip': 'feature_server_ip',
        'fs_ip': 'feature_server_ip',

        # Portal and other URLs
        'portalurl': 'portal_url',
        'portal_url': 'portal_url',
        'urlportal': 'portal_url',
        'url_portal': 'portal_url',

        'password': 'password',
        'adminpassword': 'password',
        'admin_password': 'password',

        'grafanaurl': 'grafana_url',
        'grafana_url': 'grafana_url',

        'homerurl': 'homer_url',
        'homer_url': 'homer_url',
    }

    return mappings.get(key_lower, key)


def get_stack_status(stack_name: str, region: str) -> str:
    """
    Get the current status of a CloudFormation stack.

    Args:
        stack_name: Name of the CloudFormation stack
        region: AWS region

    Returns:
        Stack status string (e.g., 'CREATE_COMPLETE', 'UPDATE_IN_PROGRESS')

    Raises:
        CFError: If status cannot be retrieved
    """
    try:
        result = subprocess.run(
            [
                "aws", "cloudformation", "describe-stacks",
                "--stack-name", stack_name,
                "--region", region,
                "--query", "Stacks[0].StackStatus",
                "--output", "text"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            raise CFError(f"Failed to get stack status: {error_msg}")

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        raise CFError("AWS CLI command timed out")


def wait_for_stack_complete(
    stack_name: str,
    region: str,
    timeout: int = 600
) -> bool:
    """
    Wait for a CloudFormation stack to reach a complete state.

    Args:
        stack_name: Name of the CloudFormation stack
        region: AWS region
        timeout: Maximum wait time in seconds

    Returns:
        True if stack reached a complete state

    Raises:
        CFError: If stack fails or timeout is reached
    """
    import time

    start_time = time.time()
    complete_states = ['CREATE_COMPLETE', 'UPDATE_COMPLETE']
    failed_states = ['CREATE_FAILED', 'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED',
                     'DELETE_FAILED', 'UPDATE_ROLLBACK_COMPLETE']

    logger.info(f"Waiting for stack '{stack_name}' to complete...")

    while time.time() - start_time < timeout:
        status = get_stack_status(stack_name, region)
        logger.debug(f"Stack status: {status}")

        if status in complete_states:
            logger.info(f"Stack '{stack_name}' is {status}")
            return True

        if status in failed_states:
            raise CFError(f"Stack '{stack_name}' failed with status: {status}")

        time.sleep(10)

    raise CFError(f"Timeout waiting for stack '{stack_name}' to complete")


def detect_deployment_type(outputs: Dict[str, str]) -> str:
    """
    Detect the deployment type from CloudFormation outputs.

    CloudFormation outputs differ by deployment type:
    - mini: ServerIP (all-in-one)
    - medium: SbcServerIP, WebServerIP
    - large: SipServerIP, RtpServerIP, WebServerIP

    Args:
        outputs: Dictionary of CloudFormation stack outputs (normalized keys)

    Returns:
        Deployment type: 'mini', 'medium', or 'large'
    """
    # Large deployment has separate SIP and RTP servers
    if 'sip_server_ip' in outputs or 'rtp_server_ip' in outputs:
        return 'large'
    # Medium deployment has SBC server
    elif 'sbc_server_ip' in outputs:
        return 'medium'
    # Mini deployment has single server
    else:
        return 'mini'


def get_server_instances(outputs: Dict[str, str], deployment_type: str) -> List[Dict]:
    """
    Get list of server instances for a deployment.

    Returns a list of server dictionaries with role, IP, and optional jump host.

    Args:
        outputs: Dictionary of CloudFormation stack outputs (normalized keys)
        deployment_type: Deployment type ('mini', 'medium', 'large')

    Returns:
        List of server instance dictionaries:
        [
            {'role': 'mini', 'ip': '1.2.3.4', 'jump_host': None},
            ...
        ]
    """
    instances = []

    if deployment_type == 'mini':
        if outputs.get('server_ip'):
            instances.append({
                'role': 'mini',
                'ip': outputs.get('server_ip'),
                'jump_host': None
            })

    elif deployment_type == 'medium':
        if outputs.get('sbc_server_ip'):
            instances.append({
                'role': 'sbc',
                'ip': outputs.get('sbc_server_ip'),
                'jump_host': None
            })
        if outputs.get('web_server_ip'):
            instances.append({
                'role': 'web-monitoring',
                'ip': outputs.get('web_server_ip'),
                'jump_host': None
            })
        # Feature servers if present (auto-scaling group instances)
        if outputs.get('feature_server_ip'):
            instances.append({
                'role': 'feature-server',
                'ip': outputs.get('feature_server_ip'),
                'jump_host': None
            })

    elif deployment_type == 'large':
        if outputs.get('sip_server_ip'):
            instances.append({
                'role': 'sip',
                'ip': outputs.get('sip_server_ip'),
                'jump_host': None
            })
        if outputs.get('rtp_server_ip'):
            instances.append({
                'role': 'rtp',
                'ip': outputs.get('rtp_server_ip'),
                'jump_host': None
            })
        if outputs.get('web_server_ip'):
            instances.append({
                'role': 'web',
                'ip': outputs.get('web_server_ip'),
                'jump_host': None
            })
        if outputs.get('monitoring_server_ip'):
            instances.append({
                'role': 'monitoring',
                'ip': outputs.get('monitoring_server_ip'),
                'jump_host': None
            })
        # Feature servers if present
        if outputs.get('feature_server_ip'):
            instances.append({
                'role': 'feature-server',
                'ip': outputs.get('feature_server_ip'),
                'jump_host': None
            })

    return instances


def get_web_server_ip(outputs: Dict[str, str], deployment_type: str) -> Optional[str]:
    """
    Get the IP of the server that hosts the portal/webapp.

    Args:
        outputs: Dictionary of CloudFormation stack outputs
        deployment_type: Deployment type ('mini', 'medium', 'large')

    Returns:
        IP address of the web server, or None if not found
    """
    if deployment_type == 'mini':
        return outputs.get('server_ip')
    else:  # medium or large
        return outputs.get('web_server_ip')


def get_sip_server_ip(outputs: Dict[str, str], deployment_type: str) -> Optional[str]:
    """
    Get the IP for SIP DNS record.

    Args:
        outputs: Dictionary of CloudFormation stack outputs
        deployment_type: Deployment type ('mini', 'medium', 'large')

    Returns:
        IP address of the SIP server, or None if not found
    """
    if deployment_type == 'mini':
        return outputs.get('server_ip')
    elif deployment_type == 'medium':
        return outputs.get('sbc_server_ip')
    else:  # large
        return outputs.get('sip_server_ip')
