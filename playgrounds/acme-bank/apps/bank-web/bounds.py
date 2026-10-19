"""What the page may say of the time of a call: the bounds a link of the evidence and the answers a run hands back are held to."""

AT_RANGE = (946_684_800_000, 4_102_444_800_000)      # 2000 to 2100, in epoch ms: nothing outside is a call of this page
SPAN = 24 * 3600 * 1000                              # a run is a day at most
FUTURE = 60_000                                      # a call is not later than this from now


def moment(value: object) -> int | None:
    """A time of a call the page handed back, in epoch ms, or None where it is not one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and AT_RANGE[0] <= value <= AT_RANGE[1] else None
