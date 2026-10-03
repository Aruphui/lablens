# LabLens

Upload a lab report (PDF/image) -> AI flags out-of-range values, explains them and suggests next steps -> trend charts across all your reports.

Stack: FastAPI + SQLite, Hugging Face free LLM (Qwen2.5-7B-Instruct), React + Vite + Recharts.

## Run

Backend (Python 3.10+)
    cd backend
    python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env        # paste your free HF token (huggingface.co/settings/tokens)
    uvicorn main:app --reload --port 8000

Frontend (Node 18+)
    cd frontend
    npm install
    npm run dev                 # http://localhost:5173  (proxies /api to :8000)

Scanned PDFs / photos need OCR: install the Tesseract app (Windows installer, `brew install tesseract`, or `apt install tesseract-ocr`).

## Fully local (no token, private)
    ollama pull qwen2.5:7b
    # in backend/.env
    LLM_BASE_URL=http://localhost:11434/v1
    LLM_MODEL=qwen2.5:7b

## How it works
1. extract.py   - pdfplumber text, OCR fallback for scans
2. analyze.py   - LLM extracts JSON (regex fallback) -> names normalised (FBS = Glucose (Fasting)) -> status computed in code
3. analyze.py   - LLM explains only the flagged values; critical values force "see a doctor promptly"
4. db.py        - reports + results tables; /api/trends reads one test across dates

## Before going public
- Replace the browser-generated X-User-Id with real auth (Clerk/Auth0/FastAPI-Users) and HTTPS
- Move SQLite -> Postgres, add rate limiting, add a privacy policy / consent screen
- Add an edit screen so users can correct misread values
