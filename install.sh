#!/usr/bin/env bash
# Instalación nueva; no modifica la instalación anterior de /home/admin.
set -Eeuo pipefail
umask 027
trap 'echo "Instalación interrumpida en línea $LINENO. Corrige el error antes de continuar." >&2' ERR
[[ $EUID -eq 0 ]] || { echo 'Ejecuta: sudo bash install.sh'; exit 1; }
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 22.04 ]] || { echo 'Este instalador está preparado para Ubuntu 22.04.'; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'Este paquete requiere un VPS x86_64.'; exit 1; }
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
target=/opt/jessyca
marker=/opt/jessyca/.installer-v1
if [[ ! -f $marker ]]; then
  for unit in jessyca-local jessyca-whatsapp; do
    if [[ $(systemctl show "$unit" -p LoadState --value) != not-found ]]; then
      echo "Ya existe $unit. Usa este instalador en el VPS NUEVO; no sobreescribirá tu instalación actual."
      exit 1
    fi
  done
  [[ ! -e $target && ! -e /var/lib/jessyca ]] || { echo 'Ya existe una carpeta de destino. Revisar antes de instalar.'; exit 1; }
  if command -v ollama >/dev/null; then
    echo 'Ya existe Ollama. Este instalador requiere un VPS sin una instalación previa de Ollama.'
    exit 1
  fi
fi
[[ -f $src/backend/requirements.txt && -f $src/whatsapp/package-lock.json ]] || exit 1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl xz-utils zstd git python3 python3-venv python3-pip build-essential pkg-config libatomic1
if ! id jessyca >/dev/null 2>&1; then
  useradd --system --user-group --create-home --home-dir /var/lib/jessyca --shell /usr/sbin/nologin jessyca
fi
install -d -m 755 "$target" "$target/runtime"
touch "$marker"
install -d -o jessyca -g jessyca -m 700 /var/lib/jessyca /var/lib/jessyca/data /var/lib/jessyca/huggingface /var/lib/jessyca/whatsapp-session
install -d -m 750 -o root -g jessyca /etc/jessyca
if [[ ! -f /etc/jessyca/jessyca.env ]]; then
  install -m 640 -o root -g jessyca "$src/config.env.example" /etc/jessyca/jessyca.env
fi
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
node_version=24.21.0
node_dir="$target/runtime/node-v${node_version}-linux-x64"
if [[ ! -x $node_dir/bin/node ]]; then
  archive="node-v${node_version}-linux-x64.tar.xz"
  curl --fail --show-error --location --retry 3 "https://nodejs.org/dist/v${node_version}/$archive" -o "$tmp/$archive"
  curl --fail --show-error --location --retry 3 "https://nodejs.org/dist/v${node_version}/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
  (cd "$tmp" && awk -v f="$archive" '$2 == f {print}' SHASUMS256.txt > selected.sha256 && test -s selected.sha256 && sha256sum -c selected.sha256)
  tar -xJf "$tmp/$archive" -C "$target/runtime"
fi
export PATH="$node_dir/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
[[ $(node --version) == v24.21.0 ]]
[[ $(npm --version) == 11.19.0 ]]

# Todas las dependencias se instalan antes de habilitar WhatsApp.
systemctl stop jessyca-whatsapp.service jessyca-local.service 2>/dev/null || true
install -d -o jessyca -g jessyca -m 750 "$target/backend" "$target/whatsapp"
cp -a "$src/backend/." "$target/backend/"
cp -a "$src/whatsapp/." "$target/whatsapp/"
chown -R jessyca:jessyca "$target/backend" "$target/whatsapp"
runuser -u jessyca -- python3 -m venv "$target/backend/.venv-local"
runuser -u jessyca -- "$target/backend/.venv-local/bin/python" -m pip install --no-cache-dir -r "$target/backend/requirements.txt"
runuser -u jessyca -- "$target/backend/.venv-local/bin/python" -m pip check
(cd "$target/whatsapp" && runuser -u jessyca -- env PATH="$PATH" npm ci --no-audit --no-fund)
(cd "$target/whatsapp" && runuser -u jessyca -- env PATH="$PATH" node --input-type=module -e "await import('@whiskeysockets/baileys'); const {default: sharp}=await import('sharp'); await sharp({create:{width:2,height:2,channels:3,background:'white'}}).jpeg().toBuffer(); console.log('Baileys y Sharp OK');")
if ! command -v ollama >/dev/null; then
  curl --fail --show-error --location --retry 3 https://ollama.com/install.sh -o "$tmp/ollama-install.sh"
  OLLAMA_VERSION=0.40.0 sh "$tmp/ollama-install.sh"
fi
install -d /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/jessyca.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_CONTEXT_LENGTH=2048"
Environment="OLLAMA_KEEP_ALIVE=30m"
EOF
systemctl daemon-reload
systemctl enable ollama
systemctl restart ollama
ready=false
for attempt in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version > "$tmp/ollama-version.json"; then ready=true; break; fi
  sleep 1
done
[[ $ready == true ]] || { echo 'Ollama no arrancó. Consulta journalctl -u ollama.'; exit 1; }
python3 - "$tmp/ollama-version.json" <<'PY'
import json,sys
version=json.load(open(sys.argv[1]))['version']
if version != '0.40.0':
    raise SystemExit(f'Se esperaba Ollama 0.40.0; el servidor informa {version}')
PY
# config.env.example usa sintaxis común a shell y systemd (sin espacios).
set -a
source /etc/jessyca/jessyca.env
set +a
export OLLAMA_HOST=127.0.0.1:11434
ollama pull "$TEXT_MODEL"
ollama pull "$VISION_MODEL"
runuser -u jessyca -- env HF_HOME=/var/lib/jessyca/huggingface "$target/backend/.venv-local/bin/python" -c 'from faster_whisper import WhisperModel; WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)'
for name in jessyca-local jessyca-whatsapp; do
  install -m 644 "$src/scripts/$name.service" "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
systemctl enable --now jessyca-local
ready=false
for attempt in {1..30}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8001/health >/dev/null; then ready=true; break; fi
  sleep 1
done
[[ $ready == true ]] || { echo 'La API no arrancó. Consulta journalctl -u jessyca-local.'; exit 1; }
# Verifica generación real, no solo que el puerto esté abierto.
curl -fsS --max-time 180 http://127.0.0.1:8001/chat -H 'Content-Type: application/json' -d '{"chat_id":"instalacion","text":"Responde únicamente: JESSYCA lista."}'
systemctl enable --now jessyca-whatsapp
echo
echo 'Instalado. Vincula WhatsApp leyendo el QR con:'
echo 'sudo journalctl -u jessyca-whatsapp -f -n 60 --no-pager'
echo 'Ctrl+C deja de mostrar registros; los servicios siguen funcionando.'
