from bian_quant.data.adapters.fear_greed import RevisionRisk

MAX_PROMOTION_LEVEL = "observed"


def can_promote_to(target_level: str, required_risks: list[str]) -> bool:
    if target_level not in ("observed", "validated", "alpha"):
        return False
    if RevisionRisk.BACKFILLED_REVISED.value in required_risks:
        return target_level == MAX_PROMOTION_LEVEL
    return True


def enforce_ceiling(target_level: str, required_risks: list[str]) -> None:
    if target_level not in ("observed", "validated", "alpha"):
        raise ValueError(f"Unknown promotion level: {target_level}")
    if (
        RevisionRisk.BACKFILLED_REVISED.value in required_risks
        and target_level != MAX_PROMOTION_LEVEL
    ):
        raise ValueError(
            f"Cannot promote above '{MAX_PROMOTION_LEVEL}' when a required dataset has "
            f"{RevisionRisk.BACKFILLED_REVISED.value} risk"
        )
