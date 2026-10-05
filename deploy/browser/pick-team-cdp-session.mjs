// Fixed-stage, read-only CDP transport. Never accepts arbitrary JS or account writes.
import fs from 'node:fs';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';

export const STAGES = new Set(['navigate','page_gate','base','open_sheet','sheet_state','close_sheet','sheet_closed','verify','diagnose']);
const SAFE = new Set(['FPL_AUTH_REQUIRED','FPL_PRIVATE_API_ERROR','FPL_BOOTSTRAP_API_ERROR',
  'FPL_PICK_TEAM_PAGE_REQUIRED','FPL_AUTH_OR_ORIGIN_REQUIRED','FPL_STARTER_INDEX_INVALID',
  'FPL_PLAYER_CONTROLS_CHANGED','FPL_CAPTAIN_CHECKBOX_MISSING',
  'FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS','FPL_PLAYER_SHEET_DID_NOT_CLOSE',
  'FPL_TEAM_CHANGED_DURING_PROBE','FPL_PROBE_STAGE_INVALID','FPL_PROBE_CDP_TIMEOUT',
  'FPL_PROBE_CDP_FAILED','FPL_PROBE_NAVIGATION_CONTEXT_LOST','FPL_PROBE_TARGET_AMBIGUOUS',
  'FPL_PROBE_DIALOG_BLOCKED','FPL_PROBE_CLOCK_EXPIRED','FPL_PROBE_RESPONSE_INVALID']);
export function safeCode(error) { return SAFE.has(error?.message) ? error.message : 'FPL_PROBE_CDP_FAILED'; }
const failed = code => { throw new Error(code); };
export function selectTarget(targets) {
  const pages=targets.filter(t=>{try{return t.type==='page'&&new URL(t.url).origin==='https://fantasy.premierleague.com';}catch{return false;}});
  if(pages.length!==1) failed('FPL_PROBE_TARGET_AMBIGUOUS');
  return pages[0].targetId;
}

export async function connect(port, { fetcher=fetch, Socket=WebSocket, clock=()=>performance.now() }={}) {
  const deadline=clock()+90000;
  const response=await fetcher(`http://127.0.0.1:${port}/json/version`,{signal:AbortSignal.timeout(5000)});
  const version=await response.json();
  const url=new URL(version.webSocketDebuggerUrl);
  if(url.protocol!=='ws:' || !['127.0.0.1','localhost'].includes(url.hostname) || Number(url.port)!==port) failed('FPL_PROBE_CDP_FAILED');
  const ws=new Socket(url.href); const pending=new Map();let id=0, dialog=false, closed=false;
  const abandon=()=>{closed=true;for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('FPL_PROBE_CDP_FAILED'));}pending.clear();};
  ws.addEventListener('close',abandon);ws.addEventListener('error',abandon);
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('FPL_PROBE_CDP_TIMEOUT')),5000);
    ws.addEventListener('open',()=>{clearTimeout(timer);resolve();},{once:true});
    ws.addEventListener('error',()=>{clearTimeout(timer);reject(new Error('FPL_PROBE_CDP_FAILED'));},{once:true});
  });
  ws.addEventListener('message',event=>{
    let data;try{data=JSON.parse(event.data);}catch{return;}
    if(data.method==='Page.javascriptDialogOpening')dialog=true;
    if(data.method==='Page.javascriptDialogClosed')dialog=false;
    const p=pending.get(data.id);if(!p)return;pending.delete(data.id);clearTimeout(p.timer);
    if(data.error){
      const contextLost=/Inspected target navigated or closed|Cannot find context/.test(data.error.message||'');
      p.reject(new Error(contextLost?'FPL_PROBE_NAVIGATION_CONTEXT_LOST':'FPL_PROBE_CDP_FAILED'));
    }else p.resolve(data.result);
  });
  const call=(method,params={},sessionId,cap=25000)=>new Promise((resolve,reject)=>{
    if(closed)return reject(new Error('FPL_PROBE_CDP_FAILED'));
    const remaining=deadline-clock();if(remaining<1000)return reject(new Error('FPL_PROBE_CLOCK_EXPIRED'));
    const key=++id;const timer=setTimeout(()=>{pending.delete(key);reject(new Error(dialog?'FPL_PROBE_DIALOG_BLOCKED':'FPL_PROBE_CDP_TIMEOUT'));},Math.min(25000,cap,remaining));
    pending.set(key,{resolve,reject,timer});
    ws.send(JSON.stringify({id:key,method,params,...(sessionId?{sessionId}:{})}));
  });
  const close=()=>{abandon();ws.close();};
  try{
    const target=selectTarget((await call('Target.getTargets')).targetInfos);
    const session=(await call('Target.attachToTarget',{targetId:target,flatten:true})).sessionId;
    await call('Page.enable',{},session);
    return {close, async evaluate(expression,cap){
      if(dialog)failed('FPL_PROBE_DIALOG_BLOCKED');
      const result=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},session,cap);
      if(result.exceptionDetails){
        const match=(result.exceptionDetails.exception?.description||'').match(/\bFPL_[A-Z_]+\b/);
        failed(match&&SAFE.has(match[0])?match[0]:'FPL_PROBE_CDP_FAILED');
      }
      if(!result.result || !Object.hasOwn(result.result,'value'))failed('FPL_PROBE_RESPONSE_INVALID');
      return result.result.value;
    }};
  }catch(error){close();throw error;}
}

async function main(){
  const [teamText,portText]=process.argv.slice(2);const team=Number(teamText),port=Number(portText);
  if(!Number.isSafeInteger(team)||team<1||!Number.isInteger(port)||port<1||port>65535)failed('FPL_PROBE_RESPONSE_INVALID');
  const template=fs.readFileSync(new URL('./pick-team-dom-probe.js',import.meta.url),'utf8');
  const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});let browser;
  try{
    for await(const line of lines){
      try{
        if(Buffer.byteLength(line)>1048576)failed('FPL_PROBE_RESPONSE_INVALID');
        const request=JSON.parse(line);
        if(!STAGES.has(request.stage))failed('FPL_PROBE_STAGE_INVALID');
        if(!request.expected||typeof request.expected!=='object'||Array.isArray(request.expected)
            ||!Number.isFinite(request.cap_ms)||request.cap_ms<1000||request.cap_ms>25000)failed('FPL_PROBE_RESPONSE_INVALID');
        browser ||= await connect(port);
        const expression=template.replaceAll('__MOVA_TEAM_ID__',String(team))
          .replaceAll('__MOVA_PROBE_STAGE__',JSON.stringify(request.stage))
          .replaceAll('__MOVA_PROBE_EXPECTED__',JSON.stringify(request.expected));
        const payload=await browser.evaluate(expression,request.cap_ms);
        process.stdout.write(JSON.stringify({ok:true,payload})+'\n');
      }catch(error){process.stdout.write(JSON.stringify({ok:false,error_code:safeCode(error)})+'\n');}
    }
  }finally{browser?.close();lines.close();}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  main().catch(error=>{process.stdout.write(JSON.stringify({ok:false,error_code:safeCode(error)})+'\n');process.exitCode=1;});
}
