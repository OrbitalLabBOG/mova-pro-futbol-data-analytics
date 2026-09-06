from experiments.data_ground_truth.statsbomb_goal_calibration import tally,compare


def event(kind,player,team,**fields):
    return dict(id=kind,period=1,type={'name':kind},player={'id':player},team={'id':team},**fields)


def test_own_goal_is_credited_to_opponent_without_double_counting():
    events=[event('Own Goal Against',10,1),event('Own Goal For',20,2),event('Goal Keeper',11,1)]
    goals,own,teams,witnesses,unknown=tally(events,{1,2})
    assert not goals and own[10]==1 and teams[2]==1 and teams[1]==0
    assert len(witnesses)==1 and unknown==0


def test_shots_not_on_target_do_not_become_goals():
    events=[event('Shot',10,1,shot={'outcome':{'name':'Goal'}}),event('Shot',10,1,shot={'outcome':{'name':'Saved'}})]
    goals,own,teams,_,_=tally(events,{1,2})
    assert goals[10]==1 and teams[1]==1 and not own
    assert compare(0,'')['status']=='FPL_unknown'
    assert compare(0,'0')['status']=='equal'


def test_unidentified_goal_actor_is_reported_and_not_assigned_to_a_player():
    e=event('Shot',10,1,shot={'outcome':{'name':'Goal'}})
    del e['player']
    goals,_,teams,_,unknown=tally([e],{1,2})
    assert unknown==1 and not goals and teams[1]==1
