import { installConversationTracking, recordIncoming, recordStatuses, recordProgress } from './crm-conversations.js';
import { route, stillAllowed, markAnswered } from './presence.js';
// RAMY_FAST_WELCOME_V1
import { createFastWelcome } from './fast-welcome.mjs';
const fastWelcome = createFastWelcome({stillAllowed, markAnswered});

import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  normalizeMessageContent,
  generateMessageIDV2,
  downloadContentFromMessage
} from '@whiskeysockets/baileys';

import qrcode from 'qrcode-terminal';
import pino from 'pino';
import sharp from 'sharp';

import { mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';


process.umask(0o077);

const authDir = join(
  homedir(),
  '.jessyca-whatsapp-session'
);

const logger = pino({
  level: 'silent'
});

const seen = new Set();
// RAMY_VENTAS_V2: registro persistente de IDs recibidos.
import { claimMessage } from "./ramy-dedup.mjs";
const queues = new Map();
let globalQueue = Promise.resolve();
const messageBuffers = new Map();

const MESSAGE_BUFFER_MS = 5000;
const MAX_BUFFER_TEXT = 12000;

const IMAGE_MAX_DIMENSION = 512;
const IMAGE_JPEG_QUALITY = 72;

let reconnectDelay = 2000;
let reconnectTimer = null;


/*
 * Identidad estable del contacto para la memoria.
 */
function getStableChatId(jid, ticket) {
  const keys = Array.isArray(ticket?.keys)
    ? ticket.keys
    : [];

  const phoneJid = keys.find(
    key =>
      typeof key === 'string' &&
      key.endsWith('@s.whatsapp.net')
  );

  if (phoneJid) {
    return `whatsapp:${phoneJid}`;
  }

  const lidJid = keys.find(
    key =>
      typeof key === 'string' &&
      key.endsWith('@lid')
  );

  if (lidJid) {
    return `whatsapp:${lidJid}`;
  }

  return `whatsapp:${jid}`;
}


async function streamToBuffer(stream) {
  const chunks = [];

  for await (const chunk of stream) {
    chunks.push(
      Buffer.isBuffer(chunk)
        ? chunk
        : Buffer.from(chunk)
    );
  }

  return Buffer.concat(chunks);
}


/*
 * Descarga y optimiza una imagen de WhatsApp.
 */

async function getAudioBase64(message) {
  const content = normalizeMessageContent(
    message.message
  );

  const audioMessage = content?.audioMessage;

  if (!audioMessage) {
    return null;
  }

  const stream = await downloadContentFromMessage(
    audioMessage,
    'audio'
  );

  const audioBuffer = await streamToBuffer(
    stream
  );

  if (!audioBuffer.length) {
    throw new Error(
      'WhatsApp entregó un audio vacío'
    );
  }

  if (audioBuffer.length > 20 * 1024 * 1024) {
    throw new Error(
      'La nota de voz supera 20 MB'
    );
  }

  return audioBuffer.toString(
    'base64'
  );
}


async function receiptAwareImage(sock, jid, message, ticket) {
  try {
  const response = await fetch('http://127.0.0.1:8001/ramy/receipt-status?chat_id=' + encodeURIComponent(getStableChatId(jid, ticket)), {signal: AbortSignal.timeout(8000)});
  if (!response.ok) throw new Error('No se pudo consultar el pedido para esta imagen');
  const data = await response.json();
  if (!data.expects_receipt) return getOptimizedImageBase64(message);
  const content = normalizeMessageContent(message.message);
  const stream = await downloadContentFromMessage(content.imageMessage, 'image');
  const chunks = []; let size = 0;
  for await (const chunk of stream) {
    size += chunk.length;
    if (size > 8 * 1024 * 1024) throw new Error('Comprobante mayor a 8 MB');
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString('base64');
  } catch (error) {
    if (stillAllowed(ticket)) {
      await sock.sendMessage(jid, {text: 'No pude procesar esta imagen. Si es tu comprobante, reenvíalo como foto JPG, PNG o WebP de hasta 8 MB. No he confirmado su registro ni el pago.'});
      markAnswered(ticket);
    }
    return null;
  }
}

async function getOptimizedImageBase64(message) {
  const content = normalizeMessageContent(
    message.message
  );

  const imageMessage = content?.imageMessage;

  if (!imageMessage) {
    return null;
  }

  const stream = await downloadContentFromMessage(
    imageMessage,
    'image'
  );

  const original = await streamToBuffer(
    stream
  );

  const optimized = await sharp(original)
    .rotate()
    .resize({
      width: IMAGE_MAX_DIMENSION,
      height: IMAGE_MAX_DIMENSION,
      fit: 'inside',
      withoutEnlargement: true
    })
    .jpeg({
      quality: IMAGE_JPEG_QUALITY,
      mozjpeg: true
    })
    .toBuffer();

  return optimized.toString(
    'base64'
  );
}


/*
 * Respuesta normal de texto.
 */
async function answerText(
  sock,
  jid,
  text,
  ticket
) {
  if (!stillAllowed(ticket)) {
    return;
  }

  let reply;
  let paymentQr = false;
  let productImage = null;

  try {
    const response = await fetch(
      'http://127.0.0.1:8001/chat',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          chat_id: getStableChatId(jid, ticket),
          text,
          assistant_context: ticket.context
        }),
        signal: AbortSignal.timeout(90000)
      }
    );

    if (!response.ok) {
      const detail = await response.text();

      throw new Error(
        `HTTP ${response.status}: ${detail.slice(0, 300)}`
      );
    }

    const data = await response.json();

    if (
      typeof data.reply !== 'string' ||
      !data.reply.trim()
    ) {
      throw new Error('Respuesta vacía');
    }

    reply = data.reply.trim();
    if (data.sales_progress) recordProgress(jid, ticket, data.sales_progress);
    paymentQr = data.payment_qr === true;
    if (typeof data.product_image_base64 === 'string' && data.product_image_base64.length <= 7000000) {
      productImage = Buffer.from(data.product_image_base64, 'base64');
    }

  } catch (error) {
    console.log(
      'Error al consultar JESSYCA texto:',
      error.message
    );

    reply =
      'Perdona, hubo un problema al generar mi respuesta. ' +
      '¿Puedes intentarlo de nuevo?';
  }

  if (!stillAllowed(ticket)) {
    return;
  }

  await sock.sendMessage(
    jid,
    productImage ? {
      image: productImage,
      caption: (/\bsoy\s+jessyca\b/i.test(reply) ? reply : ticket.prefix + reply).slice(0, 1024)
    } : paymentQr ? {
      image: { url: '/home/admin/whatsapp-bridge/assets/yape-ramy.png' },
      caption: (/\bsoy\s+jessyca\b/i.test(reply) ? reply : ticket.prefix + reply).slice(0, 1024)
    } : {
      text: (/\bsoy\s+jessyca\b/i.test(reply) ? reply : ticket.prefix + reply).slice(0, 12000)
    }
  );

  markAnswered(ticket);

  console.log(
    `Respuesta de texto enviada a ${jid}.`
  );
}


/*
 * Respuesta para imagen.
 */

async function answerAudio(
  sock,
  jid,
  audioBase64,
  ticket,
  sourceMessage
) {
  if (!stillAllowed(ticket)) {
    return;
  }

  let reply;
  let transcript = '';

  try {
    console.log(
      `Procesando nota de voz de ${jid}...`
    );

    const response = await fetch(
      'http://127.0.0.1:8001/audio',
      {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json'
        },

        body: JSON.stringify({
          chat_id: getStableChatId(
            jid,
            ticket
          ),

          audio: audioBase64,

          assistant_context:
            ticket.context
        }),

        signal:
          AbortSignal.timeout(240000)
      }
    );

    if (!response.ok) {
      const detail =
        await response.text();

      throw new Error(
        `HTTP ${response.status}: ${detail.slice(0, 300)}`
      );
    }

    const data =
      await response.json();

    if (
      typeof data.reply !== 'string' ||
      !data.reply.trim()
    ) {
      throw new Error(
        'Respuesta de audio vacía'
      );
    }

    reply = data.reply.trim();
    if (data.sales_progress) recordProgress(jid, ticket, data.sales_progress);

    if (
      typeof data.transcript === 'string'
    ) {
      transcript =
        data.transcript.trim();
    }

    if (transcript && sourceMessage) recordIncoming(sourceMessage, transcript, 'audio');

  } catch (error) {
    console.log(
      'Error al procesar audio:',
      error.message
    );

    reply =
      'Recibí tu nota de voz, pero no pude entenderla correctamente. ' +
      'Puedes intentar enviarla nuevamente.';
  }

  if (!stillAllowed(ticket)) {
    return;
  }

  await sock.sendMessage(
    jid,
    {
      text:
        (/\bsoy\s+jessyca\b/i.test(reply) ? reply : ticket.prefix + reply).slice(
          0,
          12000
        )
    }
  );

  markAnswered(ticket);

  console.log(
    `Respuesta de audio enviada a ${jid}.`
  );
}


async function answerVision(
  sock,
  jid,
  text,
  imageBase64,
  ticket
) {
  if (!stillAllowed(ticket)) {
    return;
  }

  let reply;

  try {
    const prompt = text && text.trim()
      ? text.trim()
      : 'Describe brevemente esta imagen en español sin inventar detalles.';

    const response = await fetch(
      'http://127.0.0.1:8001/vision',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          chat_id: getStableChatId(jid, ticket),
          text: prompt,
          image: imageBase64,
          assistant_context: ticket.context
        }),
        signal: AbortSignal.timeout(320000)
      }
    );

    if (!response.ok) {
      const detail = await response.text();

      throw new Error(
        `HTTP ${response.status}: ${detail.slice(0, 300)}`
      );
    }

    const data = await response.json();

    if (
      typeof data.reply !== 'string' ||
      !data.reply.trim()
    ) {
      throw new Error('Respuesta visual vacía');
    }

    reply = data.reply.trim();
    if (data.sales_progress) recordProgress(jid, ticket, data.sales_progress);

  } catch (error) {
    console.log(
      'Error al consultar JESSYCA visión:',
      error.message
    );

    reply =
      'Pude recibir la imagen, pero no logré analizarla correctamente. ' +
      '¿Puedes reenviarla o decirme qué necesitas saber de ella?';
  }

  if (!stillAllowed(ticket)) {
    return;
  }

  await sock.sendMessage(
    jid,
    {
      text:
        (/\bsoy\s+jessyca\b/i.test(reply) ? reply : ticket.prefix + reply).slice(0, 12000)
    }
  );

  markAnswered(ticket);

  console.log(
    `Respuesta visual enviada a ${jid}.`
  );
}


/*
 * Cola por contacto.
 */
function queueTask(
  jid,
  task
) {
  const next = globalQueue
    .then(async () => {
      console.log(
        `[COLA IA] Procesando ${jid}`
      );

      await task();
    })
    .catch(error => {
      console.log(
        'Respuesta no enviada:',
        error.message
      );
    });

  globalQueue = next.then(
    () => undefined,
    () => undefined
  );
}

function queueTextAnswer(
  sock,
  jid,
  message,
  text,
  ticket
) {
  queueTask(
    jid,
    async () => {
      if (!stillAllowed(ticket)) {
        return;
      }

      const fresh = route(
        sock,
        message,
        text
      );

      if (
        fresh.kind !== 'answer' ||
        fresh.revision !== ticket.revision
      ) {
        return;
      }

      await answerText(
        sock,
        jid,
        text,
        fresh
      );
    }
  );
}



function queueAudioAnswer(
  sock,
  jid,
  message,
  ticket
) {
  queueTask(
    jid,
    async () => {
      if (!stillAllowed(ticket)) {
        return;
      }

      const fresh = route(
        sock,
        message,
        'Jessyca'
      );

      if (
        fresh.kind !== 'answer' ||
        fresh.revision !== ticket.revision
      ) {
        return;
      }

      const audioBase64 =
        await getAudioBase64(
          message
        );

      if (!audioBase64) {
        throw new Error(
          'No se pudo descargar el audio'
        );
      }

      await answerAudio(
        sock,
        jid,
        audioBase64,
        fresh,
        message
      );
    }
  );
}


function queueVisionAnswer(
  sock,
  jid,
  message,
  text,
  ticket
) {
  queueTask(
    jid,
    async () => {
      if (!stillAllowed(ticket)) {
        return;
      }

      const fresh = route(
        sock,
        message,
        text
      );

      if (
        fresh.kind !== 'answer' ||
        fresh.revision !== ticket.revision
      ) {
        return;
      }

      const imageBase64 =
        await receiptAwareImage(sock, jid, message, fresh);

      if (!imageBase64) {
        return;
      }

      await answerVision(
        sock,
        jid,
        text,
        imageBase64,
        fresh
      );
    }
  );
}


function flushMessageBuffer(
  sock,
  jid
) {
  const buffer = messageBuffers.get(
    jid
  );

  if (!buffer) {
    return;
  }

  if (buffer.timer) {
    clearTimeout(
      buffer.timer
    );
  }

  messageBuffers.delete(jid);

  const combinedText = buffer.texts
    .filter(Boolean)
    .join('\n')
    .trim()
    .slice(0, MAX_BUFFER_TEXT);

  if (!combinedText) {
    return;
  }

  console.log(
    `Agrupados ${buffer.texts.length} mensaje(s) de ${jid}.`
  );

  queueTextAnswer(
    sock,
    jid,
    buffer.lastMessage,
    combinedText,
    buffer.ticket
  );
}


function bufferMessage(
  sock,
  jid,
  message,
  text,
  ticket
) {
  let buffer = messageBuffers.get(
    jid
  );

  if (!buffer) {
    buffer = {
      texts: [],
      timer: null,
      lastMessage: message,
      ticket
    };

    messageBuffers.set(
      jid,
      buffer
    );
  }

  if (
    buffer.ticket.revision !==
    ticket.revision
  ) {
    flushMessageBuffer(
      sock,
      jid
    );

    buffer = {
      texts: [],
      timer: null,
      lastMessage: message,
      ticket
    };

    messageBuffers.set(
      jid,
      buffer
    );
  }

  buffer.texts.push(
    text
  );

  buffer.lastMessage = message;
  buffer.ticket = ticket;

  if (buffer.timer) {
    clearTimeout(
      buffer.timer
    );
  }

  const totalLength =
    buffer.texts.reduce(
      (total, item) =>
        total + item.length + 1,
      0
    );

  if (
    totalLength >= MAX_BUFFER_TEXT
  ) {
    flushMessageBuffer(
      sock,
      jid
    );
    return;
  }

  buffer.timer = setTimeout(
    () => {
      flushMessageBuffer(
        sock,
        jid
      );
    },
    MESSAGE_BUFFER_MS
  );
}


async function connect() {
  await mkdir(
    authDir,
    {
      recursive: true,
      mode: 0o700
    }
  );

  const {
    state,
    saveCreds
  } = await useMultiFileAuthState(
    authDir
  );

  const sock = makeWASocket({
    auth: state,
    logger,
    markOnlineOnConnect: false,
    syncFullHistory: false
  });

  const tracking = installConversationTracking(sock, generateMessageIDV2);

  sock.ev.on(
    'creds.update',
    () => {
      saveCreds().catch(() => {
        console.error(
          'No se pudo guardar la sesión.'
        );
        process.exit(1);
      });
    }
  );

  sock.ev.on(
    'connection.update',
    ({
      connection,
      lastDisconnect,
      qr
    }) => {
      if (qr) {
        console.log(
          'Escanea este QR desde Dispositivos vinculados:'
        );
        qrcode.generate(
          qr,
          { small: true }
        );
      }

      if (connection === 'open') {
        reconnectDelay = 2000;
        console.log(
          'WHATSAPP CONECTADO. JESSYCA responderá chats privados.'
        );
      }

      if (connection === 'close') {
        sock.ev.removeAllListeners('messages.upsert');
        if (reconnectTimer) return;
        const code =
          lastDisconnect?.error?.output?.statusCode;

        if (
          code === DisconnectReason.loggedOut ||
          code === DisconnectReason.connectionReplaced
        ) {
          console.log(
            'Sesión cerrada o reemplazada. Deteniendo el conector.'
          );
          process.exit(1);
        }

        console.log(
          `Conexión cerrada (${code ?? 'sin código'}). Reconectando...`
        );

        reconnectTimer = setTimeout(
          () => {
            reconnectTimer = null;
            connect().catch(() => {
              console.error(
                'No se pudo reconectar.'
              );
              process.exit(1);
            });
          },
          reconnectDelay
        );

        reconnectDelay = Math.min(
          reconnectDelay * 2,
          30000
        );
      }
    }
  );

  sock.ev.on(
    'messages.upsert',
    async ({ type, messages }) => {
      console.log(
        `[WHATSAPP EVENT] type=${type} mensajes=${messages?.length ?? 0}`
      );

      if (
        type !== 'notify' &&
        type !== 'append'
      ) {
        return;
      }

      for (const message of messages) {
        console.log(
          '[MENSAJE RECIBIDO]',
          'jid=', message?.key?.remoteJid,
          'fromMe=', message?.key?.fromMe,
          'tipos=', Object.keys(message?.message || {}).join(',')
        );
        const jid = message.key.remoteJid;

        if (
          !jid ||
          !message.message ||
          !message.key.id
        ) {
          continue;
        }

        if (
          !jid.endsWith('@s.whatsapp.net') &&
          !jid.endsWith('@lid')
        ) {
          continue;
        }

        const content = normalizeMessageContent(
          message.message
        );

        const text = (
          content?.conversation ||
          content?.extendedTextMessage?.text ||
          content?.imageMessage?.caption ||
          ''
        ).trim();

        const hasImage = Boolean(
          content?.imageMessage
        );

        const hasAudio = Boolean(
          content?.audioMessage
        );

        const hasOtherMedia =
          content?.videoMessage ||
          content?.videoMessage ||
          content?.documentMessage ||
          content?.stickerMessage ||
          content?.contactMessage ||
          content?.locationMessage;

        if (
          !text &&
          !hasImage &&
          !hasAudio &&
          !hasOtherMedia
        ) {
          continue;
        }

        /*
         * Por ahora:
         * - texto ✅
         * - imagen ✅
         * - audio ❌
         * - otros medios ❌
         */
        if (
          !message.key.fromMe &&
          !text &&
          !hasImage &&
          !hasAudio
        ) {
          recordIncoming(message, text, 'otro');
          continue;
        }

        if (
          !message.key.fromMe &&
          text.length > 12000
        ) {
          continue;
        }

        const id =
          message.key.id;

        if (seen.has(id) || !claimMessage(id)) {
          continue;
        }

        seen.add(id);

        if (seen.size > 5000) {
          seen.delete(
            seen.values().next().value
          );
        }

        if (message.key.fromMe && tracking.isBotMessage(message.key)) continue;

        let ticket;

        try {
          const routingText =
            hasAudio && !text
              ? 'Jessyca'
              : text;

          ticket = route(
            sock,
            message,
            routingText
          );

          recordIncoming(message, text, hasAudio ? 'audio' : hasImage ? 'imagen' : hasOtherMedia ? 'otro' : 'texto');
          if (message.key.fromMe) recordStatuses();
        } catch (error) {
          console.error(
            'No se pudo guardar el estado:',
            error.message
          );
          process.exit(1);
        }

        if (ticket.kind === 'control') {
          console.log(
            'Control del propietario recibido en su chat personal.'
          );

          sock.sendMessage(
            jid,
            {
              text:
                ticket.reply
            }
          ).catch(() =>
            console.log(
              'No se pudo confirmar el comando.'
            )
          );

          continue;
        }

        if (ticket.kind !== 'answer') {
          continue;
        }

        // Saludo inicial sin buffer, cola global ni llamada al modelo.
        if (!hasImage && !hasAudio && !hasOtherMedia) {
          try {
            if (await fastWelcome(sock, jid, text, ticket)) continue;
          } catch (error) {
            console.error('No se pudo enviar el saludo rápido.');
            // Sigue el flujo existente como respaldo ante fallo de envío.
          }
        }

        if (hasAudio) {
          flushMessageBuffer(
            sock,
            jid
          );

          console.log(
            `Nota de voz recibida de ${jid}.`
          );

          queueAudioAnswer(
            sock,
            jid,
            message,
            ticket
          );

          continue;
        }

        if (hasImage) {
          flushMessageBuffer(
            sock,
            jid
          );

          queueVisionAnswer(
            sock,
            jid,
            message,
            text,
            ticket
          );

          continue;
        }

        bufferMessage(
          sock,
          jid,
          message,
          text,
          ticket
        );
      }
    }
  );
}


connect().catch(() => {
  console.error(
    'No se pudo iniciar la conexión con WhatsApp.'
  );
  process.exit(1);
});
