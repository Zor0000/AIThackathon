# Groundtruth

A review-preparation assistant that checks self-review claims against selected
GitHub and Jira records before drafting a source-linked manager review.

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The application starts in `fixture` mode, so no external credentials are
required. To add integrations, copy the values from `.env.example` into the
local `.env` file. Never commit `.env` or `.streamlit/secrets.toml`.

## Credentials

- `GEMINI_API_KEY` — needed when the AI workflow is implemented.
- `GITHUB_TOKEN` — needed only for live GitHub records; use a read-only,
  fine-grained token scoped to the demo repository.
- `JIRA_*` — needed only for live Jira records; use a Jira Free demo project
  and an API token.

For a public demo, use fictional fixture records. The product brief is in
`Groundtruth-Product-Brief-v1.md`.
