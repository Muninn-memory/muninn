FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    locales \
    && locale-gen pt_BR.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=pt_BR.UTF-8
ENV LANGUAGE=pt_BR:pt
ENV LC_ALL=pt_BR.UTF-8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

CMD ["python", "cli.py", "chat"]