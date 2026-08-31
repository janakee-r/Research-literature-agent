# Research Literature Agent

A personalized scientific-literature assistant built with **Google ADK** and **Gemini 3.5 Flash on Vertex AI**. It learns a researcher's interests from saved literature and explicit preferences, discovers and ranks new arXiv papers, keeps a separate model of the researcher's own work, and can deep-read full papers on request.

![Architecture](assets/architecture.png)

## What it does

- Imports arXiv bookmarks into a structured library.
- Infers an evidence-calibrated research-interest profile from saved papers.
- Maintains editable Markdown for research interests and the researcher's own work.
- Searches recent or historical arXiv literature and ranks papers by personalized relevance.
- Searches arXiv directly by author and supports an explicit Authors to Follow list.
- Saves papers, reading state, provenance, and recommendation feedback in SQLite.
- Deep-reads an explicitly requested paper from its full PDF and persists the analysis.
- Persists mutable state to Google Cloud Storage when deployed.
- Runs autonomous literature scans with Cloud Run Jobs + Cloud Scheduler.

## Stack

- **Agent framework:** Google Agent Development Kit (ADK)
- **Model:** Gemini 3.5 Flash
- **Model platform:** Vertex AI
- **Hosting:** Google Cloud Run
- **Persistent cloud state:** Google Cloud Storage
- **Automation:** Cloud Run Jobs + Cloud Scheduler
- **Literature source:** arXiv API / arXiv PDFs
- **Local structured state:** SQLite + Markdown

## Repository layout

```text
.
├── agent.py
├── config.py
├── agents/                 # ADK specialist agents
├── tools/                  # deterministic retrieval/storage/PDF tools
├── data/
│   ├── bookmarks.txt       # one arXiv ID/URL per line
│   ├── researcher_profile.md
│   ├── researcher_work.md
│   ├── papers/             # downloaded PDFs; gitignored
│   └── scheduled_reports/  # generated reports; gitignored
├── storage/                # SQLite DB; gitignored
├── assets/architecture.png
├── run_scheduled_scan.py
└── smoke_test.py
```

## Local setup

Requirements: Python 3.11+ and a Google Cloud project with Vertex AI access.

```bash
# Clone into a Python-safe folder name.
git clone <YOUR_REPOSITORY_URL> research_literature_agent
cd research_literature_agent

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```text
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_LOCATION=global
RESEARCH_AGENT_MODEL=gemini-3.5-flash
RESEARCH_AGENT_TIMEZONE=Asia/Kolkata
```

Authenticate for local Vertex AI use:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Run the smoke test from the repository's parent directory:

```bash
cd ..
python research_literature_agent/smoke_test.py
```

Start ADK Web from the parent directory:

```bash
adk web --allow_origins="*"
```

ADK Web is intended for development/testing. Do not expose it publicly with sensitive researcher data in a production deployment.

## Researcher state

The initial repository contains an empty library and editable profile/work templates. Add arXiv IDs or URLs to `data/bookmarks.txt`, then ask the agent to import the bookmarks and infer interests.

The application creates `storage/papers.db` automatically. The database, downloaded PDFs, generated reports, `.env`, and ADK session state are excluded from Git.

## Cloud Run deployment

The ADK CLI can package and deploy the agent to Cloud Run:

```bash
cd ..
adk deploy cloud_run \
  --project=YOUR_PROJECT_ID \
  --region=YOUR_CLOUD_RUN_REGION \
  --service_name=research-literature-agent \
  --with_ui \
  research_literature_agent \
  -- --allow-unauthenticated
```

Set runtime variables on the deployed service:

```bash
gcloud run services update research-literature-agent \
  --region=YOUR_CLOUD_RUN_REGION \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,RESEARCH_AGENT_MODEL=gemini-3.5-flash,RESEARCH_AGENT_GCS_BUCKET=YOUR_BUCKET"
```

For a private deployment, omit `--allow-unauthenticated` and configure Cloud Run IAM appropriately.

## Persistent Cloud Storage

Create a bucket and grant the Cloud Run service identity object access:

```bash
gcloud storage buckets create gs://YOUR_BUCKET \
  --location=YOUR_CLOUD_RUN_REGION \
  --project=YOUR_PROJECT_ID

gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET \
  --member="serviceAccount:YOUR_CLOUD_RUN_SERVICE_ACCOUNT" \
  --role="roles/storage.objectAdmin"
```

Set `RESEARCH_AGENT_GCS_BUCKET=YOUR_BUCKET` on the service. The persistence layer synchronizes:

- `storage/papers.db`
- `data/researcher_profile.md`
- `data/researcher_work.md`
- generated scheduled reports

This prototype is designed for a single researcher / low-concurrency demo workload; copying a SQLite file to object storage is not intended as a general multi-user database architecture.

## Scheduled autonomous scan

`run_scheduled_scan.py` runs the same personalized literature workflow non-interactively and writes a timestamped report.

Local test:

```bash
python run_scheduled_scan.py
```

For Google Cloud automation, deploy the source as a Cloud Run Job, configure the job command to execute `run_scheduled_scan.py`, then create a Cloud Scheduler HTTP job targeting the Cloud Run Jobs `:run` endpoint. The deployed job needs the same Vertex AI and Cloud Storage environment variables/permissions as the web service.

Example Scheduler target:

```text
https://run.googleapis.com/v2/projects/PROJECT_ID/locations/REGION/jobs/research-literature-scan:run
```

## Data model

A bibliographic work is separate from the researcher's relationship to it. The same paper can therefore be bookmarked, saved, an own publication, and read without collapsing those concepts into one status field. Separate tables track identifiers, authorship, provenance events, reading state, paper roles, recommendation feedback, files, and deep-read analyses.

See [ARCHITECTURE.md](ARCHITECTURE.md) for more detail.

## Notes

This is a hackathon research prototype. It intentionally uses agent reasoning for scientific judgment and deterministic Python for deterministic tasks. Full-paper reading happens only on explicit request; normal discovery remains abstract-level to control latency and model usage.
