# Finance Dashboard

A web dashboard refactor of the personal finance desktop application.

## Stack

- FastAPI backend
- SQLite database
- HTML/CSS/JavaScript frontend
- Chart.js for charts

The backend keeps the existing SQLite schema compatible with the desktop application:
`transactions`, `recurring_transactions`, `budgets`, and `settings`.

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

The database defaults to `data/personal_finance.db`.

## Existing database

Copy your existing `personal_finance.db` into `data/` if you want to use your existing data.

The API creates missing tables but does not delete or reset existing data.

## Project structure

```text
finance-dashboard/
├── backend/
│   ├── app/
│   │   ├── database.py
│   │   ├── main.py
│   │   └── schemas.py
│   ├── requirements.txt
│   └── legacy_desktop.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── data/
```

## API

Useful endpoints:

- `GET /api/dashboard`
- `GET /api/transactions`
- `POST /api/transactions`
- `PUT /api/transactions/{id}`
- `DELETE /api/transactions/{id}`
- `GET /api/recurring`
- `POST /api/recurring`
- `DELETE /api/recurring/{id}`
- `GET /api/budgets`
- `POST /api/budgets`
- `DELETE /api/budgets/{id}`
- `GET /api/categories`

Swagger documentation is available at `/docs`.

## GitHub

```bash
git init
git add .
git commit -m "Initial finance dashboard"
git branch -M main
git remote add origin <your-github-repository-url>
git push -u origin main
```
