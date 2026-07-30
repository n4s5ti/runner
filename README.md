# runner

Public, stateless GitHub Actions runner for research and iOS workloads:

- `research-ollama`: runs Ollama on a GitHub-hosted runner and posts a JSON result.
- `research-searxng-ollama`: runs an ephemeral SearXNG service container plus Ollama and posts a JSON result.
- `build-multica-ios`: builds the public Multica iOS source.
- `build-omi-ios`: manually verifies or signs an immutable, protected-main commit from the private Omi repository.

The research and Multica workflows contain no vault data or persisted cache and require no repository secrets. The Omi workflow intentionally requires credentials that forks do not inherit; a fork cannot run it without configuring its own source and signing trust.

## Security model

- Required inputs are validated before work proceeds.
- `query` must be non-empty.
- `destination_url` must be HTTPS and must not contain embedded credentials.
- `temperature` must be numeric from `0.0` through `2.0`.
- SearXNG `top_n` must be an integer from `1` through `10`.
- Logs include only status, source counts, and `query_sha256`.
- Logs do not include raw query text, model output, SearXNG result content, or destination URL.
- Result posting uses `curl -fsS -o /dev/null` so response bodies are not printed.

## CLI usage

```bash
gh workflow run research-ollama.yml \
  --repo n4s5ti/runner \
  -f query="synthetic smoke test" \
  -f destination_url="https://httpbin.org/post" \
  -f model="llama3.2:3b" \
  -f temperature="0.2"

gh workflow run research-searxng-ollama.yml \
  --repo n4s5ti/runner \
  -f query="synthetic smoke test" \
  -f destination_url="https://httpbin.org/post" \
  -f model="llama3.2:3b" \
  -f temperature="0.2" \
  -f top_n="5"
```

## Omi iOS builds

Dispatch the public workflow only from its `main` branch and identify Omi source with a full 40-hex commit SHA:

```bash
gh workflow run build-omi-ios.yml \
  --repo n4s5ti/runner \
  --ref main \
  -f source_sha="<protected Omi main commit SHA>" \
  -f mode="verify"
```

Use `mode=signed` for the encrypted signed-IPA path. Both modes reject source commits that are not ancestors of protected Omi `main`. Build logs are public and can include private source paths or compiler diagnostics.

The workflow uses two GitHub environments restricted to runner `main`:

- `omi-ios-source-read`: `OMI_SOURCE_DEPLOY_KEY`, a read-only deploy key for the private Omi repository.
- `omi-ios-signing`: its own copy of `OMI_SOURCE_DEPLOY_KEY`, plus `IOS_SIGNING_CERTIFICATE_BASE64`, `IOS_SIGNING_CERTIFICATE_PASSWORD`, `IOS_PROVISIONING_PROFILES_BASE64`, and the public recipient certificate `IPA_ARTIFACT_ENCRYPTION_CERT_PEM`.

The signed workflow uploads only CMS ciphertext and a checksum summary. Keep the matching artifact decryption private key off GitHub; decrypt with `.github/scripts/decrypt-omi-ios-artifact.sh`. Forks must create equivalent environments, branch policies, deploy keys, signing material, and an artifact recipient certificate under their own ownership.

Watch runs with:

```bash
gh run watch --repo n4s5ti/runner
```

## `repository_dispatch` usage

`research-ollama` accepts event type `research-request`:

```bash
gh api repos/n4s5ti/runner/dispatches \
  --method POST \
  -f event_type=research-request \
  -F client_payload='{"query":"synthetic smoke test","destination_url":"https://httpbin.org/post","model":"llama3.2:3b","temperature":"0.2"}'
```

`research-searxng-ollama` accepts event type `searxng-research-request`:

```bash
gh api repos/n4s5ti/runner/dispatches \
  --method POST \
  -f event_type=searxng-research-request \
  -F client_payload='{"query":"synthetic smoke test","destination_url":"https://httpbin.org/post","model":"llama3.2:3b","temperature":"0.2","top_n":"5"}'
```

## Result JSON schema

Both workflows post one JSON document:

```json
{
  "flow": "research-ollama | research-searxng-ollama",
  "query_sha256": "hex sha256 of the query",
  "model": "llama3.2:3b",
  "temperature": 0.2,
  "generated_at": "2026-05-17T00:00:00Z",
  "answer": "model output",
  "sources": [
    {
      "title": "source title",
      "url": "https://example.test/source",
      "snippet": "short search result snippet",
      "engine": "search engine name"
    }
  ]
}
```

For `research-ollama`, `sources` is always an empty array. For `research-searxng-ollama`, `sources` contains up to `top_n` SearXNG results.

## Operational limits

- Default model: `llama3.2:3b`.
- Larger Ollama models can exceed GitHub-hosted runner capacity.
- SearXNG depends on public search engines and may return sparse or rate-limited results.
- Workflows require outbound network access to the Ollama model registry, SearXNG engines, and the supplied HTTPS destination.
