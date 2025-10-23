#!/bin/bash
#
# Pre-commit hook to validate file changes using redlines
#
# Installation:
#   cp pre_commit_hook.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# This hook compares staged files with their HEAD version and validates changes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Running pre-commit checks with redlines..."

# Check if redlines is installed
if ! command -v redlines &> /dev/null; then
    echo -e "${RED}Error: redlines is not installed${NC}"
    echo "Install with: pip install redlines"
    exit 1
fi

# Get list of staged files (modified or added)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=AM)

if [ -z "$STAGED_FILES" ]; then
    echo -e "${GREEN}✓ No files staged for commit${NC}"
    exit 0
fi

# Create temporary directory for comparisons
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

TOTAL_FILES=0
FILES_WITH_CHANGES=0
TOTAL_CHANGES=0

echo ""
echo "Checking staged files..."
echo "----------------------------------------"

for FILE in $STAGED_FILES; do
    # Skip if file doesn't exist (deleted files)
    if [ ! -f "$FILE" ]; then
        continue
    fi

    # Only check text files (skip binaries)
    if file "$FILE" | grep -q "text"; then
        TOTAL_FILES=$((TOTAL_FILES + 1))

        # Get the file from HEAD (if it exists)
        if git show HEAD:"$FILE" > "$TEMP_DIR/old_version" 2>/dev/null; then
            # File exists in HEAD, compare changes
            if redlines stats "$TEMP_DIR/old_version" "$FILE" --quiet > "$TEMP_DIR/stats" 2>&1; then
                # Extract change count from stats output
                CHANGES=$(grep "Total Changes:" "$TEMP_DIR/stats" | awk '{print $3}')

                if [ "$CHANGES" -gt 0 ]; then
                    FILES_WITH_CHANGES=$((FILES_WITH_CHANGES + 1))
                    TOTAL_CHANGES=$((TOTAL_CHANGES + CHANGES))

                    # Get change ratio
                    RATIO=$(grep "Change Ratio:" "$TEMP_DIR/stats" | awk '{print $3}')

                    echo -e "${YELLOW}△${NC} $FILE - $CHANGES changes ($RATIO)"
                else
                    echo -e "${GREEN}✓${NC} $FILE - no changes"
                fi
            else
                echo -e "${RED}✗${NC} $FILE - error comparing"
                cat "$TEMP_DIR/stats"
                exit 1
            fi
        else
            # New file
            echo -e "${GREEN}+${NC} $FILE - new file"
        fi
    fi
done

echo "----------------------------------------"
echo ""
echo "Summary:"
echo "  Files checked: $TOTAL_FILES"
echo "  Files with changes: $FILES_WITH_CHANGES"
echo "  Total changes: $TOTAL_CHANGES"
echo ""

# Optional: Fail commit if too many changes
# Uncomment and adjust threshold as needed
# MAX_CHANGES=100
# if [ $TOTAL_CHANGES -gt $MAX_CHANGES ]; then
#     echo -e "${RED}Error: Too many changes ($TOTAL_CHANGES > $MAX_CHANGES)${NC}"
#     echo "Consider splitting this into smaller commits"
#     exit 1
# fi

echo -e "${GREEN}✓ Pre-commit checks passed${NC}"
exit 0
