# Separate the simulation kernel from the production domain

The simulation kernel is limited to simulation time, deterministic event ordering, checkpointable random streams, resource allocation, and process activation. Automotive-production concepts such as plants, halls, stations, workers, vehicles, and buffers belong to a separate domain layer, while the organizational location hierarchy and the directed material-flow graph remain orthogonal models; this prevents domain growth or layout changes from coupling to the engine.

