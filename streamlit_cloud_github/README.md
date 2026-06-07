# Aviation Space Weather Dashboard

Streamlit dashboard for aviation ionospheric monitoring using **SERENE** data and **AIDA/TOMIRIS** models.  
Generates **ICAO-style prototype risk advisories** (academic only — not official ICAO warnings).

**Live demo:** deploy to Streamlit Community Cloud → `https://<your-app>.streamlit.app`

---

## Repository layout (GitHub root)

```
streamlit_cloud_github/          ← use this folder as the Git repo root
├── app.py                       ← Streamlit entry point
├── config.py
├── serene_client.py
├── data_loader.py
├── alert_engine.py
├── visualisation.py
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example     ← template only (do not commit real secrets)
├── data/
│   ├── latest_aida_grid.json
│   └── test_aida_grid.json
├── README.md
└── 部署说明.md
```

---

## Deploy to Streamlit Cloud (step by step)

### 1. Create a GitHub repository

1. On GitHub: **New repository** (e.g. `aviation-space-weather-dashboard`)
2. Copy the **contents** of this folder into the repo root (not the parent folder name)
3. Commit and push:

```bash
cd streamlit_cloud_github
git init
git add .
git commit -m "Initial commit: Streamlit aviation space weather dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

**Do not** commit `.env` or `.streamlit/secrets.toml`.

### 2. Deploy on Streamlit Community Cloud

1. Open [https://share.streamlit.io](https://share.streamlit.io)
2. Sign in with **GitHub**
3. Click **New app**
4. Select your repository, branch `main`, main file path: **`app.py`**
5. Click **Advanced settings** → **Secrets**
6. Paste (with your real token):

```toml
SERENE_API_BASE_URL = "https://spaceweather.bham.ac.uk"
SERENE_API_TOKEN = "your-api-token-here"
SERENE_API_TIMEOUT = "30"
SERENE_AUTH_SCHEME = "Token"
```

7. Click **Deploy**

Your public URL will be: `https://<app-name>-<user>.streamlit.app`

### 3. Recommended settings for visitors

- Default data source in the app is **Local sample file** (fast, no API quota)
- Use **SERENE API** only with a **small region** (sidebar shows estimated API calls, max 50)
- In **SERENE API** mode, the dashboard also downloads SERENE `Kp_ap.csv`
  indices and uses Kp/ap together with AIDA variables (`vTEC`/`TEC`,
  `MUF3000`, `foF2`) to generate prototype risk advisories.

---

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your SERENE token
python -m streamlit run app.py
```

Official SERENE API:

```bash
curl -X POST \
  -H "Authorization: Token YOUR_TOKEN" \
  -d latitude=52.4862 -d longitude=1.8904 \
  https://spaceweather.bham.ac.uk/api/calc/
```

---

## Disclaimer

Prototype academic advisories only. **Not** official ICAO warnings. **Not** for operational aviation use.
