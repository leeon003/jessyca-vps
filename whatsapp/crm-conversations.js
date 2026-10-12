// Registro local duradero: no contiene credenciales de WhatsApp ni bloquea respuestas.
import { mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync, unlinkSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { chatStatus, allChatStatuses } from './presence.js';
const root = join(homedir(), '.jessyca-crm-outbox');
mkdirSync(root, { recursive: true, mode: 0o700 });
const idsFile = join(root, 'bot-ids.json');
let ids = {};
try { ids = JSON.parse(readFileSync(idsFile, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
const norm = jid => (jid || '').replace(/:\d+(?=@)/, '');
const digest = value => createHash('sha256').update(value).digest('hex');
function saveIds() {
  const entries = Object.entries(ids).sort((a,b) => b[1]-a[1]).slice(0,20000);
  ids = Object.fromEntries(entries);
  writeFileSync(idsFile+'.tmp', JSON.stringify(ids), { mode: 0o600 });
  renameSync(idsFile+'.tmp',idsFile);
}
export function isBotMessage(key) { return Boolean(ids[key?.id]); }
function enqueue(data) {
  try {
    const path = join(root, digest(data.event_id)+'.json');
    if (existsSync(path)) {
      const previous=JSON.parse(readFileSync(path,'utf8'));
      if (previous.text || !data.text) return;
    }
    if (readdirSync(root).filter(n => /^[a-f0-9]{64}\.json$/.test(n)).length >= 10000) {
      console.error('CRM: cola llena; este evento no pudo registrarse.'); return;
    }
    writeFileSync(path+'.tmp', JSON.stringify(data), { mode: 0o600 });
    renameSync(path+'.tmp',path);
  } catch { console.error('CRM: no se pudo guardar un evento en disco.'); }
}
function event(jid, alt, id, sender, text, type, timestamp, name='') {
  const status=chatStatus(jid,alt);
  return { event_id: digest(id), message_id: id.slice(0,180),
    keys: status.keys, active: status.active, sender, text: (text||'').slice(0,12000),
    type, timestamp: timestamp || new Date().toISOString(), name: name.slice(0,180), state_only:false };
}
export function recordIncoming(message, text, type) {
  let timestamp;
  const seconds=Number(message.messageTimestamp);
  if (Number.isFinite(seconds) && seconds>0 && seconds<8640000000000) timestamp=new Date(seconds*1000).toISOString();
  enqueue(event(message.key.remoteJid,message.key.remoteJidAlt,message.key.id,
    message.key.fromMe?'propietario':'cliente',text,type,timestamp,message.key.fromMe?'':message.pushName||''));
}
export function recordStatuses() {
  for (const status of allChatStatuses()) enqueue({ ...status, event_id:randomUUID(),
    message_id:'estado', sender:'propietario',text:'',type:'texto',timestamp:new Date().toISOString(),name:'',state_only:true });
}
let busy=false, retryAt=0, failures=0;
async function flush() {
  if (busy || Date.now()<retryAt) return;
  busy=true;
  try {
    const token=process.env.JESSYCA_CONVERSATIONS_TOKEN;
    if (!token || token.length<32) return;
    const names=readdirSync(root).filter(n => /^[a-f0-9]{64}\.json$/.test(n))
      .map(name => ({name, timestamp:JSON.parse(readFileSync(join(root,name),'utf8')).timestamp}))
      .sort((a,b)=>a.timestamp.localeCompare(b.timestamp)).slice(0,100).map(item=>item.name);
    for (const name of names) {
      const path=join(root,name);
      const response=await fetch('http://127.0.0.1:8000/api/interno/conversaciones', {
        method:'POST', headers:{'content-type':'application/json','x-conversations-token':token},
        body:readFileSync(path,'utf8'), signal:AbortSignal.timeout(4000)
      });
      if (!response.ok) throw new Error('Registro no disponible');
      unlinkSync(path); failures=0;
    }
  } catch { failures++; retryAt=Date.now()+Math.min(60000,1000*2**Math.min(failures,6));
    console.error('CRM: registro pendiente; se reintentará sin interrumpir WhatsApp.');
  } finally { busy=false; }
}
setInterval(flush,2000).unref();
let beforeBotSend=async()=>{};
export function setControlBarrier(fn){beforeBotSend=fn;}

export function installConversationTracking(sock, generateId) {
  const send=sock.sendMessage.bind(sock);
  sock.sendMessage=async (jid,content,options={}) => {
    const human=options.ramyHuman===true;
    const self=[sock.user?.id,sock.user?.lid].filter(Boolean).some(key=>norm(key)===norm(jid));
    if(!human&&!self){await beforeBotSend(jid);if(!chatStatus(jid).active)throw Error('Chat pausado: respuesta automática cancelada');}
    const cleanOptions={...options};delete cleanOptions.ramyHuman;
    const id=options.messageId || generateId(sock.user?.id);
    // Persistir antes de enviar: también reconoce ecos tras reinicios.
    ids[id]=Date.now();
    try { saveIds(); } catch { console.error('CRM: identificador del bot guardado solo en memoria por un error de disco.'); }
    const sent=await send(jid,content,{...cleanOptions,messageId:id});
    enqueue(event(jid,undefined,sent?.key?.id||id,human?'propietario':'jessyca',content.text||content.caption||'', 'texto'));
    return sent;
  };
  recordStatuses();
  return {isBotMessage};
}

export function recordProgress(jid, ticket, progress) {
  const status=chatStatus(jid);
  enqueue({event_id:randomUUID(),message_id:'seguimiento',keys:ticket.keys || status.keys,
    active:status.active,sender:'jessyca',text:'',type:'texto',timestamp:new Date().toISOString(),name:'',state_only:true,progress});
}
