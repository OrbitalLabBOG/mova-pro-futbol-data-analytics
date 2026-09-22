// One ephemeral turn per host permit. No hidden replay after interruption.
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';

export async function runMeteredTurn({command='codex', args=[], prompt, model, effort,
    schema, config={}, cwd='/tmp/mova-research', tokenLimit=80000, timeoutMs=240000, preflightOnly=false, requiredTools=[], onEvent=()=>{}}) {
  const child=spawn(command,['app-server',...args],{cwd,
    stdio:['pipe','pipe','pipe'],detached:true});
  const pending=new Map();
  const rejectPending=reason=>{
    for(const waiter of pending.values()){clearTimeout(waiter.timer);waiter.reject(new Error(reason));}
    pending.clear();
  };
  let nextId=1; let threadId,turnId; let inferenceDispatched=false;
  let usage=null, finalText='', stopped=false, failure=null, doneResolve;
  const done=new Promise(resolve=>{doneResolve=resolve;});
  let eventBytes=0;
  const emit=value=>{
    eventBytes+=Buffer.byteLength(JSON.stringify(value));
    if(eventBytes<=16*1024*1024)onEvent(value);
    else if(!stopped)stop('event_output_limit');
  };
  const send=value=>child.stdin.write(JSON.stringify(value)+'\n');
  const request=(method,params)=>new Promise((resolve,reject)=>{
    const id=nextId++;
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('rpc_timeout'));},30000);
    pending.set(id,{resolve,reject,timer});send({id,method,params});
  });
  const stop=reason=>{
    if(stopped)return;
    stopped=true;failure=reason;
    rejectPending(reason);
    emit({type:'meter.stop',reason,observed_usage:usage});
    if(threadId && turnId) request('turn/interrupt',{threadId,turnId}).catch(()=>{});
    setTimeout(()=>doneResolve({status:'interrupted'}),3000).unref();
  };
  const lines=createInterface({input:child.stdout});
  lines.on('line',line=>{
    let event;try{event=JSON.parse(line);}catch{return;}
    // Responses to config/start may contain host paths; persist notifications only.
    if(event.id!==undefined && !event.method){
      const waiter=pending.get(event.id);if(!waiter)return;
      clearTimeout(waiter.timer);pending.delete(event.id);
      event.error?waiter.reject(new Error('rpc_error')):waiter.resolve(event.result);return;
    }
    if(event.id!==undefined && event.method){
      // No interactive permission/user-input flow is authorized in this worker.
      send({id:event.id,error:{code:-32601,message:'interactive_request_not_allowed'}});
      stop('unexpected_interactive_request');return;
    }
    emit(event);
    const p=event.params||{};
    if(event.method==='turn/started')turnId=p.turn?.id||turnId;
    if(event.method==='thread/tokenUsage/updated'){
      const total=p.tokenUsage?.total;
      if(total && Number.isFinite(total.inputTokens) && Number.isFinite(total.outputTokens)){
        usage={input_tokens:total.inputTokens,output_tokens:total.outputTokens,
          cached_input_tokens:total.cachedInputTokens};
        emit({type:'meter.usage',usage});
        if(usage.input_tokens+usage.output_tokens>=tokenLimit)stop('logical_token_guard');
      }
    }
    if(event.method==='item/completed' && p.item?.type==='agentMessage'
        && p.item.phase!=='commentary') finalText=p.item.text||finalText;
    if(event.method==='turn/completed')doneResolve(p.turn||{status:'failed'});
  });
  // Drain stderr without persisting arbitrary credential/provider diagnostics.
  child.stderr.on('data',()=>{});
  child.on('error',()=>{failure='app_server_spawn_failed';rejectPending(failure);doneResolve({status:'failed'});});
  child.stdin.on('error',()=>{failure ||= 'app_server_pipe_failed';rejectPending(failure);doneResolve({status:'failed'});});
  child.on('exit',()=>{failure ||= 'app_server_exited';rejectPending(failure);doneResolve({status:'failed'});});
  const timeout=setTimeout(()=>stop('app_server_timeout'),timeoutMs);
  let result;
  try{
    await request('initialize',{clientInfo:{name:'mova-research',version:'1.2.0'},
      capabilities:{experimentalApi:true}});
    send({method:'initialized',params:{}});
    const thread=await request('thread/start',{ephemeral:true,cwd,
      model,approvalPolicy:'never',sandbox:'read-only',config:{
        ...config,project_doc_max_bytes:0,'skills.bundled.enabled':false,
        'skills.include_instructions':false,'web_search':'disabled'}});
    threadId=thread.thread.id;
    let inventory;
    if(preflightOnly || requiredTools.length){
      inventory=await request('mcpServerStatus/list',{threadId});
      const available=new Set((inventory.data||[]).filter(s=>s.name==='mova_evidence').flatMap(s=>Object.keys(s.tools||{})));
      if(requiredTools.some(name=>!available.has(name))){failure='required_tools_unavailable';throw new Error(failure);}
    }
    if(preflightOnly){
      finalText=JSON.stringify({inference_dispatched:false,servers:(inventory.data||[]).map(s=>({
        name:s.name,tools:Object.keys(s.tools||{})}))});
      usage={input_tokens:0,output_tokens:0};result={status:'completed'};
    }else{
      inferenceDispatched=true;
      const turn=await request('turn/start',{threadId,model,effort,
        input:[{type:'text',text:prompt,text_elements:[]}],outputSchema:schema});
      turnId=turn.turn.id;
      result=await done;
    }
  }catch{failure ||= 'app_server_protocol_failed';result={status:'failed'};}
  finally{
    clearTimeout(timeout);
    for(const waiter of pending.values()){clearTimeout(waiter.timer);waiter.reject(new Error('closed'));}
    pending.clear();child.stdin.end();lines.close();
    try{process.kill(-child.pid,'SIGTERM');}catch{}
  }
  const success=!failure && result.status==='completed' && finalText;
  // Canceled in-flight inference has uncertain usage. Preserve observed usage in
  // telemetry, but return null accounting so the host retains its conservative charge.
  return {status:success?0:1,stdout:'',text:success?finalText:null,
    error_code:success?null:failure||'app_server_turn_failed',
    usage:success && usage?usage:!inferenceDispatched?{input_tokens:0,output_tokens:0}:{input_tokens:null,output_tokens:null},observed_usage:usage};
}
