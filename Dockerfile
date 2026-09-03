# A base já traz o Chromium + libs do sistema. A versão TEM que bater com o
# pin de `playwright==` no requirements.txt — senão o binário do browser que o
# pip instala não corresponde ao que está na imagem e o render quebra em runtime.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

# Fonte oficial do template (o design usa Open Sans)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-open-sans \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY . .

# Railway injeta $PORT em runtime (porta aleatória) — precisa ser shell form
# pra expandir a variável; o fallback 3001 é só pra rodar local.
# STATE_DB: aponte pra um Volume do Railway (ex.: /data) pra não zerar o
# histórico de fotos a cada deploy.
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3001}"]
