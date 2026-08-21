# Essay Canvas API

FastAPI backend for essay generation, paragraph evaluation, authentication, and progress tracking.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python auth.py  # generate an AUTH_PASSWORD_HASH, then put it in .env
uvicorn main:app --reload
```

The API is available at `http://localhost:8000`; interactive documentation is at `/docs`.

The API uses Supabase PostgreSQL through `DATABASE_URL`. Run `supabase/schema.sql` in the Supabase SQL Editor, then import topics into the `topics` table before using the topic endpoints.

## Configuration

Required environment variables are `DATABASE_URL`, `AUTH_USERNAME`, `AUTH_PASSWORD_HASH`, `AUTH_SECRET`, and `GROQ_API_KEY`. `GROQ_MODEL` is optional. Set `FRONTEND_ORIGINS` to a comma-separated list of frontend URLs. For a Vercel frontend, use `AUTH_COOKIE_SECURE=true` and `AUTH_COOKIE_SAMESITE=none`.

## Docker and Render

```bash
docker build -t essay-canvas-api .
docker run --env-file .env -p 8000:8000 essay-canvas-api
```

The included `render.yaml` deploys the Docker service and uses `/health` for health checks. In Render, set `DATABASE_URL` to the Supabase pooled connection string, set `FRONTEND_ORIGINS` to the deployed Vercel URL, and provide `AUTH_PASSWORD_HASH` and `GROQ_API_KEY` as secrets. The frontend only needs the public Render API URL, for example `NEXT_PUBLIC_API_URL=https://your-api.onrender.com`.

Endpoints include:

- `GET /health`
- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `GET /topics`, `GET /topics/{topic_id}`, `GET /topic/today`
- `POST /essay/generate`, `GET /practice/prompt`, `POST /evaluate`, `POST /evaluate/essay`
- `GET /progress`
