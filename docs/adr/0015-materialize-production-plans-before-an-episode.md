# Materialize Production Plans before an Episode

Each Episode consumes an explicit Production Plan containing release times, variants, quantities, and optional due dates, and creates individually tracked Production Units with deterministic identities. Stochastic demand is materialized before the Episode begins and shared by Counterfactual Branches; this excludes adaptive demand generation during a branch in exchange for fair policy comparisons and reproducible inputs.
