"""Idempotently seeds/patches docker/hermes/data/config.yaml — the file
Hermes Agent actually reads from its bind-mounted /opt/data — with the
model (Ollama) and mcp_servers (finance-mcp) blocks from
docker/hermes/config.yaml.

Why this exists: Hermes generates its own full default config.yaml on
first launch if none is present yet (~30 top-level keys — personalities,
tool_loop_guardrails, etc.), so simply bind-mounting our minimal
docker/hermes/config.yaml over it would either be ignored (file already
exists from a prior run) or lose those Hermes-managed defaults (if we
overwrote wholesale). This script instead merges just the two keys we
care about into whatever's already there, run before every `hermes`
invocation so it's always in sync — see the Makefile's `chat` target.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "docker" / "hermes" / "config.yaml"
TARGET = REPO_ROOT / "docker" / "hermes" / "data" / "config.yaml"


def main() -> None:
    with SOURCE.open() as f:
        source_config = yaml.safe_load(f)

    if TARGET.exists():
        with TARGET.open() as f:
            target_config = yaml.safe_load(f) or {}
    else:
        target_config = {}

    target_config["model"] = source_config["model"]
    target_config["mcp_servers"] = source_config["mcp_servers"]

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w") as f:
        yaml.safe_dump(target_config, f, sort_keys=False, default_flow_style=False)

    print(
        f"Patched {TARGET} with model={source_config['model']['default']!r} "
        f"and mcp_servers={list(source_config['mcp_servers'])!r}"
    )


if __name__ == "__main__":
    main()
