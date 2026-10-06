# Plan bounded, valid Decision Batches

The Industrial World Model study evaluates all existing Decision Action types together, but independent action choices can conflict and unrestricted numeric controls make search unbounded. Each versioned Decision Request supplies a finite catalog of valid candidates, and the planner selects a complete Decision Batch that passes joint validation. A Machine action that requires an idle resource receives a no-effect action in the current batch and a new request at the next eligible idle boundary; unrelated valid actions proceed in the current atomic batch.
