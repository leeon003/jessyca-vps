import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

const file = process.env.JESSYCA_PRESENCE_FILE || join(homedir(), '.jessyca-presence.json');
const normalize = jid => typeof jid === 'string' ? jid.replace(/:\d+(?=@)/, '') : '';
const words = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
let state = { mode: 'available', reason: '', revision: randomUUID(), chats: {}, paused: {} };
try {
  state = JSON.parse(readFileSync(file, 'utf8'));
  if (!['available', 'away', 'paused'].includes(state.mode) || !state.revision || !state.chats || !state.paused) throw new Error('Estado inválido');
} catch (error) { if (error.code !== 'ENOENT') throw error; }
state.blocked ??= {};
state.epochs ??= {};
state.aliases ??= {};

function relatedKeys(raw) {
  const keys = new Set(raw);
  for (const key of keys) {
    for (const alias of state.aliases[key] || []) keys.add(alias);
  }
  const all = [...keys];
  for (const key of all) state.aliases[key] = all;
  return all;
}

function save() {
  for (const name of ['chats']) {
    const keys = Object.keys(state[name]);
    for (const key of keys.slice(0, Math.max(0, keys.length - 1000))) delete state[name][key];
  }
  writeFileSync(file + '.tmp', JSON.stringify(state), { mode: 0o600 });
  renameSync(file + '.tmp', file);
}

function command(text) {
  const cmd = words(text).replace(/^jessyca[,:]?\s*/, '').replace(/[.!?]+$/, '').trim();
  if (cmd === 'estado') return `Estado: ${{available: 'disponible', away: 'ausente', paused: 'pausada'}[state.mode]}. ${state.reason || ''}`;
  if (cmd === 'ayuda') return 'Aquí: jessyca estoy durmiendo, estoy ocupado, estoy en clase, estoy manejando, estoy en una reunion, ya volvi, pausa, estado. En el chat de otra persona: /jessyca off para silenciar y /jessyca on para permitir respuestas según tu estado general. Solo acepto controles enviados por ti.';
  const reasons = {
    'estoy durmiendo': 'Diego está descansando.',
    'estoy tomando una siesta': 'Diego está tomando una siesta.',
    'estoy ocupado': 'Diego está ocupado en este momento.',
    'estoy trabajando': 'Diego está trabajando.',
    'estoy en clase': 'Diego está en clase.',
    'estoy manejando': 'Diego está conduciendo.',
    'estoy en una reunion': 'Diego está en una reunión.'
  };
  let mode, reason = '';
  if (reasons[cmd]) { mode = 'away'; reason = reasons[cmd]; }
  else if (cmd === 'ya volvi' || cmd === 'estoy disponible') mode = 'available';
  else if (cmd === 'pausa') mode = 'paused';
  else return 'No cambié el estado. Escribe jessyca ayuda para ver los comandos.';
  state = { ...state, mode, reason, revision: randomUUID(), chats: {}, paused: {} };
  save();
  return mode === 'away' ? `${reason} Atenderé los chats privados mientras estás ausente.` : mode === 'paused' ? 'Respuestas automáticas pausadas.' : 'Ya estás disponible. Atenderé los chats privados habilitados. Usa /jessyca off para silenciar un chat o jessyca pausa para pausar todas las respuestas.';
}

export function route(sock, message, text) {
  const keys = relatedKeys([message.key.remoteJid, message.key.remoteJidAlt].map(normalize).filter(Boolean));
  const own = new Set([sock.user?.id, sock.user?.lid, sock.authState?.creds?.me?.id, sock.authState?.creds?.me?.lid].map(normalize).filter(Boolean));
  const self = keys.some(key => own.has(key));
  if (message.key.fromMe) {
    if (text.startsWith('◆ JESSYCA')) return { kind: 'ignore' };
    if (self) {
      return /^jessyca(?:\s|[,:]|$)/i.test(text) ? { kind: 'control', reply: command(text) } : { kind: 'ignore' };
    }
    const toggle = words(text).match(/^\/jessyca\s+(off|on)$/);
    if (toggle) {
      for (const key of keys) {
        state.epochs[key] = (state.epochs[key] || 0) + 1;
        if (toggle[1] === 'off') state.blocked[key] = true;
        else { delete state.blocked[key]; delete state.paused[key]; }
      }
      save();
      console.log(toggle[1] === 'off' ? 'Chat desactivado por el propietario.' : 'Chat habilitado por el propietario.');
      return { kind: 'ignore' };
    }
    // Un mensaje manual del propietario no pausa automáticamente a JESSYCA.
    // Para silenciar un chat se usa explícitamente /jessyca off.
    return { kind: 'ignore' };
  }
  if (self || state.mode === 'paused' || keys.some(key => state.blocked[key])) return { kind: 'ignore' };
  if (/^\/jessyca\s+(off|on)$/i.test(text.trim())) return { kind: 'ignore' };
  const chat = keys.map(key => state.chats[key]).find(Boolean) || { id: randomUUID(), introduced: false };
  const called = /\bjessyca\b/i.test(text) || /^\/buscar(?:\s|$)/i.test(text);
  // JESSYCA responde automáticamente a chats privados habilitados.
  // /jessyca off sigue bloqueando individualmente cada chat.

  for (const key of keys) state.chats[key] = chat;
  save();
  const intro = !chat.introduced;
  return {
    kind: 'answer', keys, revision: state.revision, chatId: chat.id,
    epochs: Object.fromEntries(keys.map(key => [key, state.epochs[key] || 0])),
    first: intro,
    prefix: intro ? (state.mode === 'away' ? `${state.reason} Soy JESSYCA, su asistente. ` : 'Soy JESSYCA, la asistente de Diego. ') : '',
    context: `Actúas como la asistente de Diego, no como Diego. ${state.reason || 'Diego indicó que está disponible.'} El programa añade tu presentación cuando corresponde: no saludes ni te presentes. Responde al último mensaje de forma concreta. ${intro ? 'No menciones su estado en esta respuesta: el programa ya lo añade.' : 'No repitas el estado de Diego salvo que pregunten por él.'} No prometas avisos ni afirmes que Diego leyó, aceptó o confirmó algo. Los mensajes quedan en este chat para que los lea.`,
  };
}

export function stillAllowed(ticket) {
  const keys = relatedKeys(ticket.keys);
  return ticket.revision === state.revision && state.mode !== 'paused' && !keys.some(key => state.blocked[key] || (state.epochs[key] || 0) !== (ticket.epochs?.[key] || 0));
}

export function markAnswered(ticket) {
  if (!stillAllowed(ticket)) return;
  for (const key of ticket.keys) if (state.chats[key]) state.chats[key].introduced = true;
  save();
}
