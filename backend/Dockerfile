FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the SQLite DB at image build time so startup is instant
RUN python -c "from main import build_db; from pathlib import Path; Path('data').mkdir(exist_ok=True); build_db()"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
