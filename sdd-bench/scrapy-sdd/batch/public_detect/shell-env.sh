# Loaded by noninteractive Bash, including bash -lc after /etc/profile.
export PATH=/opt/sdd-tools/bin:/opt/agent/bwrap/bin:/opt/agent/bin:/opt/agent/node/bin:/usr/local/bin:/usr/bin:/bin
export DO_NOT_TRACK=1
export OPENSPEC_TELEMETRY=0

# Shell functions avoid shebang execution rejected by the existing sandbox.
openspec() { /usr/local/bin/python3 /run/sdd-public/tool.py openspec "$@"; }
specify() { /usr/local/bin/python3 /run/sdd-public/tool.py specify "$@"; }
cc-sdd() { /usr/local/bin/python3 /run/sdd-public/tool.py cc-sdd "$@"; }
