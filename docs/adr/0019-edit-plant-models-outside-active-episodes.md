# Edit Plant models outside active Episodes

The local frontend supports both visual Plant modeling and Episode control, but edits to a Plant configuration apply only to a subsequent Episode. Keep the active Episode's model fixed and permit human intervention through validated Decision Batches instead of arbitrary live model edits; this preserves reproducibility and the consistent decision semantics of ADR-0002 and ADR-0003, at the cost of restarting an Episode to evaluate a changed Plant.
