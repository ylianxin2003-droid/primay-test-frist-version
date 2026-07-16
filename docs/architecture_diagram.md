# Architecture Diagram for Dissertation

This diagram summarises the final MSc project architecture. It can be copied
into the dissertation or converted into a figure.

```mermaid
flowchart LR
    A["SERENE/AIDA raw and forecast outputs"] --> B["Data loading"]
    B --> C["Indicator processing"]
    C --> D["Risk engine"]
    D --> E["Visualisation"]
    E --> F["Engineering outputs"]

    B --> B1["Live SERENE API mode"]
    B --> B2["Cached trial output mode"]
    B --> B3["Historical event replay"]

    C --> C1["TEC"]
    C --> C2["MUF3000F2"]
    C --> C3["Kp/ap global context"]
    C --> C4["30-day same-UTC MUF baseline"]

    D --> D1["GNSS risk from Vertical TEC"]
    D --> D2["HF COM risk from PSD"]
    D --> D3["Overall risk status"]

    E --> E1["Risk cards"]
    E --> E2["Categorical and raw maps"]
    E --> E3["ICAO-style summary table"]
    E --> E4["TEST research messages"]

    F --> F1["Engineering Impact: HF Communication Coverage"]
    F --> F2["UK to North Atlantic to New York JFK route assessment"]
    F --> F3["Frequency sensitivity comparison"]
    F --> F4["Engineering interpretation and decision-support context"]
```

Decision-support flow:

```text
Risk Assessment
  -> Communication Impact
  -> Engineering Interpretation
  -> Decision Support
```

Scientific guardrail:

The current HF module is a MUF-threshold engineering proxy. It is not Trace ray
tracing and it is not operational aviation guidance. Trace integration is
documented separately in `Trace_Integration_Report.md`.
