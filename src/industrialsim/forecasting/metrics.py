from __future__ import annotations

from typing import Sequence
import numpy as np

from industrialsim.forecasting.protocol import ForecastResult


def mean_absolute_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_t = np.asarray(y_true, dtype=np.float64)
    y_p = np.asarray(y_pred, dtype=np.float64)
    return float(np.mean(np.abs(y_t - y_p)))


def root_mean_squared_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_t = np.asarray(y_true, dtype=np.float64)
    y_p = np.asarray(y_pred, dtype=np.float64)
    return float(np.sqrt(np.mean((y_t - y_p) ** 2)))


def weighted_absolute_percentage_error(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_t = np.asarray(y_true, dtype=np.float64)
    y_p = np.asarray(y_pred, dtype=np.float64)
    total_actual = float(np.sum(np.abs(y_t)))
    if total_actual == 0.0:
        return 0.0 if np.allclose(y_t, y_p) else 1.0
    return float(np.sum(np.abs(y_t - y_p)) / total_actual)


def pinball_loss(y_true: np.ndarray, q_pred: np.ndarray, q: float) -> np.ndarray:
    diff = np.asarray(y_true, dtype=np.float64) - np.asarray(q_pred, dtype=np.float64)
    return np.maximum(q * diff, (q - 1.0) * diff)


def weighted_quantile_loss(y_true: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    loss = pinball_loss(y_true, q_pred, q)
    total_actual = float(np.sum(np.abs(y_true)))
    if total_actual == 0.0:
        return float(2.0 * np.mean(loss))
    return float(2.0 * np.sum(loss) / total_actual)


def continuous_ranked_probability_score(
    y_true: np.ndarray,
    q_preds: np.ndarray,  # shape (horizon, num_quantiles)
    quantiles: Sequence[float],
) -> float:
    """Discrete approximation of CRPS across predicted quantiles."""
    y_t = np.asarray(y_true, dtype=np.float64)
    q_array = np.asarray(q_preds, dtype=np.float64)
    total_loss = 0.0
    for idx, q in enumerate(quantiles):
        total_loss += float(np.mean(pinball_loss(y_t, q_array[:, idx], q)))
    return float((2.0 / len(quantiles)) * total_loss)


def evaluate_forecast(
    y_true: dict[str, np.ndarray],
    result: ForecastResult,
) -> dict[str, dict[str, float]]:
    """Compute point and quantile metrics for all shared targets."""
    metrics: dict[str, dict[str, float]] = {}

    for target, actual in y_true.items():
        if target not in result.point_forecast:
            continue

        pred_point = result.get_mean(target)
        # Match lengths if necessary
        n = min(len(actual), len(pred_point))
        act_slice = actual[:n]
        pt_slice = pred_point[:n]

        mae_val = mean_absolute_error(act_slice, pt_slice)
        rmse_val = root_mean_squared_error(act_slice, pt_slice)
        wape_val = weighted_absolute_percentage_error(act_slice, pt_slice)

        target_metrics = {
            "mae": mae_val,
            "rmse": rmse_val,
            "wape": wape_val,
        }

        if target in result.quantile_forecast:
            q_slice = result.quantile_forecast[target][:n, :]
            crps_val = continuous_ranked_probability_score(act_slice, q_slice, result.quantiles)
            target_metrics["crps"] = crps_val

            # Compute average WQL across quantiles
            wql_vals = [
                weighted_quantile_loss(act_slice, q_slice[:, q_idx], q)
                for q_idx, q in enumerate(result.quantiles)
            ]
            target_metrics["mean_wql"] = float(np.mean(wql_vals))
            target_metrics["wql_q50"] = float(weighted_quantile_loss(act_slice, result.get_quantile(target, 0.5)[:n], 0.5))
            target_metrics["wql_q90"] = float(weighted_quantile_loss(act_slice, result.get_quantile(target, 0.9)[:n], 0.9))

        metrics[target] = target_metrics

    return metrics
