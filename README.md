# URL Shortener: a containers, Kubernetes and DevSecOps learning project

A tiny bit.ly clone, used to learn Docker, Kubernetes and a secure CI/CD pipeline
step by step. The app is deliberately small so the focus stays on the platform.

```
Browser ──▶ FastAPI app (3 replicas) ──▶ PostgreSQL (links and click counts)
                                    └──▶ Redis (rate limiting, shared by all replicas)
```

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/shorten` | Body `{"url": "https://…"}` → returns a short code |
| `GET` | `/{code}` | Redirects to the original URL and counts the click |
| `GET` | `/api/stats/{code}` | Click count for a code |
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe (checks the database) |
| `GET` | `/` | Small web page to shorten links |

## Stage 0: run it with plain Python

No database needed; it keeps links in memory.

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080.

## Stage 1: one container

```bash
docker build -t url-shortener .
docker run --rm -p 8080:8080 url-shortener
```

Things to try:
- `docker images url-shortener`: see how small the multi-stage build keeps the image.
- `docker run --rm url-shortener whoami` prints an error: the image has no root shell user, it runs as UID 10001.

## Stage 2: app + database + cache with Docker Compose

```bash
copy .env.example .env          # then edit .env and set a password
docker compose up --build
```

Things to try:
- Shorten a link, run `docker compose down`, then `up` again: the link still works (the `pgdata` volume).
- `docker compose down -v` deletes the volume, and the links are gone.

## Stage 3: Kubernetes

Needs a local cluster: Docker Desktop's built-in Kubernetes, [kind](https://kind.sigs.k8s.io/),
or [k3d](https://k3d.io/). The Ingress needs an ingress controller (k3d ships with Traefik).

1. In `k8s/kustomization.yaml`, replace `OWNER` with your GitHub username (lowercase).
   CI publishes the image there. If the package is private, make it public under
   GitHub → your profile → Packages, or create an image pull secret.
2. Create the secret file and deploy:

   ```bash
   copy k8s\secrets.env.example k8s\secrets.env   # then set a password
   kubectl apply -k k8s/
   kubectl -n url-shortener get pods -w
   ```

3. Open http://shortener.localhost, or without an ingress:
   `kubectl -n url-shortener port-forward svc/url-shortener 8080:80`.

Things to try:
- **Self-healing:** `kubectl -n url-shortener delete pod -l app=url-shortener` and watch new pods appear.
- **Scaling:** `kubectl -n url-shortener scale deploy/url-shortener --replicas=6`.
- **Readiness:** `kubectl -n url-shortener scale statefulset/postgres --replicas=0`. App pods
  become *not ready* and stop receiving traffic, but aren't restarted. Scale back to 1.
- **Rollback:** `kubectl -n url-shortener set image deploy/url-shortener app=nginx:doesnotexist`,
  watch the rollout stall, then `kubectl -n url-shortener rollout undo deploy/url-shortener`.
- **Security:** the namespace enforces the `restricted` Pod Security Standard. Try removing
  `runAsNonRoot` from `k8s/app.yaml` and re-applying: Kubernetes refuses the pods.

## The CI/CD pipeline (GitHub Actions)

Every push and pull request runs `.github/workflows/ci.yml`:

| Job | Tool | Catches |
|---|---|---|
| Lint and test | Ruff (with bandit rules), pytest | Bugs, insecure code patterns, broken features |
| Secret scan | Gitleaks | Passwords or keys committed by mistake (whole history) |
| Dependency and config scan | Trivy | Vulnerable libraries, risky Dockerfile/Kubernetes settings |
| Build and image scan | Docker Buildx, Trivy | Vulnerabilities in the final image's OS packages |
| Publish (main only) | ghcr.io, SBOM, provenance | A versioned image plus a list of everything inside it |
| Sign (main only) | Cosign (keyless) | Proof the image was built by this pipeline |

Also:
- `.github/workflows/codeql.yml`: CodeQL static analysis, results under **Security → Code scanning**.
- `.github/dependabot.yml`: weekly pull requests for outdated Python packages, base images and actions.
- All actions are pinned to commit SHAs, so a hijacked tag can't inject code into the pipeline.

Verify a signed image:

```bash
cosign verify ghcr.io/OWNER/url-shortener:main \
  --certificate-identity-regexp "https://github.com/OWNER/url-shortener/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### Break it on purpose

The best way to learn the scanners is to make them fail:
1. Commit a fake AWS key (`AKIAIOSFODNN7EXAMPLE` style) in a branch: Gitleaks fails.
2. Change the base image to an old one like `python:3.8-slim`: the Trivy image scan fails.
3. Add `privileged: true` to `k8s/app.yaml`: the Trivy config scan fails.
4. Use `conn.execute(f"SELECT … {code}")` in `app/store.py`: Ruff's S608 rule and CodeQL flag SQL injection.

## Recommended GitHub settings

- **Settings → Branches → Add rule** for `main`: require a pull request and require the
  CI and CodeQL checks to pass before merging.
- **Settings → Code security**: turn on Dependabot alerts, secret scanning and push protection.

## Roadmap

- [ ] GitOps deployment with Argo CD
- [ ] Kyverno policy: only run images signed by this pipeline
- [ ] OWASP ZAP baseline scan (DAST) against a running instance
- [ ] Prometheus metrics and a Grafana dashboard
- [ ] HorizontalPodAutoscaler and a load test
- [ ] Helm chart
