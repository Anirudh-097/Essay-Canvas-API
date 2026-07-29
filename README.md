# Backend

Run from the project root:

```bash
venv/bin/uvicorn backend.main:app --reload
```

The API uses `data/topics.db` by default. Available endpoints:

- `GET /health`
- `GET /topics?offset=0&limit=50`
- `GET /topics/{topic_id}`
- `GET /topic/today`
- `POST /essay/generate` with `{"topic_id": 1}`
- `GET /practice/prompt?exclude_topic_id=1`
- `POST /evaluate` with a topic ID, paragraph type, and paragraph
- `GET /progress` for attempt history and grammar, vocabulary, structure, and
  argument-quality averages

To enable the Groq-backed essay and evaluation endpoints locally, copy
`.env.example` to `.env` and add your key from [console.groq.com](https://console.groq.com):

```bash
cp .env.example .env
# edit .env and set GROQ_API_KEY
venv/bin/uvicorn backend.main:app --reload
```

`GROQ_MODEL` is optional; the default is `llama-3.3-70b-versatile` (free tier).
Other free-tier options include `llama-3.1-8b-instant` (faster, higher daily
limits) and `openai/gpt-oss-20b`. The key is only read by the backend and is
never sent to the frontend. The `.env` file is ignored by Git.

For Docker, inject the same variables at runtime rather than copying `.env`
into the image:

```bash
docker run --env-file .env -p 8000:8000 essay-learner-backend
```

With Docker Compose, use `env_file: .env` on the backend service. Hosted
providers such as Render expose the same values as service environment
variables or secrets.

Interactive API documentation is available at `/docs` while the server is running.
