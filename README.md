## ssh_proxy.py
 
A Flask + OpenAPI tool server that executes commands on remote hosts over SSH, with a per-host **command allowlist** configured in `config.json`.
 
Each host entry lists which commands it will run. This can be either:
- an explicit list of exact command strings (`["show version", "show interfaces"]`), or
- a wildcard (`"*"`) that allows **any** command string sent by the caller.
Callers hit `/api/v1/exec` with a `hostname` and a `command`, and the server checks the command against that host's allowlist before running it via Paramiko.
 
### Known limitations
 
- **`"*"` means no allowlist at all.** Any host configured with a wildcard accepts arbitrary shell commands from any caller. There's no way to give a command flexible parameters (e.g. a variable case number) without either wildcarding the whole host or listing every literal variant — this is a known gap versus the template-based design.
- **No authentication.** Any client that can reach the container's port can call `/api/v1/exec`. There's no API key, token, or network-level restriction built in.
- **SSH host keys are auto-accepted.** `AutoAddPolicy()` trusts any host key on first connection and doesn't pin or verify it against a known set, which leaves it open to interception if an attacker can sit between this service and the target host.
### When to use this vs. hac-ssh-proxy
 
Use this script only for trusted, low-stakes, internal-network scenarios where the allowlist is a short explicit list (not `"*"`) and network access to the container is already restricted.
 
### API
 
- `GET /api/v1/hosts` — list configured hosts
- `GET /api/v1/hosts/<hostname>/commands` — list a host's allowed commands
- `GET /api/v1/commands` — list allowed commands for all hosts
- `POST /api/v1/exec` — run a command: `{"hostname": "...", "command": "..."}`
- `GET /openapi.json` — OpenAPI spec for tool-server integration (e.g. Open WebUI)
 
