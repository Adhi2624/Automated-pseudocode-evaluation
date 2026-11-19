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
2. Create a virtualenv and install dependencies:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r fastapi/requirements.txt
   ```
3. Start MongoDB and configure the environment:
   ```bash
   cp .env.example .env   # then edit as needed
   ```
4. Run the FastAPI server from the `fastapi/` directory:
   ```bash
   cd fastapi
   PYTHONPATH=.. uvicorn main:app --reload
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

Questions live in `questions.json` at the repo root.

### Running the grader

From the repository root:
```bash
python -m pseudo_evaluation.evaluator
```

## 📄 Pages

- **Welcome Page:** Introduction to the competition 👋
- **Details Page:** Collect user information 📋
- **Pseudocode Competition Page:** Submit pseudocode solutions 🧠
- **Thank You Page:** Confirmation after submission 🎉

## 💾 Data Storage

User details and pseudocode submissions are securely stored in MongoDB for easy retrieval and analysis.

---

Happy Coding! 💻🎉
