# Experimente & Benchmark-Ergebnisse

Dieses Verzeichnis dient der wissenschaftlichen und operativen Dokumentation aller mit **IndustrialSim** durchgeführten Modellvergleiche, Heuristikevaluationen und Reinforcement-Learning-Experimente.

---

## Struktur des Verzeichnisses

```
experiments/
├── README.md                           # Diese Übersicht und Index
├── EXPERIMENT_TEMPLATE.md              # Verbindliche Vorlage für neue Experimentberichte
└── 2026-09-22-timesfm3-evaluation.md   # [EXP-0001] TimesFM 3 Evaluation & Benchmarks
```

---

## Index der Experimente

| ID | Datum | Titel | Modell(e) | Status | Bericht |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **EXP-0001** | 2026-09-22 | Evaluierung von TimesFM 3 für multivariates Forecasting & vorausschauende Steuerung | TimesFM 3 (Multivariat & Univariat) vs. Baselines | Abgeschlossen | [2026-09-22-timesfm3-evaluation.md](file:///workspaces/IndustrialSim/experiments/2026-09-22-timesfm3-evaluation.md) |
| **EXP-0002** | 2026-09-22 | Kausales Counterfactual Branching unter Engpass- und Termin-Stress | TimesFM 3 Predictive Control vs. FIFO-Baseline | Abgeschlossen | [2026-09-22-timesfm3-stress-evaluation.md](file:///workspaces/IndustrialSim/experiments/2026-09-22-timesfm3-stress-evaluation.md) |
| **EXP-0003** | 2026-09-22 | Hierarchisches Multi-Level Forecasting & Kausale Entscheidungssteuerung | TimesFM 3 Hierarchisch vs. Moving Average vs. Baseline | Abgeschlossen | [2026-09-22-hierarchical-forecasting-evaluation.md](file:///workspaces/IndustrialSim/experiments/2026-09-22-hierarchical-forecasting-evaluation.md) |
| **EXP-0004** | 2026-09-22 | Großer Multi-Horizont & Multi-Seed Forecasting- und Entscheidungs-Benchmark | TimesFM 3 vs. Exponential Smoothing & Baselines ($H \in \{8..128\}$, 140 Units) | Abgeschlossen | [2026-09-22-large-scale-forecasting-benchmark.md](file:///workspaces/IndustrialSim/experiments/2026-09-22-large-scale-forecasting-benchmark.md) |

---

## Anleitung für neue Experimente

1. **Vorlage kopieren**:
   Kopieren Sie [`EXPERIMENT_TEMPLATE.md`](file:///workspaces/IndustrialSim/experiments/EXPERIMENT_TEMPLATE.md) unter einem neuen sprechenden Namen im Format `YYYY-MM-DD-<thema>.md`.
2. **Simulation oder Benchmark ausführen**:
   Nutzen Sie die CLI oder die Python-Module (z. B. `industrialsim run`, `industrialsim branch` oder `industrialsim.forecasting.benchmark`), um Läufe durchzuführen. Artefakte (Parquet-Telemetrie, Auditlogs) werden im git-ignorierten Verzeichnis `./runs/` abgelegt.
3. **Ergebnisse dokumentieren**:
   Tragen Sie die resultierenden Kennzahlen, Tabellen und Audit-Auszüge in den Bericht ein.
4. **Index aktualisieren**:
   Fügen Sie das neue Experiment der Index-Tabelle in dieser `README.md` hinzu.
