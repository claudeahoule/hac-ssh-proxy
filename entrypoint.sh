#!/usr/bin/env bash
# Simple wrapper that prints the config location and starts Flask
echo "=== SSH Proxy Server ==="
echo "Config directory: /config"
echo "Log level: ${LOG_LEVEL:-INFO}"
exec /opt/venv/bin/python -u ssh_proxy.py
