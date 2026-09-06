import subprocess

from experiments.data_ground_truth.calendar_descendant_publication import descendant_hours


def test_descendant_search_uses_aware_clocks_and_never_deadline_hour(monkeypatch):
    candidate=dict(commit='a',committer_at='2025-08-20T07:00:00Z',deadline='2025-08-20T10:00:00Z')
    def git(repo,*args):
        if args[-1]=='foreign':raise subprocess.CalledProcessError(1,args)
        return ''
    monkeypatch.setattr('experiments.data_ground_truth.calendar_descendant_publication.git',git)
    commits=[('a','2025-08-20T07:00:00Z'),('b','2025-08-20T11:10:00+02:00'),
             ('foreign','2025-08-20T08:00:00Z'),('late','2025-08-20T10:00:00Z')]
    assert descendant_hours(candidate,commits,None)==['2025-08-20-09']
