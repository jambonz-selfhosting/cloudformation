#!/bin/bash
#
# Merge AMI mappings from mappings/ami-mappings.yaml into CloudFormation templates.
#
# This script reads the shared AMI mappings file and inserts the appropriate
# Mappings section into each CloudFormation template (mini, medium, large).
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MAPPINGS_FILE="$REPO_ROOT/mappings/ami-mappings.yaml"

# Function to extract mappings for a specific size and convert to CF format
generate_mappings_section() {
    local size="$1"
    local tmpfile="$2"

    echo "Mappings:" > "$tmpfile"
    echo "  AWSRegion2AMI:" >> "$tmpfile"

    # Use awk to extract the section for this size
    awk -v size="$size" '
        BEGIN { in_section = 0 }

        # Match the size header (e.g., "mini:", "medium:", "large:")
        $0 ~ "^" size ":" {
            in_section = 1
            next
        }

        # If we hit another top-level key (not indented), stop
        in_section && /^[a-z]+:/ {
            in_section = 0
        }

        # Skip comment lines and empty lines at section level
        in_section && /^  #/ { next }
        in_section && /^$/ { next }

        # Print region lines (2-space indent in source -> 4-space in output)
        in_section && /^  [a-z]/ {
            sub(/^  /, "    ")
            print
        }

        # Print AMI lines (4-space indent in source -> 6-space in output)
        in_section && /^    [A-Z]/ {
            sub(/^    /, "      ")
            print
        }
    ' "$MAPPINGS_FILE" >> "$tmpfile"

    echo "" >> "$tmpfile"
}

# Function to merge mappings into a template
merge_template() {
    local dir="$1"
    local size="$2"
    local base_file="$REPO_ROOT/$dir/jambonz-base-template.yaml"
    local output_file="$REPO_ROOT/$dir/jambonz.yaml"
    local tmp_mappings
    local tmp_output

    if [[ ! -f "$base_file" ]]; then
        echo "Skipping $dir: $base_file not found" >&2
        return 0
    fi

    echo "Merging $size mappings into $output_file"

    tmp_mappings=$(mktemp)
    tmp_output=$(mktemp)

    # Generate the mappings section to a temp file
    generate_mappings_section "$size" "$tmp_mappings"

    # Find the line number of the first section after AWSTemplateFormatVersion
    local insert_line
    insert_line=$(grep -n "^Parameters:\|^Conditions:\|^Resources:" "$base_file" | head -1 | cut -d: -f1)

    if [[ -z "$insert_line" ]]; then
        echo "  Error: Could not find insertion point in $base_file" >&2
        rm -f "$tmp_mappings" "$tmp_output"
        return 1
    fi

    # Split the file and insert mappings
    # Skip the warning header comment block (lines starting with #) at the beginning
    local content_start
    content_start=$(grep -n "^[^#]" "$base_file" | head -1 | cut -d: -f1)

    # Get content from first non-comment line up to (but not including) the insertion point
    head -n $((insert_line - 1)) "$base_file" | tail -n +$content_start > "$tmp_output"
    cat "$tmp_mappings" >> "$tmp_output"
    tail -n +$insert_line "$base_file" >> "$tmp_output"

    mv "$tmp_output" "$output_file"
    rm -f "$tmp_mappings"

    echo "  Done: $output_file"
}

# Main
echo "Merging AMI mappings into CloudFormation templates..."
echo ""

merge_template "mini" "mini"
merge_template "medium" "medium"
merge_template "large" "large"

echo ""
echo "All templates updated successfully."
