# CI/CD setup (GitHub)

How the pipelines work and the one-time GitHub configuration. Server preparation is in
[AWS_EC2_SETUP.md](AWS_EC2_SETUP.md).

## How it works

```
feature branch ──push──▶ CI                       (tests only, nothing deployed)
pull request → main ──▶ CI + Security + CodeQL     (must be green to merge)
merge to main ────────▶ Deploy workflow:
                          CI (again, on the merge commit) ─┐
                          Security ────────────────────────┤─▶ package sahi-<sha>.tar.gz
                                                           └─▶ deploy job (environment "production")
                                                                 verify artifact = this commit
                                                                 ssh (pinned host key) → sahi-deploy
                                                                 public health check → tag deploy-<time>-<sha>
```

| Workflow | File | Runs on | Blocks deploy? |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | PRs to main, pushes to `feature/**` `fix/**` `hotfix/**` `chore/**` `release/**`, called by Deploy | Yes |
| Security | `.github/workflows/security.yml` | PRs to main, weekly (Mon), manual, called by Deploy | Yes |
| CodeQL | `.github/workflows/codeql.yml` | PRs, pushes to main, weekly | No (findings are reviewed by a person) |
| Deploy | `.github/workflows/deploy.yml` | Push to main, manual "Run workflow" | — |

### What CI checks

Backend (Python 3.14, the server's version):
- clean virtualenv from the **hash-pinned** `backend/requirements.lock` + `requirements-dev.lock`, then `pip check`
- every package in `requirements.txt` is present in the lock
- `compileall` (syntax), **Ruff** (undefined names, unused imports/variables, syntax errors)
- `import app.main`
- **unit tests**, then **integration tests** (API + SQLite) as separate steps, plus a check that every test belongs to
  one of the two groups (none silently skipped)
- **production boot smoke test** (`deploy/bin/smoke-boot.sh`): starts uvicorn with `ENVIRONMENT=production` on a
  throwaway database with the broker feed and price loop off, then checks health, auth guard, docs disabled and the
  Host-header check

Frontend (Node 22): `npm ci` (exact lockfile), `tsc --noEmit`, `npm test` (vitest), `npm run build`, and a scan
of the built bundle for server-side secret names. ESLint is not configured in this project, so it is not run.

Server config: shellcheck on every deploy script, `nginx -t` on the site file, `visudo -c` on the sudoers file,
and a workflow lint (top-level `permissions:` everywhere, no `write-all`, no `pull_request_target`, every action
pinned to a full commit SHA).

## One-time GitHub configuration

### 1. Create a dedicated deploy SSH key (on your PC)

Never reuse the EC2 `.pem` key for CI. Create a new key that can only log in as the restricted `deploy` user:

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f sahi_deploy_key
# sahi_deploy_key      -> private key: goes into the GitHub secret EC2_SSH_KEY (then delete the local copy)
# sahi_deploy_key.pub  -> public key: passed to bootstrap.sh --deploy-key on the server
```

### 2. Record the server's host key (so CI can detect a fake server)

From a machine you trust, after the server exists:

```bash
ssh-keyscan -t ed25519 <EC2_PUBLIC_IP> 2>/dev/null
```

Compare the fingerprint with the one the server itself reports (on the server:
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`). If they match, the `ssh-keyscan` output line is the value of
`EC2_SSH_KNOWN_HOSTS`.

### 3. Create the `production` environment and its secrets

GitHub → repository → **Settings → Environments → New environment** → `production`.

- **Deployment branches and tags**: *Selected branches* → add `main`. (Only main can ever deploy.)
- **Required reviewers** (optional, recommended once others contribute): add yourself; every deploy then waits for
  a click on "Approve".
- **Environment secrets**:

| Secret | Value | Required |
|---|---|---|
| `EC2_HOST` | Public IP (or DNS name) of the instance | yes |
| `EC2_SSH_KEY` | Contents of `sahi_deploy_key` (the private key, including the BEGIN/END lines) | yes |
| `EC2_SSH_KNOWN_HOSTS` | The verified `ssh-keyscan` line from step 2 | yes |

Repository **variables** (Settings → Secrets and variables → Actions → Variables), all optional:

| Variable | Default | Purpose |
|---|---|---|
| `EC2_SSH_USER` | `deploy` | SSH user |
| `EC2_SSH_PORT` | `22` | SSH port |
| `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `AWS_SG_ID` | unset | Open port 22 only for the runner's IP during a deploy (see below) |

Application secrets (Angel One keys, `SECRET_KEY`) are **not** stored in GitHub. They live only on the server in
`/etc/sahi/sahi.env`.

`GITLEAKS_LICENSE` is only needed if the repository is moved into a GitHub **organization**.

### 4. Protect `main`

Settings → **Branches → Add branch ruleset** (or classic protection rule) for `main`:
- Require a pull request before merging
- Require status checks to pass: `Backend (lint, tests, boot)`, `Frontend (types, tests, build)`,
  `Server config (shellcheck, nginx -t, sudoers)`, `Secret scan (gitleaks) + repo hygiene`,
  `Python dependency audit`, `npm dependency audit`
- Block force pushes and deletions

### 5. Optional: keep SSH closed to the internet

GitHub's runners use thousands of IP addresses, so with plain SSH deploys port 22 must be open to `0.0.0.0/0`
(key-only login for a user that can run three scripts — acceptable, but not ideal). To keep port 22 closed except
during a deploy:

1. In AWS IAM create an OIDC identity provider for `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`).
2. Create a role trusted by that provider with the condition
   `token.actions.githubusercontent.com:sub = repo:<owner>/<repo>:environment:production`, and a policy allowing only
   `ec2:AuthorizeSecurityGroupIngress` and `ec2:RevokeSecurityGroupIngress` on the instance's security group.
3. Set the variables `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION` (e.g. `ap-south-1`) and `AWS_SG_ID`.
4. Remove the `0.0.0.0/0` rule for port 22 (keep a rule for your own IP for admin access).

The deploy job then adds a `/32` rule for its own IP, deploys, and always removes the rule again.

## Day-to-day

```bash
git switch -c feature/my-change      # work on a branch
git push -u origin feature/my-change # CI runs
# open a pull request to main on GitHub; merge when green -> automatic deploy
```

- **Watch a deploy**: GitHub → Actions → Deploy → the latest run. The "Install release" step shows every server step.
- **Re-deploy the current main** (e.g. after fixing the server): Actions → Deploy → Run workflow.
- **Deployed versions**: tags `deploy-YYYYMMDD-HHMMSS-<sha>` on GitHub, and on the server
  `cat /opt/sahi/DEPLOYED_REVISION` / `/var/log/sahi/deploy-history.log`.
- Two deploys never run at the same time (`concurrency: deploy-production`); a second one waits.

## Updating dependencies

Python (hash-pinned; run on any OS, the lock targets Linux + Python 3.14):

```bash
cd backend
pip install uv
# edit requirements.txt (runtime) or requirements-dev.in (tools), then:
uv pip compile requirements.txt   --universal --python-version 3.14 --generate-hashes --no-header -o requirements.lock
uv pip compile requirements-dev.in --universal --python-version 3.14 --generate-hashes --no-header -o requirements-dev.lock
# to upgrade one package: add  --upgrade-package <name>  to the first command
```

Open a pull request with the changed files; CI and the audits must pass before it can be deployed.

Frontend: Dependabot opens weekly pull requests; or `npm install <pkg>@<version>` and commit `package-lock.json`.
Nothing is upgraded or merged automatically.
