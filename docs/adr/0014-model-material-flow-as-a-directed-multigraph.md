# Model material flow as a directed multigraph

Material flow uses a directed multigraph with typed ports, cycles, and parallel routes, separate from the Plant location hierarchy. Configuration validation checks sources, sinks, port compatibility, and reachability, while every Production Unit must be at exactly one node, in one transport, or terminal; this supports rework and alternate logistics routes at the cost of stronger validation requirements.
