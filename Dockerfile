# Backend: FastAPI + OR-Tools solver + WeasyPrint PDF export.
FROM python:3.13-slim

# WeasyPrint needs Pango/Cairo/GDK-Pixbuf at runtime (it renders HTML/CSS to
# PDF via those, not a headless browser); shared-mime-info + fonts avoid
# missing-glyph/mimetype warnings when rendering the tabellone.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    shared-mime-info \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Written by app.config.Settings.TEMP_DIR; WeasyPrint/pandas scratch space.
RUN mkdir -p /tmp/calendariodocenti

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
