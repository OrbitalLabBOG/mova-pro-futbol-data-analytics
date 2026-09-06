"""Measure archived label gaps without imputing missing values or admitting data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from experiments.data_ground_truth.differential_audit import quality, read_tables
from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked

DATABASE_SHA = 'e4f1e637702f69cfa513a5719b05f87bb0aab47ddd2cd4864b40d567c1ac9f80'
SOURCE_SHAS = (
    '25fc385463b3098ea79d845c0ade24ce72ce5ebe26d39edf9dd1246af2fb1e67',
    '9c2b09fe44435264c64fa5a4ea48c6ad1da49aa6623fcf46f46480e0014a55c4',
)


def label_coverage(frame: pd.DataFrame) -> dict:
    """The denominator is archived rows, never the unknown player universe."""
    minutes = frame.minutes.notna()
    points = frame.total.notna()
    return dict(
        archived_rows=len(frame),
        both_labels=int((minutes & points).sum()),
        minutes_only=int((minutes & ~points).sum()),
        points_only=int((~minutes & points).sum()),
        neither_label=int((~minutes & ~points).sum()),
        positive_minutes_missing_points=int((frame.minutes.gt(0) & ~points).sum()),
        explicit_zero_points=int(frame.total.eq(0).sum()),
        explicit_negative_points=int(frame.total.lt(0).sum()),
        explicit_zero_minutes=int(frame.minutes.eq(0).sum()),
        both_label_fraction_of_archive=(float((minutes & points).mean()) if len(frame) else None),
    )


def build(database: Path, source_root: Path, out: Path) -> dict:
    checked(database, DATABASE_SHA)
    for sha in SOURCE_SHAS:
        checked(source_root / 'objects' / sha, sha)
    tables = read_tables(database)
    archived_quality = quality(tables)
    seasons = {}
    windows = []
    for code in (12, 13, 14):
        frame = tables['player_match'].loc[lambda x: x.season.eq(code)]
        season = f'{1999 + code}-{str(2000 + code)[-2:]}'
        seasons[season] = dict(
            **label_coverage(frame),
            fixture_count=archived_quality[str(code)]['raw_fixture_rows'],
            fixtures_with_both_labels=archived_quality[str(code)]['fixtures_with_both_labels'],
            comparable_player_totals=archived_quality[str(code)]['comparable_player_totals'],
            player_total_disagreements=archived_quality[str(code)]['player_total_disagreements'],
            gameweeks_without_any_both_labels=[
                gw for gw in range(1, 39)
                if gw not in archived_quality[str(code)]['gameweeks_with_both_labels']
            ],
        )
        for gw in range(1, 39):
            windows.append(dict(season=season, gameweek=gw,
                                **label_coverage(frame.loc[frame.gameweek.eq(gw)])))
    report = dict(
        version='historical-null-coverage-v1',
        database_sha256=DATABASE_SHA,
        source_code_sha256=list(SOURCE_SHAS),
        implementation_sha256=digest(Path(__file__).read_bytes()),
        seasons=seasons,
        zero_imputation_authorized=False,
        new_label_rows=0,
        new_complete_seasons=0,
        training_admitted=False,
        limitations=[
            'archive_row_coverage_not_registered_player_population_coverage',
            'inspected_insert_paths_write_total_unconditionally_but_omit_some_zero_components',
            'source_code_does_not_prove_which_writer_created_each_archived_row',
            'annual_sum_agreement_cannot_identify_missing_per_match_labels',
            'season_metadata_may_be_partial_not_final',
            'no_predeadline_availability_proof',
        ],
    )
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(windows, indent=2, allow_nan=False) + '\n'
    (out / 'windows.json').write_text(payload)
    report['windows_sha256'] = digest(payload.encode())
    (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.database, args.source_root, args.out), indent=2))


if __name__ == '__main__':
    main()
