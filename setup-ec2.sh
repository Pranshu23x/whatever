#!/bin/bash
set -e

echo "=== Claude Code Router — EC2 Setup ==="

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker

# Add ubuntu to docker group
sudo usermod -aG docker ubuntu

# Create app directory
sudo mkdir -p /opt/proxy
sudo chown ubuntu:ubuntu /opt/proxy

# Create systemd service
sudo tee /etc/systemd/system/claude-router.service > /dev/null <<'EOF'
[Unit]
Description=Claude Code API Router
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/proxy
ExecStart=/usr/bin/docker compose up --build
ExecStop=/usr/bin/docker compose down
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable claude-router

# Install Nginx
sudo apt install -y nginx
sudo systemctl enable nginx

# Open firewall
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your .env to /opt/proxy/.env on the EC2"
echo "  2. Copy your project files to /opt/proxy/"
echo "  3. Run: sudo systemctl start claude-router"
echo ""
echo "Or just push to GitHub — the workflow handles deployment."
