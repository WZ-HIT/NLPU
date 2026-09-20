# FROZEN POLICY EVIDENCE — runtime profile was loaded and validated separately.
#
# Purpose:
#   Allow Codex CLI 0.153.4 to bootstrap bubblewrap 0.12.0 inside the
#   scrapy-sdd Docker boundary on Ubuntu 24.04 while retaining AppArmor
#   confinement for the command executed inside bubblewrap.
#
# Fixed identities:
#   task: scrapy__scrapy__pr8017
#   baseline: 11079cb1c85b9e75a39a7269943c69d1a975d485
#   bwrap executable: /opt/agent/bwrap/bin/bwrap
#   bwrap archive SHA256: e7d65c75e05637e42b93f6abf9222fa0d26b537648a7a34c122b75021d41756d
#   bwrap executable SHA256: 77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c
#   bwrap source: https://github.com/openai/codex/releases/tag/rust-v0.153.4
#   Docker profile source:
#     https://github.com/moby/profiles/blob/836ae4d37ef2ec995c77c99fc55f5b5f3af3a897/apparmor/template.go
#   Ubuntu reference profile:
#     apparmor-profiles 4.0.1really4.0.1-0ubuntu0.24.04.7
#     package SHA256: bdac5b74d884643653565c52ed7483c9582e646ff72cce8d95d0eb8467a3139c
#
# Required companion controls (not implemented by this file):
#   - UID/GID 1007:1007; privileged=false; cap_drop=ALL
#   - no-new-privileges=true; read-only root filesystem
#   - task seccomp profile pinned by SHA256
#   - private repository, HOME, .venv, .tox and caches per experiment
#   - Docker network policy and provider-only egress when API access is enabled
#   - DeepSeek credential mounted only at /run/secrets/deepseek_api_key and
#     consumed by a parent-only command-backed authentication helper
#
# Security model and limitation:
#   The parent Codex process is part of the trusted control plane. Because Docker
#   applies no-new-privileges before Codex starts, an exec transition cannot be
#   used to grant bwrap permissions absent from the parent. The parent therefore
#   carries the AppArmor permissions needed for bwrap bootstrap. Docker's
#   non-root/capability boundary and the separate seccomp policy remain mandatory.
#   Only /opt/agent/bwrap/bin/bwrap can add the bwrap profile to the current
#   parent confinement. This stacking transition is required by no-new-privileges
#   and evaluates permissions as the intersection of parent and bwrap policies.
#   The command launched by bwrap is additionally stacked with the unprivileged
#   child profile, which audit-denies every capability.
#
# This policy intentionally omits host-local include files so identical bytes
# have identical meaning across the three experiments. Syntax-only compilation
# is not evidence that runtime confinement works.
# The Ubuntu reference's broad io_uring allowance is also omitted: AppArmor
# 4.0.1 reports that io_uring rules are not enforced by this host, and bwrap
# bootstrap does not require them. Omitting it is the stricter portable default.

abi <abi/4.0>,

include <tunables/global>

profile scrapy_sdd_codex_parent_11079cb1c85b flags=(attach_disconnected,mediate_deleted) {
  # Based on Moby's pinned docker-default template.
  allow network,
  deny network alg,
  allow capability,
  allow file rwlkm /{**,},
  allow umount,

  # Required for bwrap bootstrap under no-new-privileges.
  allow userns,
  allow mount,
  allow pivot_root,

  # Inherit this parent profile for the fixed common runtime executables.
  allow /bin/** ix,
  allow /sbin/** ix,
  allow /usr/bin/** ix,
  allow /usr/sbin/** ix,
  allow /usr/local/bin/** ix,
  allow /usr/local/sbin/** ix,
  allow /opt/agent/bin/codex ix,
  allow /opt/agent/bin/node ix,
  allow /opt/agent/bin/npm ix,
  allow /opt/agent/bin/npx ix,
  allow /opt/agent/bin/uv ix,
  allow /opt/agent/bin/uvx ix,
  allow /opt/agent/node/bin/node ix,
  allow /opt/agent/node/lib/node_modules/npm/bin/npm-cli.js ix,
  allow /opt/agent/node/lib/node_modules/npm/bin/npx-cli.js ix,

  # The trusted Codex parent may read the single fixed provider secret. The
  # broad Moby-derived file rule above already permits this access; this exact
  # rule documents the only credential path approved for formal deployment.
  allow /run/secrets/deepseek_api_key r,

  # Add bwrap restrictions to the current parent rather than replacing it.
  # A non-stacking transition is rejected under no-new-privileges.
  allow /opt/agent/bwrap/bin/bwrap px -> scrapy_sdd_codex_parent_11079cb1c85b//&scrapy_sdd_bwrap_0_12_0,

  # Preserve Docker's default process-control behavior.
  allow signal (receive) peer=unconfined,
  allow signal (receive) peer=runc,
  allow signal (receive) peer=crun,
  allow signal (send,receive) peer=scrapy_sdd_codex_parent_11079cb1c85b,
  allow ptrace (trace,tracedby,read,readby) peer=scrapy_sdd_codex_parent_11079cb1c85b,

  # Preserve Docker's default /proc and /sys protections.
  deny @{PROC}/* w,
  deny @{PROC}/{[^1-9/],[^1-9/][^0-9/],[^1-9s/][^0-9y/][^0-9s/],[^1-9/][^0-9/][^0-9/][^0-9/]*}/** w,
  deny @{PROC}/sys/[^k]** w,
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/kcore rwklx,
  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/firmware/** rwklx,
  deny /sys/devices/virtual/powercap/** rwklx,
  deny /sys/kernel/security/** rwklx,
}

# Adapted from Ubuntu's bwrap-userns-restrict profile. The attachment path is
# the fixed path inside the candidate image, not the distro default /usr/bin.
profile scrapy_sdd_bwrap_0_12_0 /opt/agent/bwrap/bin/bwrap flags=(attach_disconnected) {
  allow capability,
  allow file rwlkm /{**,},
  allow network,
  allow unix,
  allow ptrace,
  allow signal,
  allow mqueue,
  allow userns,
  allow mount,
  allow umount,
  allow pivot_root,
  allow dbus,

  # Every command launched from bwrap is stacked with the child profile.
  allow px /** -> scrapy_sdd_bwrap_0_12_0//&scrapy_sdd_unpriv_bwrap_0_12_0,
}

profile scrapy_sdd_unpriv_bwrap_0_12_0 flags=(attach_disconnected) {
  allow file rwlkm /{**,},
  allow network,
  allow unix,
  allow ptrace,
  allow signal,
  allow mqueue,
  allow userns,
  allow mount,
  allow umount,
  allow pivot_root,
  allow dbus,

  # Preserve the restricted profile across further child execs.
  allow pix /** -> &scrapy_sdd_unpriv_bwrap_0_12_0,

  # Provider authentication belongs to the trusted Codex parent. Explicit deny
  # rules override the broad compatibility allow rule above, so commands inside
  # the completed sandbox cannot read or map Docker secrets.
  audit deny /run/secrets/{,**} rwklm,

  # Do not let a sandboxed command recover credentials by inspecting another
  # process's environment or memory. Self aliases are included defensively;
  # Codex's shell-environment policy already removes secret-like variables.
  audit deny @{PROC}/{[0-9]*,self,thread-self}/environ r,
  audit deny @{PROC}/[0-9]*/task/[0-9]*/environ r,
  audit deny @{PROC}/{[0-9]*,self,thread-self}/mem rw,
  audit deny ptrace (read,trace) peer=scrapy_sdd_codex_parent_11079cb1c85b,

  # The command running inside the completed sandbox must not retain bwrap's
  # namespace-setup capabilities.
  audit deny capability,
}
