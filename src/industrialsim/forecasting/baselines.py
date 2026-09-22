from __future__ import annotations

import numpy as np

from industrialsim.forecasting.protocol import ForecastResult, TimeSeriesForecaster
from industrialsim.forecasting.timesfm_adapter import _erf_inv, DEFAULT_QUANTILES


class MovingAverageForecaster(TimeSeriesForecaster):
    """Moving Average baseline with empirical standard deviation quantile estimation."""

    def __init__(
        self,
        window_size: int = 16,
        quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    ) -> None:
        self.window_size = window_size
        self.quantiles = quantiles

    def forecast(
        self,
        past_targets: dict[str, np.ndarray],
        past_covariates: dict[str, np.ndarray] | None = None,
        future_covariates: dict[str, np.ndarray] | None = None,
        horizon: int = 64,
    ) -> ForecastResult:
        point_preds: dict[str, np.ndarray] = {}
        quantile_preds: dict[str, np.ndarray] = {}

        for target_name, raw_series in past_targets.items():
            series = np.asarray(raw_series, dtype=np.float64)
            n_obs = len(series)
            if n_obs == 0:
                point_preds[target_name] = np.zeros(horizon, dtype=np.float64)
                quantile_preds[target_name] = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
                continue

            window = series[-min(n_obs, self.window_size):]
            mean_val = float(np.mean(window))
            std_val = float(np.std(window)) if len(window) > 1 else 1.0
            if std_val < 1e-6:
                std_val = 1.0

            point_forecast = np.full(horizon, mean_val, dtype=np.float64)
            point_preds[target_name] = point_forecast

            # Expanding uncertainty over horizon
            time_steps = np.arange(1, horizon + 1, dtype=np.float64)
            spread = std_val * np.sqrt(time_steps)

            q_mat = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
            for q_idx, q in enumerate(self.quantiles):
                z_score = np.sqrt(2.0) * _erf_inv(2.0 * q - 1.0)
                q_mat[:, q_idx] = np.maximum(point_forecast + z_score * spread, 0.0)

            quantile_preds[target_name] = q_mat

        return ForecastResult(
            point_forecast=point_preds,
            quantile_forecast=quantile_preds,
            quantiles=self.quantiles,
            metadata={"model": "moving_average", "window_size": self.window_size},
        )


class LinearTrendCovariateForecaster(TimeSeriesForecaster):
    """Linear regression baseline with past and future covariates."""

    def __init__(
        self,
        quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
        ridge_alpha: float = 1.0,
    ) -> None:
        self.quantiles = quantiles
        self.ridge_alpha = ridge_alpha

    def forecast(
        self,
        past_targets: dict[str, np.ndarray],
        past_covariates: dict[str, np.ndarray] | None = None,
        future_covariates: dict[str, np.ndarray] | None = None,
        horizon: int = 64,
    ) -> ForecastResult:
        point_preds: dict[str, np.ndarray] = {}
        quantile_preds: dict[str, np.ndarray] = {}

        past_covs = past_covariates or {}
        fut_covs = future_covariates or {}

        for target_name, raw_series in past_targets.items():
            y = np.asarray(raw_series, dtype=np.float64)
            n_obs = len(y)
            if n_obs < 2:
                pred = np.full(horizon, y[-1] if n_obs == 1 else 0.0, dtype=np.float64)
                point_preds[target_name] = pred
                quantile_preds[target_name] = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
                continue

            # Build feature matrix X_past: [1, time_index, past_covariates]
            time_idx_past = np.arange(n_obs, dtype=np.float64)
            features_past = [np.ones(n_obs, dtype=np.float64), time_idx_past]

            # Future features matrix
            time_idx_future = np.arange(n_obs, n_obs + horizon, dtype=np.float64)
            features_future = [np.ones(horizon, dtype=np.float64), time_idx_future]

            for cov_name in sorted(fut_covs.keys()):
                cov_future = np.asarray(fut_covs[cov_name], dtype=np.float64)[:horizon]
                if len(cov_future) < horizon:
                    cov_future = np.pad(cov_future, (0, horizon - len(cov_future)), mode="edge")
                # Corresponding past if available
                if cov_name in past_covs:
                    cov_past = np.asarray(past_covs[cov_name], dtype=np.float64)
                    if len(cov_past) == n_obs:
                        features_past.append(cov_past)
                        features_future.append(cov_future)

            X_past = np.column_stack(features_past)
            X_future = np.column_stack(features_future)

            # Ridge regression
            n_feat = X_past.shape[1]
            reg = self.ridge_alpha * np.eye(n_feat)
            reg[0, 0] = 0.0  # Do not regularize intercept
            try:
                weights = np.linalg.solve(X_past.T @ X_past + reg, X_past.T @ y)
            except np.linalg.LinAlgError:
                weights = np.linalg.pinv(X_past) @ y

            point_forecast = X_future @ weights
            if any(k in target_name.lower() for k in ("wip", "buffer", "output", "count", "busy")):
                point_forecast = np.maximum(point_forecast, 0.0)
            point_preds[target_name] = point_forecast

            # Residual variance for quantiles
            residuals = y - (X_past @ weights)
            res_std = float(np.std(residuals))
            if res_std < 1e-6:
                res_std = 1.0

            time_steps = np.arange(1, horizon + 1, dtype=np.float64)
            spread = res_std * (0.8 + 0.2 * np.sqrt(time_steps))

            q_mat = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
            for q_idx, q in enumerate(self.quantiles):
                z_score = np.sqrt(2.0) * _erf_inv(2.0 * q - 1.0)
                q_mat[:, q_idx] = np.maximum(point_forecast + z_score * spread, 0.0)

            quantile_preds[target_name] = q_mat

        return ForecastResult(
            point_forecast=point_preds,
            quantile_forecast=quantile_preds,
            quantiles=self.quantiles,
            metadata={"model": "linear_trend_covariate"},
        )


class NaiveLastValueForecaster(TimeSeriesForecaster):
    """Naive persistence baseline."""

    def __init__(self, quantiles: tuple[float, ...] = DEFAULT_QUANTILES) -> None:
        self.quantiles = quantiles

    def forecast(
        self,
        past_targets: dict[str, np.ndarray],
        past_covariates: dict[str, np.ndarray] | None = None,
        future_covariates: dict[str, np.ndarray] | None = None,
        horizon: int = 64,
    ) -> ForecastResult:
        point_preds: dict[str, np.ndarray] = {}
        quantile_preds: dict[str, np.ndarray] = {}

        for target_name, raw_series in past_targets.items():
            series = np.asarray(raw_series, dtype=np.float64)
            last_val = series[-1] if len(series) > 0 else 0.0
            point_forecast = np.full(horizon, last_val, dtype=np.float64)
            point_preds[target_name] = point_forecast

            # Empirical diff std
            diff_std = float(np.std(np.diff(series))) if len(series) > 1 else 1.0
            if diff_std < 1e-6:
                diff_std = 1.0

            time_steps = np.arange(1, horizon + 1, dtype=np.float64)
            spread = diff_std * np.sqrt(time_steps)

            q_mat = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
            for q_idx, q in enumerate(self.quantiles):
                z_score = np.sqrt(2.0) * _erf_inv(2.0 * q - 1.0)
                q_mat[:, q_idx] = np.maximum(point_forecast + z_score * spread, 0.0)

            quantile_preds[target_name] = q_mat

        return ForecastResult(
            point_forecast=point_preds,
            quantile_forecast=quantile_preds,
            quantiles=self.quantiles,
            metadata={"model": "naive_last_value"},
        )


class ExponentialSmoothingForecaster(TimeSeriesForecaster):
    """
    Holt's Linear / Damped Trend Exponential Smoothing baseline.
    Standard time-series forecasting benchmark in manufacturing, supply-chain, and ERP systems.
    """

    def __init__(
        self,
        alpha: float = 0.3,
        beta: float = 0.1,
        phi: float = 0.95,
        quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    ) -> None:
        self.alpha = alpha
        self.beta = beta
        self.phi = phi
        self.quantiles = quantiles

    def forecast(
        self,
        past_targets: dict[str, np.ndarray],
        past_covariates: dict[str, np.ndarray] | None = None,
        future_covariates: dict[str, np.ndarray] | None = None,
        horizon: int = 64,
    ) -> ForecastResult:
        point_preds: dict[str, np.ndarray] = {}
        quantile_preds: dict[str, np.ndarray] = {}

        for target_name, raw_series in past_targets.items():
            series = np.asarray(raw_series, dtype=np.float64)
            n_obs = len(series)
            if n_obs == 0:
                point_preds[target_name] = np.zeros(horizon, dtype=np.float64)
                quantile_preds[target_name] = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
                continue
            if n_obs == 1:
                point_preds[target_name] = np.full(horizon, series[0], dtype=np.float64)
                quantile_preds[target_name] = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
                continue

            # Initialization of level and trend
            level = float(series[0])
            trend = float(series[1] - series[0])
            errors = []

            for t in range(1, n_obs):
                y_t = float(series[t])
                y_hat = level + self.phi * trend
                error = y_t - y_hat
                errors.append(error)

                new_level = self.alpha * y_t + (1.0 - self.alpha) * (level + self.phi * trend)
                new_trend = self.beta * (new_level - level) + (1.0 - self.beta) * self.phi * trend
                level, trend = new_level, new_trend

            # Extrapolate damped trend over horizon h
            damp_factors = np.cumsum([self.phi ** i for i in range(1, horizon + 1)])
            point_forecast = level + damp_factors * trend

            if any(k in target_name.lower() for k in ("wip", "buffer", "output", "count", "busy", "scrap")):
                point_forecast = np.maximum(point_forecast, 0.0)
            point_preds[target_name] = point_forecast

            # Residual variance for quantiles
            res_std = float(np.std(errors)) if errors else 1.0
            if res_std < 1e-6:
                res_std = 1.0

            time_steps = np.arange(1, horizon + 1, dtype=np.float64)
            spread = res_std * np.sqrt(1.0 + self.alpha**2 * (time_steps - 1.0))

            q_mat = np.zeros((horizon, len(self.quantiles)), dtype=np.float64)
            for q_idx, q in enumerate(self.quantiles):
                z_score = np.sqrt(2.0) * _erf_inv(2.0 * q - 1.0)
                q_vals = point_forecast + z_score * spread
                if any(k in target_name.lower() for k in ("wip", "buffer", "output", "count", "busy", "scrap")):
                    q_vals = np.maximum(q_vals, 0.0)
                q_mat[:, q_idx] = q_vals

            quantile_preds[target_name] = q_mat

        return ForecastResult(
            point_forecast=point_preds,
            quantile_forecast=quantile_preds,
            quantiles=self.quantiles,
            metadata={
                "model": "exponential_smoothing",
                "alpha": self.alpha,
                "beta": self.beta,
                "phi": self.phi,
            },
        )
