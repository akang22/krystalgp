#!/bin/bash
# SSH script to connect to EC2 instance

# Configuration
EC2_HOST="admin@ec2-52-15-131-215.us-east-2.compute.amazonaws.com"
SSH_KEY="${HOME}/Downloads/test.pem"
PROJECT_DIR="~/krystalgp"

# Check if SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "Error: SSH key not found at $SSH_KEY"
    echo "Please update the SSH_KEY variable in this script."
    exit 1
fi

# Set proper permissions on the key file
chmod 400 "$SSH_KEY" 2>/dev/null

# Connect to EC2
echo "Connecting to EC2 instance..."
echo "Host: $EC2_HOST"
echo "Key: $SSH_KEY"
echo ""

# If arguments provided, execute them; otherwise, start interactive session
if [ $# -gt 0 ]; then
    # Execute command remotely
    ssh -i "$SSH_KEY" "$EC2_HOST" "$@"
else
    # Interactive session - cd to project directory
    ssh -i "$SSH_KEY" "$EC2_HOST" "cd $PROJECT_DIR && exec \$SHELL"
fi
