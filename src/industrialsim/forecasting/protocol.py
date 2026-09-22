from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence
import numpy as np


@dataclass(frozen=True)
class ForecastResult:
    """Container for point and quantile time-series forecasts."""

    point_forecast: dict[str, np.ndarray]  # target_name -> 1D array of shape (horizon,)
    quantile_forecast: dict[str, np.ndarray]  # target_name -> 2D array of shape (horizon, num_quantiles)
    quantiles: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_mean(self, target: str) -> np.ndarray:
        if target not in self.point_forecast:
            raise KeyError(f"Target '{target}' not in point forecast. Available: {list(self.point_forecast.keys())}")
        return self.point_forecast[target]

    def get_quantile(self, target: str, q: float) -> np.ndarray:
        if target not in self.quantile_forecast:
            raise KeyError(f"Target '{target}' not in quantile forecast. Available: {list(self.quantile_forecast.keys())}")
        # Find closest quantile
        idx = min(range(len(self.quantiles)), key=lambda i: abs(self.quantiles[i] - q))
        return self.quantile_forecast[target][:, idx]


class TimeSeriesForecaster(Protocol):
    """Protocol for zero-shot and baseline multivariate forecasters."""

    def forecast(
        self,
        past_targets: dict[str, np.ndarray],
        past_covariates: dict[str, np.ndarray] | None = None,
        future_covariates: dict[str, np.ndarray] | None = None,
        horizon: int = 64,
    ) -> ForecastResult:
        """Generate forecasts for the specified horizon."""
        ...
