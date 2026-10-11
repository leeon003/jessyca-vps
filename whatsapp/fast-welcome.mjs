export const WELCOME = 'Soy JESSYCA, asesora de ventas de Tiendas RAMY. ¡Hola! 😊\n¿En qué puedo ayudarte hoy con nuestros productos de Tiendas RAMY? 🛍️✨';
export function isGreeting(text) {
  const normalized = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[¡!¿?.,:;\p{Emoji_Presentation}\p{Extended_Pictographic}\uFE0F]/gu, '').trim().replace(/\s+/g, ' ');
  return /^(hola|holi|holis|buenas|buenos dias|buenas tardes|buenas noches)( jessyca)?$/.test(normalized);
}
export function createFastWelcome({stillAllowed, markAnswered}) {
  const pending = new Map();
  return async function fastWelcome(sock, jid, text, ticket) {
    if (!ticket.first || !isGreeting(text)) return false;
    if (!stillAllowed(ticket)) return true;
    const key = ticket.chatId || jid;
    if (pending.has(key)) { await pending.get(key); return true; }
    const started = Date.now();
    const job = (async () => {
      if (!stillAllowed(ticket)) return;
      await sock.sendMessage(jid, {text: WELCOME});
      markAnswered(ticket);
      console.log(`[SALUDO RAPIDO] Envío completado en ${Date.now()-started} ms`);
    })();
    pending.set(key, job);
    try { await job; } finally { if (pending.get(key) === job) pending.delete(key); }
    return true;
  };
}
