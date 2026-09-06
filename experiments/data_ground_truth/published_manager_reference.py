"""Extract published aggregate manager statistics; never a causal policy benchmark."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path

PDF_SHA = 'f96623fdc04e3521119e6ec29ea0df7841edc6428409ee668b41e08804873f32'
COHORTS = ('10^3', '10^4', '10^5', '10^6')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def number(value):
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid published numeric cell') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('invalid published numeric cell')
    return result


def parse(text):
    section = text.split('S2 Table:', 1)[1].split('obtained a lower points total', 1)[0]
    tokens = section.split('\nGW\n', 1)[1].strip().splitlines()
    if tokens[:8] != ['Mean', 'SD'] * 4 or len(tokens[8:]) != 38 * 9:
        raise ValueError('unexpected S2 table layout')
    weekly = []
    tokens = tokens[8:]
    for gw in range(1, 39):
        values = tokens[(gw - 1) * 9:gw * 9]
        if values[0] != str(gw):
            raise ValueError('missing or duplicate published GW')
        for i, cohort in enumerate(COHORTS):
            mean, sd = values[1 + 2 * i:3 + 2 * i]
            number(mean); number(sd)
            weekly.append(dict(season='2018-19', published_cohort=cohort, gw=gw,
                               mean_points=mean, sd_points=sd, source_page=3,
                               cohort_selection='retrospective_final_rank_tier', eligible_training=False))
    section = text.split('S3 Table:', 1)[1].split('S4 Table:', 1)[0]
    tokens = section.split('\nTier\n', 1)[1].strip().splitlines()
    if tokens[:5] != ['Everyone', '103', '104', '105', '106']:
        raise ValueError('unexpected S3 cohort labels')
    expected = ['n', 'Max', 'Min', 'Mean', 'Median', 'Std. dev', 'IQR']
    tokens = tokens[5:]
    if len(tokens) != 6 * len(expected):
        raise ValueError('unexpected S3 table size')
    columns = {}
    for j, name in enumerate(expected):
        values = tokens[j * 6:(j + 1) * 6]
        if values[0] != name:
            raise ValueError('unexpected S3 metric order')
        for v in values[1:]:
            number(v)
        columns[name] = values[1:]
    summary = [dict(season='2018-19', published_cohort=cohort,
                    **{k: v[i] for k, v in columns.items()}, eligible_training=False)
               for i, cohort in enumerate(('Everyone',) + COHORTS)]
    return weekly, summary


def reconcile(weekly, summary):
    lookup = {r['published_cohort']: r for r in summary}
    if len(lookup) != 5 or set(lookup) != {'Everyone', *COHORTS}:
        raise ValueError('unexpected summary population')
    for row in summary:
        n = number(row['n'])
        if n != n.to_integral_value() or n <= 0:
            raise ValueError('invalid cohort size')
    if sum(number(lookup[c]['n']) for c in COHORTS) != number(lookup['Everyone']['n']):
        raise ValueError('cohort sizes do not reconcile')
    checks = []
    for cohort in COHORTS:
        rows = [r for r in weekly if r['published_cohort'] == cohort]
        if len(rows) != 38 or {r['gw'] for r in rows} != set(range(1, 39)):
            raise ValueError('incomplete weekly cohort')
        total = sum(number(r['mean_points']) for r in rows)
        season_mean = number(lookup[cohort]['Mean'])
        difference = total - season_mean
        # Published two-decimal cells: compatibility only, not proof of a rounding mechanism.
        compatible = abs(difference) <= Decimal('0.005') * 39
        if not compatible:
            raise ValueError('weekly and seasonal means disagree beyond rounding bound')
        checks.append(dict(published_cohort=cohort, weekly_mean_sum=str(total),
                           published_season_mean=str(season_mean), difference=str(difference),
                           two_decimal_rounding_compatible=compatible))
    return checks


def build(root, out):
    import fitz
    pdf = (root / 'objects' / PDF_SHA).read_bytes()
    if digest(pdf) != PDF_SHA:
        raise ValueError('source PDF hash mismatch')
    with fitz.open(stream=pdf, filetype='pdf') as document:
        text = '\n\n'.join(page.get_text() for page in document)
        pages = len(document)
    weekly, summary = parse(text)
    checks = reconcile(weekly, summary)
    out.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for name, rows in [('weekly-cohorts.csv', weekly), ('season-cohorts.csv', summary)]:
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
        data = stream.getvalue().encode(); (out / name).write_bytes(data); artifacts[name] = digest(data)
    result = dict(version='published-manager-reference-v1', source_pdf_sha256=PDF_SHA,
                  extractor='PyMuPDF ' + fitz.VersionBind, source_pages=pages,
                  extracted_text_sha256=digest(text.encode()), implementation_sha256=digest(Path(__file__).read_bytes()),
                  weekly_rows=len(weekly), seasonal_summary_rows=len(summary), artifacts=artifacts,
                  represented_managers=int(summary[0]['n']), reconciliation=checks,
                  source_doi='10.1371/journal.pone.0246698.s001',
                  training_admitted=False, promotion_benchmark_admitted=False, production_changed=False,
                  limitations=['aggregate_reference_not_individual_manager_actions',
                               'cohorts_selected_by_final_rank_not_preseason_information',
                               'sample_is_not_a_census_of_all_managers',
                               'weekly_standard_deviations_do_not_determine_joint_season_uncertainty',
                               'rounded_means_not_exact_individual_scores_or_rank_thresholds',
                               'no_new_player_labels_or_complete_FPL_seasons'])
    (out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(); print(json.dumps(build(a.root, a.out), indent=2))


if __name__ == '__main__':
    main()
