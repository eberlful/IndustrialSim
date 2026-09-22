# Konfigurationshandbuch: IndustrialSim

Dieses Dokument ist das vollständige Referenzhandbuch für die deklarative YAML-Konfiguration von **IndustrialSim**.

---

## 1. Grundprinzipien & Validierung

IndustrialSim verwendet **YAML 1.2** für alle Modell-, Prozess- und Experimentdefinitionen (vgl. [ADR-0012](file:///workspaces/IndustrialSim/docs/adr/0012-use-strict-declarative-configuration-and-trusted-plugins.md)).

### 1.1 Strikte Validierung
- **Keine unbekannten Felder**: Alle Konfigurationsmodelle basieren auf Pydantic mit `extra = "forbid"`. Tippfehler oder veraltete Feldnamen führen unmittelbar zu einem Validierungsfehler.
- **Keine dynamischen Codeausführungen**: Die Konfiguration darf weder Python-Code noch implizite Imports enthalten. Erweiterungen müssen als explizite Plugins registriert und deklariert sein.
- **Typ- und Konsistenzprüfungen**: Vor Beginn einer Simulation werden alle IDs, Referenzen (z. B. auf Hallen, Maschinen, Worker, Puffer) und Graphpfade statisch validiert.

### 1.2 Zeit- und Dauerformate
Zeiten und Dauern können als ganzzahlige Nanosekunden (`int`) oder als lesbare Zeichenketten mit Einheit angegeben werden:
- `ns`: Nanosekunden
- `us` / `µs`: Mikrosekunden
- `ms`: Millisekunden
- `s`: Sekunden
- `m` / `min`: Minuten
- `h`: Stunden
- `d`: Tage

*Beispiele*: `"120s"`, `"10m"`, `"8h"`, `"5d"`, `"1h 30m"`.

---

## 2. Struktur einer Konfigurationsdatei

Eine vollständige Konfigurationsdatei gliedert sich in folgende Hauptsektionen:

```yaml
schema_version: "1.0"
seed: 42

calibration:
  is_calibrated: false
  notes: "Synthetisches Modell für Experimente"
  uncalibrated_parameters:
    - "station_cycle_times"
    - "failure_hazard_rates"

episode:
  start_time: "0s"
  warm_up_time: "8h"
  end_condition:
    type: "max_time"
    max_time: "5d"

telemetry:
  enabled: true
  sample_interval: "1h"
  domain_events:
    - "operation_completed"
    - "machine_state_change"

plant:
  # Werkshierarchie (Plant -> Area -> Hall)

material_flow:
  # Gerichteter Multigraph (Nodes, Ports, Routes)

machines:
  # Physische Maschinen und Degradationsparameter

workers:
  # Arbeiter, Qualifikationen und Schichten

vehicle_pools:
  # Logistikpools

vehicles:
  # Transportfahrzeuge

production_plan:
  # Vorab materialisierter Auftragseingang

process_plans:
  # Arbeitspläne je Produktvariante

decisions:
  # Trigger, Hysterese und Fallbacks
```

---

## 3. Die Sektionen im Detail

### 3.1 Allgemeine Metadaten & `calibration`
- `schema_version`: String, aktuell `"1.0"`.
- `seed`: Ganzzahl für den Haupt-Zufallsgenerator (Standard: `42`).
- `calibration`: Kennzeichnung, ob das Modell auf Realdaten kalibriert wurde.
  - `is_calibrated`: Boolean (`true` / `false`).
  - `calibration_id`: Optionaler Bezeichner des Kalibrierungsdatensatzes.
  - `uncalibrated_parameters`: Liste von Parameternamen, die synthetisch geschätzt sind.

### 3.2 `episode`: Simulationsgrenzen
Definiert den zeitlichen Rahmen einer Episode:
- `start_time`: Simulationsbeginn (Standard: `"0s"`).
- `warm_up_time`: Optionaler Vorlauf (z. B. `"8h"`). Daten aus dieser Phase werden nicht in die Leistungsmetriken oder Rewards eingerechnet.
- `end_condition`:
  - `type: "max_time"` mit `max_time: "5d"`: Endet nach Erreichen einer festen Zeit.
  - `type: "all_units_terminal"`: Endet, sobald alle Production Units eine Senke (`sink`) erreicht haben oder verschrottet wurden.

---

### 3.3 `plant`: Organisations- und Standortstruktur
Beschreibt die statische Fabrikorganisation (vgl. [CONTEXT.md](file:///workspaces/IndustrialSim/CONTEXT.md)):
- `id`: Eindeutige Kennung des Plants.
- `name`: Lesbarer Name.
- `areas`: Liste von Bereichen (z. B. Rohbau, Lackiererei, Endmontage).
  - `id`, `name`
  - `halls`: Liste von Hallen innerhalb der Area.
    - `id`, `name`

*Wichtig*: Der Materialfluss ist unabhängig von dieser Struktur, jedoch können Stationen und Puffer über `hall_id` einer Halle zugeordnet werden.

---

### 3.4 `material_flow`: Der Materialflussgraph
Modelliert den gerichteten Multigraphen (vgl. [ADR-0014](file:///workspaces/IndustrialSim/docs/adr/0014-model-material-flow-as-a-directed-multigraph.md)):

#### Knoten (`nodes`)
Ein Knoten besitzt ein Feld `kind`:
- `source`: Quelle zur Einlastung von Production Units. Besitzt nur `output_ports`.
- `sink`: Senke zur Ausschleusung fertiger oder verschrotteter Einheiten. Besitzt nur `input_ports`.
- `station`: Bearbeitungsknoten mit deklarierten Operationen.
- `buffer`: Kapazitätsbegrenzter Zwischenspeicher.

```yaml
material_flow:
  nodes:
    - id: "src-bodies"
      kind: "source"
      hall_id: "hall-body-construction"
      output_ports:
        - id: "p-out"
          port_type: "body"
          direction: "output"

    - id: "buf-weld-1"
      kind: "buffer"
      hall_id: "hall-body-construction"
      capacity: 5
      input_ports:
        - id: "p-in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "body"
          direction: "output"

    - id: "st-body-weld-1"
      kind: "station"
      hall_id: "hall-body-construction"
      input_ports:
        - id: "p-in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "body"
          direction: "output"
      operations:
        - id: "op-weld"
          duration: "120s"
          required_machines: ["m-welder-1"]
          required_workers:
            - qualification: "welder_cert"
              count: 1
          interruption_policy: "resume"
```

#### Routen (`routes`)
Verbinden Ports miteinander:
```yaml
  routes:
    - id: "route-src-to-buf"
      source_node: "src-bodies"
      source_port: "p-out"
      target_node: "buf-weld-1"
      target_port: "p-in"
      transit_time: "30s"
      capacity: 2
      pool_id: "pool-agv"
```

---

### 3.5 `machines` & `workers`: Produktionsressourcen

#### Maschinen (`machines`)
```yaml
machines:
  - id: "m-welder-1"
    name: "Schweißroboter 1"
    hall_id: "hall-body-construction"
    initial_health: 1.0
    modes:
      - id: "normal"
        wear_rate: 0.0001
        cycle_time_factor: 1.0
      - id: "boost"
        wear_rate: 0.0004
        cycle_time_factor: 0.8
    failure:
      hazard_rate: 0.001
      required_workers:
        - qualification: "maintenance_tech"
          count: 1
      duration: "45m"
    maintenance:
      scheduled_interval: "24h"
      duration: "30m"
      health_restore_max: 0.95
      required_workers:
        - qualification: "maintenance_tech"
          count: 1
```

#### Worker (`workers`)
```yaml
workers:
  - id: "worker-01"
    name: "Max Mustermann"
    qualifications: ["welder_cert", "body_operator"]
    shifts:
      - id: "early-shift"
        start_time: "06:00"
        end_time: "14:00"
        handover_rule: "handover"
        breaks:
          - start_time: "09:30"
            duration: "30m"
```

---

### 3.6 `production_plan` & `process_plans`

#### Produktionsplan (`production_plan`)
Vor Beginn materialisierter Auftragseingang (vgl. [ADR-0015](file:///workspaces/IndustrialSim/docs/adr/0015-materialize-production-plans-before-an-episode.md)):
```yaml
production_plan:
  - id: "batch-sedan-01"
    variant: "sedan"
    quantity: 50
    release_time: "0s"
    due_date: "12h"
    source_id: "src-bodies"
```

#### Prozessplan (`process_plans`)
Deklariert die geordneten Fertigungsschritte je Variante:
```yaml
process_plans:
  - variant: "sedan"
    steps:
      - step_index: 1
        operation_id: "op-weld"
        compatible_stations: ["st-body-weld-1", "st-body-weld-2"]
      - step_index: 2
        operation_id: "op-inspect"
        compatible_stations: ["st-quality-gate"]
    rework_steps:
      - defect_name: "weld_defect"
        operation_id: "op-weld-rework"
        compatible_stations: ["st-rework-weld"]
```

---

### 3.7 `decisions`: Entscheidungsauslöser & Trigger

Trigger bestimmen, wann die Simulation pausiert und ein `DecisionBatch` für den Decision Provider erzeugt wird:
- `routing_decision`: Beim Verlassen eines Knotens zur Stations- oder Routenwahl.
- `dispatch_decision`: Bei Entstehung oder Zuordnung von Transportaufträgen.
- `machine_decision`: Bei Statusänderungen oder kritischer Degradation von Maschinen.
- `buffer_threshold`: Bei Erreichen von Füllstandsschwellen (inklusive Hysterese zur Vermeidung von Dauerfeuer).
- `safe_point`: Zu festen Simulationsintervallen für taktische Entscheidungen.

```yaml
decision_triggers:
  - id: "trig-buffer-high"
    trigger_type: "buffer_threshold"
    buffer_id: "buf-weld-1"
    high_watermark: 4
    low_watermark: 2
    re_arm_condition: "below_low"

  - id: "trig-periodic-safe"
    trigger_type: "safe_point"
    interval: "1h"
```

---

### 3.8 `telemetry` & `rewards`
- `sample_interval`: Zeitintervall für Parquet-Snapshots.
- `domain_events`: Liste spezifischer Domänenereignisse zur Aufzeichnung.
- `backpressure`: Verhalten bei Schreibengpässen (`policy: "thin"`, `thin_factor: 2`).
- `reward_policy`: Gewichtung von Gutteilen, Durchlaufzeiten, Verspätungen und Ausfällen für RL-Training.
- `hard_constraints`: Maximale Pufferüberfüllung oder Sicherheitsgrenzen, deren Verletzung zum Episodenabbruch führt.

---

## 4. Beispiel: Minimalbeispiel

Siehe [`examples/minimal_episode.yaml`](file:///workspaces/IndustrialSim/examples/minimal_episode.yaml):
```yaml
schema_version: "1.0"
seed: 42

episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

production_units:
  - id: "unit-001"
    variant: "sedan"
    release_time: "0s"

stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
```

---

## 5. Validierung ausführen

Konfigurationsdateien können vor dem Start über die CLI validiert werden:
```bash
industrialsim validate examples/reference_automotive_plant.yaml
```

Erfolgreiche Ausgabe:
```json
{
  "valid": true,
  "errors": [],
  "schema_version": "1.0"
}
```
Treten Fehler auf, liefert der Validator präzise Pfadangaben und Beschreibungen (z. B. verbotene zusätzliche Felder, ungültige Referenzen, unerreichbare Knoten).
