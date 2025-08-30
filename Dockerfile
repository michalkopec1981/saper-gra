# Dockerfile

# Użyj oficjalnego, lekkiego obrazu Python
FROM python:3.9-slim

# Ustaw katalog roboczy wewnątrz kontenera
WORKDIR /app

# Zainstaluj zależności systemowe (dla PostgreSQL i innych)
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Skopiuj plik z wymaganiami
COPY requirements.txt .

# Zainstaluj zależności Pythona
RUN pip install --no-cache-dir -r requirements.txt

# Skopiuj resztę kodu aplikacji do kontenera
COPY . .

# Railway użyje pliku Procfile do uruchomienia aplikacji,
# więc nie potrzebujemy tutaj komendy CMD.
