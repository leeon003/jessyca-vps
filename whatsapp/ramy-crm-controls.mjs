import {mkdirSync,readFileSync,writeFileSync,renameSync,readdirSync,unlinkSync} from 'node:fs';
import {homedir} from 'node:os';import {join} from 'node:path';
import {chatStatus,setChatActive} from './presence.js';
import {recordStatuses,setControlBarrier} from './crm-conversations.js';
const root=join(homedir(),'.jessyca-crm-controls');mkdirSync(root,{recursive:true,mode:0o700});
function persist(id,data){const p=join(root,id+'.json');writeFileSync(p+'.tmp',JSON.stringify(data),{mode:0o600});renameSync(p+'.tmp',p);}
function token(){return process.env.JESSYCA_CONVERSATIONS_TOKEN||readFileSync(join(homedir(),'.config/jessyca-conversaciones.env'),'utf8').split(/\r?\n/).find(s=>s.startsWith('JESSYCA_CONVERSATIONS_TOKEN='))?.split('=').slice(1).join('=').trim();}
async function api(data){
 const credential=token();if(!credential||credential.length<32)throw Error('Credencial no configurada');
 const r=await fetch('http://127.0.0.1:8000/api/interno/conversaciones-control',{method:'POST',headers:{'Content-Type':'application/json','X-Conversations-Token':credential},body:JSON.stringify(data),signal:AbortSignal.timeout(4000)});
 if(!r.ok)throw Error('Control no disponible');return r.json();
}
export function startCRMControls(sock){
 let closed=false,running=null;
 const own=new Set([sock.user?.id,sock.user?.lid].filter(Boolean).map(s=>s.replace(/:\d+(?=@)/,'')));
 async function sync(){
  if(closed)throw Error('Conector desconectado');
  if(running)return running;
  running=(async()=>{
   for(const name of readdirSync(root).filter(n=>/^\d+\.json$/.test(n))){
    const p=join(root,name);let record=JSON.parse(readFileSync(p,'utf8'));
    if(record.estado==='INICIANDO')record={modo:'confirmar',id:record.id,estado:'INCIERTO',detalle:'Envío interrumpido: revisa WhatsApp; no se reenvía automáticamente',fecha:new Date().toISOString()};
    await api(record);unlinkSync(p);
   }
   for(let i=0;i<4;i++){
    if(closed)return;
    const {operacion:o}=await api({modo:'tomar'});if(!o)return;
    let result={modo:'confirmar',id:o.id,estado:'ERROR',detalle:'No se pudo aplicar la operación',fecha:new Date().toISOString()};
    if(!Array.isArray(o.keys)||!o.keys.length||o.keys.some(k=>!/^[0-9]{5,30}@(s\.whatsapp\.net|lid)$/.test(k))||o.keys.some(k=>own.has(k))){result.detalle='Destino de WhatsApp inválido o cuenta propia';}
    else if(o.accion==='PAUSAR'||o.accion==='REACTIVAR'){
     try{const actual=setChatActive(o.keys,o.accion==='REACTIVAR');recordStatuses();result={...result,estado:'APLICADO',activa:actual.active,detalle:o.accion==='REACTIVAR'&&!actual.active?'Continúa pausada por el estado general':''};}
     catch{result.detalle='No se pudo guardar el estado de pausa';}
    }else if(o.accion==='ENVIAR'){
     const jid=o.keys.find(k=>k.endsWith('@s.whatsapp.net'))||o.keys[0];
     if(chatStatus(jid).active)result.detalle='Jessyca está activa: pausa este chat antes de enviar';
     else if(typeof o.texto!=='string'||!o.texto.trim()||o.texto.length>4000||!/^[A-Za-z0-9_-]{4,180}$/.test(o.message_id||''))result.detalle='Mensaje inválido';
     else{
      persist(o.id,{id:o.id,estado:'INICIANDO'});
      try{
       if(closed)throw Error('Conector desconectado');
       const sent=await sock.sendMessage(jid,{text:o.texto},{messageId:o.message_id,ramyHuman:true});
       const mid=sent?.key?.id||o.message_id;
       result={...result,estado:'ENVIADO',whatsapp_id:mid,detalle:'Enviado desde el WhatsApp del negocio',fecha:new Date().toISOString()};
      }catch{result={...result,estado:'INCIERTO',detalle:'No se confirmó el envío. Revisa WhatsApp antes de repetir'};}
     }
    }
    persist(o.id,result);await api(result);unlinkSync(join(root,o.id+'.json'));
   }
  })();
  try{return await running;}finally{running=null;}
 }
 setControlBarrier(sync);
 const timer=setInterval(()=>{void sync().catch(()=>console.error('RAMY_CONTROL_CRM pendiente; se reintentará.'));},1000);timer.unref();
 void sync().catch(()=>console.error('RAMY_CONTROL_CRM esperando conexión con CRM.'));
 return ()=>{closed=true;clearInterval(timer);};
}
