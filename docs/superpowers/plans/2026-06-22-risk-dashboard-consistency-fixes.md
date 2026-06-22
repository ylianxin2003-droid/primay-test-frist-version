# Risk Dashboard Consistency Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make historical event ranges, global alerts, regional forecast maps, and alert charts internally consistent and prepare a local Claude Code handoff.

**Architecture:** Keep Kp/ap as one global geomagnetic context while regional maps remain driven only by spatial AIDA variables. Correct presentation at the alert-generation and visualisation boundaries without changing the official AIDA calculation adapter.

**Tech Stack:** Python 3.12, pandas, Plotly, Streamlit, unittest.

---

### Task 1: Historical event semantics

**Files:**
- Modify: `streamlit_cloud_github/app_utils.py`
- Test: `streamlit_cloud_github/tests/test_historical_risk_windows.py`

- [ ] Rename table fields to `Peak Kp` and `Peak ap`.
- [ ] End API load ranges five minutes before each displayed three-hour boundary.
- [ ] Verify the four stored peaks against the SERENE Kp/ap resource.

### Task 2: Global alert consistency

**Files:**
- Modify: `streamlit_cloud_github/alert_engine.py`
- Test: `streamlit_cloud_github/tests/test_alert_consistency.py`

- [ ] Add a failing test showing Kp and ap currently produce duplicate global alerts.
- [ ] Merge Kp/ap evidence into one global geomagnetic alert using the worst level.
- [ ] Rename the overall metric language to loaded-sample peak risk.

### Task 3: Alert chart correctness

**Files:**
- Modify: `streamlit_cloud_github/visualisation.py`
- Test: `streamlit_cloud_github/tests/test_alert_consistency.py`

- [ ] Add failing tests for G4 summary visibility, G4 colour, and single-time axis padding.
- [ ] Add G1–G5 categories and colours to both alert charts.
- [ ] Give equal timestamps a readable UTC time range.

### Task 4: Regional map clarity

**Files:**
- Modify: `streamlit_cloud_github/forecast_visualisation.py`
- Modify: `streamlit_cloud_github/app.py`
- Test: `streamlit_cloud_github/tests/test_forecast_engine.py`
- Test: `streamlit_cloud_github/tests/test_dashboard_settings.py`

- [ ] Add failing tests for fixed marker size, fitted regional bounds, and explicit Kp/ap exclusion text.
- [ ] Fit the geo projection to selected AIDA points and reduce marker overlap.
- [ ] Label `Now` as the latest loaded AIDA state and global Kp/ap as excluded.
- [ ] Show peak Kp/ap metrics so they agree with the selected-range advisory.

### Task 5: Handoff and delivery

**Files:**
- Create: `CLAUDE_CODE_HANDOFF.md`

- [ ] Document fixed issues, known scientific limitations, setup, tests, and Streamlit commands without secrets.
- [ ] Run all unit tests, compileall, Streamlit AppTest, and live deployment checks.
- [ ] Push a branch without `codex` in its name, merge the PR, and clone the merged main branch to local folder `dashboard-project`.
