# [EXP-XXXX] Titel des Experiments

> **Status**: Abgeschlossen / In Bearbeitung / Verworfen  
> **Datum**: YYYY-MM-DD  
> **Autor**: Name / Agent  
> **Untersuchtes Modell / Heuristik**: z. B. TimesFM 3 (Multivariat) vs. Baseline  
> **Verwendete Anlagenkonfiguration**: [`examples/...yaml`](file:///workspaces/IndustrialSim/examples/)  
> **Seed**: `42`  
> **Artefakt-Verzeichnis**: `./runs/...`  

---

## 1. Motivation & Hypothese

### Problemstellung
*Kurze Beschreibung des betrieblichen oder wissenschaftlichen Problems (z. B. Puffer-Engpässe, ungeplante Maschinenausfälle, Varianten-Stau).*

### Hypothese
*Was soll durch den Einsatz des Modells / der Steuerungsentscheidung bewiesen oder verbessert werden?*
> **Hypothese**: *Durch die Vorhersage von [Metrik] mittels [Modell] über einen Horizont von [H] Schritten kann [Zielgröße] um mindestens X% gesteigert bzw. gesenkt werden.*

---

## 2. Versuchsaufbau & Konfiguration

### 2.1 Fabrikmodell & Randbedingungen
- **Plant / Layout**: *Kurzbeschreibung der Stationen, Puffer und Transportwege.*
- **Stochastik**: *Verwendete Ausfallraten, Bearbeitungszeit-Variabilitäten.*
- **Produktionsplan**: *Anzahl Einheiten, Variantenmix, Einsteuerungsfenster.*
- **Telemetrie-Raster**: *z. B. 30s äquidistant.*

### 2.2 Untersuchte Richtlinien / Branches
| Branch-ID | Name | Beschreibung / Modell |
| :--- | :--- | :--- |
| **Branch A** | Baseline (Reaktiv) | Standard-Heuristik (FIFO, reaktive Reparatur) |
| **Branch B** | Modell-Vorschlag | Vorausschauende Steuerung (z. B. TimesFM 3 Multivariat) |
| **Branch C** | Vergleichs-Baseline | z. B. Moving Average oder Univariat |

---

## 3. Offline Forecasting Evaluation (Statistische & Probabilistische Güte)

*Auswertung über rollierende Vorhersagefenster auf den Parquet-Telemetriedaten (`runs/.../telemetry/metrics_*.parquet`).*

### 3.1 Aggregierte Modellmetriken
| Modell | MAE | RMSE | WAPE | CRPS | Mean WQL | WQL@q90 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Modell B** | - | - | - | - | - | - |
| **Modell C** | - | - | - | - | - | - |
| **Naive Baseline** | - | - | - | - | - | - |

### 3.2 Detailanalyse nach Zielgrößen (Targets)
- **Work-in-Progress (WIP)**: *Beobachtungen zur Vorhersagegenauigkeit und Trendtreue.*
- **Durchsatz (`good_output`)**: *Relative Fehlerquote (WAPE).*
- **Maschinenauslastung / Stillstand**: *Quantilbewertung für seltene Ereignisse (z. B. $q=0.9$).*

---

## 4. Kausales Counterfactual Branching (Operative Fabrik-KPIs)

*Vergleich der Auswirkung alternativer Entscheidungen ab einem identischen Checkpoint unter identischen Philox-Zufallsströmen.*

### 4.1 Operative KPI-Vergleichstabelle
| Kennzahl | Branch A (Reaktiv) | Branch B (Modell B) | Branch C (Vergleich) | Delta (B vs. A) |
| :--- | :--- | :--- | :--- | :--- |
| **Good Output (Stück)** | | | | **+%** |
| **Ausschuss (`scrap`)** | | | | |
| **WIP am Ende** | | | | |
| **Gesamtstillstand (`downtime_s`)** | | | | **-%** |
| **Mittlere Durchlaufzeit (`lead_time_s`)** | | | | |
| **Terminverspätung (`lateness_s`)** | | | | |
| **Deterministischer Result-Hash** | `...` | `...` | `...` | *Eindeutige Hashes* |

---

## 5. Auditlog- & Invarianten-Prüfung

- **Ausgelöste Decision Batches**: *Anzahl und Zeitpunkte.*
- **Aktionsvalidierung**: *Wurden 100% der Aktionen akzeptiert oder gab es Fallback-Auslösungen?*
- **Entscheidungs-Verhalten**: *Beispielhafter Auszug aus `audit.jsonl` für eine entscheidende Aktion.*

```json
{
  "simulated_time_ns": 0,
  "event_type": "decision_action",
  "provenance": {
    "provider_id": "...",
    "model_id": "..."
  },
  "details": {
    "action_type": "..."
  }
}
```

---

## 6. Fazit & Erkenntnisse

### Wichtigste Ergebnisse
1. **...**
2. **...**

### Limitierungen & Auffälligkeiten
- *z. B. Verzögerungen durch Berechnungszeit, Grenzfälle bei Überlast.*

### Nächste Schritte & Optimierungen
- [ ] *Hyperparameter anpassen*
- [ ] *Weiteres Modell testen*

---

## 7. Reproduktionsanleitung

```bash
# 1. Telemetrie generieren und Offline-Benchmark ausführen
uv run python -m industrialsim.forecasting.benchmark \
    --config examples/...yaml \
    --generate-telemetry \
    --output-dir ./runs/...

# 2. Counterfactual Branching ausführen
uv run python -m industrialsim.forecasting.experiment \
    --config examples/...yaml \
    --output-dir ./runs/.../branch_comparison
```
