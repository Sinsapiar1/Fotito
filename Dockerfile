# Usa una imagen base de Python oficial, que ya tiene muchas herramientas comunes.
# Quitamos '-slim-buster' para usar una imagen más completa que suele tener
# las herramientas de compilación necesarias para paquetes más complejos,
# aunque esperamos que no se necesiten para tus 6 dependencias.
FROM python:3.9

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo requirements.txt al directorio de trabajo
COPY requirements.txt .

# Instala las dependencias de Python
# --no-cache-dir: Para ahorrar espacio y evitar cachés problemáticas
# --upgrade pip: Para asegurar que pip esté actualizado
# pip cache purge: Para borrar cualquier caché de pip dentro del contenedor
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip cache purge

# Copia el resto de tu aplicación al directorio de trabajo
COPY . .

# Comando para iniciar la aplicación cuando el contenedor se ejecute
CMD exec gunicorn --bind 0.0.0.0:8000 photo:app
