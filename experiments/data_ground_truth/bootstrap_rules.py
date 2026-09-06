"""Archive selected bootstrap rules and GW calendars without inventing replay semantics."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

from experiments.data_ground_truth.bootstrap_audit import decode, inspect
from experiments.data_ground_truth.publication_archive import aware
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

SECTIONS=('game_settings','game_config','chips','element_types')
EVENT_FIELDS=('id','name','deadline_time','finished','data_checked','is_current','is_next','is_previous',
              'can_enter','can_manage','released','release_time','overrides')
ROLE_FIELDS=('id','singular_name_short','squad_select','squad_min_select','squad_max_select',
             'squad_min_play','squad_max_play','sub_positions_locked')
STRATEGIC_SETTINGS=('squad_squadsize','squad_squadplay','squad_total_spend','squad_team_limit','max_extra_free_transfers',
                    'transfers_cap','transfers_sell_on_fee','element_sell_at_purchase_price','sys_vice_captain_enabled')


def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()


def extract(snapshot,candidate):
    _,possible=inspect(snapshot,candidate['path'])
    matching=[c for c in possible if c['season']==candidate['season'] and c['gw']==candidate['gw'] and c['deadline']==candidate['deadline']]
    if len(matching)!=1:raise ValueError('rule/calendar candidate mismatch')
    sections={k:snapshot[k] for k in SECTIONS if k in snapshot}
    for name in ('game_settings','game_config'):
        if name in sections and sections[name] is not None and not isinstance(sections[name],dict):raise ValueError('invalid rules section')
    for name in ('chips','element_types'):
        if name in sections and sections[name] is not None and not isinstance(sections[name],list):raise ValueError('invalid rules list')
    calendar=[{k:e[k] for k in EVENT_FIELDS if k in e} for e in snapshot['events']]
    settings=sections.get('game_settings') or {};config=sections.get('game_config') or {}
    roles=[{k:e[k] for k in ROLE_FIELDS if k in e} for e in (sections.get('element_types') or [])]
    strategic=dict(settings={k:settings[k] for k in STRATEGIC_SETTINGS if k in settings},element_types=roles,
        chips_present='chips' in sections,chips=sections.get('chips'),scoring_present='scoring' in config,scoring=config.get('scoring'))
    return sections,calendar,strategic


def build(raw_root:Path,selection_root:Path,out:Path):
    selection_bytes=(selection_root/'report.json').read_bytes();selection=json.loads(selection_bytes)
    manifest_bytes=checked(raw_root/'manifest.json',selection['manifest_sha256'])
    manifest=json.loads(manifest_bytes);records={r['path']:r for r in manifest['records']}
    candidates=json.loads(checked(selection_root/'nominal_deadline_candidates.json',selection['artifacts']['nominal_deadline_candidates.json']))
    proofs=json.loads(checked(selection_root/'publication_witnesses.json',selection['artifacts']['publication_witnesses.json']))
    indexed={(p['season'],p['gw']):p for p in proofs}
    if len(indexed)!=len(proofs):raise ValueError('duplicate publication witness')
    out.mkdir(parents=True,exist_ok=True);(out/'objects').mkdir(exist_ok=True)
    rows=[];changes=[];conflicts=[];previous={};seasons={};nonempty_overrides=[]
    for c in sorted(candidates,key=lambda c:(c['season'],c['gw'])):
        if records[c['path']]['sha256']!=c['sha256']:raise ValueError('rule source mismatch')
        snapshot=decode(checked(raw_root/'objects'/c['sha256'],c['sha256']))
        sections,calendar,strategic=extract(snapshot,c)
        p=indexed.get((c['season'],c['gw']))
        if p and (p['source_sha256']!=c['sha256'] or p['deadline']!=c['deadline'] or p['eligible_predeadline'] is not True):raise ValueError('rule publication mismatch')
        hashes={}
        for name,value in [('sections',sections),('calendar',calendar),('strategic',strategic)]:
            payload=canonical(value);sha=digest(payload);target=out/'objects'/sha
            if target.exists():checked(target,sha)
            else:target.write_bytes(payload)
            hashes[name]=sha
        row=dict(season=c['season'],gw=c['gw'],source_sha256=c['sha256'],source_path=c['path'],deadline=c['deadline'],
            source_claimed_at=c['source_claimed_at'],available_at=p['available_at'] if p else None,
            publication_verified=p is not None,section_presence={k:k in sections for k in SECTIONS},
            scoring_present=strategic['scoring_present'],calendar_events=len(calendar),fixture_schedule_present='fixtures' in snapshot,
            artifacts=hashes,eligible_training=False,eligible_replay=False)
        rows.append(row)
        s=seasons.setdefault(c['season'],dict(candidates=0,verified=0,sections=Counter(),scoring_present=0,calendar_rows=0,
            fixture_schedule_snapshots=0,strategic_hashes=set(),chip_hashes=set(),scoring_hashes=set()))
        s['candidates']+=1;s['verified']+=int(p is not None);s['sections'].update(k for k in SECTIONS if k in sections)
        s['scoring_present']+=int(strategic['scoring_present']);s['calendar_rows']+=len(calendar)
        s['fixture_schedule_snapshots']+=int('fixtures' in snapshot);s['strategic_hashes'].add(hashes['strategic'])
        if 'chips' in sections:s['chip_hashes'].add(digest(canonical(sections['chips'])))
        if strategic['scoring_present']:s['scoring_hashes'].add(digest(canonical(strategic['scoring'])))
        settings=sections.get('game_settings') or {};config=sections.get('game_config') or {}
        config_rules=config.get('rules') or {}
        differing={k:dict(game_settings=settings[k],game_config=config_rules[k]) for k in settings.keys() & config_rules.keys() if settings[k]!=config_rules[k]}
        if differing:conflicts.append(dict(season=c['season'],gw=c['gw'],fields=differing))
        for chip in sections.get('chips') or []:
            override=chip.get('overrides') or {}
            if any(v not in ({},[],None) for v in override.values()):
                nonempty_overrides.append(dict(season=c['season'],observed_gw=c['gw'],chip_id=chip['id'],chip_name=chip['name'],overrides=override,source_sha256=c['sha256']))
        for event in calendar:
            k=(c['season'],event['id']);before=previous.get(k)
            if before and before['event']['deadline_time']!=event['deadline_time']:
                changes.append(dict(season=c['season'],event=event['id'],previous_observed_gw=before['gw'],observed_gw=c['gw'],
                    previous_deadline=before['event']['deadline_time'],deadline=event['deadline_time'],
                    previous_source_sha256=before['sha256'],source_sha256=c['sha256'],available_at=row['available_at']))
            previous[k]=dict(event=event,gw=c['gw'],sha256=c['sha256'])
    for s in seasons.values():
        for field in ('strategic_hashes','chip_hashes','scoring_hashes'):s[field]=sorted(s[field])
        s['sections']=dict(s['sections'])
    artifacts={}
    for name,value in [('snapshots.json',rows),('deadline_changes.json',changes),('rule_conflicts.json',conflicts),('chip_overrides.json',nonempty_overrides)]:
        payload=(json.dumps(value,indent=2)+'\n').encode();(out/name).write_bytes(payload);artifacts[name]=digest(payload)
    report=dict(version='bootstrap-rules-v1',source_manifest_sha256=digest(manifest_bytes),selection_report_sha256=digest(selection_bytes),
        implementation_sha256=digest(Path(__file__).read_bytes()),snapshots=len(rows),verified_snapshots=sum(r['publication_verified'] for r in rows),
        seasons=seasons,deadline_changes=len(changes),rule_conflicts=len(conflicts),nonempty_chip_override_observations=len(nonempty_overrides),
        artifacts=artifacts,eligible_replay=False,eligible_training=False,production_changed=False,
        limitations=['GW_deadlines_are_not_fixture_assignments_or_kickoffs','raw_configuration_is_not_a_complete_rule_interpreter',
                     'absent_chip_or_scoring_section_does_not_mean_no_chips_or_zero_points','field_semantics_and_overrides_require_validation'])
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('raw-root','selection-root','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();print(json.dumps(build(a.raw_root,a.selection_root,a.out),indent=2))


if __name__=='__main__':main()
