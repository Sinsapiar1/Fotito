# Guía de Despliegue en Render - Fotito

Esta guía explica paso a paso cómo desplegar la aplicación Fotito en Render.

## Requisitos Previos

- Cuenta en [Render](https://render.com)
- Repositorio GitHub con el código (ej: `Sinsapiar1/Fotito`)
- Archivos necesarios en el repositorio:
  - `photo.py` (aplicación Flask)
  - `requirements.txt` (dependencias)
  - `render.yaml` (configuración opcional)

## Paso 1: Crear la Base de Datos PostgreSQL

**IMPORTANTE**: Crea la base de datos ANTES del Web Service.

1. Ve a tu dashboard de Render: https://dashboard.render.com/
2. Click en **"New +"** → **"PostgreSQL"**
3. Configura la base de datos:
   - **Name**: `fotito-db` (o el nombre que prefieras)
   - **Database**: `fotito`
   - **User**: (se genera automáticamente)
   - **Region**: **Oregon (US West)** (o la región que prefieras)
   - **PostgreSQL Version**: (dejar por defecto)
   - **Instance Type**: **Free** (para empezar)
4. Click en **"Create Database"**
5. Espera 1-2 minutos a que se cree la base de datos
6. Una vez creada, **copia el "Internal Database URL"**
   - Se ve algo así: `postgresql://user:password@dpg-xxxxx.oregon-postgres.render.com/fotito`
   - **GUARDA ESTE URL**, lo necesitarás en el siguiente paso

## Paso 2: Crear el Web Service

1. En el dashboard de Render, click en **"New +"** → **"Web Service"**
2. Conecta tu repositorio de GitHub
3. Selecciona el repositorio (ej: `Sinsapiar1/Fotito`)

### Configuración del Web Service

Render detectará automáticamente que es una app Flask. Configura así:

#### Configuración Básica:
- **Name**: `mislinks` (o el nombre que prefieras)
- **Language**: `Python 3`
- **Branch**: `main`
- **Region**: **Oregon (US West)** (MISMA región que la base de datos)
- **Root Directory**: (dejar vacío)

#### Build & Deploy:
- **Build Command**:
  ```bash
  pip install -r requirements.txt
  ```
- **Start Command**:
  ```bash
  gunicorn --bind 0.0.0.0:$PORT photo:app
  ```

#### Instance Type:
- Selecciona **Free** (para empezar)
  - 512 MB RAM
  - 0.1 CPU
  - Se duerme después de inactividad
  - Suficiente para pruebas

#### Environment Variables (Variables de Entorno):

**IMPORTANTE**: Agrega estas variables ANTES de crear el servicio:

1. Click en **"Add Environment Variable"**

2. **Variable 1 - SECRET_KEY**:
   - **Key**: `SECRET_KEY`
   - **Value**: (genera una clave secreta aleatoria, ej: `mi_clave_super_secreta_12345_abcdef`)
   - Puedes usar cualquier string largo y aleatorio

3. **Variable 2 - DATABASE_URL**:
   - **Key**: `DATABASE_URL`
   - **Value**: (pega el "Internal Database URL" que copiaste en el Paso 1)
   - Ejemplo: `postgresql://user:pass@dpg-xxxxx.oregon-postgres.render.com/fotito`

#### Configuración Avanzada:

- **Health Check Path**: Dejar **VACÍO** (borrar `/healthz` si aparece)
- **Auto-Deploy**: Activado (despliega automáticamente con cada commit)
- **Pre-Deploy Command**: Dejar vacío

### Resumen de Variables de Entorno:
```
SECRET_KEY = tu_clave_secreta_aleatoria_aqui
DATABASE_URL = postgresql://user:pass@dpg-xxxxx.oregon-postgres.render.com/fotito
```

4. Una vez configurado todo, click en **"Create Web Service"**

## Paso 3: Monitorear el Despliegue

1. Render comenzará a construir y desplegar tu aplicación
2. Verás los logs en tiempo real:
   - `==> Cloning from GitHub...`
   - `==> Installing dependencies...`
   - `==> Build successful 🎉`
   - `==> Deploying...`
   - `==> Your service is live 🎉`

3. El proceso toma aproximadamente **2-5 minutos**

4. Una vez completado, verás un mensaje: **"Your service is live 🎉"**

5. Tu aplicación estará disponible en:
   ```
   https://mislinks.onrender.com
   ```
   (o el nombre que hayas elegido)

## Paso 4: Inicializar la Base de Datos

**IMPORTANTE**: Después del primer despliegue exitoso, debes inicializar las tablas de la base de datos.

1. Visita esta URL en tu navegador:
   ```
   https://tu-app.onrender.com/init_db
   ```

2. Deberías ver el mensaje: **"Base de datos inicializada (tablas creadas)."**

3. Esto crea las tablas: `drive_config`, `link`, y `photo`

4. Si tienes una base de datos existente y necesitas agregar soporte para Cloudinary, visita:
   ```
   https://tu-app.onrender.com/migrate_db
   ```
   Esto agregará las columnas necesarias para soportar múltiples proveedores de almacenamiento.

## Paso 5: Configurar Almacenamiento en la Nube (Opcional)

La aplicación soporta dos proveedores de almacenamiento: **Google Drive** y **Cloudinary**.

### Opción A: Google Drive

Para que las fotos se suban automáticamente a Google Drive:

1. Ve a tu aplicación: `https://tu-app.onrender.com/config_drive`
2. Selecciona "Google Drive" como proveedor
3. Crea una Service Account en Google Cloud Console
4. Genera credenciales JSON
5. Copia el contenido del JSON y pégalo en el formulario
6. Agrega el ID de la carpeta de Google Drive donde quieres guardar las fotos
7. (Opcional) Agrega tu email de Google para evitar errores de cuota
8. Guarda la configuración

### Opción B: Cloudinary (Recomendado para simplicidad)

Cloudinary es más fácil de configurar y tiene un tier gratuito generoso:

1. Crea una cuenta gratuita en [Cloudinary](https://cloudinary.com)
2. Ve a tu Dashboard de Cloudinary
3. Copia tu **Cloud Name**, **API Key** y **API Secret**
4. Ve a tu aplicación: `https://tu-app.onrender.com/config_drive`
5. Selecciona "Cloudinary" como proveedor
6. Ingresa las credenciales copiadas
7. (Opcional) Especifica una carpeta personalizada (default: "fotito")
8. Guarda la configuración

**Ventajas de Cloudinary**:
- Configuración más simple (no requiere Service Account)
- URLs de imágenes optimizadas y CDN integrado
- Transformaciones de imágenes automáticas
- 25 GB de almacenamiento gratis al mes

## Verificación del Despliegue

### ✅ Checklist de Verificación:

- [ ] Base de datos PostgreSQL creada
- [ ] Web Service creado y desplegado
- [ ] Variables de entorno configuradas (SECRET_KEY, DATABASE_URL)
- [ ] Build exitoso (sin errores)
- [ ] Servicio "live" (activo)
- [ ] URL accesible en el navegador
- [ ] Base de datos inicializada (`/init_db`)
- [ ] Google Drive configurado (opcional)

### 🧪 Prueba la Aplicación:

1. **Home**: `https://tu-app.onrender.com/`
   - Deberías ver la página principal

2. **Crear un link de prueba**:
   - Ingresa una URL de destino
   - Dale un nombre
   - Click en "Generar Link"

3. **Probar la captura**:
   - Abre el link generado en otro navegador/dispositivo
   - Acepta permisos de cámara
   - Verifica que te redirija al destino

4. **Ver fotos capturadas**: `https://tu-app.onrender.com/gallery`

5. **Panel Admin**: `https://tu-app.onrender.com/admin`

## Solución de Problemas Comunes

### ❌ Error: "Application Error" o 502

**Causa**: La aplicación no puede conectarse a la base de datos

**Solución**:
1. Ve a Environment Variables en Render
2. Verifica que `DATABASE_URL` esté correctamente configurada
3. Verifica que la base de datos esté activa (no pausada)
4. Redeploy manual: Settings → Manual Deploy → Deploy latest commit

### ❌ Error: "Build failed - Publish directory does not exist"

**Causa**: Creaste un "Static Site" en lugar de un "Web Service"

**Solución**:
1. Elimina el servicio actual
2. Crea un nuevo **"Web Service"** (no Static Site)
3. Sigue las instrucciones del Paso 2

### ❌ Las instancias Free se duermen después de inactividad

**Comportamiento normal**: Las instancias gratuitas de Render se duermen después de 15 minutos de inactividad.

**Efecto**: La primera request después de dormir toma 30-60 segundos en responder.

**Soluciones**:
- Actualizar a instancia pagada ($7/mes Starter)
- Usar un servicio de ping externo para mantener activo (ej: UptimeRobot)

### ❌ Error: "No se pueden capturar fotos"

**Causas posibles**:
- HTTPS requerido para acceso a cámara (Render proporciona HTTPS automáticamente)
- Permisos de cámara denegados por el usuario
- Navegador no compatible

**Solución**: Asegúrate de usar HTTPS (render.com siempre usa HTTPS)

## Actualizaciones y Redeploy

### Auto-Deploy (Automático):

Por defecto, cada vez que haces `git push` a la rama `main`, Render automáticamente:
1. Detecta el cambio
2. Hace build
3. Despliega la nueva versión

### Manual Deploy:

Si necesitas redesplegar manualmente:
1. Ve a tu Web Service en Render
2. Click en **"Manual Deploy"** (arriba derecha)
3. Selecciona **"Deploy latest commit"**

## Comandos Git para Actualizar

```bash
# Hacer cambios en el código
# ...

# Commit los cambios
git add .
git commit -m "Descripción de los cambios"

# Push a GitHub (esto triggerea auto-deploy en Render)
git push origin main
```

## Recursos Adicionales

- **Dashboard de Render**: https://dashboard.render.com/
- **Logs de la aplicación**: En tu Web Service → Logs
- **Documentación de Render**: https://render.com/docs
- **Soporte**: https://render.com/support

## Estructura de URLs de la Aplicación

Una vez desplegada, estas son las rutas disponibles:

```
https://tu-app.onrender.com/                    → Página principal
https://tu-app.onrender.com/config_drive        → Configurar Google Drive
https://tu-app.onrender.com/gallery             → Ver fotos capturadas
https://tu-app.onrender.com/admin               → Panel de administración
https://tu-app.onrender.com/p/{link_id}         → Links de captura generados
https://tu-app.onrender.com/init_db             → Inicializar base de datos (primera vez)
```

## Notas de Seguridad

⚠️ **IMPORTANTE**: Esta aplicación NO tiene autenticación. Considera agregar:
- Autenticación para `/admin`, `/gallery`, `/config_drive`
- Rate limiting para prevenir abuso
- Validación de origins para la captura de fotos
- Sanitización adicional de inputs

---

**¿Necesitas ayuda?** Revisa los logs en Render Dashboard → Tu servicio → Logs
