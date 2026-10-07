import gc
import os
import tempfile
from threading import Lock

from faster_whisper import WhisperModel


MODEL_SIZE = "base"
transcription_lock = Lock()


def transcribe_audio(audio_bytes):
    if not audio_bytes:
        raise ValueError("Audio vacío")

    if len(audio_bytes) > 20 * 1024 * 1024:
        raise ValueError("El audio supera 20 MB")

    temp_path = None
    model = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".ogg",
            delete=False,
        ) as temp:
            temp.write(audio_bytes)
            temp.flush()
            temp_path = temp.name

        with transcription_lock:
            model = WhisperModel(
                MODEL_SIZE,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                num_workers=1,
            )

            segments, info = model.transcribe(
                temp_path,
                language=None,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                condition_on_previous_text=True,
            )

            parts = []

            for segment in segments:
                text = segment.text.strip()

                if text:
                    parts.append(text)

            transcript = " ".join(parts).strip()

        if not transcript:
            raise ValueError(
                "No se detectó voz en el audio"
            )

        return {
            "text": transcript,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": getattr(info, "duration", None),
        }

    finally:
        if model is not None:
            del model

        gc.collect()

        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
