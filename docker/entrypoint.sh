#!/bin/bash
set -e

# каталоги для Apache и чистка pid-файла после перезапуска контейнера
mkdir -p /var/run/apache2 /var/lock/apache2
rm -f /var/run/apache2/apache2.pid

# права на том uploads
chown www-data:www-data /app/uploads

# создаём таблицу один раз, до старта Apache, она ждет бд
echo "[entrypoint] initializing database..."
python -c "from web_service import init_db; init_db()"

echo "[entrypoint] starting Apache..."
. /etc/apache2/envvars
exec apache2 -D FOREGROUND