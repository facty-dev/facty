# Use cases — Facty multi-tenant isolation

Real-world scenarios for isolating client projects with Facty on
**SmolVM micro-VMs** (ADR-0005 — the gondolin/pi runtime this page used to
describe is retired). Each client runs in its own SmolVM machine booted from
the single facty OCI image: its project in the repo, its credentials injected
host-side, its egress allow-listed. Nothing else exists inside the machine.

Core primitives:

```bash
# Build the one image, then boot client machines from it
docker build -t facty .
docker save facty > /tmp/facty.tar

# One-off run (CI, ephemeral):
smolvm machine run --net --image /tmp/facty.tar -- bash

# Persistent per-client machine:
smolvm machine create --net --name acme --image /tmp/facty.tar
smolvm machine start --name acme
smolvm machine exec --name acme -- bash
```

- Each machine is a separate VM with its own filesystem state, its own
  TerminusDB instance (`TERMINUSDB_DB=<client>` inside the machine), and its
  own network namespace
- Credentials never enter the guest: the machine only ever sees
  `MISTRAL_API_KEY=<placeholder>`; the host substitutes the real value into
  outbound requests to allowed hosts only (the SmolVM host-secret path —
  open item in ADR-0005; the design is unchanged from the retired runtime)
- Egress is an explicit allow-list (api.mistral.ai, registry.npmjs.org,
  api.uprelic.com); everything else is unreachable by construction

---

## 1. Freelance developer with multiple clients

Each client gets a dedicated machine with only their project + their keys.

```bash
# Acme Corp (their Mistral key, supplied host-side at boot)
MISTRAL_API_KEY=... smolvm machine create --net --name acme --image /tmp/facty.tar
smolvm machine exec --name acme -- env TERMINUSDB_DB=acme ./facty case init ...

# Beta Inc (a different machine, different db, different key source)
MISTRAL_API_KEY=... smolvm machine create --net --name beta --image /tmp/facty.tar
```

Acme's machine cannot see Beta's database, Beta's key, or the host filesystem —
and vice versa. Personal projects get their own machine with personal keys.

## 2. Agency with team members

Machines are per-user and per-client — two developers on the same host never
share a machine, a database, or secret placeholders.

```bash
# Alice — works on Acme and Beta (two machines, one per client)
alice$ smolvm machine create --net --name alice-acme --image /tmp/facty.tar
alice$ smolvm machine create --net --name alice-beta  --image /tmp/facty.tar

# Bob — Gamma and Delta (different machines, same host)
bob$ smolvm machine create --net --name bob-gamma --image /tmp/facty.tar
```

## 3. Consultant with compliance requirements

Egress is an explicit allow-list per deployment — the audit story is concrete:
what was allowed, what was substituted, what was blocked.

```bash
# Healthcare client — only the model API is reachable (deployment allow-list)
smolvm machine create --net --name healthco --image /tmp/facty.tar   # egress: api.mistral.ai only

# Fintech client — model API + their payment sandbox (per-deployment allow-list)
smolvm machine create --net --name fintech --image /tmp/facty.tar    # egress: api.mistral.ai + api.sandbox.paypal.com
```

Compliance evidence: the egress allow-list is the policy; any other host is
unreachable by construction. Secrets are provably absent from the guest (it
holds only the placeholder; substitution happens host-side on egress).

## 4. Solo developer with side projects

Work credentials and personal credentials never meet — separate machines,
separate placeholder envs, separate TerminusDB databases.

```bash
# Work machine (employer's key, host-side)
smolvm machine create --net --name work --image /tmp/facty.tar

# Side-project machine (personal key, host-side)
smolvm machine create --net --name side --image /tmp/facty.tar
```

The work machine's env contains no personal keys (only the placeholder that
was explicitly injected), and the reverse holds too.

## 5. Open source maintainer

OSS work uses your public GitHub identity and public repos only; client work
never intersects — different machine, different egress allow-list.

```bash
# OSS machine — public repos only (egress: github.com, api.github.com, api.mistral.ai)
smolvm machine create --net --name oss --image /tmp/facty.tar
```

## 6. Enterprise team lead

Everyone installs SmolVM and builds/distributes the one image; machines are
per-user, so isolation needs no central service.

```bash
# Shared once: docker build -t facty . && docker save facty > facty.tar (distribute the tar)
# Per user: smolvm machine create --net --name <me>-<client> --image facty.tar → self-serve isolation
```

---

## Common patterns

### Rotating credentials

Rotate the host-side value before the next machine boot — placeholder
substitution always uses the host's current value. No state to update inside
the machine.

### Adding a new project for an existing client

Boot a new machine (or a new TerminusDB branch on the existing one —
`facty case branch` / git-for-data) — nothing else changes.

### Per-project state, same client

Machines are cheap — boot one per project. Durable state lives in the git
branches (TerminusDB git-for-data) and the repo, which are the source of
truth; the machine itself is disposable.

### Emergency: revoke all access for a client

1. Stop and remove their machines (`smolvm machine stop --name …`, `smolvm machine rm --name …`)
2. Delete their case branches / databases (`facty case delete <id>`)
3. Remove the client's credential from where you source it host-side
   (your secret manager / shell env) — any future boot simply fails to
   authenticate

### Backup and restore

- Image: `docker save facty` — a single tar; copy it anywhere
- Case state: TerminusDB branches/commits (export/import, or just the git repo)
- Credentials: wherever you already keep them host-side (they were never in the VM)
