# Automatic base frame cap for frame generation.
# A cap only paces well when every shown frame stays on screen for the same number of display
# refreshes, i.e. when refresh is a multiple of cap * multiplier (at 2x on 120 Hz: 60, 30, 20
# or 15). Auto picks the highest such step the game actually holds, measured from its sessions:
# the cap only takes effect at launch, so each session's measurement sets the next one's cap.

STEPS = (60, 40, 30, 24, 20, 15)
DEFAULT_TARGET = 30   # before any measurement: what heavier games hold on this device
HOLD = 1.03           # a step counts as held when the game's typical base rate is within 3%
PINNED = 0.8          # share of samples at the cap for the game to try one step higher
WARMUP_S = 20         # ignore a session's first seconds (shader compiles, menus loading)
MIN_SAMPLES = 15


def steps(refresh: int, multiplier: int) -> list[int]:
    """Evenly paced caps for this refresh rate and multiplier, highest first."""
    out = [c for c in STEPS if c * multiplier <= refresh and refresh % (c * multiplier) == 0]
    return out or [max(10, refresh // multiplier)]


def summarize(samples: list[float], cap: int | None) -> dict | None:
    """A session's base frame rates -> typical rate and how often it sat at the cap."""
    if len(samples) < MIN_SAMPLES:
        return None
    s = sorted(samples)
    median = s[len(s) // 2]
    kept = [x for x in s if x >= 0.5 * median]  # loading screens and stalls
    base = kept[int(0.2 * len(kept))]            # held 80% of the time
    at_cap = sum(x >= 0.95 * cap for x in kept) / len(kept) if cap else 0.0
    return {"base": round(base, 1), "median": round(median, 1), "at_cap": round(at_cap, 2),
            "cap": cap, "samples": len(kept)}


def decide(measure: dict | None, refresh: int, multiplier: int, failed: list[int]) -> int:
    st = steps(refresh, multiplier)
    if not measure:
        return next((c for c in st if c <= DEFAULT_TARGET), st[-1])
    cap = measure.get("cap")
    if cap and measure["at_cap"] >= PINNED:
        # held its cap all session: it may do more, so try the next step up once
        higher = [c for c in st if c > cap and c not in failed]
        if higher:
            return min(higher)
        return max([c for c in st if c <= cap] or [st[-1]])
    fit = [c for c in st if c <= measure["base"] * HOLD]
    return max(fit) if fit else st[-1]


def failed_after(measure: dict | None, failed: list[int]) -> list[int]:
    """Steps the game couldn't hold aren't probed again (until the game's settings are reset)."""
    if measure and measure.get("cap") and measure["at_cap"] < 0.5 and \
            measure["base"] * HOLD < measure["cap"] and measure["cap"] not in failed:
        return sorted(failed + [measure["cap"]])
    return failed
