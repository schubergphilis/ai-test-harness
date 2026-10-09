import importlib
import textwrap

import pytest

HARNESSES = """
[ports]
docker_local = 18080
qa = 18400

[[harness]]
name = "alpha"
index = 1
language = "python"
package = "alpha-sdk"
repo = "org/alpha"
licence = "MIT"

[[harness]]
name = "beta-js"
index = 7
language = "node"
package = "@org/beta"
repo = "org/beta"
licence = "Apache-2.0"
"""

MODELS = """
[[model]]
alias = "fake"
kind = "mock"
default_qa = true
red_team = false

[[model]]
alias = "compat"
kind = "sovereign"
base_url = "T_COMPAT_URL"
api_key = "T_COMPAT_KEY"
model = "T_COMPAT_MODEL"
default_qa = true
red_team = true

[[model]]
alias = "router"
kind = "frontier"
provider = "openrouter"
api_key = "T_OR_KEY"
model = "T_OR_MODEL"
default_qa = false
red_team = true

[[model]]
alias = "rock"
kind = "frontier"
provider = "bedrock"
model = "T_BR_MODEL"
region = "T_BR_REGION"
aws_profile = "T_BR_PROFILE"
default_qa = false
red_team = false
"""


@pytest.fixture
def reg(tmp_path, monkeypatch):
    import registry
    registry = importlib.reload(registry)
    (tmp_path / "harnesses.toml").write_text(HARNESSES)
    (tmp_path / "models.toml").write_text(MODELS)
    monkeypatch.setattr(registry, "ROOT", tmp_path)
    monkeypatch.setattr(registry, "HARNESS_FILE", tmp_path / "harnesses.toml")
    monkeypatch.setattr(registry, "MODEL_FILE", tmp_path / "models.toml")
    for v in ("T_COMPAT_URL", "T_COMPAT_KEY", "T_COMPAT_MODEL", "T_OR_KEY", "T_OR_MODEL", "T_BR_MODEL", "T_BR_REGION",
              "T_BR_PROFILE"):
        monkeypatch.delenv(v, raising=False)
    return registry


def test_names_ports_and_lookup(reg):
    assert reg.names() == ["alpha", "beta-js"]
    assert reg.port("alpha", "qa") == 18401
    assert reg.port("beta-js", "docker_local") == 18087
    assert reg.harness("beta-js")["language"] == "node"
    with pytest.raises(KeyError):
        reg.harness("nope")


def test_port_shift_moves_every_range(reg, monkeypatch):
    monkeypatch.setenv("AGENTRT_PORT_SHIFT", "40")
    assert reg.port("alpha", "qa") == 18441
    assert reg.runtime_port({"port_base": 18700}, "beta-js") == 18747


@pytest.mark.parametrize("bad", ["10", "80", "-20"])
def test_port_shift_rejects_overlapping_values(reg, monkeypatch, bad):
    monkeypatch.setenv("AGENTRT_PORT_SHIFT", bad)
    with pytest.raises(ValueError):
        reg.port_shift()


def test_start_command_by_language(reg):
    assert reg.start_command("beta-js", 1234) == ["node", "dist/server.js"]
    cmd = reg.start_command("alpha", 1234)
    assert cmd[:3] == ["uv", "run", "uvicorn"] and "1234" in cmd


@pytest.mark.parametrize("bad", [
    'name = "Bad_Name"\nindex = 2\nlanguage = "python"',
    'name = "dup"\nindex = 1\nlanguage = "python"',
    'name = "ok-name"\nindex = 20\nlanguage = "python"',
    'name = "ok-name"\nindex = 3\nlanguage = "rust"',
])
def test_invalid_harness_entries_rejected(reg, bad):
    extra = "\n[[harness]]\n" + bad + '\npackage = "p"\nrepo = "o/r"\nlicence = "MIT"\n'
    reg.HARNESS_FILE.write_text(HARNESSES + extra)
    with pytest.raises(ValueError):
        reg.harnesses()


def test_model_filters_and_configuration(reg, monkeypatch):
    aliases = lambda ms: [m["alias"] for m in ms]  # noqa: E731
    assert aliases(reg.models()) == ["fake", "compat", "router", "rock"]
    compat = reg.models()[1]
    assert reg.missing_env(compat) == ["T_COMPAT_URL", "T_COMPAT_KEY", "T_COMPAT_MODEL"]
    for v in ("T_COMPAT_URL", "T_COMPAT_KEY", "T_COMPAT_MODEL"):
        monkeypatch.setenv(v, "x")
    assert reg.missing_env(compat) == []
    rock = reg.models()[3]
    assert reg.missing_env(rock) == ["T_BR_MODEL", "T_BR_REGION"]  # aws_profile is optional
    assert "T_BR_PROFILE" in reg.model_env_vars(rock)
    assert reg.missing_env(reg.models()[0]) == []  # mock needs nothing


def test_litellm_generation_per_provider(reg):
    out = reg.gen_litellm()
    assert out.startswith("# GENERATED")
    blocks = {b.split()[0]: b for b in out.split("  - model_name: ")[1:]}
    assert "api_base: os.environ/MOCK_LLM_BASE_URL" in blocks["fake"]
    assert "custom_llm_provider: openai" in blocks["compat"] and "api_base: os.environ/T_COMPAT_URL" in blocks["compat"]
    assert "custom_llm_provider: openrouter" in blocks["router"] and "api_base" not in blocks["router"]
    assert "api_key: os.environ/T_OR_KEY" in blocks["router"]
    assert "custom_llm_provider: bedrock" in blocks["rock"]
    assert "aws_region_name: os.environ/T_BR_REGION" in blocks["rock"]
    assert "aws_profile_name: os.environ/T_BR_PROFILE" in blocks["rock"] and "api_key" not in blocks["rock"]


def test_unknown_provider_rejected(reg):
    reg.MODEL_FILE.write_text(MODELS + textwrap.dedent('''
        [[model]]
        alias = "weird"
        kind = "frontier"
        provider = "carrier-pigeon"
        model = "X"
        '''))
    with pytest.raises(ValueError):
        reg.gen_litellm()


def test_compose_and_k8s_generation(reg):
    compose = reg.gen_compose()
    assert "x-agent: &agent" in compose
    assert "agentrt/beta-js:dev" in compose and '"127.0.0.1:18087:8080"' in compose
    k8s = reg.gen_k8s("alpha")
    assert "namePrefix: alpha-" in k8s and "newName: agentrt/alpha" in k8s


def test_gen_check_round_trip(reg, capsys):
    assert reg.gen(check=True) == 1                     # nothing generated yet -> stale
    assert reg.gen(check=False) == 0
    assert reg.gen(check=True) == 0                     # in sync
    (reg.ROOT / "runtimes/docker-local/litellm.yaml").write_text("tampered")
    assert reg.gen(check=True) == 1
    orphan = reg.ROOT / "runtimes/k8s/overlays/removed-harness"
    orphan.mkdir(parents=True)
    reg.gen(check=False)
    assert not orphan.exists()                          # overlays of removed harnesses are cleaned up
    assert "stale:" in capsys.readouterr().out


@pytest.mark.parametrize("egress", ["open", "proxy-only"])
def test_container_runtime_egress(reg, egress):
    r = {"name": "rt", "harnesses": ["alpha"], "kind": "container", "port_base": 18700, "egress": egress}
    compose = reg.gen_compose_runtime(r)
    agent = compose.split("  alpha-rt:\n", 1)[1].split("\n  alpha-rt-gw:", 1)[0]
    if egress == "open":
        assert '"127.0.0.1:18701:8080"' in agent and "internal: true" not in compose
    else:  # agent only on the internal network, the gateway publishes its port, litellm joins that network
        assert "networks: [rt-egress]" in agent and "ports:" not in agent
        gw = compose.split("  alpha-rt-gw:", 1)[1]
        assert '"127.0.0.1:18701:8080"' in gw and "TCP:alpha-rt:8080" in gw
        assert "  litellm:\n    networks: [default, rt-egress]" in compose and "internal: true" in compose
