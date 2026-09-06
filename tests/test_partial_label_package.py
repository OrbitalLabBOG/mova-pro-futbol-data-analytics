import json
import pandas as pd
import pytest
from experiments.data_ground_truth.partial_label_package import consolidate,verify
from experiments.data_ground_truth.raw_bundle import canonical
from experiments.data_ground_truth.raw import digest


def sample():
    return pd.DataFrame([
        dict(source_presence='both',fpl_id=1,id=1,matchId=2,gameweek=1,gw=1,minutes=90,mins=90,total=None,gw_pts=0,candidate_missing_points=True,corroborated_link=True,player_player_id=3,fixture_id=4),
        dict(source_presence='left_only',fpl_id=2,id=None,matchId=2,gameweek=1,gw=None,minutes=30,mins=None,total=None,gw_pts=None,candidate_missing_points=False,corroborated_link=False,player_player_id=5,fixture_id=4),
        dict(source_presence='right_only',fpl_id=None,id=3,matchId=2,gameweek=None,gw=1,minutes=None,mins=0,total=None,gw_pts=0,candidate_missing_points=False,corroborated_link=False,player_player_id=None,fixture_id=None)])


def test_consolidation_recovers_only_observed_values_and_retains_unknowns():
    raw=sample();rows=consolidate(raw)
    assert rows.label_status.tolist()==['observed','unknown','observed']
    assert rows.total_points.iloc[0]==0 and pd.isna(rows.total_points.iloc[1])
    assert rows.minutes.iloc[2]==0 and raw.total.isna().all()
    assert not rows.eligible_training.any()


def test_identity_conflicts_and_unsubstantiated_recovery_fail():
    f=sample();f.loc[0,'id']=9
    with pytest.raises(ValueError,match='identity or gameweek'):consolidate(f)
    f=sample();f.loc[0,'mins']=89
    with pytest.raises(ValueError,match='conflicting observed'):consolidate(f)
    f=sample();f.loc[0,'corroborated_link']=False
    with pytest.raises(ValueError,match='unsupported recovery'):consolidate(f)
    f=sample();f=pd.concat([f,f.iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError,match='duplicate label identity'):consolidate(f)


def test_verification_detects_artifact_tampering(tmp_path):
    f=consolidate(sample());a=f[f.label_status.eq('observed')];b=f[f.label_status.eq('unknown')]
    output={'observed_labels.csv':a.to_csv(index=False).encode(),'unknown_rows.csv':b.to_csv(index=False).encode(),'inferred_candidates.json':b'[]\n'}
    m=dict(coverage=dict(observed_rows=2,unknown_rows=1,union_rows=3,positive_minute_observed_rows=1,explicit_zero_minute_rows=1,observed_fixtures=1,observed_gameweeks=1),artifacts={n:dict(sha256=digest(v),bytes=len(v)) for n,v in output.items()})
    key=digest(canonical(m));root=tmp_path/key;root.mkdir()
    (root/'manifest.json').write_bytes(canonical(m|dict(dataset_id=key)))
    for n,v in output.items():(root/n).write_bytes(v)
    assert verify(root)['dataset_id']==key
    (root/'observed_labels.csv').write_bytes(output['observed_labels.csv']+b'\n')
    with pytest.raises(ValueError):verify(root)
