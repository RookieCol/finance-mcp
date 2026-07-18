"""Proactive scheduler entrypoint (digests + alerts, no-Hermes fallback delivery).

Job wiring lands in Stage 7 (Proactive scheduler); this stub exists so the
`finance-scheduler` console script and package layout are wired up from
Stage 1 onward.
"""


def main() -> None:
    raise NotImplementedError(
        "Scheduler jobs land in Stage 7 — see the README status checklist for progress."
    )


if __name__ == "__main__":
    main()
