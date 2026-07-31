# LiveKit spike lane — owner approval checklist

`.github/workflows/build-livekit-spike.yml` compiles the OBS-1712 LiveKit direct-path
spike (`spike/livekit-direct/`) from the private `n4s5ti/omp-wakeword` repository on a
`macos-15` runner with Xcode 16.4, and uploads the `xcodebuild` log.

**The lane is staged, not armed.** It is committed on the branch
`feature/livekit-spike-lane` and it references trust material that does not exist yet.
Nothing in this branch created a deploy key, a repository secret, or a GitHub
environment, and nothing here can: those are owner actions. Until all four steps below
are performed by the repository owner, dispatching the workflow fails — first because
the workflow file is not on `main` (`if: github.ref == 'refs/heads/main'`), and then
because the `omp-wakeword-source-read` environment and its
`OMP_WAKEWORD_DEPLOY_KEY` secret are absent.

Run the steps in order. Steps 1–3 arm the trust material; step 4 admits the lane.

## What you are approving

| Item | Value |
| --- | --- |
| Private source repo | `n4s5ti/omp-wakeword` (read-only) |
| Admitted branch | `feature/livekit-direct-spike` (**not** `main`) |
| New environment | `omp-wakeword-source-read` |
| New secret | `OMP_WAKEWORD_DEPLOY_KEY` (private half of a read-only deploy key) |
| Runner | `macos-15`, `DEVELOPER_DIR=/Applications/Xcode_16.4.app/...` |
| Build | `xcodegen generate` + `xcodebuild build ... CODE_SIGNING_ALLOWED=NO` |
| Output | public `xcodebuild` log artifact, 14-day retention |

Exposure: `n4s5ti/runner` is **public**, so the build log is public. It can contain
private source paths, Swift diagnostics, and dependency URLs from the spike. It cannot
contain a signed artifact — this lane holds no signing secrets and never runs
`xcodebuild archive`. The deploy key is read-only and is destroyed inside the admission
step *before* any admitted source executes; the static tripwire
`.github/scripts/test_build_livekit_spike_workflow.py` fails the run if that ordering,
the branch-scoped ancestry check, the pinned action SHAs, or `CODE_SIGNING_ALLOWED=NO`
is ever weakened.

## Step 1 — generate a dedicated ed25519 keypair

Do this on a trusted local machine. Use a key that exists for nothing else.

```bash
mkdir -p ~/.ssh/omp-wakeword-source-read
ssh-keygen -t ed25519 -N '' \
  -C 'runner omp-wakeword-source-read (read-only, LiveKit spike lane)' \
  -f ~/.ssh/omp-wakeword-source-read/id_ed25519
chmod 600 ~/.ssh/omp-wakeword-source-read/id_ed25519
```

## Step 2 — add the public half as a READ-ONLY deploy key on the source repo

`gh` has no deploy-key create command, so this goes through the API. Omitting
`read_only` would grant write access to the private source repo — it is required.

```bash
gh api --method POST /repos/n4s5ti/omp-wakeword/keys \
  -f title='runner livekit spike lane (read-only)' \
  -f key="$(cat ~/.ssh/omp-wakeword-source-read/id_ed25519.pub)" \
  -F read_only=true
```

Verify it landed read-only:

```bash
gh api /repos/n4s5ti/omp-wakeword/keys \
  --jq '.[] | select(.title == "runner livekit spike lane (read-only)") | {id, read_only}'
```

## Step 3 — create the environment on the runner and store the private half

Create the environment, restrict its deployment branches to `main` only, then add the
secret scoped to that environment (not to the repository).

```bash
# 3a. create the environment
gh api --method PUT /repos/n4s5ti/runner/environments/omp-wakeword-source-read

# 3b. restrict it to the protected main branch
gh api --method PUT /repos/n4s5ti/runner/environments/omp-wakeword-source-read \
  --input - <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
gh api --method POST \
  /repos/n4s5ti/runner/environments/omp-wakeword-source-read/deployment-branch-policies \
  -f name='main' -f type='branch'

# 3c. store the PRIVATE key as an environment secret
gh secret set OMP_WAKEWORD_DEPLOY_KEY \
  --repo n4s5ti/runner \
  --env omp-wakeword-source-read \
  < ~/.ssh/omp-wakeword-source-read/id_ed25519
```

Verify the secret exists and the branch policy is `main`-only:

```bash
gh secret list --repo n4s5ti/runner --env omp-wakeword-source-read
gh api /repos/n4s5ti/runner/environments/omp-wakeword-source-read/deployment-branch-policies \
  --jq '.branch_policies[].name'
```

## Step 4 — merge the lane branch into runner `main`

The workflow is inert on any other ref. Review the diff first, run the tripwire
locally, then merge and dispatch.

```bash
cd /path/to/runner
git fetch origin
git switch main && git pull --ff-only

git diff --stat main..feature/livekit-spike-lane
python3 .github/scripts/test_build_livekit_spike_workflow.py

git merge --no-ff feature/livekit-spike-lane \
  -m 'ci: admit the LiveKit direct-path spike build lane'
git push origin main
```

Then dispatch against a commit on the spike branch:

```bash
SPIKE_SHA="$(gh api /repos/n4s5ti/omp-wakeword/commits/feature/livekit-direct-spike --jq .sha)"

gh workflow run build-livekit-spike.yml \
  --repo n4s5ti/runner \
  --ref main \
  -f source_sha="$SPIKE_SHA"

gh run watch --repo n4s5ti/runner
```

Retrieve the compiler output:

```bash
gh run download --repo n4s5ti/runner \
  --name "livekit-spike-xcodebuild-log-${SPIKE_SHA}" --dir ./livekit-spike-log
```

## Revoking the lane

Any one of these disarms it; do all three to remove it completely.

```bash
# revoke the deploy key (id from the step 2 verification)
gh api --method DELETE /repos/n4s5ti/omp-wakeword/keys/<key_id>

# drop the secret and the environment
gh secret delete OMP_WAKEWORD_DEPLOY_KEY --repo n4s5ti/runner --env omp-wakeword-source-read
gh api --method DELETE /repos/n4s5ti/runner/environments/omp-wakeword-source-read
```
