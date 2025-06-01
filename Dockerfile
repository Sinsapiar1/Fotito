# Usa una imagen base de Python oficial, que ya tiene muchas herramientas comunes.
FROM python:3.9-slim-buster

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo requirements.txt al directorio de trabajo
COPY requirements.txt .

# Instala las dependencias de Python
# Utilizamos --no-cache-dir para ahorrar espacio y --upgrade pip para asegurarnos de que pip esté actualizado
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia el resto de tu aplicación al directorio de trabajo
COPY . .

# Comando para iniciar la aplicación cuando el contenedor se ejecute
# 'exec' reemplaza el proceso de la shell con el proceso de gunicorn para una mejor gestión de señales
CMD exec gunicorn --bind 0.0.0.0:$PORT photo:app
