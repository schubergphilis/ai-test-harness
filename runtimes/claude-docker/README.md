# claude-docker runtime

A **harness-specific runtime**: it runs only the `claude-code` harness, the way
[claude-docker](https://github.com/schubergphilis/claude-docker) runs Claude Code: on its hardened image and with
its guardrail flags. The harness itself ([harnesses/claude-code](../../harnesses/claude-code/README.md)) has a
plain image and runs on every generic runtime; this runtime swaps in `Dockerfile` here, which builds FROM
`ghcr.io/schubergphilis/claude-docker:v0.3.3` (pinned by digest), as `agentrt/claude-code:claude-docker`.

| claude-docker guardrail | here |
|---|---|
| pinned, scanned image (hadolint, dockle, grype); pinned Claude Code CLI | base image; the harness uses the image's CLI (`CLAUDE_CLI_PATH=claude`) |
| entrypoint drops root to an unprivileged user (`runuser`), Claude Code ends up with no capabilities | kept: base `ENTRYPOINT`, `HOST_UID=10001` |
| `--init`, `--security-opt no-new-privileges`, `--cap-drop ALL` + `CHOWN SETUID SETGID DAC_READ_SEARCH` | `run.sh` and the QA runner (`make qa-box`, sandbox `claude-docker`) via `scripts/registry.py run-args claude-docker`; `docker-compose.yml` (service `claude-code-claude-docker`) and the k8s overlay `runtimes/k8s/overlays/claude-docker`, generated from `[[runtime]]` in `harnesses.toml`; all from one list in `scripts/registry.py` |
| credential dirs masked with tmpfs unless opted in (`~/.aws`, gh, glab, terraform, azure) | all masked; no credential flags are used |
| no persistent volumes (`--ephemeral`) | no volumes |
| model access only via an explicit gateway (`--api`: `ANTHROPIC_BASE_URL` …) | the harness derives `ANTHROPIC_BASE_URL` from `OPENAI_BASE_URL` (the litellm proxy) |
| network: Docker's default bridge, so the agent can reach any host | **limited here** (`egress = "proxy-only"`): the container is on its own `--internal` network; a gateway container (`runtimes/egress-gw`, socat, read-only, no capabilities) forwards only the LiteLLM port (and the OTLP port when tracing is on) and publishes the API port. `run.sh` and the QA runner do this (`scripts/egress_gw.py`); `docker-compose.yml` and the k8s overlay do **not** yet (use a NetworkPolicy there) |
| GitHub auth-proxy sidecar, `--ro` workspaces | not applicable: the canary needs no GitHub access and no workspace |

Two ways to run it; both serve on `127.0.0.1:18706` (`port_base` in `harnesses.toml`), next to the generic
claude-code harness on 18086:

```bash
# A: native litellm + plain docker run
make native-up
docker build -f runtimes/claude-docker/Dockerfile -t agentrt/claude-code:claude-docker .
docker build -t agentrt/egress-gw:dev runtimes/egress-gw     # proxy-only gateway
runtimes/claude-docker/run.sh sovereign

# B: everything in Compose (litellm in a container too, so stop the native one first: both use :4000)
make native-down && make up-claude-docker MODEL=sovereign

make test RUNTIME=claude-docker HARNESS=claude-code   # conformance suite against the container
```

Status: the image is built in CI; running it locally with these flags has not been exercised yet (see the
repo README, "Status and limitations").

Checking the egress limit: the QA `box` suite runs `sandbox_no_internet` (`qa/egress.py`), which starts the image
on the same proxy-only network and fetches `http://ifconfig.co/json` from inside. It passes only when that fails
**and** the LiteLLM proxy answers (so a broken network is an error, not a pass). By hand, with `run.sh` running:
`docker exec -u claude agentrt-claude-code curl -sm 8 ifconfig.co/json` must fail with "Could not resolve host".
