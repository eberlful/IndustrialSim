Status: ready-for-agent

# Reproducible Industrial Production Simulation

## Problem Statement

Der Nutzer benötigt eine leicht erweiterbare, reproduzierbare Simulationsumgebung für eine Automobilproduktion. Ein Plant besteht organisatorisch aus Areas und Halls, während der tatsächliche Materialfluss unabhängig davon als gerichteter Graph modelliert werden muss. Production Units sollen durch Rohbau, Lackiererei und Endmontage fließen und dabei begrenzte Buffer, Maschinenzustände, Worker, Transporte, Qualitätsabweichungen, Nacharbeit und Ausfälle erleben.

Die Umgebung soll nicht lediglich Durchsatz berechnen. Sie soll feste Heuristiken und externe Decision Provider unter identischen Bedingungen vergleichen, strukturierte Decision Requests auslösen, den Lauf an konsistenten Punkten pausieren und aus einem Checkpoint mehrere kontrollierte Counterfactual Branches bilden. Ohne deterministische Zeit-, Ereignis- und Zufallssemantik wären diese Vergleiche nicht belastbar. Ohne klare Verträge zwischen Engine, Produktionsdomäne, Entscheidungen und Telemetrie wäre das System außerdem schwer erweiterbar und würde schnell stationsspezifische Logik in den Simulationskern ziehen.

## Solution

V1 liefert eine headless, konfigurationsgetriebene diskrete Ereignissimulation auf CPython 3.14. Ein kleiner eigener Event-Kernel verwaltet ausschließlich ganzzahlige Simulationszeit, deterministisch geordnete Datenereignisse, expliziten Zustand, Zufallsströme und portable Checkpoints. Die Automobilproduktion liegt in einer getrennten Domänenschicht. Der organisatorische Aufbau Plant → Area → Hall und der Material Flow Graph sind orthogonale Modelle.

Das mitgelieferte Referenzmodell bildet Rohbau, Lackiererei und Endmontage mit zwei Produktvarianten, parallelen und sequenziellen Stations, begrenzten Buffers, expliziter Logistik, Nacharbeit, Ausschuss, Worker-Schichten, Ausfällen und zustandsabhängiger Degradation ab. Eine feste Baseline-Heuristik kann gegen einen austauschbaren Decision Provider verglichen werden. Decision Batches liefern versionierte, begrenzte Beobachtungen und validierbare Aktionsschemas. Checkpoints erlauben reproduzierbare Fortsetzung und isolierte Counterfactual Branches mit kontrolliert gemeinsamem Zufall.

Ein verlustfreies JSONL-Auditlog hält entscheidungs- und reproduktionsrelevante Ereignisse fest. Optionale Telemetrie wird laufzeitkonfigurierbar gesammelt und in abgeschlossene Parquet-Fragmente überführt. CLI und Python-API verwenden dieselbe Application-Schicht für Validierung, Episodenläufe, Resume, Branching, Inspektion und Benchmarks.

## User Stories

1. Als Simulationsanwender möchte ich ein Plant aus YAML laden, damit ich Produktionsmodelle ohne Änderungen am Simulationskern definieren kann.
2. Als Modellierer möchte ich ein Plant in Areas und Halls gliedern, damit organisatorische und räumliche Zugehörigkeiten ausdrücklich beschrieben sind.
3. Als Modellierer möchte ich den Material Flow Graph unabhängig von der Plant-Hierarchie definieren, damit Transporte Bereichs- und Hallengrenzen überqueren können.
4. Als Modellierer möchte ich Stations, Buffers, Quellen und Senken als Knoten eines gerichteten Multigraphen anlegen, damit reale Produktionsflüsse einschließlich Alternativrouten abbildbar sind.
5. Als Modellierer möchte ich parallele Routen und Zyklen definieren, damit Umleitungen und Nacharbeit modelliert werden können.
6. Als Modellierer möchte ich typisierte Ports verwenden, damit inkompatible Materialübergaben bereits vor einem Lauf erkannt werden.
7. Als Modellierer möchte ich stabile, lesbare IDs vergeben, damit Konfiguration, Auditlog und Diagnoseberichte dieselben Objekte eindeutig benennen.
8. Als Modellierer möchte ich Makromodelle und detaillierte Teilgraphen über denselben äußeren Vertrag austauschen, damit ich die Granularität abschnittsweise skalieren kann.
9. Als Modellierer möchte ich neue Kombinationen vorhandener Policies ausschließlich per Konfiguration erstellen, damit Varianten keinen neuen Code benötigen.
10. Als Plugin-Autor möchte ich wirklich neues Verhalten über stabile Typ-IDs registrieren, damit Erweiterungen explizit, versioniert und validierbar bleiben.
11. Als Sicherheitsverantwortlicher möchte ich, dass Konfiguration keinen dynamischen Code und keine impliziten Imports ausführen kann, damit das Laden eines Modells vorhersehbar bleibt.
12. Als Simulationsanwender möchte ich unbekannte Konfigurationsfelder als Fehler sehen, damit Tippfehler nicht stillschweigend zu falschen Experimenten führen.
13. Als Produktionsplaner möchte ich einen Production Plan mit Freigabezeiten, Varianten, Mengen und Lieferterminen definieren, damit eine Episode einen klaren Auftragseingang besitzt.
14. Als Experimentverantwortlicher möchte ich stochastische Nachfrage vor Episodenbeginn materialisieren, damit alle Counterfactual Branches dasselbe Produktionsprogramm erhalten.
15. Als Modellierer möchte ich pro Produktvariante einen Process Plan definieren, damit erforderliche Operations und kompatible Alternativen nachvollziehbar sind.
16. Als Produktionsplaner möchte ich mehrere kompatible Stations und Routen für einen Process-Plan-Schritt zulassen, damit eine Routing Policy die konkrete Ausführung wählen kann.
17. Als Qualitätsplaner möchte ich Nacharbeit als explizite zusätzliche Operations modellieren, damit Prozesshistorie und Kosten nachvollziehbar bleiben.
18. Als Analyst möchte ich jede Production Unit über eine stabile Identität, Variante, Quality State und Prozesshistorie verfolgen, damit Einzelschicksale analysiert werden können.
19. Als Modellierer möchte ich gewährleisten, dass jede Production Unit genau an einem Knoten, in einem Transport oder terminal ist, damit Material weder verschwindet noch dupliziert wird.
20. Als Modellierer möchte ich Operations definieren, die Einheiten verändern, zusammenführen, aufteilen, nacharbeiten oder verschrotten können, damit unterschiedliche Fertigungsprozesse abbildbar sind.
21. Als Modellierer möchte ich Buffers mit begrenzter Kapazität konfigurieren, damit Rückstau und Blockierung realistisch entstehen.
22. Als Produktionsanalyst möchte ich blocking-after-service als Standard erleben, damit eine fertige Einheit eine Station bis zur möglichen Übergabe blockieren kann.
23. Als Modellierer möchte ich optionale Stations-Ausgangskapazitäten definieren, damit abweichende reale Layouts darstellbar sind.
24. Als Modellierer möchte ich Machines und Workers als belegbare Ressourcen definieren, damit Operations von real verfügbaren Kapazitäten abhängen.
25. Als Schichtplaner möchte ich Worker-Qualifikationen, Schichten und Pausen konfigurieren, damit nur geeignete und verfügbare Worker eingesetzt werden.
26. Als Modellierer möchte ich alle Ressourcen einer Operation atomar reservieren, damit keine Teilreservierungs-Deadlocks entstehen.
27. Als Modellierer möchte ich pro Operation festlegen, ob eine Unterbrechung Resume, Restart oder Scrap verursacht, damit fachlich unterschiedliche Prozesse korrekt reagieren.
28. Als Schichtplaner möchte ich eine ausdrückliche Übergaberegel für laufende Arbeit definieren, damit Schichtende nicht implizit und überraschend unterbricht.
29. Als Instandhalter möchte ich geplante Störungen und stochastische Maschinenausfälle konfigurieren, damit robuste Steuerungen getestet werden können.
30. Als Instandhalter möchte ich einen Health State und optionale physikalische Zustandsgrößen modellieren, damit Maschinen zustandsabhängig degradieren können.
31. Als Modellierer möchte ich Verschleiß abhängig vom Maschinenmodus definieren, damit höhere Leistung nachvollziehbare Langzeitfolgen hat.
32. Als Instandhalter möchte ich Health State auf Zykluszeit, Defektwahrscheinlichkeit und Ausfallhazard wirken lassen, damit Degradation operative Entscheidungen beeinflusst.
33. Als Instandhalter möchte ich Inspektion, präventive Wartung und Reparatur als zeit- und ressourcenverbrauchende Operations behandeln, damit Wartung nicht kostenlos geschieht.
34. Als Modellierer möchte ich begrenzen, wie weit Wartung den Health State wiederherstellt, damit Reparatur keine unrealistische Sofortheilung ist.
35. Als Qualitätsverantwortlicher möchte ich latenten Quality State von Quality Findings trennen, damit ein Decision Provider keine verborgenen Defekte kennt.
36. Als Qualitätsverantwortlicher möchte ich Sensitivität und Falsch-Positiv-Rate von Prüfungen konfigurieren, damit unvollkommene Inspektion abbildbar ist.
37. Als Qualitätsverantwortlicher möchte ich Prüfintensität, Stichprobenrate und Freigabeschwellen innerhalb freigegebener Grenzen verändern können, damit taktische Qualitätsentscheidungen möglich sind.
38. Als Sicherheitsverantwortlicher möchte ich gesetzliche und sicherheitskritische Grenzen unveränderlich halten, damit ein Agent schlechte Qualität nicht durch Umklassifizierung kaschieren kann.
39. Als Logistikplaner möchte ich explizite Transport Orders erzeugen, damit Materialbewegungen Kapazität und Zeit beanspruchen.
40. Als Logistikplaner möchte ich gemeinsam genutzte Fahrzeugpools und routenbezogene Kapazität definieren, damit Fahrzeugkonflikte und Stau entstehen können.
41. Als Steuerungsentwickler möchte ich eine austauschbare Dispatch Policy verwenden, damit Fahrzeug- und Routenzuweisung unabhängig von der Logistikphysik optimiert werden kann.
42. Als Steuerungsentwickler möchte ich eine austauschbare Routing Policy verwenden, damit Produktionsrouting unabhängig vom Process Plan variiert werden kann.
43. Als Benchmark-Nutzer möchte ich eine deterministische Baseline mit FIFO, Liefertermin-Tie-Breaker, nächstem geeigneten Fahrzeug, kürzester Route und Health-basierter Wartung ausführen, damit Agentenergebnisse einen verständlichen Vergleichspunkt haben.
44. Als Agentenentwickler möchte ich Prioritäten, zulässige Routen, Maschinenmodi, Transportzuweisungen und Wartungszeitpunkte beeinflussen, damit der Decision Provider reale Zielkonflikte steuern kann.
45. Als Sicherheitsverantwortlicher möchte ich verhindern, dass Actions Kapazitäten erfinden, verborgene Qualität lesen oder harte Constraints überschreiben, damit Entscheidungen fachlich zulässig bleiben.
46. Als Agentenentwickler möchte ich ereignisgetriebene Decision Requests bei Ausfällen, kritischer Qualität, Buffer-Schwellen und anderen Zustandsübergängen erhalten, damit nicht nur periodisch entschieden wird.
47. Als Agentenentwickler möchte ich taktische und strategische Actions getrennt behandeln, damit weitreichende Eingriffe nur an sicheren Entscheidungspunkten erfolgen.
48. Als Simulationsanwender möchte ich, dass ein Decision Batch das gesamte Plant an einem konsistenten Zustand pausiert, damit alle Antworten dieselbe Welt beobachten.
49. Als Agentenentwickler möchte ich lokale Details, relevante Nachbarschaft, aggregierte Plant-Metriken und begrenzte Historie erhalten, damit Entscheidungen informativ bleiben, ohne Interna offenzulegen.
50. Als Integrator möchte ich versionierte JSON-kompatible Beobachtungs- und Aktionsschemas verwenden, damit derselbe Vertrag in-process und später remote funktioniert.
51. Als Experimentverantwortlicher möchte ich Provider-, Modell- und Prompt-Metadaten protokollieren, damit Ergebnisse einem konkreten Agentenaufbau zugeordnet werden können.
52. Als Simulationsanwender möchte ich alle Actions eines Decision Batch gemeinsam validieren, damit Konflikte nicht durch zufällige Reihenfolge gelöst werden.
53. Als Simulationsanwender möchte ich Konflikte explizit ablehnen und per Fallback oder Episodenabbruch behandeln, damit fehlerhafte Agentenantworten sichtbar bleiben.
54. Als Betreiber möchte ich pro Request-Typ eine deterministische Fallback Policy konfigurieren, damit Provider-Ausfälle reproduzierbar behandelt werden.
55. Als Betreiber möchte ich Wall-Clock-Timeouts im Host-Adapter statt im Simulationskern definieren, damit während des Wartens keine Simulationszeit verstreicht.
56. Als Modellierer möchte ich Trigger mit Hysterese, Re-Arm-Bedingung und Deduplizierungsschlüssel konfigurieren, damit unveränderte Zustände keine Endlosschleifen erzeugen.
57. Als Experimentverantwortlicher möchte ich eine Episode über Simulationsdauer, Warm-up und zusätzliche Abbruchbedingungen definieren, damit Trainingsbeispiele vergleichbar sind.
58. Als Analyst möchte ich Warm-up-Daten aus Reward und Ergebnis ausschließen, damit ein künstlich leerer Anfangszustand Kennzahlen nicht verzerrt.
59. Als Experimentverantwortlicher möchte ich Deadlocks, ungültige Konfigurationen und harte Constraint-Verletzungen als strukturierte Endzustände sehen, damit gescheiterte Episoden auswertbar sind.
60. Als Diagnostiker möchte ich bei einem Deadlock beteiligte Production Units, Resources, Buffers und Wartebeziehungen erhalten, damit die Ursache auffindbar ist.
61. Als Experimentverantwortlicher möchte ich einen Root Seed und deterministisch abgeleitete Episode-, Branch-, Event- und Production-Unit-IDs verwenden, damit ein Experiment exakt wiederholbar ist.
62. Als Experimentverantwortlicher möchte ich denselben Lauf aus Konfiguration, Startzustand, Seed und Actions bitgenau reproduzieren, damit Policy-Vergleiche belastbar sind.
63. Als Entwickler möchte ich gleichzeitige Events über Zeit, feste Priorität und monotone Sequenznummer ordnen, damit Gleichstände eindeutig aufgelöst werden.
64. Als Entwickler möchte ich Simulationszeit als ganzzahlige Nanosekunden speichern, damit Gleitkommarundung keine Ereignisreihenfolge verändert.
65. Als Konfigurationsautor möchte ich menschenlesbare Dauern angeben, damit Modelle trotz exakter interner Zeit verständlich bleiben.
66. Als Experimentverantwortlicher möchte ich semantisch adressierte Philox-Zufallsströme verwenden, damit zusätzliche Ziehungen in einem Branch andere Entitäten nicht unbeabsichtigt verändern.
67. Als Experimentverantwortlicher möchte ich an einem Decision Point einen Checkpoint erzeugen, damit alternative Actions vom identischen Zustand starten.
68. Als Experimentverantwortlicher möchte ich Checkpoints dauerhaft speichern und später fortsetzen, damit Ergebnisse unabhängig vom laufenden Prozess reproduzierbar sind.
69. Als Experimentverantwortlicher möchte ich inkompatible Checkpoints mit klarer Diagnose ablehnen, damit Best-Effort-Laden keine falschen Ergebnisse erzeugt.
70. Als Entwickler möchte ich explizite getestete Checkpoint-Migrationen bereitstellen können, damit ausgewählte historische Experimente weiter nutzbar bleiben.
71. Als Experimentverantwortlicher möchte ich zwei bis acht Counterfactual Branches isoliert ausführen, damit Actions direkt miteinander verglichen werden können.
72. Als Diagnostiker möchte ich Branches wahlweise sequenziell ausführen, damit Debugging ohne Prozessparallelität dasselbe Ergebnis liefert.
73. Als Betreiber möchte ich mehrere Branches in getrennten Worker-Prozessen ausführen, damit CPU-Kerne genutzt werden, ohne einen Branch intern nebenläufig zu machen.
74. Als Analyst möchte ich rohe Metriken zu Gutteilen, Durchlaufzeit, WIP, Ausschuss, Stillstand, Verspätung und Ressourcenauslastung erhalten, damit unterschiedliche Zielsysteme vergleichbar bleiben.
75. Als Agentenentwickler möchte ich eine transparente Reward Policy konfigurieren, damit normalisierte Metriken in einen skalaren Trainingsreward überführt werden können.
76. Als Sicherheitsverantwortlicher möchte ich harte Constraints getrennt vom Reward auswerten, damit kein hoher Durchsatz Sicherheitsverletzungen aufwiegt.
77. Als Auditor möchte ich Decision Requests, Actions, Rewards, Ausfälle und Production-Unit-Übergänge verlustfrei und geordnet in JSONL erhalten, damit ein Lauf nachvollziehbar bleibt.
78. Als Datenanalyst möchte ich Metriken und Trainingsdaten als abgeschlossene Parquet-Fragmente erhalten, damit sie effizient analysiert werden können.
79. Als Betreiber möchte ich Telemetrie zur Laufzeit aktivieren und Sample-Raten konfigurieren, damit Beobachtungsaufwand kontrollierbar bleibt.
80. Als Betreiber möchte ich optionale Telemetrie bei Backpressure ausdünnen können, ohne kritische Auditdaten zu verlieren, damit Monitoring die Simulation nicht unkontrolliert blockiert.
81. Als Auditor möchte ich ein Run-Manifest mit Runtime-, Schema-, Modell-, Konfigurations- und Pluginversionen erhalten, damit Reproduzierbarkeit überprüfbar ist.
82. Als Nutzer möchte ich, dass jeder Lauf in ein neues, fest strukturiertes Ergebnisverzeichnis schreibt, damit Ergebnisse nicht überschrieben oder vermischt werden.
83. Als Nutzer möchte ich unvollständige Läufe eindeutig erkennen, damit Teilergebnisse nicht als erfolgreiche Experimente ausgewertet werden.
84. Als Nutzer möchte ich ein Modell und Experiment vor Ausführung validieren, damit strukturelle Fehler früh sichtbar werden.
85. Als Nutzer möchte ich eine Episode über CLI oder Python-API ausführen, damit interaktive und automatisierte Workflows dieselbe Logik verwenden.
86. Als Nutzer möchte ich einen Checkpoint fortsetzen, damit lange oder pausierte Experimente wieder aufgenommen werden können.
87. Als Nutzer möchte ich alternative Actions von einem Checkpoint vergleichen, damit Counterfactual-Daten ohne eigene Orchestrierung entstehen.
88. Als Nutzer möchte ich Manifeste, Checkpoints und Ergebnisse inspizieren, damit ich Läufe ohne manuelles Parsen verstehen kann.
89. Als Entwickler möchte ich Scheduler- und Referenzwerk-Benchmarks ausführen, damit Performance-Regressions sichtbar werden.
90. Als CI-Betreiber möchte ich maschinenlesbare CLI-Ausgaben und eindeutige Exitcodes erhalten, damit Automatisierung Fehler sicher erkennt.
91. Als Entwickler möchte ich fünf Millionen einfache Scheduler-Events in weniger als 60 Sekunden auf dokumentierter Referenzhardware verarbeiten, damit der Kernel die V1-Zielgröße trägt.
92. Als Anwender möchte ich eine Produktionswoche mit 100 bis 500 aktiven Ressourcen und mehreren Millionen Events in weniger als 60 Sekunden simulieren, damit Experimente interaktiv nutzbar bleiben.
93. Als Entwickler möchte ich Ergebnis-Hashes wiederholter Läufe vergleichen, damit Determinismus automatisch nachgewiesen wird.
94. Als Modellvalidator möchte ich kleine Modelle gegen analytisch berechenbare Ergebnisse prüfen, damit fachliche Korrektheit nicht nur aus Codeabdeckung abgeleitet wird.
95. Als Modellvalidator möchte ich realistische Modelle gegen dokumentierte Referenzdaten kalibrieren, damit quantitative Aussagen belastbar sind.
96. Als Analyst möchte ich synthetische, nicht kalibrierte Parameter im Run-Manifest erkennen, damit Ergebnisse keine Scheingenauigkeit suggerieren.

## Implementation Decisions

- V1 verwendet CPython 3.14 und beschränkt die unterstützte Runtime auf diese Minor-Version. Das bestehende 3.12-Gerüst wird vor der Implementierung entsprechend angehoben.
- Es wird ein kleiner eigener diskreter Event-Kernel gebaut. SimPy ist keine Runtime-Abhängigkeit, weil generatorbasierte Prozesse portable, versionierte Checkpoints und günstige Counterfactual Branches behindern.
- Der Kernel kennt ausschließlich ganzzahlige Simulationszeit, deterministische Eventordnung, checkpointbare Zufallsströme, Ressourcenaktivierung und explizite serialisierbare Zustände. Produktionsbegriffe verbleiben in der Domain-Schicht.
- Queue-Einträge sind Datenrecords aus Zeit, Priorität, Sequenz, stabiler Event-Typ-ID, Payload-Version und Payload. Persistierter Zustand enthält keine Generatoren, Closures, Callables oder lebenden Domain-Objekte.
- Die feste Prioritätsordnung behandelt zuerst Sicherheit und harte Constraints, danach Ausfälle, Abschlüsse, Ressourcenfreigaben und -erwerb, neue Arbeit und zuletzt Telemetrie-Snapshots.
- Domain-Handler dürfen expliziten Zustand verändern und neue Datenereignisse planen, aber Uhr und interne Queue-Struktur nicht direkt manipulieren.
- Die Simulationszeit wird intern in ganzzahligen Nanosekunden geführt. Konfigurationsdauern werden beim Laden exakt normalisiert; Gleitkommazeit ist unzulässig.
- Zufall verwendet benannte, checkpointbare Philox-Ströme. Semantische Schlüssel enthalten mindestens Stream-Art, Entitäts-ID, Fehlermodus und Auftretensnummer.
- Die Architektur besteht aus getrennten Modulen für Engine, Domain, Decisions, Telemetry und Application. Referenzmodelle liegen außerhalb der Kernmodule.
- CLI und Python-API greifen auf dieselbe Application-Schicht zu. Vorgesehene Operationen sind validate, run, resume, branch, inspect und benchmark.
- Pydantic validiert Systemgrenzen strikt; Event-Hotpaths verwenden schlanke explizite Zustandsrecords.
- Modelle und Experimente verwenden YAML 1.2. Unbekannte Felder, doppelte Typ-IDs, fehlende Pluginversionen, dynamischer Code und implizite Importpfade sind Fehler.
- Plugins werden über stabile Typ-IDs und Python Entry Points registriert und müssen lokal installiert sowie ausdrücklich freigegeben sein.
- Die Standortstruktur Plant → Area → Hall ist unabhängig vom Material Flow Graph.
- Der Material Flow Graph ist ein gerichteter Multigraph mit typisierten Ports, Zyklen und parallelen Routen. Quellen, Senken, Portkompatibilität und Erreichbarkeit werden vor Ausführung geprüft.
- Station definiert eine dünne abstrakte Schnittstelle für Identität, Ports, beobachtbaren Zustand und Eventbehandlung. Zykluszeit, Ressourcenbedarf, Qualität, Degradation und Ausfälle werden durch komponierte registrierte Policies implementiert.
- Makromodelle und detaillierte Teilgraphen verwenden denselben Vertrag für Materialeingänge, Materialausgänge, Kapazität, beobachtbaren Zustand und Ereignisse.
- Production Units besitzen stabile Identität, Variante, latenten Quality State und Historie. Verbrauchsteile werden in V1 als Bestände statt als einzeln verfolgte Einheiten modelliert.
- Jede Production Unit befindet sich genau an einem Graphknoten, in genau einem Transport oder in einem terminalen Zustand.
- Production Plans werden vor Episodenbeginn vollständig materialisiert. Process Plans deklarieren erforderliche Operations und kompatible Alternativen; Routing Policies wählen den konkreten Pfad.
- Operations erwerben alle erforderlichen Ressourcen atomar. Blocking-after-service ist Standard; optionale Ausgangskapazität kann konfiguriert werden.
- Unterbrechungsverhalten wird pro Operation als Resume, Restart oder Scrap festgelegt. Schichtwechsel verwenden ausdrückliche Übergaberegeln.
- Worker können individuell oder gepoolt sein und besitzen Qualifikationen, Schichtverfügbarkeit und Pausen. Dynamische Ermüdung und Ergonomie sind nicht Bestandteil des ersten Slice.
- Machines besitzen einen Health State von 0 bis 1 und optional benannte physikalische Zustände. Betrieb, Leerlauf, Inspektion, Wartung und Reparatur verändern den Zustand über konfigurierte Funktionen.
- Health State kann Zykluszeit, Defektwahrscheinlichkeit und Ausfallhazard beeinflussen. Wartung und Reparatur benötigen Zeit, optional qualifizierte Worker, und stellen Health nur bis zu einem konfigurierten Niveau wieder her.
- Quality State ist latent. Quality Findings entstehen durch Prüfungen mit konfigurierbarer Sensitivität und Falsch-Positiv-Rate. Decision Provider erhalten niemals latente Wahrheit.
- Transport Orders, Fahrzeugpools, Routenkapazität und Dispatch Policies sind explizite Domain-Elemente. Fahrer, Batterien und detaillierte Verkehrswege bleiben Erweiterungen.
- Decision Requests werden ereignisgetrieben an Zustandsübergängen ausgelöst. Trigger besitzen Re-Arm-Bedingungen oder Hysterese, Deduplizierungsschlüssel und ein Batch-Limit pro Simulationszeitpunkt.
- Alle Decision Requests eines Pausepunkts bilden einen Decision Batch, beobachten denselben Zustand und werden gemeinsam validiert. Actions werden atomar angewendet; Konflikte führen zu Fallback oder Abbruch.
- Der vollständige Simulationslauf pausiert an einem Decision Batch. Während des Wartens vergeht keine Simulationszeit. Wall-Clock-Timeouts liegen im Host-Adapter.
- Decision-Verträge sind versioniert und JSON-kompatibel. Sie enthalten Episode-, Branch- und Batch-Korrelation sowie Provider-, Modell- und Prompt-Provenienz.
- Beobachtungen enthalten lokale Details, relevante Nachbarschaft, aggregierte Plant-Metriken und begrenzte Historie. Direkter Zugriff auf interne Objekte und latenten Quality State ist ausgeschlossen.
- Taktische Actions umfassen Priorisierung, Dispatch, Routing und zulässige Maschinenmodi. Strategische Actions wie Umrüstung, Wartungsplanung, Personalneuzuweisung und Qualitätsparameteränderung sind nur an sicheren Entscheidungspunkten zulässig und tragen Dauer und Kosten.
- Sicherheitskritische Qualitätsgrenzen sind keine Actions. Prüfintensität, Stichprobenrate und Freigabeschwellen dürfen nur innerhalb freigegebener Grenzen verändert werden.
- Jeder Request-Typ verlangt eine deterministische Fallback Policy. Eine ungültige Antwort wird mit Fehlergrund protokolliert und genau einmal ersetzt oder beendet die Episode gemäß Konfiguration.
- Eine Episode besitzt konfigurierbare Dauer, standardmäßig eine Produktionswoche, sowie optional eine ausgeschlossene Warm-up-Schicht. Deadlock, ungültiger Zustand oder harte Constraint-Verletzung können zusätzlich abbrechen.
- Deadlocks werden durch Wait-for-Zyklen und eine konfigurierbare Zeit ohne Domain-Fortschritt erkannt. Diagnoseberichte nennen beteiligte Entitäten und Wartebeziehungen.
- Checkpoints enthalten vollständigen Fortsetzungszustand, Queue, Zeit, nächste Sequenz, Root Seed, Zufallszähler und Kompatibilitätsmetadaten. Inkompatible Checkpoints werden ohne ausdrückliche Migration abgelehnt.
- Ein Branch bleibt single-threaded. Mehrere Branches dürfen aus serialisierten Checkpoints in isolierten Worker-Prozessen laufen; sequenzielle Ausführung muss identische Ergebnisse liefern.
- Die Simulation liefert einen rohen Metrikvektor. Eine konfigurierbare Reward Policy kann normalisierte Komponenten in einen Skalar überführen; harte Constraints bleiben getrennt.
- JSONL ist das kanonische, geordnete und verlustfreie Auditlog. Parquet wird in abgeschlossenen rotierenden Fragmenten als abgeleitetes Analyseformat geschrieben.
- Optionale Telemetrie besitzt Laufzeit-Toggle, Sample-Rate und konfigurierbare Backpressure. Kritische Auditdaten dürfen niemals ausgedünnt werden.
- Jeder Lauf schreibt atomar in ein neues Ergebnisverzeichnis mit Manifest, aufgelöster Konfiguration, Auditlog, Checkpoints, Metriken und Summary. Unvollständige Läufe bleiben markiert.
- Das Referenzwerk umfasst Rohbau mit parallelen Stations, Lackvorbehandlung, Lackierkabine, Trocknung, sequenzielle Endmontage, begrenzte Buffers, gemeinsam genutzte Fahrzeuge, zwei Varianten, Nacharbeit und Ausschuss.
- Die Baseline Policy verwendet FIFO, frühesten Liefertermin als Tie-Breaker, nächstes geeignetes Fahrzeug, kürzeste zulässige Route und Health-basierte präventive Wartung. Strategische Umrüstung findet in der Baseline während einer Episode nicht statt.
- Der V1-Scope umfasst Durchsatz, Qualität, WIP, Ausfälle, Degradation, Ressourcen, Schichten, begrenzte Buffers und Logistik. Energie, CO₂, dynamische Ermüdung und Ergonomie erhalten Erweiterungspunkte, aber keine V1-Dynamik.

## Testing Decisions

- Die primäre Testnaht ist die Application API. Tests laden ein vollständiges Experiment, führen es aus und beurteilen ausschließlich sichtbare Ergebnisse: Status, Summary, Auditlog, Metriken, Checkpoints und Diagnoseartefakte.
- CLI-Tests bleiben dünn und prüfen, dass die Application-Funktionen korrekt erreichbar sind, maschinenlesbare Ergebnisse liefern und eindeutige Exitcodes verwenden. Fachlogik wird nicht über CLI-Interna doppelt getestet.
- Der Kernel erhält ergänzende Property-Tests, weil Determinismus, Ereignisordnung und Snapshot-Äquivalenz fundamentale Invarianten sind, die an der höchsten End-to-End-Naht allein nur schwer lokalisierbar wären.
- Für dieselbe Konfiguration, denselben Startzustand, denselben Seed und dieselben Actions müssen wiederholte Läufe identische Ergebnis-Hashes erzeugen.
- Ein ununterbrochener Lauf und ein Lauf mit Snapshot, Serialisierung, Restore und Fortsetzung müssen identische sichtbare Ergebnisse liefern.
- Sequenziell und in isolierten Worker-Prozessen berechnete Counterfactual Branches müssen identische Branch-Ergebnisse liefern.
- Property-Tests erzeugen variierte Eventfolgen und prüfen die Ordnung nach Zeit, Priorität und Sequenz sowie die Monotonie der Simulationszeit.
- Property-Tests variieren Graphen und prüfen, dass jede Production Unit immer genau einen zulässigen Ort oder terminalen Zustand besitzt.
- Konfigurationstests prüfen unbekannte Felder, ungültige YAML-Typen, inkompatible Ports, unerreichbare Senken, doppelte IDs, doppelte Plugin-Typen und fehlende Pluginversionen.
- Ressourcen-Szenarien prüfen atomare Reservierung, blocking-after-service, Resume, Restart, Scrap und Schichtübergabe ausschließlich anhand beobachtbarer Zustandsfolgen.
- Decision-Szenarien prüfen gemeinsame Beobachtung eines Batches, atomare Action-Anwendung, Konfliktablehnung, Fallback, Abbruch, Trigger-Hysterese und Schutz gegen Wiederholung am selben Zeitpunkt.
- Qualitäts-Szenarien prüfen, dass latente Defekte Beobachtungen nicht ohne Quality Finding beeinflussen und dass Sensitivität sowie Falsch-Positiv-Rate reproduzierbar wirken.
- Degradations-Szenarien prüfen sichtbare Auswirkungen auf Zykluszeit, Defektwahrscheinlichkeit, Ausfälle, Wartungsdauer und Health-Wiederherstellung.
- Logistik-Szenarien prüfen Transportkapazität, Fahrzeugkonflikte, Dispatch, alternative Routen und Rückstau.
- Deadlock-Tests erzeugen bekannte Wait-for-Zyklen und Stillstand trotz irrelevanter Kalenderereignisse und prüfen den strukturierten Diagnosebericht.
- Audit-Tests prüfen Reihenfolge und Verlustfreiheit kritischer Records. Telemetrie-Tests dürfen Ausdünnung optionaler Samples erlauben, aber niemals den Verlust kritischer Records.
- Parquet-Tests prüfen Schema, abgeschlossene Fragmente und inhaltliche Ableitung aus dem Audit-/Metrikstrom, nicht interne Writer-Aufrufe.
- Ein analytisch lösbares Kleinstmodell validiert Durchsatz, Wartezeit und Ressourcenauslastung gegen erwartete Werte.
- Das Referenzwerk bildet den primären End-to-End-Test: Laden, eine Produktionswoche ausführen, Baseline gegen In-Process-Provider vergleichen, Checkpoint bilden, mindestens zwei Branches fortsetzen und alle Artefakte prüfen.
- Der Scheduler-Benchmark verarbeitet fünf Millionen einfache Events in unter 60 Sekunden auf dokumentierter Referenzhardware.
- Der Referenzwerk-Benchmark simuliert eine Produktionswoche mit 100 bis 500 aktiven Ressourcen und mehreren Millionen Events in unter 60 Sekunden.
- Performance wird erst nach Korrektheit optimiert. Copy-on-write-Zustände oder alternative Datenstrukturen werden nur aufgrund gemessener Snapshot-, Speicher- oder Laufzeitprobleme eingeführt.
- Das Repository besitzt derzeit keine Test-Suite und damit keine direkte Prior Art. Die neuen Tests etablieren Application-Level-Szenarien und Kernel-Property-Tests als Projektstandard.

## Out of Scope

- Eine grafische Benutzeroberfläche oder interaktive 2D-/3D-Visualisierung.
- Verteilte Ausführung eines einzelnen Branches oder ein Cluster-Scheduler.
- Remote-Provider-Protokolle wie HTTP oder Message Bus; V1 definiert den serialisierbaren Vertrag und liefert einen In-Process-Provider.
- Ein vollständiger digitaler Zwilling eines konkreten realen Werks oder eine Zusage quantitativer Realität ohne Kalibrierungsdaten.
- Dynamische Energiepreise, Energieverbrauchsoptimierung und CO₂-Bilanzierung im ersten vertikalen Slice.
- Dynamische Ermüdung, Ergonomiebewertung und personenbezogene Belastungsmodelle im ersten vertikalen Slice.
- Fahrer als eigene Ressourcen, Fahrzeugbatterien, Ladepunkte und detaillierte Verkehrsgeometrie.
- Individuelle Verfolgung aller Verbrauchsteile und Lieferketten außerhalb des Plant.
- Unbegrenzte Checkpoint-Abwärtskompatibilität oder automatische Best-Effort-Migration.
- Laden nicht vertrauenswürdiger Plugins oder Ausführen von Code aus YAML.
- SimPy als produktiver Simulationskern.
- Automatische strategische Umrüstung in der Baseline Policy.
- Implementierung der vertikalen Scheiben im Rahmen dieser Spec-Erstellung.

## Further Notes

- Das Repository ist bis auf ein minimales Python-3.12-Gerüst Greenfield. Vor Implementierungsbeginn muss dieses Gerüst auf die beschlossene CPython-3.14-Basis angehoben werden.
- Die kanonische Domain-Sprache ist Englisch, auch wenn Erläuterungen und Nutzerkommunikation Deutsch sein können.
- Die Architekturentscheidungen sind in den bestehenden ADRs festgehalten und gelten als verbindliche Leitplanken für die spätere Zerlegung in Implementierungsissues.
- Synthetische Referenzparameter müssen im Run-Manifest als nicht kalibriert markiert sein. Quantitative Realitätstreue ist erst nach dokumentierter Kalibrierung zulässig.
- Der Performancewert von 60 Sekunden ist nur zusammen mit Referenzhardware, Python-/Bibliotheksversionen und konkretem Benchmarkprofil aussagekräftig.
- Nach dieser Spec können getrennte, nummerierte Issues für Kernel/Checkpoints, Production Domain, Decisions/Counterfactuals, Referenzwerk, Telemetrie/Exporte sowie CLI/Benchmarks angelegt werden. Diese Spec startet keine dieser Implementierungen.
