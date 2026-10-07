# OpenShell runtime (NVIDIA OpenShell 0.1.x, alpha)

Runs the **same harness image** inside an OpenShell sandbox:
- default-deny egress (`policy.yaml`)
- Landlock filesystem limits
- optional credential injection through a provider (`litellm-provider.yaml`)

**Status: written from the v0.1.2 docs and source, not yet run.** Docker is stopped for now (memory).

## How it maps to the compat contract
| contract item | OpenShell |
|---|---|
| image unchanged | ✅ `--from agentrt/<h>:dev` takes local Docker images directly (no registry) |
| CMD | ❌ ignored. The supervisor replaces ENTRYPOINT/CMD, so `run.sh` passes the start command after `--` |
| `:8080` reachable | `openshell forward service --target-port 8080 --local <openshell port>` (harnesses.toml: 38080 + index) (gRPC tunnel; the only option that lets us pick the host port) |
| LLM endpoint | `http://host.openshell.internal:4000/v1`, allowed in `policy.yaml` |
| secrets | `--env` is for non-secrets only. Proper path: provider profile → sandbox sees a placeholder key |
| restart | none. If the main process exits, the sandbox is done |

## Run
```bash
make up HARNESS=strands                      # litellm + mock + image built
openshell doctor check
openshell-gateway --compute-driver docker --disable-tls &
openshell gateway add http://127.0.0.1:17670 --local --name local && openshell gateway select local
runtimes/openshell/run.sh strands            # → http://localhost:38081
make test RUNTIME=openshell HARNESS=strands
```
Docker Desktop must have host networking enabled and Enhanced Container Isolation disabled.

## Verify first (open questions)
1. **Can `host.openshell.internal:4000` reach litellm?** Compose publishes litellm on `127.0.0.1:4000`, and loopback is always blocked inside sandboxes. If the call fails, publish litellm on the Docker bridge or the host IP, or point the sandbox straight at the private proxy (`<fqdn>:443`).
2. **Binary-path matching.** The policy keys egress on the real executable. The venv `python` is a symlink to `/usr/local/bin/python3.13`; confirm the glob matches.
3. **Is `/app` usable as the workspace?** The images now `chown` `/app` to the runtime user.
4. **Does `--detach` work together with `forward service`?**
