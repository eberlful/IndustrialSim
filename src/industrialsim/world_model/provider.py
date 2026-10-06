"""Frozen world-model planning against public study observations only."""
from __future__ import annotations
from typing import Any, Sequence

from industrialsim.application import _compute_reward
from industrialsim.config import RewardPolicyConfig
from industrialsim.decisions import DecisionBatch, DecisionProvider, DecisionAction
from industrialsim.world_model.contracts import (IndustrialWorldModel, PlantGraph, StudyObservation,
                                                TimedAction, digest)
from industrialsim.world_model.planning import BoundedBatchPlanner, CandidateCatalog, public_batch, response_for, model_action


class WorldModelDecisionProvider(DecisionProvider):
    def __init__(self, model: IndustrialWorldModel, catalog: CandidateCatalog,
                 reward_policy: RewardPolicyConfig, production_plan: Sequence[dict[str, Any]],
                 model_id: str, beam_width: int = 32) -> None:
        self.model, self.catalog, self.reward_policy = model, catalog, reward_policy
        self.production_plan, self.model_id = list(production_plan), model_id
        self.planner = BoundedBatchPlanner(beam_width)
        self.history: list[StudyObservation] = []
        self.graph: PlantGraph | None = None
        self.fallback_count = 0
        self.inference_count = 0
        self.last_ranking: list[dict[str, Any]] = []

    def update_observation(self, observation: StudyObservation, graph: PlantGraph) -> None:
        if self.history and (observation.episode_id, observation.branch_id) != (
                self.history[-1].episode_id, self.history[-1].branch_id):
            self.history.clear()
        if self.history and observation.time_ns <= self.history[-1].time_ns:
            raise ValueError("Study observations must advance monotonically")
        self.history.append(observation)
        self.history = self.history[-32:]
        self.graph = graph

    def decide(self, batch: DecisionBatch) -> Any:
        # Any exception goes to the simulator's existing deterministic fallback.
        # This provider never calls the simulator or trains on test observations.
        try:
            if not self.history or self.graph is None:
                raise ValueError("No study observation for world-model planning")
            batch = public_batch(batch)
            graph = self.graph
            indices = {nid: i for i, nid in enumerate(graph.node_ids)}
            last = self.history[-1]
            catalog = {}
            for req in batch.requests:
                index = indices.get(req.target_id)
                busy = (index is not None and graph.node_types[index] == "machine" and
                        last.values[index][5] > 0)
                catalog[req.request_id] = self.catalog.candidates(req, busy)
            cache: dict[str, float] = {}
            ranking = []
            requests_by_target = {r.target_id: r for r in batch.requests}
            def score(actions: Sequence[DecisionAction]) -> float:
                data = [model_action(a, requests_by_target.get(a.target_id), batch.time_ns) for a in actions]
                key = digest(data)
                if key not in cache:
                    # Shared future policy: retain current settings and request no
                    # further interventions in this ten-step planning horizon.
                    timed = [TimedAction(batch.time_ns, a) for a in data]
                    prediction = self.model.rollout(self.history, graph, timed, self.production_plan, 10)
                    reward, _ = _compute_reward(prediction.metrics[-1], self.reward_policy)
                    if reward is None:
                        raise ValueError("Study planning requires a Reward Policy")
                    cache[key] = -reward
                    ranking.append({"candidate_id": key, "cost": -reward, "actions": data})
                    self.inference_count += 1
                return cache[key]
            def score_many(batches: Sequence[Sequence[DecisionAction]]) -> Sequence[float]:
                rollout_many = getattr(self.model, "rollout_many", None)
                if rollout_many is None:
                    return [score(actions) for actions in batches]
                unique: dict[str, list[dict[str, Any]]] = {}
                keys = []
                for actions in batches:
                    data = [model_action(a, requests_by_target.get(a.target_id), batch.time_ns) for a in actions]
                    key = digest(data)
                    keys.append(key)
                    if key not in cache:
                        unique[key] = data
                if unique:
                    predictions = rollout_many(self.history, graph,
                        [[TimedAction(batch.time_ns, action) for action in data] for data in unique.values()],
                        self.production_plan, 10)
                    for (key, data), prediction in zip(unique.items(), predictions):
                        reward, _ = _compute_reward(prediction.metrics[-1], self.reward_policy)
                        if reward is None:
                            raise ValueError("Missing planning Reward Policy")
                        cache[key] = -reward
                        ranking.append({"candidate_id": key, "cost": -reward, "actions": data})
                        self.inference_count += 1
                return [cache[key] for key in keys]
            actions = self.planner.choose(batch, catalog, score, score_many)
            self.last_ranking = sorted(ranking, key=lambda r: (r["cost"], r["candidate_id"]))
            return response_for(batch, actions, "industrial-world-model", self.model_id)
        except Exception:
            self.fallback_count += 1
            raise
