# JESSYCA en un VPS

Asistente por WhatsApp con Baileys, FastAPI y Ollama local. Exportación del código entregado el 7 de octubre de 2026, preparada para instalación en **otro VPS Ubuntu 22.04 x86_64**, con sudo, systemd y salida a Internet. Referencia de hardware: 4 vCPU, 8 GB de RAM, 100 GB de disco.

## Funciones conservadas

- Conversación con Qwen3 4B, memoria persistente y perfiles por contacto.
- Imágenes con Qwen3-VL 4B y notas de voz con Faster Whisper base.
- Búsqueda explícita `/buscar consulta`, activable y desactivable.
- Estado de Diego desde su chat consigo mismo y pausa por contacto.
- Cabecera de JESSYCA, agrupación de mensajes durante 5 segundos y cola global.

La pausa de 5 segundos forma parte del código recibido: se cuenta desde el último mensaje. No es tiempo de generación. Imágenes y audios pueden tardar más en CPU. El modelo visual se descarga de memoria antes de texto y los dos modelos antes de transcribir audio.

## Subir este paquete a tu repositorio actual

**En PowerShell de tu PC**, tras descargar `jessyca-vps-listo.tar.gz`:

```powershell
scp -o ConnectTimeout=15 "$env:USERPROFILE\Downloads\jessyca-vps-listo.tar.gz" "admin@169.58.16.235:/home/admin/"
```

**En el VPS actual**, esto solo prepara el código; no ejecutes allí `install.sh`:

```bash
mkdir -p ~/jessyca-git-preparacion
tar -xzf ~/jessyca-vps-listo.tar.gz -C ~/jessyca-git-preparacion
```

Si aún no configuraste acceso GitHub desde ese VPS:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
if [ ! -f ~/.ssh/jessyca_github ]; then
  ssh-keygen -t ed25519 -C jessyca-vps -f ~/.ssh/jessyca_github -N ''
fi
cat ~/.ssh/jessyca_github.pub
```

Agrega únicamente la clave **pública** en el repositorio `leeon003/jessyca-vps`: Settings → Deploy keys → Add deploy key → Allow write access. No copies ni compartas el archivo sin `.pub`.

Después:

```bash
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/jessyca_github -o IdentitiesOnly=yes"
git clone git@github.com:leeon003/jessyca-vps.git ~/jessyca-git-publicacion
```

En la primera conexión SSH, verifica la huella de GitHub antes de aceptar: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints

Si la carpeta de destino ya existe, no la borres: usa otra carpeta vacía para el clon. Continúa solo si `git clone` terminó correctamente:

```bash
cp -a ~/jessyca-git-preparacion/jessyca-vps/. ~/jessyca-git-publicacion/
cd ~/jessyca-git-publicacion
git config user.name "leeon003"
git config user.email "leeon003@users.noreply.github.com"
git add README.md VALIDACION.md .gitignore install.sh config.env.example scripts backend whatsapp
git diff --cached --stat
git diff --cached --name-only
```

El listado debe incluir código, instrucciones y dependencias; nunca sesiones, claves, conversaciones ni perfiles reales. Luego:

```bash
git commit -m "Preparar instalación portable de JESSYCA"
git push -u origin HEAD
```

No se usa `--force`. Si aparecen cambios remotos concurrentes o conflictos, detente y revisa el mensaje antes de continuar. Conserva el repositorio privado. Copiar código al repositorio no modifica el proceso que ya está funcionando.

## Instalar en el VPS nuevo

1. Usa Ubuntu 22.04 x86_64 sin otra instalación de JESSYCA u Ollama. Configura una **nueva clave pública de lectura** como deploy key de este repositorio privado; no copies la clave privada del VPS anterior.
2. Clona el repositorio y ejecuta el instalador:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone git@github.com:leeon003/jessyca-vps.git
cd jessyca-vps
sudo bash install.sh
```

El clon usa la clave SSH predeterminada de ese nuevo usuario. Si le pusiste un nombre especial, indica su ruta mediante `GIT_SSH_COMMAND`, igual que en el ejemplo anterior.

El instalador usa Node 24.21.0/npm 11.19.0, Ollama 0.40.0, `npm ci` y los pins Python de tu exportación. Descarga `qwen3:4b-instruct-2507-q4_K_M`, `qwen3-vl:4b-instruct-q4_K_M` y Whisper base. No copia las otras etiquetas de tu listado de Ollama.

La instalación depende de que estas versiones continúen disponibles en sus registros. Si una descarga o dependencia falla, el script se detiene; no sustituye versiones por su cuenta. Se puede repetir el comando para reintentar una instalación creada por este instalador. **No es un actualizador de tu instalación antigua.**

3. Antes de usar el mismo WhatsApp en el nuevo VPS, detén su conector anterior:

```bash
# Solo en el VPS anterior, cuando decidas hacer el cambio:
sudo systemctl disable --now jessyca-whatsapp
```

4. En el nuevo VPS, muestra el QR y escanéalo desde WhatsApp → Dispositivos vinculados:

```bash
sudo journalctl -u jessyca-whatsapp -f -n 60 --no-pager
```

`Ctrl+C` cierra la vista de registros, sin detener el servicio. Si el QR venció, espera el siguiente. Tras vincular, prueba texto, una imagen y una nota de voz desde otro número. No se ha probado aquí una vinculación real.

## Ubicación y administración

| Elemento | Ruta |
|---|---|
| Código instalado y runtime | `/opt/jessyca` |
| Configuración privada | `/etc/jessyca/jessyca.env` |
| Conversaciones y perfiles | `/var/lib/jessyca/data` |
| Estado y chats silenciados | `/var/lib/jessyca/presence.json` |
| Sesión de WhatsApp | `/var/lib/jessyca/whatsapp-session` |
| Caché de Whisper | `/var/lib/jessyca/huggingface` |

Los procesos de JESSYCA se ejecutan como usuario `jessyca`; API y Ollama escuchan en `127.0.0.1`, puertos 8001 y 11434. No hace falta un túnel ni abrir esos puertos al público.

```bash
systemctl is-active ollama jessyca-local jessyca-whatsapp
sudo journalctl -u jessyca-local -u jessyca-whatsapp -n 50 --no-pager
curl --max-time 120 -sS http://127.0.0.1:8001/chat -H 'Content-Type: application/json' -d '{"chat_id":"prueba","text":"Hola, preséntate brevemente."}'
```

Para cambiar búsquedas, edita `WEB_SEARCH_ENABLED=true` o `false` en:

```bash
sudo nano /etc/jessyca/jessyca.env
sudo systemctl restart jessyca-local
```

El archivo de personalidad instalado está en `/opt/jessyca/backend/sales_prompt.txt`; reinicia `jessyca-local` tras editarlo. Para conservar ese cambio también en Git, aplícalo a `backend/sales_prompt.txt` del clon y haz commit. `git pull` por sí solo no despliega cambios en `/opt/jessyca`.

## Controles en WhatsApp

En tu chat contigo mismo: `jessyca ayuda`, `jessyca estado`, `jessyca estoy durmiendo`, `jessyca estoy ocupado`, `jessyca estoy trabajando`, `jessyca estoy en clase`, `jessyca estoy manejando`, `jessyca estoy en una reunion`, `jessyca ya volvi`, `jessyca pausa`.

En un chat individual, enviados **por ti**: `/jessyca off` silencia ese chat y `/jessyca on` lo habilita. La pausa global tiene prioridad. Según tu código actual, escribir manualmente no pausa al bot y estar disponible tampoco lo silencia: responde a los chats privados habilitados. Se corrigió el texto de confirmación antiguo para describir esa conducta.

## Datos privados y traslado

Git conserva el programa, no la memoria ni los chats silenciados. El nuevo VPS empieza sin ellos y requiere QR. Para trasladar también esos datos hace falta una copia privada aparte, con los servicios detenidos durante la copia; no los agregues al repositorio. Guarda el VPS anterior hasta validar el nuevo. No se incluye un procedimiento automático para trasladar sesiones activas.

Baileys es una integración no oficial; su compatibilidad y la continuidad de la sesión dependen de WhatsApp. El repositorio incluye tu comportamiento actual, sin garantizar disponibilidad permanente de esa conexión.

Fuentes de instalación: https://nodejs.org/en/download/archive/v24.21.0 y https://docs.ollama.com/linux .
