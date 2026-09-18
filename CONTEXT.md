# Industrial Production Simulation

This context describes an automotive plant as a reproducible discrete-event environment for comparing production-control policies and external decision agents.

## Plant structure

**Plant**:
The complete simulated production site and the root of its organizational location hierarchy.
_Avoid_: Factory, Site

**Area**:
An organizational subdivision of a Plant that contains one or more Halls.
_Avoid_: Department, Shop

**Hall**:
A physical subdivision of an Area that provides locations for production and logistics resources.
_Avoid_: Building, Shop Floor

**Material Flow Graph**:
The directed multigraph of production and storage nodes connected by transport routes. It permits cycles and parallel routes and is independent of the Plant's organizational location hierarchy.
_Avoid_: Plant hierarchy, Production tree

**Port**:
A typed input or output boundary through which a material-flow node accepts or releases Production Units.
_Avoid_: Endpoint, Connector

## Production

**Production Unit**:
An individually identified vehicle or body whose product variant, quality state, and production history are tracked throughout a run. It is always located at exactly one material-flow node, in one transport, or in a terminal state.
_Avoid_: Product, Workpiece, Item

**Station**:
A material-flow node that performs declared Operations while holding the required production resources.
_Avoid_: Machine, Workplace

**Operation**:
A declared production transformation that may change Production Units, combine or split them, or result in rework or scrap.
_Avoid_: Step, Task

**Production Plan**:
The episode input that declares planned release times, product variants, quantities, and optional due dates for Production Units.
_Avoid_: Demand, Schedule

**Process Plan**:
The ordered production requirements for a product variant, including compatible alternatives and any explicit rework Operations.
_Avoid_: Route, Recipe

**Buffer**:
A capacity-constrained material-flow node that holds Production Units between Operations or transports.
_Avoid_: Queue, Storage

**Worker**:
An individual or pooled production resource with qualifications, shift availability, and breaks.
_Avoid_: Operator, Employee, Human resource

**Machine**:
A production resource whose capacity, availability, and condition may constrain an Operation. A Machine is used by a Station but is not itself a Station.
_Avoid_: Station, Equipment

**Health State**:
The condition of a Machine, including a normalized health value and any explicitly modeled physical state variables that influence its behavior.
_Avoid_: Wear, Condition score

**Quality State**:
The latent condition of a Production Unit, including defects that may not yet have been detected.
_Avoid_: Inspection result, Quality score

**Quality Finding**:
An observed indication about a Production Unit produced by an inspection with imperfect sensitivity and specificity.
_Avoid_: Quality State, Defect

## Logistics

**Transport Order**:
A request to move one or more Production Units between material-flow nodes.
_Avoid_: Delivery, Move

**Dispatch Policy**:
A replaceable decision policy that assigns Transport Orders to vehicles and routes.
_Avoid_: Scheduler, Router

**Routing Policy**:
A replaceable decision policy that selects a compatible Station and material-flow route for the next requirement in a Process Plan.
_Avoid_: Process Plan, Dispatch Policy

## Decisions and evaluation

**Decision Request**:
A typed, versioned request emitted at a consistent pause point, containing a bounded observation and an explicit action schema.
_Avoid_: Hook, Prompt

**Decision Batch**:
The complete set of Decision Requests emitted at one consistent pause point and answered against the same observed state.
_Avoid_: Request queue, Decision group

**Decision Provider**:
A transport-independent participant that answers a Decision Request with a proposed action.
_Avoid_: Agent, LLM

**Reward Policy**:
An experiment-specific rule that derives an optional scalar reward from raw simulation metrics without redefining hard constraints.
_Avoid_: Objective, Score

**Episode**:
A bounded simulation run evaluated as one training or comparison sample, optionally preceded by an excluded warm-up period.
_Avoid_: Run, Trial

**Experiment**:
A reproducible definition of Episodes, policies, seeds, configurations, and evaluation criteria used for a comparison or training objective.
_Avoid_: Episode, Scenario

**Fallback Policy**:
A deterministic rule that supplies an action when a Decision Provider fails or proposes an invalid action.
_Avoid_: Default action, Recovery

**Checkpoint**:
A versioned snapshot containing all state required to continue a run reproducibly.
_Avoid_: Save, Backup

**Deadlock**:
A terminal state in which unfinished production cannot make domain progress because Production Units, resources, or Buffers form unresolved wait relationships.
_Avoid_: Idle time, Downtime

**Counterfactual Branch**:
An isolated continuation from a checkpoint used to compare an alternative action under controlled randomness.
_Avoid_: Scenario, Copy
