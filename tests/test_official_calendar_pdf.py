import pytest
from experiments.data_ground_truth.official_calendar_pdf import fill_at,fixtures_2013,validate_matrix,validate_pairs


def pairs():
    return [dict(home=str(a),away=str(b)) for a in range(20) for b in range(20) if a!=b]


def test_fixture_population_rejects_duplicates_missing_and_self_matches():
    rows=pairs();validate_pairs(rows)
    for invalid in [rows[:-1],rows[:-1]+[rows[0]],rows[:-1]+[dict(home='1',away='1')]]:
        with pytest.raises(ValueError):validate_pairs(invalid)


def test_pdf_clock_remains_local_and_does_not_invent_fpl_gameweek():
    text='Premier League Fixtures\n2013/14 Season\n'+'\n'.join('17/08/2013 15:00 '+r['home']+' v '+r['away'] for r in pairs())
    rows=fixtures_2013([dict(text=text)])
    assert len(rows)==380 and all(r['timezone'] is None and r['gw'] is None and r['kickoff_time'] is None for r in rows)
    assert rows[0]['source_local_datetime']=='2013-08-17T15:00:00'
    with pytest.raises(ValueError,match='unparsed'):fixtures_2013([dict(text=text+'\nunparsed row')])
    with pytest.raises(ValueError,match='outside'):fixtures_2013([dict(text=text.replace('2013 15:00','2015 15:00'))])


def test_fill_uses_exact_containing_color_without_nearest_palette_guess():
    fills=[dict(rect=[0,0,10,10],color=[0.8,0.8,0.8])]
    assert fill_at((5,5),fills)==(0.8,0.8,0.8)
    with pytest.raises(ValueError):fill_at((20,20),fills)
    with pytest.raises(ValueError):fill_at((5,5),fills+[dict(rect=[1,1,9,9],color=[1,0,0])])


def test_fdr_population_and_reciprocity_required():
    # Circle schedule, reverse venues in the second half.
    clubs=[str(i) for i in range(20)];rows=[]
    for gw in range(1,20):
        for i in range(10):
            a,b=clubs[i],clubs[-1-i]
            rows.extend([dict(club=a,opponent=b,venue='H',gw=gw),dict(club=b,opponent=a,venue='A',gw=gw),
                         dict(club=a,opponent=b,venue='A',gw=gw+19),dict(club=b,opponent=a,venue='H',gw=gw+19)])
        clubs=[clubs[0],clubs[-1],*clubs[1:-1]]
    validate_matrix(rows)
    with pytest.raises(ValueError,match='population'):validate_matrix(rows[:-1])
    with pytest.raises(ValueError,match='reciprocity'):validate_matrix([dict(rows[0],venue='A'),*rows[1:]])
