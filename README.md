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
| OLLAMA_URL | http://localhost:11434/api/generate | Ollama endpoint used by the grader |
| OLLAMA_MODEL | llama3.1:latest | Model used by the grader |
| OLLAMA_TIMEOUT | 60 | Seconds per Ollama request |
| OLLAMA_RETRIES | 3 | Retries per request |
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
