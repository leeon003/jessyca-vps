# Alcance de la validación

Se conserva el código del archivo exportado, con estos cambios:

- Rutas Python relativas al módulo, sin depender del usuario `admin`.
- Variables de entorno para datos, sesión, presencia y nombres de modelos.
- Confirmación de `jessyca ya volvi` coherente con la lógica actual.
- Instalador de VPS nuevo, unidades systemd y documentación.

Verificaciones locales: sintaxis Bash, Python y JavaScript; lectura y escritura de memoria/perfiles en una ubicación temporal; controles de presencia y revocación de respuestas pendientes; correspondencia de dependencias declaradas con package-lock; revisión de archivos y patrones comunes de secretos.

No se ejecutó una instalación completa de Ubuntu, descarga de todos los paquetes/modelos, inferencia de Ollama, transcripción real ni conexión WhatsApp en este entorno. Los pins Python proceden del archivo exportado: su resolución completa se comprobará durante la instalación con pip y pip check. El instalador prueba importaciones, Sharp, disponibilidad de Ollama, descargas, salud de la API y una generación de texto antes de iniciar WhatsApp.

No se detectaron archivos de sesión, credenciales ni conversaciones reales en el paquete entregado. La revisión por patrones no equivale a una auditoría exhaustiva de seguridad.
