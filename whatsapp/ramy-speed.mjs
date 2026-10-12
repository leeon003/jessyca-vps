// Orden por contacto; solo la inferencia lenta comparte una plaza.
export function createChatQueue(onError=()=>{}) {
  const queues=new Map();
  return function enqueue(key,task) {
    const old=queues.get(key)||Promise.resolve();
    const next=old.then(task).catch(error=>onError(error));
    queues.set(key,next);
    void next.finally(()=>{if(queues.get(key)===next)queues.delete(key);});
    return next;
  };
}
export function createInferenceGate() {
  let tail=Promise.resolve();
  return function run(task,allowed=()=>true) {
    const next=tail.then(()=>{if(!allowed())throw Error('Consulta pausada antes de generar');return task();});
    tail=next.then(()=>undefined,()=>undefined);return next;
  };
}
const inference=createInferenceGate();
export async function ramyInferenceFetch(url,options,allowed=()=>true) {
  if(!allowed())throw Error('Chat pausado');
  if(url.endsWith('/vision')) {
    const payload=JSON.parse(options.body);
    const r=await fetch('http://127.0.0.1:8001/ramy/receipt-status?chat_id='+encodeURIComponent(payload.chat_id),{signal:AbortSignal.timeout(8000)});
    if(!r.ok)throw Error('No se pudo comprobar si la imagen es un comprobante');
    const state=await r.json();
    if(state.expects_receipt===true) {
      if(!allowed())throw Error('Chat pausado');
      return fetch(url,{...options,signal:AbortSignal.timeout(30000)});
    }
  }
  return inference(()=>fetch(url,{...options,signal:AbortSignal.timeout(url.endsWith('/audio')?240000:90000)}),allowed);
}
export async function ramyTextRequest(payload,allowed=()=>true) {
  if(!allowed())throw Error('Chat pausado');
  const start=Date.now();
  const options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)};
  const fast=await fetch('http://127.0.0.1:8001/ramy/fast-text',{...options,signal:AbortSignal.timeout(15000)});
  if(!fast.ok)throw Error('Vía rápida HTTP '+fast.status);
  const result=await fast.json();
  if(result.needs_ai!==true) {
    if(typeof result.reply!=='string'||!result.reply.trim())throw Error('Respuesta rápida vacía');
    console.log('[RAMY_RAPIDEZ] respuesta directa en '+(Date.now()-start)+' ms');
    return result;
  }
  const slow=await inference(()=>fetch('http://127.0.0.1:8001/chat',{...options,signal:AbortSignal.timeout(90000)}),allowed);
  if(!slow.ok)throw Error('IA HTTP '+slow.status);
  return slow.json();
}
