import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { chatStatus } from './presence.js';
export function startRamyOrderNotifications(sock, qrPath) {
  let closed=false,busy=false;const delivered=new Set();
  async function call(path,body) {
    const token=readFileSync(join(homedir(),'.config/jessyca-conversaciones.env'),'utf8').split(/\r?\n/).find(x=>x.startsWith('JESSYCA_CONVERSATIONS_TOKEN='))?.split('=').slice(1).join('=').trim();
    if(!token||token.length<32)throw Error('Credencial no disponible');
    const r=await fetch('http://127.0.0.1:8001/ramy/notificaciones'+path,{method:body?'POST':'GET',headers:{'X-Conversations-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(20000)});
    if(!r.ok)throw Error('Aviso no disponible');return r.json();
  }
  async function tick() {
    if(closed||busy)return;busy=true;
    try {
      const {events}=await call('');
      for(const item of events||[]) {
        if(closed)break;
        if(delivered.has(item.id)){await call('/confirmar-envio',{id:item.id});continue;}
        const {event}=await call('/validar',{id:item.id});
        if(closed||!event||!chatStatus(event.jid).active)continue;
        const content=event.payment_qr?{image:{url:qrPath},caption:event.text}:{text:event.text};
        await sock.sendMessage(event.jid,content,{messageId:event.id.slice(0,32).toUpperCase()});
        delivered.add(event.id);
        await call('/confirmar-envio',{id:event.id});
        console.log('RAMY_AVISO_PEDIDO enviado y registrado.');
      }
    } catch {console.error('RAMY_AVISO_PEDIDO pendiente; se reintentará.');}
    finally {busy=false;}
  }
  const timer=setInterval(tick,5000);timer.unref();void tick();
  return ()=>{closed=true;clearInterval(timer);};
}
