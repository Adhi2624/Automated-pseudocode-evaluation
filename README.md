# 🚀 Automated Pseudocode Evaluation System

An efficient platform for evaluating pseudocode submissions in programming competitions.

## 🛠️ Technologies Used

- **Backend:** FastAPI 🚀
- **Frontend:** HTML, CSS, JavaScript 🎨
- **Database:** MongoDB 🍃
- **LLMS:**LLama3.1

## 🌟 Features

- User-friendly interface for submitting pseudocode 📝
- Automated evaluation of pseudocode submissions ⚙️
- Secure storage of user details and submissions 🔒
- Responsive design for various devices 📱💻

## 🚀 Getting Started

1. Clone this repository
2. Install dependencies with [uv](https://docs.astral.sh/uv/):
   ```bash
   uv sync
   ```
3. Start MongoDB and configure the environment:
   ```bash
   cp .env.example .env   # then edit as needed
   ```
4. Run the FastAPI server from the repo root:
   ```bash
   uv run uvicorn app.main:app --reload
   ```
5. Run the tests: `uv run pytest`

### Project structure

```
app/
  main.py            # FastAPI app (uvicorn app.main:app)
  config.py db.py    # settings + MongoDB helpers
  schemas.py         # pydantic models
  dependencies.py    # FastAPI dependencies
  security.py        # signed cookies, rate limiter
  routers/           # pages.py (HTML), student.py, staff.py (JSON API)
  services/          # contest timing, question bank, answers helpers
  worker.py          # polls the jobs collection, runs grading + evaluation schedules (python -m app.worker)
  grader/            # LLM grading logic (also a CLI: python -m app.grader.evaluator)
  templates/ static/ # frontend
data/questions.json  # seed questions (first run only)
tests/
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| MONGO_URI | mongodb://localhost:27017/ | MongoDB connection string |
| MONGO_DB | sproc | Database name |
| MONGO_COLLECTION | user-details | Collection name |
| CORS_ORIGINS | (empty) | Comma-separated allowed origins; empty disables CORS |
| LLM_API_KEY | (required for grading) | API key for the LLM provider (`OPENROUTER_API_KEY` also accepted); keep secret, never commit |
| LLM_BASE_URL | https://openrouter.ai/api/v1 | Any OpenAI-compatible base URL (OpenRouter, OpenAI `https://api.openai.com/v1`, vLLM, Ollama `http://host:11434/v1`, ...); `/chat/completions` is appended |
| LLM_MODEL | meta-llama/llama-3.1-70b-instruct | Model id for that provider |
| LLM_JSON_MODE | true | Send `response_format: json_object`; set false if the provider rejects it |
| LLM_TIMEOUT | 60 | Seconds per LLM request |
| LLM_RETRIES | 3 | Retries per request |
| EVAL_DELAY_SECONDS | 1 | Delay between grading calls |
| MAX_ANSWER_CHARS | 4000 | Max characters per submitted answer |
| OUTPUT_XLSX | user_pseudocode_scores.xlsx | Grader output file |
| STAFF_USERNAME / STAFF_PASSWORD | (empty) | Staff dashboard login; disabled until both are set |
| SECRET_KEY | random per start | Signs session cookies |
| COOKIE_SECURE | false | Mark cookies Secure (use with HTTPS) |
| SESSION_HOURS | 12 | Login session length |


### Running the grader

From the repository root:
```bash
uv run python -m app.grader.evaluator
```

## 📄 Pages & roles

| Page | Who | Purpose |
|---|---|---|
| `/` | everyone | Landing page |
| `/login` | students | Sign in with **register number + date of birth** |
| `/test` | students | Start the timed test, answers autosave, auto-submit when time is up |
| `/thank` | students | Confirmation |
| `/staff/login`, `/staff` | staff | Upload the student list (CSV/Excel), contest title, duration, open/close time, publish switch; add/edit/delete questions; view submissions and scores |

Students cannot register themselves: staff upload the roster (`RegNo, Name, DOB` required; Email, Mobile, Year, Branch, Section optional; DOB as `YYYY-MM-DD` or `DD-MM-YYYY`). Re-uploading updates existing students and keeps their answers.

**Running a live test (coordinator tools)** in `/staff`:

- **Live monitor** – refreshes every 5 s: who is online, in progress, submitted or out of time, time left, answers filled, tab switches and pastes (flagged rows are highlighted). Per student: *Extend* time (works past the closing time, e.g. after a power cut), *Force submit*, and *Reset* (fresh attempt; the old answers are archived in `previous_attempts`). Broadcast an **announcement** that appears as a banner on every student's screen.
- **Integrity** – one active session per student (a new sign-in logs the old one out); tab/window switches, paste and copy are recorded for staff but never block the student; the student sees a notice before starting.
- **Results** – queue a grading job from the dashboard, rank students, set a **shortlist cutoff**, and download a CSV (per-question scores, totals, flags, shortlist column).

**Evaluation (grading) jobs** – grading never runs inside a web request. The web app writes a job into the `jobs` collection and a separate **worker** (`python -m app.worker`, the `worker` service in compose) polls MongoDB, claims jobs atomically, grades with the LLM and records progress and a log you can watch on the Results tab. Per test (Settings → *Evaluation*) choose when grading starts:

| Mode | Starts |
|---|---|
| Manual | when you press *Queue grading now* |
| Immediately | shortly after each student submits or runs out of time |
| After the test closes | closing time + a delay you set |
| At a specific time | the date/time you set (editing the schedule re-arms it) |

Only finished attempts (submitted or out of time) are graded, answers that already have a score are skipped, one job runs per test at a time, and a job whose worker died is re-queued. The Results tab shows whether the worker is online; jobs simply wait while it is offline.

**Multiple tests** – create any number of tests; each has its own questions, timing, publish switch, announcements, monitor, submissions and results. The student roster is shared: every published test appears on a student's *Your tests* page with its own timer and status.

Staff sign in with `STAFF_USERNAME` / `STAFF_PASSWORD` from the environment (login is disabled until both are set).
Sessions are signed HttpOnly cookies; set `SECRET_KEY` so they survive restarts, and `COOKIE_SECURE=true` behind HTTPS.
Login attempts are rate-limited per register number / username / IP.

**Timing:** a student's personal timer starts when they press *Start* and lasts *duration* minutes, but never runs past the contest *closing time*. Questions are only sent to a student after they start.
Questions live in MongoDB and are seeded from `data/questions.json` the first time the app starts with an empty question collection; after that, manage them in the staff dashboard. The grader reads the same questions from MongoDB.

## 💾 Data Storage

Participants, their answers and scores live in the `user-details` collection; questions in `questions`; the contest settings in `contest`.

---

Happy Coding! 💻🎉

## 🐳 Docker

**Local** (app + MongoDB container):
```bash
docker compose up --build
# the worker service polls for grading jobs; put LLM_API_KEY / LLM_BASE_URL / LLM_MODEL in .env
```

**Grade with a local model (Ollama)** instead of a hosted API:
```bash
ollama pull qwen3:4b          # or llama3.1:8b, then: OLLAMA_MODEL=llama3.1:8b
docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d --build
```
Ollama stays bound to `127.0.0.1`; the override puts the worker on the host network so it can reach it, without exposing the model server to your LAN. Small local models are slower and less consistent graders than large hosted ones, so spot-check scores before shortlisting.

**Render** (`render.yaml`): a single free web service with the worker embedded (`EMBEDDED_WORKER=true`). Set `MONGO_URI` (your MongoDB server), `STAFF_USERNAME`, `STAFF_PASSWORD` and `LLM_API_KEY` as secrets in the dashboard. Free services sleep when idle, so wake the site before a test and prefer a paid plan with a separate worker for real exams.

**Production** (app + grading worker only; uses MongoDB Community running on the server, set `MONGO_URI` in `.env`):
```bash
docker compose -f docker-compose.prod.yml up -d --build
```
