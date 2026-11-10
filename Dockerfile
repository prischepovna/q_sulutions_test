FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# apache2-dev + build-essential нужны для сборки mod_wsgi, curl - для отладки
RUN apt-get update && apt-get install -y --no-install-recommends \
        apache2 apache2-dev build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# mod_wsgi собран под Python образа; module-config выдаёт нужный LoadModule
RUN mod_wsgi-express module-config > /etc/apache2/mods-available/wsgi.load \
    && a2enmod wsgi

COPY apache/videoapp.conf /etc/apache2/sites-available/videoapp.conf
RUN a2dissite 000-default && a2ensite videoapp

COPY web_service.py app.wsgi ./
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p /app/uploads \
    && chown www-data:www-data /app/uploads

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]