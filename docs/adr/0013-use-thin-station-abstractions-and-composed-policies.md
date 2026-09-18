# Use thin Station abstractions and composed policies

Station implementations conform to a thin abstract interface for identity, typed ports, observable state, and event handling, while cycle timing, resource demand, quality effects, degradation, and failure behavior are supplied by composed registered policies. This honors a stable Station extension contract without creating deep inheritance trees whose combinations would be difficult to configure and test.

