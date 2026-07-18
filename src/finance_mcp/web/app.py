"""FastAPI application entrypoint for the internal UI.

Routes land in Stage 6 (Internal UI); this stub exists so the
`finance-web` console script and package layout are wired up from
Stage 1 onward.
"""

from fastapi import FastAPI

app = FastAPI(title="finance-mcp — internal UI")


def main() -> None:
    raise NotImplementedError(
        "Internal UI routes land in Stage 6 — see the README status checklist for progress."
    )


if __name__ == "__main__":
    main()
