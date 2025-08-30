# Dockerfile

# Użyj oficjalnego, stabilnego obrazu Python
FROM python:3.9

# Ustaw katalog roboczy wewnątrz kontenera
WORKDIR /app

# Zainstaluj zależności systemowe (dla PostgreSQL)
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Skopiuj plik z wymaganiami
COPY requirements.txt .

# Zainstaluj zależności Pythona
RUN pip install --no-cache-dir -r requirements.txt

# Skopiuj resztę kodu aplikacji do kontenera
COPY . .

# Bezpośrednia komenda uruchamiająca aplikację
CMD ["gunicorn", "--worker-class", "sync", "--bind", "0.0.0.0:8000", "app:app"]
