# Make production resource semantics explicit

An Operation acquires all required resources atomically before starting, uses blocking-after-service by default when its output cannot advance, and declares whether interruption causes resume, restart, or scrap. Shift transitions follow an explicit handover rule rather than implicitly preempting work; these constraints reduce modeling convenience in exchange for deterministic behavior and avoiding partial-reservation deadlocks.

