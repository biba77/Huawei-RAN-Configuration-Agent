# RAN Configuration Management with Agentic AI

A natural-language agent for updating Huawei eNodeB RAN configuration files. A radio engineer describes a change in plain English ("Change tilt to 4° on Cell 1"), the agent parses the intent, shows a preview of exactly what will change, and — only on explicit confirmation — updates the XML config file and a synchronized SQLite database together, while logging a full audit trail and generating the equivalent Huawei MML command.

Built as an internship project exploring how agentic AI patterns (natural-language intent → structured action → human-in-the-loop confirmation) apply to a real telecom operations workflow.

## Why this exists

Manually editing RAN configuration XML is slow and error-prone: engineers need to know the exact file structure, hand-translate changes into Huawei MML syntax, and there's typically no review step or structured audit trail before a change ships. This project replaces that manual process with:

- **Natural-language input** instead of raw XML editing
- **A mandatory preview-and-confirm step** before anything is written to disk
- **XML + database kept in sync automatically**, so they can never silently drift apart
- **Automatic Huawei MML command generation**
- **A complete, timestamped audit trail** of every change

## How it works

```
Radio Engineer
      │  types a plain-English request
      ▼
Streamlit Front-End  ──  preview + confirm workflow
      │
      ▼
NL Intent Parser  ──  extracts { cell, parameter, value } via an LLM call (Groq)
      │
      ▼
Update Engine  ──  validates and applies the change (in memory first)
      │
      ├──────────────┬───────────────────┐
      ▼              ▼                   ▼
 XML Config File  SQLite Database   MML + Audit Log
 (saved to disk)  (synced on every  (generated command +
                    confirmed change)  full change history)
```

Nothing touches disk until the engineer explicitly clicks **Apply**. Rejecting a preview leaves the XML file and database completely untouched.

## Project structure

```
.
├── app.py               # Streamlit front end (the main way to run this)
├── chatbot.py            # Terminal/CLI front end, same backend
├── xml_engine.py          # Parses & updates the XML, tracks derived fields (e.g. TotalTilt)
├── nl_parser.py            # Natural-language → structured intent (regex or Groq LLM)
├── db_engine.py             # SQLite schema, full sync, and incremental sync
├── mml_generator.py          # Structured change → Huawei MML command string
├── sample_data/
│   └── huawei_enodeb_sample.xml   # Synthetic eNodeB config to try the app with
├── vodafone_logo.png (not committed)   # Optional branding shown in the app header
├── requirements.txt
└── .gitignore
```

## Supported parameters

Currently scoped to four parameter types, matching the project's original brief:

| Parameter | XML location | Example |
|---|---|---|
| Tilt | `Antenna/ElectricalTilt` (linked via `LinkedCellId`) | "Change tilt to 4° on Cell 1" |
| Power | `Cell/TxPower` | "Set power to 400 for Cell 2" |
| PCI | `Cell/PhyCellId` | "Update PCI to 5 on Cell 3" |
| Bandwidth | `Cell/DlBandWidth` | "Change bandwidth to 20MHz on Cell 1" |

Changing tilt automatically recalculates `TotalTilt` (`MechanicalTilt + ElectricalTilt`), so the config never becomes internally inconsistent.

## Setup

```bash
git clone <this-repo>
cd <this-repo>
pip install -r requirements.txt
```

### Natural-language parsing: two modes

- **Groq (LLM)** — understands open-ended phrasing (default). Requires a free API key from [console.groq.com](https://console.groq.com):
  ```bash
  export GROQ_API_KEY=gsk_...          # macOS/Linux
  $env:GROQ_API_KEY="gsk_..."          # Windows PowerShell
  ```
- **Rule-based (regex)** — free, instant, no API key, but only understands the tested phrasing patterns (e.g. `change tilt to 4 on cell 1`). Selectable from the sidebar at any time, including as a live fallback if the API key isn't set or the network drops.

### Optional: logo

Drop a `vodafone_logo.png` in the project root to show it in the app header. Not included in this repo (gitignored) — the app works fine without it, just shows a small placeholder note instead.

## Running it

**Streamlit app (recommended):**
```bash
streamlit run app.py
```
Upload `sample_data/huawei_enodeb_sample.xml` in the sidebar to try it immediately.

**Terminal version:**
```bash
python3 chatbot.py sample_data/huawei_enodeb_sample.xml
```

## What gets created at runtime

Running the app creates two files in the project folder (both gitignored, since they're generated, not source):
- `ran_config.db` — SQLite mirror of the config, rebuilt from the XML on first load
- `audit_log.csv` — human-readable change history (also duplicated inside the DB's `audit_log` table)

## Scope & limitations

This was built as an 8-day internship project against a single synthetic site. Known limitations, and where this would go next:

- **No live network integration** — this updates a local XML file and database, not a real Huawei OSS/U2000 system
- **No best-practice validation** — the agent applies exactly what's requested; it doesn't check the result against RAN engineering guidelines
- **Single vendor** — built specifically against Huawei's eNodeB XML schema
- **MML syntax is a best-effort template** — verify against the official Huawei MML reference for your software release before treating it as production-ready

## Tech stack

Python · Streamlit · SQLite · `xml.etree.ElementTree` · Groq API (Llama 3.3 70B)
