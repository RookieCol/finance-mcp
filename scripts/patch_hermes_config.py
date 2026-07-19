"""Idempotently seeds/patches docker/hermes/data/config.yaml — the file
Hermes Agent actually reads from its bind-mounted /opt/data — with the
providers/model (OpenRouter), mcp_servers (finance-mcp), and
agent.reasoning_effort overrides from docker/hermes/config.yaml.

Why this exists: Hermes generates its own full default config.yaml on
first launch if none is present yet (~30 top-level keys — personalities,
tool_loop_guardrails, etc.), so simply bind-mounting our minimal
docker/hermes/config.yaml over it would either be ignored (file already
exists from a prior run) or lose those Hermes-managed defaults (if we
overwrote wholesale). This script instead merges just the keys we care
about into whatever's already there, run before every `hermes`
invocation so it's always in sync — see the Makefile's `chat` target.

`agent` is merged shallowly (only the keys present in our source file
are overridden — currently just `reasoning_effort`) rather than replaced
wholesale, since Hermes' generated `agent` block also carries unrelated
keys (personalities, max_turns, ...) we don't want to clobber.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docker" / "hermes" / "config.yaml"
TARGET = REPO_ROOT / "docker" / "hermes" / "data" / "config.yaml"

REPLACED_KEYS = ("providers", "model", "mcp_servers")
MERGED_KEYS = ("agent",)


def main() -> None:
    with SOURCE.open() as f:
        source_config = yaml.safe_load(f)

    if TARGET.exists():
        with TARGET.open() as f:
            target_config = yaml.safe_load(f) or {}
    else:
        target_config = {}

    for key in REPLACED_KEYS:
        target_config[key] = source_config[key]

    for key in MERGED_KEYS:
        if key not in source_config:
            continue
        target_config.setdefault(key, {})
        target_config[key].update(source_config[key])

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w") as f:
        yaml.safe_dump(target_config, f, sort_keys=False, default_flow_style=False)

    print(
        f"Patched {TARGET} with providers={list(source_config['providers'])!r}, "
        f"model={source_config['model']['default']!r}, "
        f"mcp_servers={list(source_config['mcp_servers'])!r}, "
        f"agent overrides={source_config.get('agent', {})!r}"
    )


if __name__ == "__main__":
    main()
