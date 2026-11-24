# Deploying to onekami.site

Branch: `deployed`. Target: one organization, up to 20 members, 10 to 15 people using it at the same time.

```
browser ──https──> Cloudflare Worker "onekami-site"  (Next.js via OpenNext, built from git by Workers Builds)
                        │  server-side fetch with an Access service token
                        ▼
                   api.onekami.site  (Cloudflare Access: service token only)
                        │  Cloudflare Tunnel (outbound connection from the server; no open ports)
                        ▼
Linode 194.195.112.145 (Ubuntu 24.04, 2 vCPU, 3.8 GiB) ── Docker Compose, project `lmqa`
   cloudflared ─> gateway :8000 (API, local embeddings, re-ranker, ingestion)
                  postgres+pgvector, pgbouncer, valkey, qdrant, seaweedfs, openbao  (127.0.0.1 only)
```

What changed on this branch:

| Change | Where |
| --- | --- |
| Local embeddings (`EMBEDDING_PROVIDER=local`, default model `BAAI/bge-base-en-v1.5`, 768 dimensions) | `libs/lmqa_vectorstore/src/lmqa_vectorstore/local_embeddings.py`, `libs/lmqa_models/src/lmqa_models/settings.py` |
| `LMQA_ENV_FILE` picks the settings file (`.env.deployed` on the server) | `libs/lmqa_models/src/lmqa_models/envfile.py` |
| API and tunnel containers, sized for this server | `compose.deployed.yaml`, `infra/docker/service.Dockerfile`, `.dockerignore` |
| `make deploy-setup`, `deploy-up`, `deploy-update`, `deploy-ps`, `deploy-logs`, `deploy-doctor`, `deploy-down` | `Makefile`, `tools/deploy_check.py` |
| Next.js on Cloudflare Workers (OpenNext), Access service-token headers on calls to the API | `frontend/wrangler.jsonc`, `frontend/open-next.config.ts`, `frontend/src/lib/backend.ts`, `frontend/src/app/api/backend/[...path]/route.ts` |
| Pack and restore the git-ignored files | `tools/pack-ignored.sh`, `tools/unpack-ignored.sh` |

The answer model stays on Gemini. Only embeddings (and, as before, the re-ranker) run on the server.

---

## 1. On the laptop: push the branch and pack the ignored files

```sh
cd ~/Downloads/LMQA/legal-medical-qa
git push -u origin deployed
tools/pack-ignored.sh                        # writes lmqa-ignored-<date>.zip (mode 600) in the repo root
scp lmqa-ignored-*.zip root@194.195.112.145:/root/
```

The zip holds every git-ignored file: `.env`, `.env.deployed`, the `.env.bak-*` files, `.secrets.*`, Terraform state,
`.kiro/specs/legal-medical-qa/reports/`, `agent_work/`, `gates/` artifacts, `data/` (without downloaded models and
rendered credentials) and `corpus/data/`. It leaves out what is rebuilt or downloaded again (`.venv`, `node_modules`,
`.next`, caches, `data/models`, `data/infra`); `tools/pack-ignored.sh --all` includes those too. It contains secrets:
copy it only over SSH.

To move Kiro as well, copy your user-level Kiro folder (steering, agents, settings):
`scp -r ~/.kiro root@194.195.112.145:/root/`. The project's `.kiro/` comes with the clone and the zip.

## 2. Prepare the server

```sh
ssh root@194.195.112.145

apt update && apt -y upgrade
apt -y install git make zip unzip curl ca-certificates ufw

# 2 GiB more swap (the Linode swap disk has 495 MiB): headroom for model loading and PDF parsing peaks
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf

# Firewall: SSH only. The tunnel is outbound, and every container port is bound to 127.0.0.1.
ufw allow OpenSSH && ufw --force enable

# Docker Engine and the Compose plugin (official repository)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt update && apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# uv (Python toolchain; it downloads Python 3.14 itself)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env

# Kiro CLI (optional, to keep working on the server)
curl -fsSL https://cli.kiro.dev/install | bash
kiro-cli login
```

## 3. Clone the branch and restore the ignored files

```sh
git clone --branch deployed <your-repo-url> /opt/legal-medical-qa
cd /opt/legal-medical-qa
tools/unpack-ignored.sh /root/lmqa-ignored-*.zip
shred -u /root/lmqa-ignored-*.zip
echo 'export LMQA_ENV_FILE=.env.deployed' >> ~/.bashrc && export LMQA_ENV_FILE=.env.deployed
```

`unpack-ignored.sh` never overwrites a tracked file and keeps existing files unless you pass `--force`. With
`LMQA_ENV_FILE` set, plain `make doctor` and `make migrate` read `.env.deployed` as well; the `deploy-*` targets set it
themselves.

## 4. Cloudflare: tunnel for the API

The domain `onekami.site` must already use Cloudflare's nameservers.

1. Zero Trust → Networks → Tunnels → **Create a tunnel** → Cloudflared → name `lmqa`.
2. On the install page, copy the token (the long string after `--token`). Do not run the install command; the token
   goes into `.env.deployed` and the `cloudflared` container uses it.
3. **Public hostname** (called *published application route* in newer dashboards): subdomain `api`, domain
   `onekami.site`, service type `HTTP`, URL `gateway:8000`. Cloudflare creates the DNS record.

## 5. Cloudflare: Access in front of the API

Only the Worker may call the API.

1. Zero Trust → Access → Service auth → Service Tokens → **Create** → name `onekami-worker`, duration non-expiring
   (or one year, with a reminder). Copy the **Client ID** and **Client Secret** (the secret is shown once).
2. Zero Trust → Access → Applications → **Add an application** → Self-hosted → domain `api.onekami.site`.
3. Add a policy: action **Service Auth**, include **Service Token** = `onekami-worker`. No other policy.

## 6. Auth0

Use the same tenant as on the laptop, with an application dedicated to the site:

1. Applications → **Create Application** → Regular Web Application → `Cyte (onekami.site)`.
   - Allowed Callback URLs: `https://onekami.site/auth/callback`
   - Allowed Logout URLs: `https://onekami.site`
   - Allowed Web Origins: `https://onekami.site`
   - Copy the Client ID and Client Secret (they go to the Worker, step 9).
2. Applications → APIs: the API with identifier `https://api.onekami.site` (RS256). Your laptop `.env` already uses
   this identifier. If the API's settings restrict which applications may request it for users, allow the new app.

## 7. Fill in `.env.deployed` and start the backend

```sh
cd /opt/legal-medical-qa
nano .env.deployed
```

Set `AUTH0_DOMAIN`, `GEMINI_API_KEY` (a key dedicated to the site), `CLOUDFLARE_TUNNEL_TOKEN` and, optionally,
`HF_TOKEN`. Leave section 3 empty: the next command generates those secrets. Keep comments on their own lines and
single-quote any value that contains `$` (Docker Compose reads this file too).

```sh
make deploy-setup     # Python deps, fresh secrets into .env.deployed, PostgreSQL/OpenBao/etc., migrations
make deploy-up        # checks .env.deployed, builds the API image, starts gateway + cloudflared
make deploy-ps        # every container healthy; memory per container
make deploy-doctor    # settings, database, Auth0, Gemini, local embeddings and re-ranker
```

The first `deploy-up` takes a few minutes (image build). The gateway then downloads the embedding model (about
0.2 GB) and the re-ranker (about 0.13 GB) into the `lmqa_gateway-data` volume and keeps them there.

Checks:

```sh
curl -s 127.0.0.1:8000/v1/health                       # {"status":"ok", ... "public_site":true}
curl -s -o /dev/null -w '%{http_code}\n' https://api.onekami.site/v1/health   # not 200: Access blocks it
```

Back up `.env.deployed` somewhere safe now (a password manager). `OPENBAO_UNSEAL_KEY` and the database passwords
are bound to the Docker volumes: without them the encrypted data cannot be read.

## 8. Cloudflare Workers: the website from git

1. Workers & Pages → **Create** → Workers → **Import a repository** → pick the repository.
2. Build settings:
   - Project name: `onekami-site` (must match `name` in `frontend/wrangler.jsonc`)
   - Production branch: `deployed`
   - Root directory: `frontend`
   - Build command: `pnpm run build:cf`
   - Deploy command: `npx opennextjs-cloudflare deploy`
   - Non-production branch deploy command: `npx opennextjs-cloudflare upload` (or turn off builds for other branches)
   - Build variables: `APP_BASE_URL=https://onekami.site`, `NEXT_TELEMETRY_DISABLED=1`
3. Save and deploy. Node 24 comes from `frontend/.node-version` and pnpm 10 from `packageManager`.
4. The Worker claims `onekami.site` as a custom domain (`routes` in `wrangler.jsonc`). If the zone already has an A,
   AAAA or CNAME record for the apex, delete it first, or the deploy fails.
5. Optional: Rules → Redirect Rules → `www.onekami.site/*` → `https://onekami.site/${1}` (301), with a proxied DNS
   record for `www` (for example `AAAA www 100::`). Sign-in works only on the apex.

**Plan:** use Workers Paid (5 USD a month). The free plan allows 10 ms of CPU per request; server-rendered pages with
session decryption go past that and fail with error 1102. The compressed bundle is about 2.4 MiB, under both plans'
size limits.

## 9. Worker variables and secrets

Workers & Pages → `onekami-site` → Settings → Variables and Secrets. Add as **Secret**:

| Name | Value |
| --- | --- |
| `AUTH0_DOMAIN` | your tenant, without `https://` |
| `AUTH0_CLIENT_ID_BFF` | Client ID of `Cyte (onekami.site)` |
| `AUTH0_CLIENT_SECRET_BFF` | its Client Secret |
| `AUTH0_SESSION_SECRET` | a new value from `openssl rand -hex 32` |
| `CF_ACCESS_CLIENT_ID` | service token Client ID (step 5) |
| `CF_ACCESS_CLIENT_SECRET` | service token Client Secret (step 5) |

`APP_BASE_URL`, `LMQA_API_INTERNAL_URL` and `AUTH0_AUDIENCE_MAIN` are set in `wrangler.jsonc`. Saving a secret deploys
a new version at once.

## 10. Try it

1. Open https://onekami.site: the public site loads.
2. **Get started** → sign up → **Create an organization**. You are its Super Admin.
3. Invite an admin, upload documents in **Library** (the zip already restored `corpus/data/` if you want the public
   corpus), ask a question, and check the citations.

If something fails: `make deploy-logs` on the server, and Workers & Pages → `onekami-site` → Logs for the Worker.

---

## Day to day

| Task | How |
| --- | --- |
| Ship a change | Commit to `deployed` and push. Cloudflare rebuilds the website. On the server: `make deploy-update` (pull, migrate, rebuild, restart). |
| Status, memory | `make deploy-ps` |
| Logs | `make deploy-logs` |
| Stop / start | `make deploy-down` / `make deploy-up` (containers also restart on reboot) |
| Database backup | `docker exec lmqa-postgres pg_dumpall -U postgres \| gzip > /root/lmqa-$(date +%F).sql.gz` |
| Key and file backup | `docker run --rm -v lmqa_openbao:/v:ro -v /root:/b alpine tar czf /b/openbao-$(date +%F).tgz -C /v .` (same for `lmqa_gateway-data`) |

Copy backups off the server. Restoring the database needs the same `.env.deployed` and the OpenBao volume.

## Capacity and limits

* **10 to 15 people at once** is within this server's range. A question spends most of its time waiting on Gemini;
  the CPU work (embedding the question, re-ranking 30 passages) takes a second or two on this CPU and runs one at a
  time, so simultaneous questions queue for a few seconds at most. One uploaded document of about 200 passages is
  embedded in roughly a minute (an estimate for the EPYC 7713, not yet measured there).
* **Gemini quota is the real limit.** On the free tier the strong models allow about 20 requests a day per key and
  each question uses two to four requests; the fallback chain then moves to Flash-Lite (about 500 a day). For a demo
  with 15 active people, use a key with billing enabled, or several keys in `GEMINI_API_KEYS` with
  `FEATURE_QUOTA_ROTATION=on`.
* **Cloudflare waits 100 seconds** for the API to answer. Answers are delivered whole (sentence streaming is off), so
  a question that takes longer, for example when every model is rate limited, ends with error 524.
* **Re-ranker:** `Xenova/ms-marco-MiniLM-L-12-v2` (English). The laptop's `BAAI/bge-reranker-v2-m3` needs about 2.3 GB
  and does not fit next to the rest of the stack.
* **`APP_ENV=local`** on the server: the public website is a frozen feature that only switches on with `local`
  (`contracts/features.toml`). It also enables the API's `/docs` page, which only the Worker can reach through Access.
* **ClamAV and observability** stay off (1.6 GB and 1 GB of memory).
* The Node.js `proxy.ts` support in OpenNext is marked experimental. It passed a local run in the Workers runtime
  (`wrangler dev`): public pages, the sign-in redirect, the CSP nonce and the Access headers.
* `frontend/shims/critters` is an empty stand-in for an optional Next.js dependency that the OpenNext proxy bundler
  otherwise fails to resolve. It is never loaded.
