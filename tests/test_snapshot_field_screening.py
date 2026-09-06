from experiments.data_ground_truth.snapshot_field_screening import INTRO_FIELDS,screen,suspect_zero_fields


def row():
    return dict(gw=2,cells={**{f:dict(status='valid',value=0) for f in INTRO_FIELDS},
                            'minutes':dict(status='valid',value=90)})


def test_final_label_agreement_cannot_change_screening():
    r=row()
    assert screen(dict(r,retrospective_equal=True),'minutes',True,set())==screen(
        dict(r,retrospective_equal=False),'minutes',True,set())
    assert screen(r,'minutes',True,set())['status']=='screen_pass'


def test_population_zero_period_and_publication_are_separate_reasons():
    r=row();suspect=suspect_zero_fields([r])
    assert suspect==INTRO_FIELDS
    assert screen(r,'starts',True,suspect)['reasons']==['population_zero_despite_observed_minutes']
    assert screen(dict(r,gw=1),'minutes',False,set())['reasons']==['publication_unproven','GW1_period_unresolved']
    r['cells']['minutes']['value']=0
    assert suspect_zero_fields([r])==set()
