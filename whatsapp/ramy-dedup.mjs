import { readFileSync, writeFileSync, renameSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

// El ID de WhatsApp es estable aunque el mismo contacto llegue por PN o LID.
// Se reclama antes de encolar: impide dos respuestas al mismo ID incluso tras reinicio.
export function createDedup(file = join(homedir(), '.ramy-whatsapp-seen-v2.json'), now = () => Date.now()) {
  let data = {};
  try { data = JSON.parse(readFileSync(file, 'utf8')); }
  catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Registro de mensajes inválido');
  return function claim(id) {
    if (typeof id !== 'string' || !id) return false;
    const t = now();
    data = Object.fromEntries(Object.entries(data).filter(([, v]) => typeof v === 'number' && t - v < 7 * 86400000).slice(-19999));
    if (Object.hasOwn(data, id)) return false;
    data[id] = t;
    writeFileSync(file + '.tmp', JSON.stringify(data), { mode: 0o600 });
    renameSync(file + '.tmp', file);
    return true;
  };
}
let claim;
export function claimMessage(id) {
  claim ??= createDedup();
  return claim(id);
}
