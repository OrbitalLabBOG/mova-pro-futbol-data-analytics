from experiments.research.audit_run import audit


def test_audit_distinguishes_search_read_and_verified_evidence():
    request={'scope_policy':{'max_documents':2},'manifest':{'research_summary':{'focus':[
        {'element':1,'team':'One'},{'element':2,'team':'Two'}]}}}
    def tool(name,args,result):
        import json
        return {'method':'item/completed','params':{'item':{'type':'mcpToolCall','tool':name,
            'arguments':args,'result':{'content':[{'text':json.dumps(result)}]}}}}
    events=[tool('search_research_web',{'query':'One team news'},{'status':'ok'}),
            tool('read_research_source',{'player_elements':[1]}, {'status':'ok','article_text':''})]
    result=audit(request,events)
    assert result['clubs']['One']['read_requested']==[1]
    assert result['clubs']['One']['tool_supported']==[]
    assert result['clubs_never_requested_for_read']==['Two']
    assert result['empty_or_failed_reads']==1
    assert result['runtime_mutated'] is False
