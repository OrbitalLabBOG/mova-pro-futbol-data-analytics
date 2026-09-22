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
    assert len(calls)==2  # same document may be checked against other subjects without refetch
    args['source_url']='https://127.0.0.1/secrets'
    assert tool.verify(args)['reasons']==['invalid_public_url']
    args['source_url']='https://example.com/news'
    args['published_at']='2025-09-22T00:00:00Z'
    assert 'stale_for_claim' in tool.verify(args)['reasons']
    assert tool.verify({**args,'path':'/etc/passwd'})['reasons']==['invalid_arguments']
    assert tool.verify(args)['reasons']==['verification_budget_exhausted']
    assert len(calls)==3


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
