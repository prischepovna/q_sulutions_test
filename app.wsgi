import os
import sys

# каталог со скриптом должен быть в sys.path, чтобы импортировался web_service
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web_service import app as application
