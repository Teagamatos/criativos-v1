FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Fonte oficial do template (o design usa Open Sans)
RUN apt-get update && apt-get install -y fonts-open-sans && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]
