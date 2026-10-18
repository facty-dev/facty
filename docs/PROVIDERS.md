# Custom providers — contemplated design (future)

**Status:** contemplated — not yet implemented · **Date:** 2026-10-17
**Inputs:** PO direction (2026-10-17) · [ADR-0004](adr/0004-cli-primary-interface.md) · the workbench auth work (`engine/auth.py`)

**ELI5:** today the workbench signs you into Mistral. Tomorrow you
should be able to point Facty at **your** provider — your own endpoint,
your own key, your own OAuth — and everything (the sensing calls, the
workbench, the demos) just uses it. This note contemplates that design;
only the seams exist so far.

## What exists today (the seams)

- **Sensing** (`engine/sensing.py`): `FACTY_PROVIDER` / `FACTY_MODEL`
  env overrides flow into the pi invocation
  (`pi -p --provider <id> --model <model>`). Any provider pi knows
  works today, with no further code.
- **Auth** (`engine/auth.py`): `auth.status(provider=…)` reads any
  provider's entry from pi's auth storage — presence + expiry, never
  token values.
- **The OAuth driver** (`engine/mistral-oauth-login.mjs`) already takes
  the OAuth module's path as an argument; it is Mistral-specific only
  in the export it calls (`createMistralOAuth`).

## The goal

Other users configure their own providers; the workbench and the
sensing path use them. A "provider" is anything pi can talk to: an
API-key provider (OpenAI-compatible, Anthropic, a custom endpoint) or
an OAuth/subscription provider registered by a pi extension.

## Where the config lives (future)

`~/.facty/providers.json` — machine-local, gitignored, and it **holds
no secrets** (it references env vars and pi's auth storage):

```json
{
  "active": "mistral-subscription",
  "providers": [
    { "id": "mistral-subscription", "name": "Mistral subscription",
      "type": "oauth-extension", "model": "mistral-large-4",
      "oauth": { "module": "git/github.com/5omeOtherGuy/pi-mistral-subscription/src/mistral-oauth.ts",
                 "export": "createMistralOAuth" } },
    { "id": "my-endpoint", "name": "My endpoint", "type": "api_key",
      "baseUrl": "https://llm.example.com/v1", "model": "my-model",
      "auth": { "env": "MY_ENDPOINT_KEY" } }
  ]
}
```

## How credentials flow (the posture is unchanged)

- **pi's auth storage (`~/.pi/agent/auth.json`) stays THE credential
  store.** The extension writes there; our `_store_credential` writes
  there — verified end-to-end (pi consumed a credential written by our
  code in a real call).
- **API-key providers**: the key comes from an env var or pi's stored
  auth — never from our config file, never logged.
- **OAuth providers**: the browser flow per provider — today's
  mistral-subscription flow, generalized (the driver gets the module
  path + the export name).
- **The engine never sees a key.** The isolation posture (pi owns the
  credential; the engine process never does) is untouched.

## Workbench UI (future, not built)

- The left column's auth section becomes a **provider list**: each
  provider shows its status (authenticated + expiry, or "set
  `MY_ENDPOINT_KEY`") and an action — browser sign-in for OAuth
  providers, a paste-key modal for API-key providers (stored via pi's
  auth storage).
- The `a` key / command palette gain **Manage providers…**
  (add / edit / remove / set active).
- The active provider drives the sensing calls (the `FACTY_PROVIDER`
  seam) and the model picker.

## Deliberately not done yet

- the providers config file + loader
- the provider-list UI, the paste-key modal, per-provider model pickers
- the per-provider OAuth driver generalization (export-name parameter)

## Migration

`mistral-subscription` becomes the first entry in the future config.
Nothing existing breaks: the env seams default to today's behavior.

## See also

- [ADR-0004](adr/0004-cli-primary-interface.md) — the `facty` CLI + the retired stdlib-only rule
- [engine/README.md](../engine/README.md) — workbench authentication
- [ADR-0003](adr/0003-detective-dss-neurosymbolic-core.md) — the neurosymbolic core (the isolation posture)
