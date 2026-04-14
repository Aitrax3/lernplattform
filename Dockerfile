# Nutze ein schlankes Python-Image als Basis
FROM python:3.11-slim

# Setze das Arbeitsverzeichnis im Container.
# Hierhin werden wir den Inhalt deines Repos kopieren.
WORKDIR /app

# Kopiere zuerst die requirements.txt und installiere die Abhängigkeiten.
# Das hilft, den Docker-Cache zu nutzen, falls sich nur der App-Code ändert.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# <<-- DAS IST JETZT WICHTIG -->>
# Kopiere den GESAMTEN Inhalt deines Repositories (von dem Verzeichnis, in dem die Dockerfile liegt)
# in das Arbeitsverzeichnis /app.
# Das bedeutet: dein Ordner `codex-test-lernplattform/` wird nach `/app/codex-test-lernplattform/` kopiert.
# Wenn du die __init__.py gerade hinzugefügt hast, ist `codex-test-lernplattform` nun ein Paket.
COPY . .
# <<----------------------------->>

# Informiere Docker, dass die Anwendung auf Port 8080 lauscht.
EXPOSE 8080

# Der Befehl zum Starten von Gunicorn.
# Da der Ordner `codex-test-lernplattform` nun als Paket innerhalb von `/app` verfügbar ist,
# und `app.py` darin liegt, kann Gunicorn die App finden.
CMD ["gunicorn", "codex-test-lernplattform.app:app", "--bind", "0.0.0.0:8080"]
