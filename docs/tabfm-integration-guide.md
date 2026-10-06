# TabFM in IndustrialSim

Stand: 4. Oktober 2026. Recherche und Integrationsvorschlag; keine Implementierung oder gemessene Modellgüte. Die Empfehlungen unten sind aus der vorhandenen Architektur abgeleitet.

## Empfehlung

TabFM zunächst als aktionsabhängiges KPI-Ersatzmodell evaluieren: Für einen beobachteten Zustand und jeden zulässigen vollständigen Decision Batch sagt es den KPI-Zuwachs der nächsten fünf Minuten voraus. Ein Decision Provider wählt den Batch mit dem besten Ergebnis nach der bestehenden Reward Policy. Ein erster Pilot kann sich auf Machine-Betriebsmodi beschränken; alle übrigen Entscheidungen beantwortet eine feste Fortsetzungspolicy.

Das passt zum Modelltyp: TabFM verarbeitet flache Tabellen für Regression und Klassifikation. Zero-shot bezeichnet unveränderte Modellgewichte; beschriftete Beispiele aus IndustrialSim werden weiterhin als Kontext benötigt. Es ist kein unmittelbar nutzbares Zeitreihen- oder Graphmodell. [Modellkarte 1.1.0](https://huggingface.co/google/tabfm-1.1.0-pytorch)

## Daten und Architektur

Eine Zeile entspricht `(beobachteter Zustand, vollständiger gültiger Decision Batch, Horizont)`:

| Gruppe | Vorschlag |
| --- | --- |
| Beobachtung | Letzte 32 Beobachtungen zusammenfassen: aktuelle Werte, Mittelwerte, Trends, Extremwerte, fehlende Sensor Readings; Buffer-Belegung, WIP, beobachtete Stillstände und Quality Findings. |
| Plant-Kontext | Typen, Kapazitäten und Nachbarschaftsmerkmale von Stations, Machines und Buffers im Material Flow Graph; bekannte Production-Plan-Freigaben und Schichtverfügbarkeit im Prognosefenster. |
| Entscheidung | Aktionstyp und numerische/kategorielle Parameter aller Aktionen eines vollständigen Decision Batch; stabile Zuordnung der betroffenen Ressourcen. |
| Horizont | Zunächst 300 Sekunden, später 600 Sekunden als numerisches Merkmal oder eigener Versuch. |
| Labels | Zuwächse von `good_output`, `scrap`, Verspätung, Stillstand und Kosten; je KPI zunächst ein separater Regressor. |

Die Eingabedaten kommen aus dem vorhandenen `StudyObservationAdapter`. Verborgener Health State und Quality State dürfen ausschließlich Evaluierungslabels sein; insbesondere ist der unveränderte v1 Decision Request nicht automatisch ein zulässiger Modelleingang. Das folgt aus [ADR-0016](adr/0016-separate-world-model-observations-from-simulator-truth.md).

`CandidateCatalog` und `BoundedBatchPlanner` liefern gemeinsam validierte vollständige Batches gemäß [ADR-0018](adr/0018-plan-bounded-valid-decision-batches.md). Der vorgeschlagene direkte Scorer erhält pro Batch eine Tabellenzeile. Die Reward Policy kombiniert die prognostizierten Rohmetriken; harte Einschränkungen bleiben bei der Validierung. Gleichstände, Modellfehler und unzureichend abgedeckte Kontexte führen zur deterministischen Fallback Policy.

Ein eigener `TabFMDecisionProvider` oder eine verallgemeinerte Scorer-Schnittstelle ist hier sinnvoll: Der vorhandene `WorldModelDecisionProvider` erwartet einen vollständigen `RolloutResult`. Ein KPI-Vektor erfüllt diesen Vertrag nicht. Erst ein späteres Zustandsübergangsmodell könnte echte Rollouts erzeugen; dafür wären zusätzlich konsistente Zustandsrekonstruktion und Fehlerkontrolle über mehrere Schritte nötig.

## Kontextdaten erzeugen und evaluieren

1. Verschiedene Episoden, Seeds, Plant-Konfigurationen und Belastungen erzeugen. An Checkpoints mehrere gültige Decision Batches in isolierten Counterfactual Branches ausprobieren. Nach der jeweils ersten Intervention überall dieselbe Fortsetzungspolicy verwenden.
2. Beobachtung und Batch unmittelbar vor der Intervention exportieren. KPI-Differenzen bis zum festen Horizont als Labels speichern. Kontrollierte gemeinsame Zufallsbedingungen verringern Vergleichsrauschen; neue Seeds dienen zur Robustheitsprüfung.
3. Eine Ursprungsepisode und sämtliche daraus entstandenen Checkpoints und Schwesterbranches immer demselben Datensplit zuordnen. Zusätzlich auf unbekannten Plant-Konfigurationen testen. Das Kontextset ausschließlich aus dem Trainingssplit bilden; Testlabels niemals in `fit()` verwenden.
4. Zuerst den Fünf-Minuten-Machine-Modus-Pilot offline gegen eine feste Policy, eine einfache tabellarische Regression und einen baumbasierten Ansatz vergleichen. Prognosefehler, Rangfolge der Batches und tatsächlich erreichten Regret gegenüber den simulierten Alternativen messen.
5. Danach im geschlossenen Regelkreis Durchsatz, Ausschuss, Verspätung, Stillstand, Kosten sowie gesamte Provider-Latenz und Speicherbedarf vergleichen. Gute Regression allein beweist keine bessere Steuerung.

SCM-Vortraining macht eine Vorhersage aus passiv beobachteten Zusammenhängen nicht automatisch zu einer kausalen Wirkungsprognose. Die hier vorgeschlagene Interventionsvariation liefert die dafür relevante Evidenz; die Aussagen bleiben abhängig von Kontextabdeckung und der festgelegten Fortsetzungspolicy. Das ist eine methodische Ableitung, keine von TabFM garantierte Eigenschaft.

Ein ausschließlich auf IndustrialSim-Branches gestütztes Ersatzmodell lernt die dort deklarierten synthetischen Mechanismen. Es ergänzt keine empirische Physik und kalibriert keine reale Plant; dafür wären reale Messungen und eine getrennte Transferprüfung erforderlich.

## Praktische Modellgrenzen

Das September-Paper beschreibt etwa 400 Millionen Parameter, synthetisches Vortraining bis 16.384 Zeilen und 100 Spalten und einen einzelnen skalaren Regressionsoutput. Größere Tabellen benötigen Längengeneralisierung oder Sampling. Diese Vortrainingsgrößen sind keine zugesicherte Hardwaregrenze. Die berichteten TabArena-Ergebnisse belegen keine Güte für IndustrialSim. [Paper, Abschnitte 3 und 6](https://arxiv.org/pdf/2609.37959)

Die aktuelle offizielle Implementierung und das README widersprechen sich: Das README-FAQ nennt 100 Kontextzeilen und `inference_batch_size`; der Quellcode verwendet `max_num_rows=None`, `n_estimators=32`, `max_num_features=500` und `batch_size=1`. `max_num_rows` sampelt tatsächlich Kontextzeilen je Ensemblemitglied; `batch_size` zählt gleichzeitig berechnete Ensemblemitglieder. Deshalb Parameter ausdrücklich setzen und Quellcode-Revision pinnen. `cache_context=True` wiederverwendet Kontextrepräsentationen nur im PyTorch-Backend; standardmäßige Cache-Quantisierung verändert Rundungen. Der Regressor liefert Punktprognosen, keine native Quantil- oder Intervallschnittstelle. [Estimator-Quellcode](https://github.com/google-research/tabfm/blob/main/tabfm/src/classifier_and_regressor.py), [README-FAQ](https://github.com/google-research/tabfm#faq)

Klassifikation unterstützt höchstens zehn Klassen und bietet `predict_proba()`. Für Ausfall- oder Überlaufrisiken wäre ein gesonderter binärer Klassifikator möglich. Probabilitäten und etwaige extern ergänzte Regressionsintervalle müssen an getrennten Validierungsdaten geprüft werden; Ensemble-Streuung allein ist keine garantierte Unsicherheit. [Modellkarte](https://huggingface.co/google/tabfm-1.1.0-pytorch)

## API-Skizze für den Offline-Pilot

Die Modellkarte des Papers nennt Version 1.1.0; der Juni-Blog und das README verwenden noch 1.0.0. Folgende Skizze folgt der 1.1.0-Modellkarte und setzt Sampling und Ensemblegröße ausdrücklich. Sie ist nicht ausgeführt und muss gegen die gepinnte Paketrevision geprüft werden. [Modellkarte 1.1.0](https://huggingface.co/google/tabfm-1.1.0-pytorch), [Juni-Blog](https://research.google/blog/introducing-tabfm-a-zero-shot-foundation-model-for-tabular-data/)

```python
from tabfm import TabFMRegressor, tabfm_v1_1_0_pytorch

model = tabfm_v1_1_0_pytorch.load(model_type="regression")
regressor = TabFMRegressor(
    model=model,
    n_estimators=1,
    max_num_rows=1024,
    max_num_features=100,
    random_state=42,
)
regressor.fit(X_context, y_good_output_delta)
predicted_delta = regressor.predict(X_valid_batches)
```

`X_context` und `X_valid_batches` müssen denselben versionierten Featurevertrag besitzen. 1.024 Kontextzeilen und 100 Merkmale sind Startwerte für den Pilot, keine optimale Konfiguration. Für Entscheidungen derselben Beobachtung alle Kandidaten gemeinsam berechnen, ein fixes Kontextset verwenden und Ladezeit getrennt von warmen Vorhersagen messen. Später Kontextcaching und mehrere Ensemblemitglieder gegeneinander benchmarken. Regressionsintervalle gegebenenfalls separat mit gehaltenen Residuen kalibrieren.

Python ab 3.11 und optionale JAX- oder PyTorch-Backends sind vorgesehen. `pyproject.toml` erzwingt keine konkrete Torch-Version; das README nennt eine aktuelle gepinnte Umgebung. TabFM sollte als optionale Modellabhängigkeit in die bestehende gemeinsame `.venv` aufgenommen werden, nach Prüfung der Kompatibilität mit dem vorhandenen ROCm/PyTorch-Build. ROCm-Kompatibilität, benötigter VRAM und Latenz wurden hier nicht verifiziert oder gemessen; aus einer CUDA-Anleitung folgt keine garantierte ROCm-Unterstützung. [Paketmetadaten](https://github.com/google-research/tabfm/blob/main/pyproject.toml), [Installationshinweise](https://github.com/google-research/tabfm#installation)

## Nutzungslizenz

Der Quellcode ist Apache-2.0-lizenziert. Die Gewichte von 1.0.0 und 1.1.0 stehen unter `tabfm-non-commercial-v1.0`. Die offizielle Lizenz erlaubt nur nichtkommerzielle, nichtproduktive Zwecke und schließt unter anderem kommerzielle Entscheidungen, Kundenergebnisse sowie entsprechende Nutzung von Outputs aus. Für kommerziellen oder produktiven Einsatz ist daher eine passende separate Berechtigung erforderlich; ein Forschungsbenchmark und eine spätere Integration müssen diesen Unterschied berücksichtigen. [README-Lizenzhinweis](https://github.com/google-research/tabfm#license-notice-for-pretrained-weights), [Gewichtslizenz](https://huggingface.co/google/tabfm-1.0.0-pytorch/blob/main/LICENSE), [1.1.0-Modellkarte](https://huggingface.co/google/tabfm-1.1.0-pytorch)
