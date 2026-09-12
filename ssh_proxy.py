#!/usr/bin/env python3
"""
Multi‑host SSH Proxy
A tiny Flask‑based JSON‑API that lets you execute pre‑approved commands
on remote hosts via SSH (Paramiko).

Author: Claude Houle
"""

import json
import os
import logging
import logging.config
from pathlib import Path
from typing import Dict, List, Any

from flask import Flask, request, jsonify, abort
import paramiko

# --------------------------------------------------------------
# Logging configuration (loads from logging.conf if present)
# --------------------------------------------------------------
LOG_CONF = Path(__file__).with_name("logging.conf")
if LOG_CONF.is_file():
    logging.config.fileConfig(LOG_CONF)
else:
    logging.basicConfig(level=logging.INFO)

log = logging.getLogger("hac-ssh-proxy")

# --------------------------------------------------------------
# Load & validate the JSON config (mounted at /config/config.json)
# --------------------------------------------------------------
CONFIG_PATH = Path("/config/config.json")

def load_config() -> Dict[str, List[Dict[str, Any]]]:
    if not CONFIG_PATH.is_file():
        log.error("Config file not found at %s", CONFIG_PATH)
        raise FileNotFoundError(f"Missing config: {CONFIG_PATH}")

    with CONFIG_PATH.open() as fp:
        data = json.load(fp)

    # Basic sanity checks
    if "hosts" not in data or not isinstance(data["hosts"], list):
        raise ValueError("Config must contain a top‑level 'hosts' list")

    for host in data["hosts"]:
        for key in ("hostname", "ip", "userid", "ssh_key", "allowed_commands"):
            if key not in host:
                raise ValueError(f"Host entry missing required key: {key}")

        # Resolve the key path *inside* the container
        host["ssh_key"] = str(Path(host["ssh_key"]).expanduser())
        if not Path(host["ssh_key"]).is_file():
            raise FileNotFoundError(f"SSH key not found: {host['ssh_key']}")

    log.info("Loaded config for %d host(s)", len(data["hosts"]))
    return data

CONFIG = load_config()
HOST_MAP = {h["hostname"]: h for h in CONFIG["hosts"]}

# --------------------------------------------------------------
# Flask app & helper utilities
# --------------------------------------------------------------
app = Flask(__name__)

def get_host_cfg(hostname: str) -> Dict[str, Any]:
    cfg = HOST_MAP.get(hostname)
    if not cfg:
        abort(404, description=f"Hostname '{hostname}' not defined in config")
    return cfg

def normalize_allowed_commands(host_cfg: Dict[str, Any]) -> Any:
    """Return the host's allowed_commands in a consistent shape.

    - "*"           -> "*"                (wildcard, all commands allowed)
    - "a, b, c"      -> ["a", "b", "c"]     (comma-separated string form)
    - ["a", "b"]     -> ["a", "b"]          (already a list)
    """
    allowed = host_cfg["allowed_commands"]
    if allowed == "*":
        return "*"
    if isinstance(allowed, str):
        return [c.strip() for c in allowed.split(",") if c.strip()]
    return list(allowed)

def is_command_allowed(host_cfg: Dict[str, Any], cmd: str) -> bool:
    allowed = normalize_allowed_commands(host_cfg)
    if allowed == "*":
        return True
    return cmd in allowed

def run_ssh_command(host_cfg: Dict[str, Any], command: str) -> Dict[str, Any]:
    """Execute a command via Paramiko and return stdout / stderr."""
    log.debug("Connecting to %s@%s", host_cfg["userid"], host_cfg["ip"])
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host_cfg["ip"],
            username=host_cfg["userid"],
            key_filename=host_cfg["ssh_key"],
            timeout=10,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        out = stdout.read().decode()
        err = stderr.read().decode()
        exit_status = stdout.channel.recv_exit_status()
        log.info(
            "Executed on %s: %s (exit=%s)",
            host_cfg["hostname"],
            command,
            exit_status,
        )
    finally:
        client.close()

    return {
        "stdout": out,
        "stderr": err,
        "exit_code": exit_status,
    }

# --------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------

@app.route("/api/v1/hosts", methods=["GET"])
def list_hosts():
    """Return a minimal list of hostnames & IPs (no keys)."""
    return jsonify([
        {"hostname": h["hostname"], "ip": h["ip"]} for h in CONFIG["hosts"]
    ])

@app.route("/api/v1/hosts/<hostname>/commands", methods=["GET"])
def list_host_commands(hostname):
    """Return the allowed commands for a single host."""
    host_cfg = get_host_cfg(hostname)
    return jsonify({
        "hostname": host_cfg["hostname"],
        "allowed_commands": normalize_allowed_commands(host_cfg),
    })

@app.route("/api/v1/commands", methods=["GET"])
def list_all_commands():
    """Return the allowed commands for every configured host."""
    return jsonify([
        {
            "hostname": h["hostname"],
            "allowed_commands": normalize_allowed_commands(h),
        }
        for h in CONFIG["hosts"]
    ])

@app.route("/api/v1/exec", methods=["POST"])
def exec_command():
    """
    Expected JSON payload:
    {
        "hostname": "router01",
        "command": "show version"
    }
    """
    payload = request.get_json(force=True)

    hostname = payload.get("hostname")
    command = payload.get("command")
    if not hostname or not command:
        abort(400, description="Both 'hostname' and 'command' are required")

    host_cfg = get_host_cfg(hostname)

    if not is_command_allowed(host_cfg, command):
        abort(403, description="Command not allowed for this host")

    result = run_ssh_command(host_cfg, command)
    return jsonify(result)

# --------------------------------------------------------------
# Graceful shutdown (useful for k8s / podman health checks)
# --------------------------------------------------------------
@app.route("/healthz", methods=["GET"])
def health():
    return "OK", 200

# --------------------------------------------------------------
OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Multi-host SSH Proxy",
        "description": "Execute pre-approved commands on remote hosts via SSH",
        "version": "0.1.0",
    },
    "paths": {
        "/api/v1/hosts": {
            "get": {
                "operationId": "list_hosts",
                "summary": "List available remote hosts",
                "responses": {
                    "200": {
                        "description": "List of configured hosts",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "hostname": {"type": "string"},
                                            "ip": {"type": "string"},
                                        },
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/hosts/{hostname}/commands": {
            "get": {
                "operationId": "list_host_commands",
                "summary": "List the allowed commands for a single host",
                "parameters": [
                    {
                        "name": "hostname",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Allowed commands for the host",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "hostname": {"type": "string"},
                                        "allowed_commands": {
                                            "oneOf": [
                                                {"type": "string", "enum": ["*"]},
                                                {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                            ]
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "404": {"description": "Hostname not defined in config"},
                },
            }
        },
        "/api/v1/commands": {
            "get": {
                "operationId": "list_all_commands",
                "summary": "List the allowed commands for every configured host",
                "responses": {
                    "200": {
                        "description": "Allowed commands per host",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "hostname": {"type": "string"},
                                            "allowed_commands": {
                                                "oneOf": [
                                                    {"type": "string", "enum": ["*"]},
                                                    {
                                                        "type": "array",
                                                        "items": {"type": "string"},
                                                    },
                                                ]
                                            },
                                        },
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/exec": {
            "post": {
                "operationId": "exec_command",
                "summary": "Execute an approved command on a remote host via SSH",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["hostname", "command"],
                                "properties": {
                                    "hostname": {
                                        "type": "string",
                                        "description": "Name of the configured host",
                                    },
                                    "command": {
                                        "type": "string",
                                        "description": "Command to run on the remote host",
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Command output",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "stdout": {"type": "string"},
                                        "stderr": {"type": "string"},
                                        "exit_code": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    },
                    "403": {"description": "Command not allowed for this host"},
                    "404": {"description": "Hostname not defined in config"},
                },
            }
        },
    },
}


@app.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return jsonify(OPENAPI_SPEC)

# --------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------
if __name__ == "__main__":
    # Bind to 0.0.0.0 so the container can be reached from other pods
    app.run(host="0.0.0.0", port=5000, debug=False)

