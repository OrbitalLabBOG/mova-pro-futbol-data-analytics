"""Audit one sealed research turn without inference, web calls or runtime writes."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def audit(request: dict, events: list[dict]) -> dict:
    calls = []
    prompt = None
    for event in events:
        item = event.get('params', {}).get('item', {})
        if event.get('method') != 'item/completed':
            continue
        if item.get('type') == 'userMessage':
            prompt = '\n'.join(part.get('text', '') for part in item.get('content', [])
                               if part.get('type') == 'text')
        if item.get('type') != 'mcpToolCall':
            continue
        try:
            result = json.loads(item['result']['content'][0]['text'])
        except (KeyError, IndexError, TypeError, ValueError):
            result = {'status': 'unreadable_telemetry'}
        calls.append({'tool': item['tool'], 'arguments': item.get('arguments') or {},
                      'result': result})
    counts = Counter(row['tool'] for row in calls)
    focus = request['manifest']['research_summary']['focus']
    inspected = {element for row in calls if row['tool'] == 'read_research_source'
                 for element in row['arguments'].get('player_elements', [])}
    checks = [row for row in calls if row['tool'] == 'verify_research_evidence']
    checked = {element for row in checks if row['result'].get('status') == 'supported'
               for element in row['result'].get('covered_focus_elements', [])}
    clubs = {}
    for row in focus:
        group = clubs.setdefault(row.get('team', f"unknown:{row['element']}"),
                                 {'required': [], 'read_requested': [], 'tool_supported': []})
        group['required'].append(row['element'])
        if row['element'] in inspected:
            group['read_requested'].append(row['element'])
        if row['element'] in checked:
            group['tool_supported'].append(row['element'])
    reads = [row['result'] for row in calls if row['tool'] == 'read_research_source']
    outside_checks = [row['arguments'].get('player_element') for row in checks
                      if row['arguments'].get('player_element') not in {r['element'] for r in focus}]
    limit = request['scope_policy']['max_documents']
    return {'schema': 'mova-research-turn-audit-v1', 'agent_version': request.get('agent_version'),
            'scope': request['scope_policy'], 'tool_calls': dict(counts),
            'search_quota_used': counts['search_research_web'],
            'verification_quota_available': min(32, max(1, limit)*2),
            'verification_quota_used': len(checks), 'outside_focus_verifications': outside_checks,
            'empty_or_failed_reads': sum(not row.get('article_text') for row in reads),
            'thin_successful_reads': sum(row.get('status') == 'ok' and 0 < len(row.get('article_text', '')) < 300 for row in reads),
            'clubs': clubs, 'clubs_never_requested_for_read': sorted(k for k,v in clubs.items() if not v['read_requested']),
            'prompt_seen': prompt is not None,
            'prompt_limits_to_two_or_three': bool(prompt and ('2-3 dudas' in prompt or 'elige dos dudas' in prompt)),
            'warning': 'Read requested and tool supported are diagnostics, not independent importer acceptance.',
            'external_calls': 0, 'runtime_mutated': False, 'autonomy_promoted': False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--events',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(audit(json.loads(args.request.read_text()),
                           [json.loads(line) for line in args.events.read_text().splitlines()]),
                     indent=2,ensure_ascii=False))
