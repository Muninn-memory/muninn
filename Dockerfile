FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    locales \
    xvfb \
    && locale-gen pt_BR.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=pt_BR.UTF-8
ENV LANGUAGE=pt_BR:pt
ENV LC_ALL=pt_BR.UTF-8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

CMD ["python", "-m", "uvicorn", "huginn.server:app", "--host", "0.0.0.0", "--port", "8000"]
