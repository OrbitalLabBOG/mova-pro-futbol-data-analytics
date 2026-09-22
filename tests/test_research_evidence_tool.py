"""Same quality primitives, bounded repair, and no acceptance authority."""
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def module():
    from mova_fpl.ops import research_evidence, research_quality
    sys.modules['research_evidence'] = research_evidence
    sys.modules['research_quality'] = research_quality
    spec = importlib.util.spec_from_file_location('evidence_tool', ROOT / 'deploy/research/evidence-tool.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_can_correct_excerpt_and_stale_source_without_promotion(tmp_path):
    mod = module()
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    request = {'research_run_id':'research_'+'a'*32,'scope_policy':{'max_documents':3},
      'manifest':{'deadline_at':'2026-10-10T10:00:00Z', 'research_summary':{
        'world':{'catalog':[[1,'Haaland','MCI'],[2,'Saka','ARS']]}}}}
    calls=[]
    def transport(url):
        calls.append(url)
        return (b'<html>22 September 2026. Haaland is available. Saka has a knee injury.</html>',
                {'content_type':'text/html','final_url':url,'http_status':200})
    tool=mod.EvidenceTool(request,tmp_path,clock=lambda:now,
        fetcher=mod.SafeEvidenceFetcher(tmp_path,transport=transport))
    args={'source_url':'https://example.com/news','evidence_text':'Haaland is injured.',
          'published_at':'2026-09-22T00:00:00Z','player_element':1,'claim_type':'availability'}
    assert tool.verify(args)['reasons']==['evidence_locator_not_verified']
    args['evidence_text']='Haaland is available.'
    result=tool.verify(args)
    assert result['status']=='supported' and result['final_acceptance'] is False
    args['player_element']=2
    assert 'identity_or_claim_unsupported' in tool.verify(args)['reasons']
    assert len(calls)==1  # one public fetch reused across excerpts/subjects within this turn
    args['source_url']='https://127.0.0.1/secrets'
    assert tool.verify(args)['reasons']==['invalid_public_url']
    args['source_url']='https://example.com/news'
    args['published_at']='2025-09-22T00:00:00Z'
    assert 'stale_for_claim' in tool.verify(args)['reasons']
    assert tool.verify({**args,'path':'/etc/passwd'})['reasons']==['invalid_arguments']
    assert tool.verify(args)['reasons']==['verification_budget_exhausted']
    assert len(calls)==1


def test_evidence_tool_refuses_deadline_unknown_and_ambiguous_identity(tmp_path):
    mod=module()
    request={'research_run_id':'research_'+'a'*32,'scope_policy':{'max_documents':3},
      'manifest':{'deadline_at':'2026-09-22T10:00:00Z','research_summary':{'world':{
        'catalog':[[1,'Silva','MCI'],[2,'Silva','FUL']]}}}}
    args={'source_url':'https://example.com/news','evidence_text':'Silva available',
          'published_at':'2026-09-22T00:00:00Z','player_element':1,'claim_type':'availability'}
    before=datetime(2026,9,22,9,tzinfo=timezone.utc)
    tool=mod.EvidenceTool(request,tmp_path,clock=lambda:before)
    assert tool.verify(args)['reasons']==['ambiguous_identity']
    assert tool.verify({**args,'player_element':99})['reasons']==['unknown_element']
    tool.clock=lambda:datetime(2026,9,22,11,tzinfo=timezone.utc)
    assert tool.verify(args)['reasons']==['fetch_after_cutoff']


def test_stdio_protocol_lists_only_verifier_and_rejects_unknown_methods(monkeypatch):
    import io
    mod=module()
    stream=io.StringIO()
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize'},
              {'jsonrpc':'2.0','method':'notifications/initialized'},
              {'jsonrpc':'2.0','id':2,'method':'tools/list'},
              {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'shell'}}]
    monkeypatch.setattr(sys,'stdin',io.StringIO('\n'.join(map(json.dumps,messages))))
    monkeypatch.setattr(sys,'stdout',stream)
    mod.serve(None)
    responses=[json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(responses)==3
    assert responses[0]['result']['protocolVersion']=='2025-06-18'
    assert [tool['name'] for tool in responses[1]['result']['tools']]==['verify_research_evidence']
    assert responses[2]['error']['code']==-32602


def test_controlled_context_preserves_catalog_and_pages_memory_without_network(tmp_path):
    mod=module()
    request={'research_run_id':'research_'+'a'*32,'agent_release':{'execution':'app_server'},
      'manifest':{'deadline_at':'2026-10-10T10:00:00Z','memory_summary':{'lessons':[{'text':'lesson'}]},
        'research_summary':{'focus':[], 'world':{'catalog':[[1,'Haaland','MCI'],[2,'Saka','ARS']]}}}}
    tool=mod.EvidenceTool(request,tmp_path)
    assert tool.context({'section':'catalog','query':'Saka','offset':0})['rows']==[[2,'Saka','ARS']]
    assert tool.context({'section':'memory','query':'','offset':0})['rows'][0]['value']=={'text':'lesson'}
    assert tool.search({'query':'x'})['status']=='rejected'
    tool.search_calls=8
    assert tool.search({'query':'team news'})['reasons']==['search_budget_or_deadline']


def test_search_missing_credential_is_typed_failure_and_never_calls_provider(tmp_path, monkeypatch):
    mod=module()
    tool=mod.EvidenceTool({'research_run_id':'research_'+'a'*32,
        'manifest':{'deadline_at':'2026-10-10T10:00:00Z'}},tmp_path)
    def missing(_path):
        raise FileNotFoundError('redacted')
    monkeypatch.setattr(mod.Path,'read_text',missing)
    monkeypatch.setattr(mod.urllib.request,'urlopen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('unexpected network')))
    assert tool.search({'query':'Premier League team news'})['reasons']==['search_not_configured']


def test_read_and_verify_share_one_public_fetch_with_body_matches(tmp_path):
    mod=module(); calls=[]
    payload=b'<html><title>Saka</title>'+b' navigation '*100+b'22 September 2026. Saka is available.</html>'
    def transport(url):
        calls.append(url)
        return payload,{'content_type':'text/html','final_url':url,'http_status':200}
    request={'research_run_id':'research_'+'a'*32,'manifest':{'deadline_at':'2026-10-10T10:00:00Z',
        'research_summary':{'world':{'catalog':[[1,'Saka','ARS']]}}}}
    tool=mod.EvidenceTool(request,tmp_path,clock=lambda:datetime(2026,9,22,12,tzinfo=timezone.utc),
        fetcher=mod.SafeEvidenceFetcher(tmp_path,transport=transport))
    r=tool.read_source({'source_url':'https://example.com/news','player_elements':[1]})
    assert any('Saka is available.' in s for s in r['literal_fragments'])
    assert tool.verify({'source_url':'https://example.com/news','evidence_text':'Saka is available.',
        'published_at':'2026-09-22T00:00:00Z','player_element':1,'claim_type':'availability'})['status']=='supported'
    assert len(calls)==1


def test_search_sends_recent_date_window_without_exposing_key(tmp_path,monkeypatch):
    import io
    mod=module(); captured=[]
    monkeypatch.setattr(mod.Path,'read_text',lambda p:'fake-test-key')
    def response(req,timeout):
        captured.append(json.loads(req.data))
        return io.BytesIO(b'{"success":true,"data":[]}')
    monkeypatch.setattr(mod.urllib.request,'urlopen',response)
    tool=mod.EvidenceTool({'research_run_id':'research_'+'a'*32,
        'manifest':{'deadline_at':'2026-10-10T10:00:00Z'}},tmp_path,
        clock=lambda:datetime(2026,9,22,12,tzinfo=timezone.utc))
    result=tool.search({'query':'Premier League injuries'})
    assert result['status']=='ok'
    assert captured[0]['tbs']=='cdr:1,cd_min:09/15/2026,cd_max:09/22/2026'
    assert 'fake-test-key' not in json.dumps(result)


def test_context_catalog_supports_multiple_names_without_inventing_ids(tmp_path):
    mod=module()
    request={'research_run_id':'research_'+'a'*32,'manifest':{'deadline_at':'2026-10-10T10:00:00Z',
        'research_summary':{'world':{'catalog':[[1,'Dunk','BHA'],[2,'Struijk','LEE'],[3,'Sangaré','BRE']]}}}}
    tool=mod.EvidenceTool(request,tmp_path)
    assert tool.context({'section':'catalog','query':'Lewis Dunk Pascal Struijk','offset':0})['rows']==[[1,'Dunk','BHA'],[2,'Struijk','LEE']]
    assert tool.context({'section':'catalog','query':'Sangare','offset':0})['rows']==[[3,'Sangaré','BRE']]
