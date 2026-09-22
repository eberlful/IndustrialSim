# CLI-Referenz: IndustrialSim

Dieses Dokument bietet eine vollständige Befehlsreferenz für die Kommandozeilenschnittstelle (`industrialsim`) von **IndustrialSim**.

---

## 1. Übersicht & allgemeine Syntax

Das CLI wird über den Befehl `industrialsim` (oder äquivalent über `python -m industrialsim.cli`) aufgerufen:

```bash
industrialsim [-h] {validate,run,inspect,resume,branch,benchmark} ...
```

### 1.1 Globale Optionen
- `-h`, `--help`: Zeigt die Hilfe und verfügbare Subcommands an.

### 1.2 Rückgabewerte (Exit-Codes)
- `0`: Befehl erfolgreich abgeschlossen.
- `1`: Fehler aufgetreten (z. B. Validierungsfehler, Deadlock, ungültige Argumente oder unvollständiger Lauf).

Alle Befehle geben maschinenlesbares, strukturiertes **JSON** auf `stdout` aus, wodurch sich das CLI nahtlos in Automatisierungs- und CI/CD-Pipelines integrieren lässt.

---

## 2. Befehlsübersicht im Detail

### 2.1 `validate`
Überprüft eine YAML-Simulationskonfiguration statisch auf Schema- und Domänenkorrektheit, ohne eine Simulation zu starten.

#### Syntax
```bash
industrialsim validate <config_path>
```

#### Argumente
- `config_path`: Pfad zur YAML-Konfigurationsdatei.

#### Beispiel
```bash
industrialsim validate examples/reference_automotive_plant.yaml
```

#### Beispielausgabe (Erfolg)
```json
{
  "valid": true,
  "errors": [],
  "schema_version": "1.0"
}
```

#### Beispielausgabe (Fehlerfall)
```json
{
  "valid": false,
  "errors": [
    "Operation 'op-weld' references unknown machine 'm-nonexistent'",
    "Extra inputs are not permitted in plant configuration: 'invalid_field'"
  ],
  "schema_version": "1.0"
}
```

---

### 2.2 `run`
Führt eine vollständige Simulationsepisode basierend auf einer Konfigurationsdatei aus.

#### Syntax
```bash
industrialsim run <config_path> [--output-dir <dir>]
```

#### Argumente
- `config_path`: Pfad zur YAML-Konfigurationsdatei.
- `--output-dir <dir>`: Optionaler Pfad zum Verzeichnis, in dem alle Lauf-Artefakte gespeichert werden. Wird kein Pfad angegeben, wird ein Zeitstempel-Verzeichnis unter `runs/<episode_id>` erzeugt.

#### Beispiel
```bash
industrialsim run examples/reference_automotive_plant.yaml --output-dir ./runs/exp_01
```

#### Beispielausgabe
```json
{
  "status": "success",
  "episode_id": "ep-automotive-42",
  "output_dir": "./runs/exp_01",
  "events_processed": 142050,
  "simulated_time_ns": 432000000000000,
  "metrics": {
    "units_completed": 85,
    "units_scrapped": 2,
    "lead_time_mean_s": 420.5,
    "wip_mean": 12.3
  }
}
```

---

### 2.3 `inspect`
Analysiert und inspiziert entweder ein generiertes Ergebnisverzeichnis oder eine einzelne komprimierte Checkpoint-Datei (`.json.gz`).

#### Syntax
```bash
industrialsim inspect <path>
```

#### Argumente
- `path`: Pfad zum Ergebnisverzeichnis (mit `manifest.json`) oder zu einer Checkpoint-Datei (`checkpoint.json.gz`).

#### Beispiel
```bash
industrialsim inspect ./runs/exp_01
```

#### Beispielausgabe
```json
{
  "artifact_type": "run_directory",
  "episode_id": "ep-automotive-42",
  "git_commit": "e85f561",
  "is_calibrated": false,
  "has_checkpoint": true,
  "has_telemetry": true,
  "total_events": 142050,
  "final_sim_time_s": 432000.0,
  "completed_cleanly": true
}
```

---

### 2.4 `resume`
Setzt eine zuvor pausierte oder abgebrochene Episode deterministisch aus einem Checkpoint fort.

#### Syntax
```bash
industrialsim resume <checkpoint_path> [--config <config_path>]
```

#### Argumente
- `checkpoint_path`: Pfad zur Checkpoint-Datei (`checkpoint.json.gz`).
- `--config <config_path>`: Optionaler Pfad zur YAML-Konfiguration, falls diese gegen den Checkpoint validiert werden soll.

#### Beispiel
```bash
industrialsim resume ./runs/exp_01/checkpoint.json.gz
```

---

### 2.5 `branch`
Führt vergleichende **Counterfactual Branches** ausgehend von einem Entscheidungspunkt (*Decision Checkpoint*) mit alternativen Aktionsmengen aus.

#### Syntax
```bash
industrialsim branch <checkpoint_path> <action_files...> [--config <config_path>] [--output-dir <dir>] [--workers <N>]
```

#### Argumente
- `checkpoint_path`: Pfad zur Checkpoint-Datei an einem Decision Point.
- `action_files`: Mindestens zwei (bis zu acht) Pfade zu JSON-Dateien mit alternativen Aktionen (`DecisionBatchResponse`).
- `--workers <N>`: Anzahl paralleler Worker-Prozesse zur Berechnung (Standard: `1`).
- `--output-dir <dir>`: Zielverzeichnis für Branch-Artefakte.

#### Beispiel
```bash
industrialsim branch ./runs/exp_01/decision_checkpoint.json.gz \
    baseline_actions.json \
    heuristic_actions.json \
    rl_agent_actions.json \
    --workers 3 \
    --output-dir ./runs/branch_comparison
```

#### Beispielausgabe
```json
{
  "status": "success",
  "branches_evaluated": 3,
  "branch_summaries": [
    {
      "branch_id": "branch-0",
      "action_file": "baseline_actions.json",
      "units_completed": 45,
      "reward": 120.5
    },
    {
      "branch_id": "branch-1",
      "action_file": "heuristic_actions.json",
      "units_completed": 49,
      "reward": 138.2
    },
    {
      "branch_id": "branch-2",
      "action_file": "rl_agent_actions.json",
      "units_completed": 54,
      "reward": 162.0
    }
  ]
}
```

---

### 2.6 `benchmark`
Führt standardisierte Kernel-Scheduler- und Referenzwerk-Benchmarks aus, um Durchsatz, Ereignisverarbeitungsgeschwindigkeit und Determinismus zu testen.

#### Syntax
```bash
industrialsim benchmark [--target {all,scheduler,kernel,plant,reference_plant}] [--kernel-events <N>] [--plant-events <N>] [--repetitions <N>] [--output-dir <dir>]
```

#### Argumente
- `--target`: Ziel des Benchmarks (`all`, `kernel` / `scheduler`, `plant` / `reference_plant`; Standard: `all`).
- `--kernel-events <N>`: Anzahl einfacher Ereignisse für den Scheduler-Test (Standard: `5.000.000`).
- `--plant-events <N>`: Zielereignisse für den Referenzwerk-Test (Standard: `100.000`).
- `--repetitions <N>`: Anzahl Wiederholungen zur Determinismusprüfung über Bit-Hash-Vergleiche (Standard: `2`).
- `--output-dir <dir>`: Optionales Verzeichnis für den Benchmark-Report.

#### Beispiel
```bash
industrialsim benchmark --target all --kernel-events 1000000 --repetitions 2
```

#### Beispielausgabe
```json
{
  "status": "success",
  "deterministic": true,
  "scheduler_benchmark": {
    "events_processed": 1000000,
    "elapsed_seconds": 1.25,
    "events_per_second": 800000.0
  },
  "plant_benchmark": {
    "events_processed": 100000,
    "elapsed_seconds": 3.82,
    "events_per_second": 26178.0
  }
}
```

---

## 3. Struktur der erzeugten Ergebnisartefakte

Jeder Simulationslauf schreibt in ein dediziertes Verzeichnis folgende Dateien:

| Datei | Format | Zweck |
| :--- | :--- | :--- |
| **`manifest.json`** | JSON | Speichert Git-Commit, Runtime-Version, Modellparameter, Root-Seed und Kalibrierungsnotizen. |
| **`audit.jsonl`** | JSON Lines | Verlustfreies, geordnetes Protokoll aller Lebenszyklus-Ereignisse, Decision Requests und Aktionen. |
| **`telemetry.parquet`** | Parquet | Effiziente Speicherung periodischer Metrik-Snapshots und Maschinenzustände. |
| **`checkpoint.json.gz`**| Gzip-JSON | Vollständiger, portabler Zustandsschnappschuss für Fortsetzung oder Counterfactual Branching. |
| **`deadlock_report.json`** | JSON | (Nur bei Abbruch durch Deadlock) Enthält den Wait-for-Graphen und beteiligte Ressourcen. |
