"""Bounded serial sessions must retain exact accounting and honest incomplete coverage."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_club_sessions_reset_context_but_share_budget_and_reject_foreign_output():
    script=r'''
import assert from 'node:assert/strict';
import {runClubSessions} from './deploy/research/research-club-sessions.mjs';
const request={request_sha256:'sealed',research_run_id:'run',cycle_id:'cycle',requested_at:'2026-10-16',
 agent_release:{coverage_allocation:'club_work_queue_v1'},guardrails:{no_team_changes:true},scope_policy:{max_documents:16},
 manifest:{deadline_at:'2026-10-17',research_summary:{focus:[{element:1,team:'A',player_name:'One'},
 {element:2,team:'B',player_name:'Two'}]}}};
const events=[],contexts=[],limits=[];let calls=0;
const runTurn=async options=>{
 const context=JSON.parse(options.prompt.split('REQUEST_JSON:\n')[1]);
 assert.equal(context.focus.length,1);assert.equal(context.guardrails.no_team_changes,true);
 assert.equal(options.schema.properties.documents.minItems,0);limits.push(options.tokenLimit);calls++;
 return {status:0,usage:{input_tokens:70000,output_tokens:1000},text:JSON.stringify({documents:[],signals:[],conflicts:[],
  limitations:['no source'],coverage:{subjects:[{player_element:context.focus[0].element,status:'not_checked',source_urls:[],note:'unavailable'}]}})};
};
const options={schema:{properties:{documents:{minItems:1}}},tokenLimit:210000,timeoutMs:300000,onEvent:e=>events.push(e)};
const result=await runClubSessions(options,request,{runTurn,onContext:(i,c)=>contexts.push(c)});
assert.equal(result.status,0);assert.equal(calls,2);assert.deepEqual(limits,[150000,119000]);
assert.deepEqual(result.usage,{input_tokens:140000,output_tokens:2000});
assert.equal(JSON.parse(result.text).coverage.subjects.length,2);assert.equal(contexts.length,2);
assert.notEqual(contexts[0].context_sha256,contexts[1].context_sha256);
assert.equal(options.schema.properties.documents.minItems,1);
// Remaining budget reserves closure instead of dispatching an impossible second session.
calls=0;const partial=await runClubSessions({...options,tokenLimit:130000},request,{runTurn});
assert.equal(calls,1);assert.equal(JSON.parse(partial.text).coverage.subjects[1].status,'not_checked');
assert.ok(JSON.parse(partial.text).limitations.includes('shared_budget_or_time_reserved'));
calls=0;const resumed=await runClubSessions(options,request,{runTurn,attemptedClubs:['A']});
assert.equal(calls,1);assert.equal(JSON.parse(resumed.text).coverage.subjects[0].note,'prior_attempt_not_replayed');
const failed=await runClubSessions(options,request,{runTurn:async()=>({status:1,error_code:'logical_token_guard',usage:{input_tokens:null,output_tokens:null}})});
assert.equal(failed.status,1);assert.equal(failed.text,null);assert.equal(failed.usage.input_tokens,null);
const foreign=await runClubSessions(options,request,{runTurn:async()=>({status:0,usage:{input_tokens:1,output_tokens:1},
 text:JSON.stringify({signals:[],coverage:{subjects:[{player_element:999}]}})})});
assert.equal(foreign.error_code,'club_session_scope_drift');
'''
    subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True)


def test_campaign_revisits_only_independently_unverified_subjects_and_reports_stop():
    script=r'''
import assert from 'node:assert/strict';
import {runClubSessions} from './deploy/research/research-club-sessions.mjs';
const request={request_sha256:'sealed',research_run_id:'run',cycle_id:'cycle',requested_at:'2026-10-16',
 agent_release:{coverage_allocation:'club_work_queue_v1',completion_campaign:{maximum_rounds:2}},guardrails:{},scope_policy:{max_documents:32},
 manifest:{deadline_at:'2026-10-17',research_summary:{focus:[{element:1,team:'A',player_name:'One'},
 {element:2,team:'B',player_name:'Two'}]}}};
const visited=[],progress=[];const verified=new Set();
const runTurn=async options=>{
 const c=JSON.parse(options.prompt.split('REQUEST_JSON:\n')[1]);visited.push([c.assigned_club,c.pass_number]);
 if(c.assigned_club==='A')verified.add(1);
 // The LLM claims coverage for both; only independent checks may stop the loop.
 return {status:0,usage:{input_tokens:1000,output_tokens:50},text:JSON.stringify({documents:[],signals:[],conflicts:[],
 limitations:[],coverage:{subjects:c.focus.map(row=>({player_element:row.element,status:'no_material_news',source_urls:[],note:'claim'}))}})};
};
const result=await runClubSessions({schema:{properties:{documents:{minItems:1}}},tokenLimit:300000,timeoutMs:400000,onEvent:()=>{}},request,
 {runTurn,readVerified:()=>[...verified],onProgress:value=>progress.push(value)});
assert.equal(result.status,0);assert.deepEqual(visited,[['A',1],['B',1],['B',2]]);
const final=progress.at(-1);assert.equal(final.evidence_subjects,1);assert.equal(final.assessed_subjects,2);
assert.equal(final.reason,'source_search_exhausted');assert.equal(final.subjects[1].status,'source_blocked');
assert.equal(final.subjects[1].attempts,2);assert.equal(final.subjects[1].final_acceptance,false);
assert.deepEqual(result.usage,{input_tokens:3000,output_tokens:150});
'''
    subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,check=True)
