"""Archive official rule articles as retrospective evidence, not executable policy."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from mova_fpl.data.sources import _get
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip-1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def visible(data):
    parser = Text(); parser.feed(data.decode('utf-8'))
    return ' '.join(' '.join(parser.parts).split())


def capture(root, article, offline=False):
    ident = article['article_id']
    if not re.fullmatch(r'[0-9]+', ident):
        raise ValueError('official numeric article ID required')
    url = 'https://www.premierleague.com/en/news/'+ident
    path = root/'records'/(ident+'.json')
    if path.exists():
        record = json.loads(path.read_text())
        if record['url'] != url:
            raise ValueError('source URL mismatch')
        data = checked(root/'objects'/record['sha256'], record['sha256'])
        if len(data) != record['bytes']:
            raise ValueError('source size mismatch')
        return record
    if offline:
        raise OSError('missing offline article '+ident)
    data, headers = _get(url, include_headers=True)
    if len(data) > 16*1024*1024:
        raise ValueError('article size limit')
    if article['title'] not in visible(data):
        raise ValueError('article title missing')
    sha = digest(data); (root/'objects').mkdir(parents=True, exist_ok=True)
    obj = root/'objects'/sha
    if obj.exists():
        checked(obj, sha)
    else:
        obj.write_bytes(data)
    record = dict(article_id=ident, url=url, sha256=sha, bytes=len(data),
                  fetched_at=datetime.now(timezone.utc).isoformat(),
                  content_type=headers.get('content-type'), last_modified=headers.get('last-modified'),
                  available_at=None, eligible_predeadline=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2)+'\n')
    return record


def annotate(article, text):
    if article['title'] not in text or article['displayed_date_text'] not in text:
        raise ValueError('article identity or displayed date mismatch')
    assertions = []
    for claim in article['assertions']:
        anchor = claim['anchor']
        offsets = [m.start() for m in re.finditer(re.escape(anchor), text)]
        if len(offsets) != 1:
            raise ValueError('missing or ambiguous evidence anchor: '+anchor)
        start = offsets[0]
        assertions.append(dict(claim, anchor_start=start, anchor_end=start+len(anchor),
                               available_at=None, eligible_replay=False, eligible_training=False,
                               interpretation='curated_retrospective_rule_statement'))
    return assertions


def build(spec_path, root, out, offline=False):
    spec_bytes = spec_path.read_bytes(); spec = json.loads(spec_bytes)
    articles = spec['articles']
    if len({a['article_id'] for a in articles}) != len(articles):
        raise ValueError('duplicate article')
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda a:capture(root,a,offline), articles))
    out.mkdir(parents=True, exist_ok=True); (out/'objects').mkdir(exist_ok=True)
    evidence = []; coverage = {}
    for article, record in zip(articles, records):
        text = visible(checked(root/'objects'/record['sha256'],record['sha256']))
        assertions = annotate(article, text)
        data = (text+'\n').encode(); sha = digest(data)
        (out/'objects'/sha).write_bytes(data)
        evidence.append(dict(article_id=article['article_id'], season=article['season'],
                             source=record, displayed_date_text=article['displayed_date_text'],
                             text_sha256=sha, assertions=assertions))
        for assertion in assertions:
            coverage.setdefault(article['season'], set()).add(assertion['dimension'])
    payload = (json.dumps(evidence,indent=2)+'\n').encode(); (out/'evidence.json').write_bytes(payload)
    manifest = (json.dumps(records,indent=2)+'\n').encode(); (out/'source_manifest.json').write_bytes(manifest)
    seasons = [f'{s}-{str(s+1)[2:]}' for s in range(2014,2026)]
    dimensions = spec['coverage_dimensions']
    matrix = {season:{d:'partial_documentary_evidence' if d in coverage.get(season,set()) else 'not_collected'
                      for d in dimensions} for season in seasons}
    result = dict(version='historical-rule-evidence-v1', spec_sha256=digest(spec_bytes),
                  implementation_sha256=digest(Path(__file__).read_bytes()),
                  articles=len(records), raw_bytes=sum(r['bytes'] for r in records),
                  assertions=sum(len(e['assertions']) for e in evidence),
                  seasons_with_evidence=len(coverage), coverage=matrix,
                  artifacts={'evidence.json':digest(payload), 'source_manifest.json':digest(manifest)},
                  production_changed=False, training_admitted=False, replay_admitted=False,
                  limitations=['displayed_article_date_is_not_proven_historical_publication',
                               'current_article_bytes_may_include_later_edits',
                               'curated_assertions_are_not_an_executable_complete_ruleset',
                               'no_cross_season_rule_inheritance',
                               'article_deadline_clocks_are_not_canonical_GW_deadlines'])
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('spec','raw-root','out'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--offline',action='store_true'); a=p.parse_args()
    print(json.dumps(build(a.spec,a.raw_root,a.out,a.offline),indent=2))


if __name__ == '__main__':
    main()
