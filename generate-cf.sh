#!/usr/bin/env bash

# generate-cf.sh
# Script to copy jambonz public AMIs to user's AWS account and generate CloudFormation template
# Usage: ./generate-cf.sh
# Requires: bash 4+ for associative arrays

set -e

# Color codes disabled for better readability
RED=''
GREEN=''
YELLOW=''
BLUE=''
NC=''

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# Backup Function
# ============================================================

# Creates a numbered backup of a file if it exists
# Usage: backup_file_if_exists "/path/to/file.yaml"
backup_file_if_exists() {
    local file="$1"

    if [ ! -f "$file" ]; then
        return 0  # No backup needed if file doesn't exist
    fi

    # Find the next available backup number
    local backup_num=1
    while [ -f "${file}.backup.${backup_num}" ]; do
        backup_num=$((backup_num + 1))
    done

    local backup_path="${file}.backup.${backup_num}"

    echo "  Existing template found. Creating backup..."
    cp "$file" "$backup_path"
    echo "  ✓ Backup created: $backup_path"
    echo ""
}

# ============================================================
# Pre-flight Checks
# ============================================================

echo "================================================"
echo "jambonz CloudFormation Generator"
echo "================================================"
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "ERROR: AWS CLI not found"
    echo ""
    echo "Please install the AWS CLI:"
    echo "  https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    echo ""
    echo "Installation instructions:"
    echo "  macOS:   brew install awscli"
    echo "  Linux:   curl 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o 'awscliv2.zip' && unzip awscliv2.zip && sudo ./aws/install"
    echo "  Windows: https://awscli.amazonaws.com/AWSCLIV2.msi"
    exit 1
fi

# Check if yq is installed (for parsing YAML)
if ! command -v yq &> /dev/null; then
    echo "ERROR: yq not found"
    echo ""
    echo "This script requires yq to parse YAML files."
    echo "Please install yq:"
    echo "  https://github.com/mikefarah/yq#install"
    echo ""
    echo "Installation instructions:"
    echo "  macOS:   brew install yq"
    echo "  Linux:   wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/local/bin/yq && chmod +x /usr/local/bin/yq"
    exit 1
fi

# Check if AWS credentials are configured
echo "Checking AWS credentials..."
if ! CALLER_IDENTITY=$(aws sts get-caller-identity 2>&1); then
    echo "ERROR: AWS credentials not configured or invalid"
    echo ""
    echo "Please configure your AWS credentials:"
    echo "  Run: aws configure"
    echo ""
    echo "You'll need:"
    echo "  - AWS Access Key ID"
    echo "  - AWS Secret Access Key"
    echo "  - Default region (e.g., us-east-1)"
    echo ""
    echo "Error details:"
    echo "$CALLER_IDENTITY"
    exit 1
fi

ACCOUNT_ID=$(echo "$CALLER_IDENTITY" | yq -p json '.Account')
USER_ARN=$(echo "$CALLER_IDENTITY" | yq -p json '.Arn')

echo "✓ Authenticated successfully"
echo "  Account ID: $ACCOUNT_ID"
echo "  User/Role:  $USER_ARN"
echo ""

# ============================================================
# User Input
# ============================================================

# Deployment size
echo "Select deployment size:"
echo "  1) mini   - Single EC2 instance with all components"
echo "  2) medium - Multi-tier deployment (SBC, Feature Server, Web/Monitoring, Recording)"
echo "  3) large  - Fully separated architecture (SBC SIP, SBC RTP, FS, Web, Monitoring, Recording)"
echo ""
read -p "Enter choice [1-3]: " SIZE_CHOICE

case $SIZE_CHOICE in
    1) SIZE="mini" ;;
    2) SIZE="medium" ;;
    3) SIZE="large" ;;
    *)
        echo "Invalid choice. Please run the script again."
        exit 1
        ;;
esac

echo "Selected: $SIZE"
echo ""

# Read available regions from mapping files
AMI_MAPPINGS_FILE="$SCRIPT_DIR/mappings/ami-mappings.yaml"
INSTANCE_TYPE_MAPPINGS_FILE="$SCRIPT_DIR/mappings/instance-type-defaults.yaml"

if [ ! -f "$AMI_MAPPINGS_FILE" ]; then
    echo "ERROR: Cannot find ami-mappings.yaml at $AMI_MAPPINGS_FILE"
    exit 1
fi

if [ ! -f "$INSTANCE_TYPE_MAPPINGS_FILE" ]; then
    echo "ERROR: Cannot find instance-type-defaults.yaml at $INSTANCE_TYPE_MAPPINGS_FILE"
    exit 1
fi

AVAILABLE_REGIONS=$(yq eval ".${SIZE} | keys | .[]" "$AMI_MAPPINGS_FILE")

# AWS Region
echo "Select AWS region:"
echo "Available regions:"
echo "$AVAILABLE_REGIONS" | nl
echo ""
read -p "Enter region name (e.g., us-east-1): " REGION

# Validate region
if ! echo "$AVAILABLE_REGIONS" | grep -q "^${REGION}$"; then
    echo "ERROR: Region '$REGION' not found in supported regions."
    echo "Supported regions for $SIZE deployment:"
    echo "$AVAILABLE_REGIONS"
    exit 1
fi

echo "Selected region: $REGION"
echo ""

# ============================================================
# AMI Discovery
# ============================================================

echo "================================================"
echo "Reading public AMI IDs from mappings..."
echo "================================================"
echo ""

# Determine AMI types based on deployment size
case $SIZE in
    mini)
        AMI_TYPES=("MiniAmi")
        ;;
    medium)
        AMI_TYPES=("SbcAmi" "FsAmi" "WebMonitoringAmi" "RecordingServerAmi")
        ;;
    large)
        AMI_TYPES=("SbcSipAmi" "SbcRtpAmi" "FsAmi" "WebserverAmi" "MonitoringServerAmi" "RecordingServerAmi")
        ;;
esac

# Read public AMI IDs and query JambonzVersion tag
# Using indexed arrays for bash 3.2 compatibility
PUBLIC_AMIS=()
NEW_AMI_IDS=()
AMI_VERSIONS=()

echo ""
echo "Querying version information from public AMIs..."
echo "This will take a moment - querying ${#AMI_TYPES[@]} AMI(s)..."
echo ""
JAMBONZ_VERSION=""

for AMI_TYPE in "${AMI_TYPES[@]}"; do
    AMI_ID=$(yq eval ".${SIZE}.${REGION}.${AMI_TYPE}" "$AMI_MAPPINGS_FILE")
    if [ "$AMI_ID" = "null" ] || [ -z "$AMI_ID" ]; then
        echo "ERROR: Cannot find $AMI_TYPE for $SIZE in region $REGION"
        exit 1
    fi
    PUBLIC_AMIS+=("$AMI_ID")

    # Query Name field from the public AMI and parse version
    echo "  Querying AMI name for $AMI_TYPE ($AMI_ID)..."
    AMI_NAME=$(aws ec2 describe-images \
        --region "$REGION" \
        --image-ids "$AMI_ID" \
        --query 'Images[0].Name' \
        --output text 2>&1)

    if [ $? -ne 0 ] || [ -z "$AMI_NAME" ] || [ "$AMI_NAME" = "None" ]; then
        echo "    ✗ ERROR: Could not retrieve AMI name"
        echo ""
        echo "ERROR: AMI $AMI_ID ($AMI_TYPE) does not have a Name field"
        echo ""
        echo "This means the AMI may not be properly configured in region $REGION."
        echo ""
        echo "You can check the AMI with:"
        echo "  aws ec2 describe-images --region $REGION --image-ids $AMI_ID --query 'Images[0].Name'"
        echo ""
        exit 1
    fi

    # Parse version from AMI name using sed (portable across Linux/macOS)
    # Expected format: jambonz-{variant}-v{VERSION}-{os}-{timestamp}
    # Example: jambonz-sip-v10.0.2-debian-12-20260116213122
    VERSION_TAG=$(echo "$AMI_NAME" | sed -n 's/.*\(v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p')

    if [ -z "$VERSION_TAG" ]; then
        echo "    ✗ ERROR: Could not parse version from AMI name"
        echo ""
        echo "ERROR: AMI $AMI_ID ($AMI_TYPE) has unexpected name format: $AMI_NAME"
        echo ""
        echo "Expected format: jambonz-{variant}-v{VERSION}-{os}-{timestamp}"
        echo "Example: jambonz-sip-v10.0.2-debian-12-20260116213122"
        echo ""
        exit 1
    fi

    AMI_VERSIONS+=("$VERSION_TAG")

    # Use the first AMI's version as the canonical version for this deployment
    if [ -z "$JAMBONZ_VERSION" ]; then
        JAMBONZ_VERSION=$VERSION_TAG
    fi

    echo "    ✓ $AMI_TYPE: $AMI_ID (name: $AMI_NAME, version: $VERSION_TAG)"
done

echo ""
echo "✓ All AMIs verified with proper version information"
echo "Detected jambonz version: $JAMBONZ_VERSION"
echo ""

# ============================================================
# Validate Source AMI Availability
# ============================================================

echo "================================================"
echo "Validating source AMI availability..."
echo "================================================"
echo ""
echo "Checking that all source AMIs are ready to be copied..."
echo ""

ALL_AVAILABLE=true
INDEX=0
for AMI_TYPE in "${AMI_TYPES[@]}"; do
    PUBLIC_AMI_ID="${PUBLIC_AMIS[$INDEX]}"

    echo "  Checking $AMI_TYPE ($PUBLIC_AMI_ID)..."

    STATE=$(aws ec2 describe-images \
        --region "$REGION" \
        --image-ids "$PUBLIC_AMI_ID" \
        --query 'Images[0].State' \
        --output text 2>&1)

    if [ "$STATE" != "available" ]; then
        ALL_AVAILABLE=false
        echo "    ✗ AMI is in '$STATE' state (must be 'available')"
    else
        echo "    ✓ AMI is available"
    fi

    INDEX=$((INDEX + 1))
done

echo ""

if [ "$ALL_AVAILABLE" != true ]; then
    # Build the AMI IDs list for the check command
    AMI_IDS_LIST=""
    for PUBLIC_AMI_ID in "${PUBLIC_AMIS[@]}"; do
        AMI_IDS_LIST+="$PUBLIC_AMI_ID "
    done

    echo "ERROR: One or more source AMIs are not yet available for copying"
    echo ""
    echo "Source AMIs must be in 'available' state before they can be copied."
    echo "The AMIs are likely still being created (in 'pending' state)."
    echo ""
    echo "Please wait for the AMI creation process to complete, then run this script again."
    echo ""
    echo "You can check AMI status with:"
    echo "  aws ec2 describe-images --region $REGION --image-ids $AMI_IDS_LIST --query 'Images[*].[ImageId,Name,State]' --output table"
    echo ""
    echo "Estimated wait time: AMI creation typically takes 10-30 minutes."
    exit 1
fi

echo "✓ All source AMIs are available and ready to copy"
echo ""

# ============================================================
# AMI Copy
# ============================================================

echo "================================================"
echo "Copying AMIs to your account..."
echo "================================================"
echo ""
echo "This will take 5-15 minutes for same-region copying. Please be patient."
echo ""
echo "Note: Keep this script running to automatically generate the CloudFormation template."
echo "Status updates every 30 seconds."
echo ""

START_TIME=$(date +%s)

# Initiate all AMI copies in parallel
echo "Initiating ${#AMI_TYPES[@]} AMI copy operation(s) in parallel..."
echo ""

INDEX=0
for AMI_TYPE in "${AMI_TYPES[@]}"; do
    PUBLIC_AMI_ID="${PUBLIC_AMIS[$INDEX]}"
    VERSION="${AMI_VERSIONS[$INDEX]}"
    AMI_NAME="jambonz-${SIZE}-${AMI_TYPE}-${VERSION}"

    echo "  Starting copy: $AMI_TYPE ($PUBLIC_AMI_ID) version $VERSION..."

    # Copy the AMI
    COPY_RESULT=$(aws ec2 copy-image \
        --region "$REGION" \
        --source-region "$REGION" \
        --source-image-id "$PUBLIC_AMI_ID" \
        --name "$AMI_NAME" \
        --description "Copied from public jambonz $VERSION AMI $PUBLIC_AMI_ID for self-hosting" \
        --output json 2>&1)

    COPY_EXIT_CODE=$?

    if [ $COPY_EXIT_CODE -ne 0 ]; then
        echo ""
        echo "ERROR: Failed to copy AMI $PUBLIC_AMI_ID ($AMI_TYPE)"
        echo ""
        echo "Error details:"
        echo "$COPY_RESULT"
        echo ""

        # Check if it's a pending AMI error
        if echo "$COPY_RESULT" | grep -qi "pending\|invalid.*state"; then
            echo "This error typically occurs when the source AMI is still being created."
            echo "Please verify the AMI state and try again once it's available."
            echo ""
        fi

        exit 1
    fi

    NEW_AMI_ID=$(echo "$COPY_RESULT" | yq -p json '.ImageId')
    NEW_AMI_IDS+=("$NEW_AMI_ID")

    echo "    ✓ Copy initiated: $NEW_AMI_ID"

    # Wait a moment for AMI to be available for tagging
    sleep 1

    # Tag the AMI - include the JambonzVersion tag
    echo "    Tagging AMI..."

    # Temporarily disable set -e for tagging command
    set +e
    TAG_RESULT=$(aws ec2 create-tags \
        --region "$REGION" \
        --resources "$NEW_AMI_ID" \
        --tags \
            Key=Name,Value="$AMI_NAME" \
            Key=ManagedBy,Value=jambonz-cloudformation \
            Key=SourceAMI,Value="$PUBLIC_AMI_ID" \
            Key=DeploymentSize,Value="$SIZE" \
            Key=JambonzVersion,Value="$VERSION" \
            Key=CreatedAt,Value="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        2>&1)
    TAG_EXIT_CODE=$?
    set -e

    if [ $TAG_EXIT_CODE -eq 0 ]; then
        echo "    ✓ AMI tagged successfully"
    else
        echo "    Warning: Failed to tag AMI (continuing anyway)"
        echo "    Error: $TAG_RESULT"
    fi

    INDEX=$((INDEX + 1))
done

echo ""
echo "✓ All ${#AMI_TYPES[@]} AMI copy operation(s) started in parallel"
echo ""

# Build the AMI IDs list for the check command
AMI_IDS_LIST=""
for NEW_AMI_ID in "${NEW_AMI_IDS[@]}"; do
    AMI_IDS_LIST+="$NEW_AMI_ID "
done

# ============================================================
# Wait for AMI copies to complete
# ============================================================

echo "================================================"
echo "Waiting for AMI copies to complete..."
echo "================================================"
echo ""
echo "Status updates every 30 seconds. This typically takes 5-15 minutes."
echo "Do not close this terminal or interrupt the script while AMI copies are in progress!"
echo "Tip: You can also check progress in another terminal:"
echo "  aws ec2 describe-images --region $REGION --image-ids $AMI_IDS_LIST --query 'Images[*].[ImageId,Name,State]' --output table"
echo ""

POLL_COUNT=0
MAX_WAIT_TIME=3600  # 1 hour max
COMPLETED_COUNT=0
TOTAL_AMIS=${#AMI_TYPES[@]}

while true; do
    ALL_AVAILABLE=true
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    ELAPSED_MIN=$((ELAPSED / 60))
    ELAPSED_SEC=$((ELAPSED % 60))

    if [ $ELAPSED -gt $MAX_WAIT_TIME ]; then
        echo "ERROR: Timeout waiting for AMI copies (waited ${ELAPSED_MIN}m ${ELAPSED_SEC}s)"
        echo "Please check AWS Console > EC2 > AMIs for status"
        echo ""
        echo "You can check AMI status with:"
        echo "  aws ec2 describe-images --region $REGION --image-ids $AMI_IDS_LIST"
        exit 1
    fi

    POLL_COUNT=$((POLL_COUNT + 1))
    COMPLETED_COUNT=0

    echo "[Check #${POLL_COUNT}] Elapsed: ${ELAPSED_MIN}m ${ELAPSED_SEC}s"

    INDEX=0
    for AMI_TYPE in "${AMI_TYPES[@]}"; do
        NEW_AMI_ID="${NEW_AMI_IDS[$INDEX]}"
        STATE=$(aws ec2 describe-images \
            --region "$REGION" \
            --image-ids "$NEW_AMI_ID" \
            --query 'Images[0].State' \
            --output text 2>&1)

        if [ "$STATE" != "available" ]; then
            ALL_AVAILABLE=false
            echo "  $AMI_TYPE ($NEW_AMI_ID): $STATE"
        else
            COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
            echo "  ✓ $AMI_TYPE ($NEW_AMI_ID): available"
        fi
        INDEX=$((INDEX + 1))
    done

    echo "  Progress: ${COMPLETED_COUNT}/${TOTAL_AMIS} AMIs ready"

    if [ "$ALL_AVAILABLE" = true ]; then
        echo ""
        echo "================================================"
        echo "✓ All ${TOTAL_AMIS} AMI(s) are now available!"
        echo "================================================"
        break
    fi

    echo ""
    sleep 30
done

TOTAL_TIME=$(($(date +%s) - START_TIME))
echo "Total time: ${TOTAL_TIME}s ($((TOTAL_TIME / 60))m $((TOTAL_TIME % 60))s)"
echo ""

# ============================================================
# CloudFormation Generation
# ============================================================

echo "================================================"
echo "Generating CloudFormation template..."
echo "================================================"
echo ""

BASE_TEMPLATE="$SCRIPT_DIR/$SIZE/_jambonz-base-template.yaml"
OUTPUT_TEMPLATE="$SCRIPT_DIR/jambonz-${SIZE}-${REGION}.yaml"

if [ ! -f "$BASE_TEMPLATE" ]; then
    echo "ERROR: Cannot find base template at $BASE_TEMPLATE"
    exit 1
fi

# Create Mappings section
MAPPINGS="Mappings:\n"
MAPPINGS+="  AWSRegion2AMI:\n"
MAPPINGS+="    ${REGION}:\n"

INDEX=0
for AMI_TYPE in "${AMI_TYPES[@]}"; do
    NEW_AMI_ID="${NEW_AMI_IDS[$INDEX]}"
    MAPPINGS+="      ${AMI_TYPE}: ${NEW_AMI_ID}\n"
    INDEX=$((INDEX + 1))
done

MAPPINGS+="\n  RegionInstanceTypeDefaults:\n"
MAPPINGS+="    ${REGION}:\n"

# Read instance type defaults based on size
INSTANCE_TYPE_SECTION="instance-types-${SIZE}"
INSTANCE_TYPES=$(yq eval ".${INSTANCE_TYPE_SECTION}.${REGION}" "$INSTANCE_TYPE_MAPPINGS_FILE" -o json)

if [ "$INSTANCE_TYPES" = "null" ] || [ -z "$INSTANCE_TYPES" ]; then
    echo "ERROR: Cannot find instance type defaults for $SIZE in region $REGION"
    exit 1
fi

# Convert instance types to YAML format and append to MAPPINGS
# Use process substitution to avoid subshell issue with pipes
while IFS= read -r line; do
    MAPPINGS+="$line\n"
done < <(echo "$INSTANCE_TYPES" | yq -p json -o yaml | sed 's/^/      /')

# Create backup if template already exists
backup_file_if_exists "$OUTPUT_TEMPLATE"

# Generate the template with proper structure
{
    # Skip the comment header block (lines 1-10) and the document separator (line 11)
    # Start from line 12 which contains AWSTemplateFormatVersion
    sed -n '12p' "$BASE_TEMPLATE"

    echo ""

    # Insert Mappings section
    echo -e "$MAPPINGS"

    # Append the rest of the template (from line 13 onwards)
    tail -n +13 "$BASE_TEMPLATE"
} > "$OUTPUT_TEMPLATE"

echo "✓ CloudFormation template generated: $OUTPUT_TEMPLATE"
echo ""

# Validate that the generated file is valid YAML
echo "Validating generated template..."
if ! yq eval '.' "$OUTPUT_TEMPLATE" > /dev/null 2>&1; then
    echo "ERROR: Generated template is not valid YAML"
    echo ""
    echo "This is likely a bug in the script. Please report this issue."
    echo "Template file: $OUTPUT_TEMPLATE"
    exit 1
fi
echo "✓ Template is valid YAML"
echo ""

# ============================================================
# Success Output
# ============================================================

echo "================================================"
echo "SUCCESS!"
echo "================================================"
echo ""
echo "Copied AMI IDs (for your records):"
INDEX=0
for AMI_TYPE in "${AMI_TYPES[@]}"; do
    echo "  $AMI_TYPE: ${NEW_AMI_IDS[$INDEX]}"
    INDEX=$((INDEX + 1))
done
echo ""

echo "Generated CloudFormation template:"
echo "  $OUTPUT_TEMPLATE"
echo ""

# Check template size and provide appropriate deployment instructions
TEMPLATE_SIZE=$(wc -c < "$OUTPUT_TEMPLATE" | tr -d ' ')
echo "Next steps:"
echo ""

if [ "$TEMPLATE_SIZE" -gt 51200 ]; then
    # Template is larger than 51KB limit for direct CLI usage
    echo "Note: This template is ${TEMPLATE_SIZE} bytes (CloudFormation has a 51,200 byte limit for direct usage)."
    echo ""
    echo "1. Upload template to S3 bucket:"
    echo "   aws s3 cp $OUTPUT_TEMPLATE s3://<your-bucket>/jambonz-${SIZE}-${REGION}.yaml"
    echo ""
    echo "2. Deploy using S3 URL:"
    echo "   aws cloudformation create-stack \\"
    echo "     --region $REGION \\"
    echo "     --stack-name jambonz-${SIZE} \\"
    echo "     --template-url https://<your-bucket>.s3.amazonaws.com/jambonz-${SIZE}-${REGION}.yaml \\"
    echo "     --capabilities CAPABILITY_IAM \\"
    echo "     --parameters \\"
    echo "       ParameterKey=KeyName,ParameterValue=<your-key-name> \\"
    echo "       ParameterKey=URLPortal,ParameterValue=<your-domain>"
    echo ""
    echo "3. Or deploy via AWS Console (recommended for large templates):"
    echo "   - Navigate to CloudFormation service in $REGION"
    echo "   - Click 'Create stack'"
    echo "   - Choose 'Upload a template file' and select: $OUTPUT_TEMPLATE"
    echo "   - Follow the wizard to configure parameters"
else
    # Template is small enough for direct usage
    echo "1. Review the generated template:"
    echo "   cat $OUTPUT_TEMPLATE"
    echo ""
    echo "2. Deploy using AWS CLI:"
    echo "   aws cloudformation create-stack \\"
    echo "     --region $REGION \\"
    echo "     --stack-name jambonz-${SIZE} \\"
    echo "     --template-body file://$OUTPUT_TEMPLATE \\"
    echo "     --capabilities CAPABILITY_IAM \\"
    echo "     --parameters \\"
    echo "       ParameterKey=KeyName,ParameterValue=<your-key-name> \\"
    echo "       ParameterKey=URLPortal,ParameterValue=<your-domain>"
    echo ""
    echo "3. Or deploy via AWS Console:"
    echo "   - Navigate to CloudFormation service in $REGION"
    echo "   - Click 'Create stack'"
    echo "   - Upload template: $OUTPUT_TEMPLATE"
    echo "   - Follow the wizard to configure parameters"
fi
echo ""

echo "================================================"
