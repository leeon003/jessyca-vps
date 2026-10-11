from app.ramy_product_photos import handle_product_photo
# RAMY_FOTOS_PRODUCTOS_V1
from app.ramy_progress import track_progress
from app.ramy_checkout import handle_checkout, receive_receipt, expects_receipt, checkout_context
from app.ramy_payments import payment_reply
# RAMY_QR_PAGOS_V1
from app.ramy_sales import catalog as consultar_productos
from app.ramy_sales import grounded_messages, guard_reply, internal_request, INTERNAL, UNAVAILABLE
# RAMY_VENTAS_V2
from app.web_search import handle_search
from app.memory_store import load_histories, save_histories
from app.contact_profiles import (
    get_profile,
    update_profile,
    add_pending,
)
from app.profile_extractor import extract_profile_facts
from app.audio_transcriber import transcribe_audio

import base64
import json
import logging
import time
import urllib.request
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


ROOT = Path("/home/admin/jessyca-whatsapp")
INSTRUCTIONS = (ROOT / "sales_prompt.txt").read_text()

TEXT_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
VISION_MODEL = "qwen3-vl:4b-instruct-q4_K_M"

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"

app = FastAPI(title="JESSYCA local")
logger = logging.getLogger("uvicorn.error")

histories = load_histories()

memory_lock = Lock()
generation_lock = Lock()


class Message(BaseModel):
    chat_id: str = Field(
        min_length=1,
        max_length=150,
    )

    assistant_context: str = Field(
        default="",
        max_length=1200,
    )

    text: str = Field(
        min_length=1,
        max_length=12000,
    )


class VisionMessage(BaseModel):
    chat_id: str = Field(
        min_length=1,
        max_length=150,
    )

    assistant_context: str = Field(
        default="",
        max_length=1200,
    )

    text: str = Field(
        default="",
        max_length=2000,
    )

    image: str = Field(
        min_length=1,
        max_length=16000000,
    )


class AudioMessage(BaseModel):
    chat_id: str = Field(
        min_length=1,
        max_length=150,
    )

    assistant_context: str = Field(
        default="",
        max_length=1200,
    )

    audio: str = Field(
        min_length=1,
        max_length=30000000,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": "ollama",
        "text_model": TEXT_MODEL,
        "vision_model": VISION_MODEL,
        "memory": "persistent",
        "contact_profiles": True,
        "vision": True,
    }


def profile_to_context(profile):
    if not profile:
        return (
            "No hay información guardada todavía "
            "sobre este contacto."
        )

    useful = {}

    allowed_keys = (
        "name",
        "relationship",
        "priority",
        "topics",
        "notes",
        "pending",
        "summary",
        "last_interaction",
    )

    for key in allowed_keys:
        value = profile.get(key)

        if value not in (
            None,
            "",
            [],
            {},
        ):
            useful[key] = value

    if not useful:
        return (
            "No hay información relevante guardada "
            "todavía sobre este contacto."
        )

    return json.dumps(
        useful,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def get_contact_profile(chat_id, text=""):
    try:
        if text:
            extracted = extract_profile_facts(
                text
            )

            updates = extracted.get(
                "updates",
                {},
            )

            if updates:
                update_profile(
                    chat_id,
                    updates,
                )

            for pending_item in extracted.get(
                "pending",
                [],
            ):
                add_pending(
                    chat_id,
                    pending_item,
                )

        return update_profile(
            chat_id,
            {},
        )

    except Exception as error:
        logger.error(
            "Perfil del contacto: %s | %s",
            type(error).__name__,
            str(error)[:300],
        )

        try:
            return get_profile(
                chat_id
            )
        except Exception:
            return {}


def build_system_prompt(
    assistant_context,
    profile,
    vision=False,
):
    contact_context = profile_to_context(
        profile
    )

    static_rules = """
REGLAS:
- Eres JESSYCA, asesora de ventas de Tiendas RAMY. No eres asistente personal de nadie.
- Quien escribe es el contacto actual.
- Usa historial y perfil solo cuando sean relevantes.
- Los datos del perfil pertenecen al cliente, no a JESSYCA.
- No inventes nombres, relaciones, fechas, preferencias, hechos ni pendientes.
- Si falta un dato, dilo claramente.
- Prioriza datos explícitos del contacto sobre inferencias.
- No menciones archivos, bases de datos, perfiles ni mecanismos internos.
- No inventes compras confirmadas, pagos verificados ni decisiones del cliente.
- No marques pendientes como completados sin confirmación.
- Responde de forma natural, breve y adecuada para WhatsApp.
"""

    if vision:
        static_rules += """
VISIÓN:
- Analiza únicamente lo visible en la imagen.
- No inventes objetos, personas, lugares ni texto ilegible.
- Si algo no se distingue, dilo.
- Si hay una pregunta junto a la imagen, responde principalmente a ella.
"""

    dynamic_context = (
        "\nCONTEXTO ACTUAL:\n"
        + (
            assistant_context.strip()
            if assistant_context.strip()
            else "Sin contexto adicional."
        )
        + "\nCONTACTO:\n"
        + contact_context
    )

    return (
        INSTRUCTIONS
        + "\n"
        + static_rules
        + dynamic_context
    )

def unload_model(model_name):
    payload = {
        "model": model_name,
        "prompt": "",
        "stream": False,
        "keep_alive": 0,
    }

    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=json.dumps(
            payload
        ).encode(),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            response.read()

    except Exception as error:
        logger.warning(
            "No se pudo descargar %s de RAM: %s",
            model_name,
            str(error)[:200],
        )


def save_conversation(
    chat_id,
    previous,
    user_text,
    reply,
):
    saved_user = {
        "role": "user",
        "content": user_text[:600],
    }

    saved_answer = {
        "role": "assistant",
        "content": reply[:600],
    }

    with memory_lock:
        histories[chat_id] = (
            previous
            + [
                saved_user,
                saved_answer,
            ]
        )[-8:]

        histories.move_to_end(
            chat_id
        )

        while len(histories) > 200:
            histories.popitem(
                last=False
            )

        try:
            save_histories(
                histories
            )

        except Exception as error:
            logger.error(
                "No se pudo guardar memoria: %s | %s",
                type(error).__name__,
                str(error)[:300],
            )


def _ramy_model_chat(
    model,
    messages,
    keep_alive,
    timeout=90,
    num_predict=180,
    num_ctx=4096,
):
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": keep_alive,
        "messages": messages,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "num_thread": 4,
        },
    }

    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(
            payload
        ).encode(),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:
        result = json.load(
            response
        )

    reply = (
        result
        .get("message", {})
        .get("content", "")
        .strip()
    )

    if not reply:
        raise ValueError(
            "Respuesta sin texto"
        )

    return reply




def ollama_chat(model, messages, keep_alive, timeout=90, num_predict=180, num_ctx=4096):
    products = consultar_productos()
    if not products:
        return UNAVAILABLE
    current = next((m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), '')
    if internal_request(current):
        return INTERNAL
    # Las respuestas antiguas que ofrecían servicios internos no vuelven al modelo.
    messages = [m for m in messages if m.get('role') != 'assistant' or not internal_request(m.get('content', ''))]
    reply = _ramy_model_chat(model, grounded_messages(messages, products), keep_alive, timeout, num_predict, max(num_ctx, 4096))
    return guard_reply(reply, products)

@app.post("/chat")
@track_progress
def chat(message: Message):
    text = message.text.strip()

    with memory_lock:
        photo_previous = list(histories.get(message.chat_id, []))[-8:]
    photo_reply = handle_product_photo(message.chat_id, text, photo_previous)
    if photo_reply is not None:
        save_conversation(message.chat_id, photo_previous, text, photo_reply['reply'])
        return photo_reply
    sales_reply = handle_checkout(message.chat_id, text, histories.get(message.chat_id, []))
    if sales_reply is not None:
        return sales_reply
    message.assistant_context = (message.assistant_context + checkout_context(message.chat_id))[-1200:]

    official_payment = payment_reply(text)
    if official_payment is not None:
        return official_payment

    # RAMY_SALUDO_V1
    saludo = text.casefold().strip(" ¡!¿?.,:;😊👋✨\n\t")
    if saludo in {
        "hola", "holi", "holis", "buenas",
        "buenos dias", "buenos días",
        "buenas tardes", "buenas noches"
    }:
        return {
            "reply": (
                "Soy JESSYCA, asesora de ventas de Tiendas RAMY. "
                "¡Hola! 😊\n"
                "¿En qué puedo ayudarte hoy con nuestros productos? 🛍️✨"
            )
        }

    if not text:
        raise HTTPException(
            400,
            "El mensaje está vacío",
        )

    if len(text) > 2000:
        return {
            "reply": (
                "¿Puedes enviarme tu consulta "
                "en mensajes más cortos?"
            )
        }

    t_profile = time.monotonic()

    profile = get_contact_profile(
        message.chat_id,
        text,
    )

    logger.info(
        "PERF perfil: %.3f s",
        time.monotonic() - t_profile,
    )


    consulta = text.lower()
    palabras_catalogo = (
        "qué productos",
        "que productos",
        "qué vendes",
        "que vendes",
        "catálogo",
        "catalogo",
        "productos disponibles",
        "qué tienes disponible",
        "que tienes disponible",
    )

    if any(p in consulta for p in palabras_catalogo):
        productos = consultar_productos()

        if productos is None:
            return {
                "reply": "Por el momento no puedo consultar el catálogo. Intenta nuevamente en unos minutos."
            }

        if not productos:
            return {
                "reply": "En este momento no tengo productos comerciales disponibles para mostrarte."
            }

        lineas = ["Estos son nuestros productos disponibles:"]

        for producto in productos[:10]:
            nombre = producto.get("nombre", "Producto")
            precio = producto.get("precio", "")
            disponible = producto.get("disponible", 0)

            if disponible > 0:
                lineas.append(
                    f"• {nombre} — S/ {precio}"
                )

        if len(lineas) == 1:
            lineas.append("Por ahora no tenemos productos con stock disponible.")

        lineas.append("¿Cuál te gustaría conocer mejor?")

        reply = "\n".join(lineas)
        with memory_lock:
            previous = list(histories.get(message.chat_id, []))[-4:]
        save_conversation(message.chat_id, previous, text, reply)
        return {"reply": reply}

    t_search = time.monotonic()

    search_reply = None  # Ventas: sin búsqueda web general.

    logger.info(
        "PERF búsqueda: %.3f s",
        time.monotonic() - t_search,
    )

    if search_reply is not None:
        return {
            "reply": search_reply
        }

    if not generation_lock.acquire(
        timeout=180
    ):
        raise HTTPException(
            503,
            "JESSYCA está atendiendo otra consulta",
        )

    try:
        with memory_lock:
            previous = list(
                histories.get(
                    message.chat_id,
                    [],
                )
            )[-4:]

        system_prompt = build_system_prompt(
            message.assistant_context,
            profile,
            vision=False,
        )

        current = {
            "role": "user",
            "content": text,
        }

        start = time.monotonic()

        try:
            # Evita conservar el modelo visual cuando llega texto.
            t_unload = time.monotonic()

            unload_model(
                VISION_MODEL
            )

            logger.info(
                "PERF unload visión: %.3f s",
                time.monotonic() - t_unload,
            )

            t_ollama = time.monotonic()

            reply = ollama_chat(
                model=TEXT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    *previous,
                    current,
                ],
                keep_alive="10m",
                timeout=90,
                num_predict=100,
                num_ctx=2048,
            )

            logger.info(
                "PERF Ollama texto: %.3f s",
                time.monotonic() - t_ollama,
            )

        except Exception as error:
            logger.error(
                "Ollama texto: %s | %s",
                type(error).__name__,
                str(error)[:300],
            )

            raise HTTPException(
                502,
                "La IA local no pudo responder",
            ) from None

        save_conversation(
            message.chat_id,
            previous,
            text,
            reply,
        )

        logger.info(
            "Respuesta texto generada en %.2f s",
            time.monotonic() - start,
        )

        return {
            "reply": reply
        }

    finally:
        generation_lock.release()


@app.post("/vision")
@track_progress
def vision(message: VisionMessage):
    sales_reply = receive_receipt(message.chat_id, message.image)
    if sales_reply is not None:
        return sales_reply
    text = message.text.strip()

    if not text:
        text = (
            "Analiza esta imagen y responde brevemente "
            "qué información relevante contiene."
        )

    image_data = message.image.strip()

    if image_data.startswith(
        "data:"
    ):
        if "," not in image_data:
            raise HTTPException(
                400,
                "Formato de imagen inválido",
            )

        image_data = image_data.split(
            ",",
            1,
        )[1]

    try:
        decoded = base64.b64decode(
            image_data,
            validate=True,
        )

    except Exception:
        raise HTTPException(
            400,
            "La imagen no contiene base64 válido",
        ) from None

    if not decoded:
        raise HTTPException(
            400,
            "La imagen está vacía",
        )

    # Aproximadamente 8 MB de imagen binaria como máximo.
    if len(decoded) > 8 * 1024 * 1024:
        raise HTTPException(
            413,
            "La imagen es demasiado grande",
        )

    profile = get_contact_profile(
        message.chat_id,
        text,
    )

    if not generation_lock.acquire(
        timeout=180
    ):
        raise HTTPException(
            503,
            "JESSYCA está atendiendo otra consulta",
        )

    try:
        with memory_lock:
            previous = list(
                histories.get(
                    message.chat_id,
                    [],
                )
            )[-4:]

        system_prompt = build_system_prompt(
            message.assistant_context,
            profile,
            vision=True,
        )

        current = {
            "role": "user",
            "content": text,
            "images": [
                image_data
            ],
        }

        start = time.monotonic()

        try:
            # Muy importante para la VPS de 8 GB:
            # sacamos Qwen texto antes de cargar Qwen-VL.
            unload_model(
                TEXT_MODEL
            )

            reply = ollama_chat(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    *previous,
                    current,
                ],
                keep_alive=0,
                timeout=300,
                num_predict=80,
                num_ctx=2048,
            )

        except Exception as error:
            logger.error(
                "Ollama visión: %s | %s",
                type(error).__name__,
                str(error)[:300],
            )

            raise HTTPException(
                502,
                "No pude analizar la imagen",
            ) from None

        memory_text = (
            "[El contacto envió una imagen] "
            + text
        )

        save_conversation(
            message.chat_id,
            previous,
            memory_text,
            reply,
        )

        logger.info(
            "Respuesta visual generada en %.2f s",
            time.monotonic() - start,
        )

        return {
            "reply": reply
        }

    finally:
        generation_lock.release()


@app.post("/audio")
def audio(message: AudioMessage):
    audio_data = message.audio.strip()

    if audio_data.startswith("data:"):
        if "," not in audio_data:
            raise HTTPException(
                400,
                "Formato de audio inválido",
            )

        audio_data = audio_data.split(
            ",",
            1,
        )[1]

    try:
        decoded = base64.b64decode(
            audio_data,
            validate=True,
        )

    except Exception:
        raise HTTPException(
            400,
            "El audio no contiene base64 válido",
        ) from None

    if not decoded:
        raise HTTPException(
            400,
            "El audio está vacío",
        )

    if len(decoded) > 20 * 1024 * 1024:
        raise HTTPException(
            413,
            "El audio es demasiado grande",
        )

    if not generation_lock.acquire(
        timeout=180
    ):
        raise HTTPException(
            503,
            "JESSYCA está atendiendo otra consulta",
        )

    start = time.monotonic()

    try:
        # Liberamos los LLM antes de Whisper.
        unload_model(
            TEXT_MODEL
        )

        unload_model(
            VISION_MODEL
        )

        try:
            transcription = transcribe_audio(
                decoded
            )

            transcript = (
                transcription["text"]
                .strip()
            )

        except Exception as error:
            logger.error(
                "Whisper: %s | %s",
                type(error).__name__,
                str(error)[:300],
            )

            raise HTTPException(
                422,
                "No pude entender el audio",
            ) from None

        if len(transcript) > 4000:
            transcript = transcript[:4000]

        profile = get_contact_profile(
            message.chat_id,
            transcript,
        )

        with memory_lock:
            previous = list(
                histories.get(
                    message.chat_id,
                    [],
                )
            )[-4:]

        system_prompt = build_system_prompt(
            message.assistant_context,
            profile,
            vision=False,
        )

        current = {
            "role": "user",
            "content": transcript,
        }

        try:
            reply = ollama_chat(
                model=TEXT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    *previous,
                    current,
                ],
                keep_alive="10m",
                timeout=90,
                num_predict=100,
                num_ctx=2048,
            )

        except Exception as error:
            logger.error(
                "Ollama después de audio: %s | %s",
                type(error).__name__,
                str(error)[:300],
            )

            raise HTTPException(
                502,
                "Entendí el audio pero no pude responder",
            ) from None

        memory_text = (
            "[Nota de voz] "
            + transcript
        )

        save_conversation(
            message.chat_id,
            previous,
            memory_text,
            reply,
        )

        logger.info(
            "Audio procesado en %.2f s | idioma=%s",
            time.monotonic() - start,
            transcription.get(
                "language",
                "desconocido",
            ),
        )

        return {
            "reply": reply,
            "transcript": transcript,
            "language": transcription.get(
                "language"
            ),
            "language_probability": transcription.get(
                "language_probability"
            ),
        }

    finally:
        generation_lock.release()


@app.get('/ramy/receipt-status')
def ramy_receipt_status(chat_id: str):
    return {'expects_receipt': expects_receipt(chat_id)}
