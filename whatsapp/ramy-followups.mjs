import {readFileSync,writeFileSync,renameSync,mkdirSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {homedir} from 'node:os';
import {createHash} from 'node:crypto';
import {chatStatus} from './presence.js';
const normalized=t=>String(t||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const optout=/\b(no me escribas|no me escriban|no me contactes|no contactar|deja de escribirme|no vuelvas a escribirme|no quiero recibir mensajes|no insistas|no me mandes mensajes|no me envies mensajes|no quiero que me escribas)\b/;
const defer=/\b(yo te aviso|te aviso luego|lo pensare|lo voy a pensar|no deseo|ya no quiero|cancelar|por ahora no|no gracias|no me interesa|no estoy interesado|ya no deseo|no quiero comprar)\b/;
const buying=/\b(quiero comprar|deseo comprar|nueva compra|quiero pedir)\b/;
export function createStore(file,clock=Date.now){
 let data={chats:{},jobs:{}},healthy=true;
 try{data=JSON.parse(readFileSync(file,'utf8'));if(!data.chats||!data.jobs)throw Error('Registro inválido');}catch(e){if(e.code!=='ENOENT')throw e;}
 const save=()=>{try{mkdirSync(dirname(file),{recursive:true,mode:0o700});writeFileSync(file+'.tmp',JSON.stringify(data),{mode:0o600});renameSync(file+'.tmp',file);}catch(e){healthy=false;throw e;}};
 return {
  healthy:()=>healthy,
  receive(chat,jid,keys,id,text,manual=false){
   const previous=data.chats[chat]||{},n=normalized(text);if(previous.episode===id)return;
   if(manual){if(data.chats[chat]){previous.manual=true;save();}return;}
   data.chats[chat]={chat,jid,keys,episode:id,customer:clock()/1000,reply:null,manual:false,no_contact:previous.no_contact||optout.test(n),deferred:defer.test(n)||(previous.deferred&&!buying.test(n))};save();
  },
  reply(chat){const s=data.chats[chat];if(!s)return;s.reply=clock()/1000;s.manual=false;save();},
  rows:()=>healthy?Object.values(data.chats).filter(s=>s.reply&&s.reply>=s.customer&&!s.manual&&!s.no_contact&&!s.deferred):[],
  current:(chat,episode)=>healthy&&data.chats[chat]?.episode===episode&&!data.chats[chat].manual&&!data.chats[chat].no_contact&&!data.chats[chat].deferred,
  phases(chat,episode){return Object.values(data.jobs).filter(j=>j.chat===chat&&j.episode===episode&&['sending','sent','uncertain'].includes(j.state)).map(j=>j.phase);},
  claim(id,row,phase){if(!healthy||data.jobs[id])return false;data.jobs[id]={chat:row.chat,episode:row.episode,phase,state:'sending',at:clock()};save();return true;},
  finish(id,state){data.jobs[id].state=state;save();},
  recover(){let changed=false;for(const j of Object.values(data.jobs))if(j.state==='sending'){j.state='uncertain';changed=true;}if(changed)save();},
  state:()=>JSON.parse(JSON.stringify(data))
 };
}
let store;
const ledger=()=>store||(store=createStore(join(homedir(),'.jessyca-followups','state.json')));
function identity(jid,alt){const status=chatStatus(jid,alt);const phone=status.keys.find(k=>/^519\d{8}@s\.whatsapp\.net$/.test(k));return phone?{chat:'whatsapp:'+phone,jid,keys:status.keys}:null;}
export function rememberFollowupIncoming(message,text){
 const key=message.key||{},v=identity(key.remoteJid,key.remoteJidAlt);if(!v)return;
 const timestamp=Number(message.messageTimestamp)*1000;if(!key.fromMe&&(!Number.isFinite(timestamp)||Math.abs(Date.now()-timestamp)>15*60000))return;
 try{ledger().receive(v.chat,v.jid,v.keys,key.id,text,key.fromMe===true);}catch{console.error('RAMY_SEGUIMIENTO registro no disponible; envíos suspendidos.');}
}
export function rememberFollowupReply(jid,human=false){const v=identity(jid);if(!v)return;try{if(human)ledger().receive(v.chat,jid,v.keys,'manual','',true);else ledger().reply(v.chat);}catch{console.error('RAMY_SEGUIMIENTO registro no disponible; envíos suspendidos.');}}
export function followupGuard(chat,episode,jid){return ledger().current(chat,episode)&&chatStatus(jid).active;}
export function startRamyFollowups(sock,options={}){
 let storage;try{storage=options.store||ledger();storage.recover();}catch{console.error('RAMY_SEGUIMIENTO deshabilitado por error del registro; ventas continúan.');return ()=>{};}
 const active=options.active||chatStatus,clock=options.clock||Date.now;
 const guard=row=>storage.current(row.chat,row.episode)&&active(row.jid).active;
 let stopped=false,busy=false,cursor=0;
 async function evaluate(row){
  if(options.evaluate)return options.evaluate(row);
  const token=readFileSync(join(homedir(),'.config/jessyca-conversaciones.env'),'utf8').split(/\r?\n/).find(x=>x.startsWith('JESSYCA_CONVERSATIONS_TOKEN='))?.split('=').slice(1).join('=').trim();if(!token||token.length<32)throw Error('Credencial no disponible');
  const response=await fetch('http://127.0.0.1:8001/ramy/seguimiento/evaluar',{method:'POST',headers:{'Content-Type':'application/json','X-Conversations-Token':token},body:JSON.stringify({chat_id:row.chat,episode:row.episode,last_customer_at:row.customer,last_reply_at:row.reply,sent_phases:storage.phases(row.chat,row.episode)}),signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw Error('Evaluación no disponible');return (await response.json()).event;
 }
 async function tick(){
  if(stopped||busy||!storage.healthy())return;busy=true;
  try{
   const rows=storage.rows(),batch=rows.length?Array.from({length:Math.min(30,rows.length)},(_,i)=>rows[(cursor+i)%rows.length]):[];cursor=rows.length?(cursor+batch.length)%rows.length:0;
   for(const row of batch){
    if(clock()/1000-row.reply<4*3600)continue;
    if(stopped)break;if(!guard(row))continue;
    const event=await evaluate(row);if(!event||!/^([a-f0-9]{64})$/.test(event.id)||typeof event.text!=='string'||event.text.length>1000||stopped||!guard(row))continue;
    // Eligibility checked again immediately before claiming a durable send.
    const fresh=await evaluate(row);if(!fresh||fresh.id!==event.id||stopped||!guard(row))continue;
    if(!storage.claim(event.id,row,event.phase))continue;
    try{
     await sock.sendMessage(row.jid,{text:event.text},{messageId:event.id.slice(0,32).toUpperCase(),ramyFollowup:true,ramyFollowupGuard:()=>!stopped&&guard(row)&&clock()/1000<(fresh.valid_until||0)});
     storage.finish(event.id,'sent');console.log('RAMY_SEGUIMIENTO enviado fase='+event.phase);
    }catch{storage.finish(event.id,'uncertain');console.error('RAMY_SEGUIMIENTO envío incierto; no se repetirá automáticamente.');}
   }
  }catch{console.error('RAMY_SEGUIMIENTO evaluación pendiente; no se enviaron nuevos avisos en ese intento.');}
  finally{busy=false;}
 }
 const timer=setInterval(tick,60000);timer.unref();if(options.autostart!==false)void tick();const stop=()=>{stopped=true;clearInterval(timer);};stop.tick=tick;return stop;
}
