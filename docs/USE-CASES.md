# Use cases — drawbridge multi-tenant isolation

Real-world scenarios for isolating client projects with drawbridge on
gondolin micro-VMs. Each client runs in its own VM session: its project
mounted, its credentials injected host-side, its egress allow-listed.
Nothing else exists inside the session.

Core primitives:

```bash
# Boot a client session (from your terminal — it hosts the session)
gondolin bash --resume pi-sandbox.qcow2 \
  --mount-hostfs ~/clients/<client>/<project>:/workspace \
  --allow-host api.mistral.ai \
  --host-secret <ENV_VAR>@api.mistral.ai \
  -- bash -l
```

- The project is visible **only** via the explicit `--mount-hostfs`
- Credentials enter as `--host-secret`: the guest sees a placeholder; the
  host proxy substitutes the real value only into requests to allowed hosts
- Everything not mounted (`~/.ssh`, other clients, host state) does not exist

---

## 1. Freelance developer with multiple clients

Each client gets a dedicated session with only their project + their keys.

```bash
# Acme Corp (their Mistral key, their AWS — from YOUR shell env at boot)
ACME_MISTRAL_KEY=... gondolin bash --resume pi-sandbox.qcow2 \
  --mount-hostfs ~/clients/acme/api:/workspace \
  --allow-host api.mistral.ai \
  --host-secret ACME_MISTRAL_KEY@api.mistral.ai

# Beta Inc (their Anthropic key — a different session, different mounts)
BETA_ANTHROPIC_KEY=... gondolin bash --resume pi-sandbox.qcow2 \
  --mount-hostfs ~/clients/beta/web:/workspace \
  --allow-host api.anthropic.com \
  --host-secret BETA_ANTHROPIC_KEY@api.anthropic.com
```

Acme's session cannot see Beta's project, Beta's key, or your home directory —
and vice versa. Personal projects get their own session with personal keys.

## 2. Agency with team members

Sessions are per-user and per-client — two developers on the same machine
never share a session, mounts, or secret placeholders.

```bash
# Alice — works on Acme and Beta (two sessions, one per client)
alice$ ACME_MISTRAL_KEY=... gondolin bash ... --mount-hostfs ~/clients/acme:/workspace ...

# Bob — Gamma and Delta (different sessions, same machine)
bob$ GAMMA_MISTRAL_KEY=... gondolin bash ... --mount-hostfs ~/clients/gamma:/workspace ...
```

## 3. Consultant with compliance requirements

Egress is an explicit allow-list per session — the audit story is concrete:
what was allowed, what was substituted, what was blocked.

```bash
# Healthcare client — only their model API
HEALTH_ANTHROPIC_KEY=... gondolin bash --resume pi-sandbox.qcow2 \
  --mount-hostfs ~/clients/healthco/app:/workspace \
  --allow-host api.anthropic.com \
  --host-secret HEALTH_ANTHROPIC_KEY@api.anthropic.com

# Fintech client — model API + their payment sandbox
FINTECH_MISTRAL_KEY=... gondolin bash --resume pi-sandbox.qcow2 \
  --mount-hostfs ~/clients/fintech/api:/workspace \
  --allow-host api.mistral.ai api.sandbox.paypal.com \
  --host-secret FINTECH_MISTRAL_KEY@api.mistral.ai
```

Compliance evidence: the egress allow-list is the policy; any other host is
unreachable by construction. Secrets are provably absent from the guest.

## 4. Solo developer with side projects

Work credentials and personal credentials never meet — separate sessions,
separate placeholder envs.

```bash
# Work session (employer's Mistral key)
WORK_MISTRAL_KEY=... gondolin bash ... --mount-hostfs ~/work/api:/workspace \
  --host-secret WORK_MISTRAL_KEY@api.mistral.ai --allow-host api.mistral.ai

# Side project session (your personal key)
PI_PERSONAL_KEY=... gondolin bash ... --mount-hostfs ~/side/idea:/workspace \
  --host-secret PI_PERSONAL_KEY@api.mistral.ai --allow-host api.mistral.ai
```

The work session's env contains no personal keys (only the placeholders that
were explicitly injected), and the reverse holds too.

## 5. Open source maintainer

OSS work uses your public GitHub identity and public repos only; client work
never intersects.

```bash
# OSS session — your key, public repos only
OSS_GITHUB_TOKEN=... gondolin bash ... --mount-hostfs ~/oss/project:/workspace \
  --allow-host github.com api.github.com api.mistral.ai \
  --host-secret OSS_GITHUB_TOKEN@api.github.com
```

## 6. Enterprise team lead

Every user installs gondolin + pi and the shared snapshot; sessions are
per-user, so isolation needs no central service.

```bash
# Shared once: build the pi-sandbox snapshot, distribute it (it is a file)
# Per user: gondolin + pi + snapshot → self-serve isolated sessions
```

---

## Common patterns

### Rotating credentials

Rotate the env value before booting the next session — placeholder
substitution always uses the session's boot-time value. No state to update
inside the VM (sessions are ephemeral-per-boot from the snapshot).

### Adding a new project for an existing client

Boot a new session with the new `--mount-hostfs` path. Nothing else changes.

### Per-project state, same client

Sessions are cheap — boot one per project. Durable state lives in the
mounted project directory (and per-project snapshots if warm state matters).

### Emergency: revoke all access for a client

1. Kill their sessions (`make vm-down` from your terminal, or close the
   hosting shell)
2. Remove the client's credential from where you source it (your secret
   manager / shell env)
3. Any future session boot simply fails to authenticate

### Backup and restore

- Snapshot: `gondolin snapshot <session-id>` — a single qcow2 file; copy it
  anywhere
- Client state: the mounted project directory is the source of truth
- Credentials: wherever you already keep them (they were never in the VM)
