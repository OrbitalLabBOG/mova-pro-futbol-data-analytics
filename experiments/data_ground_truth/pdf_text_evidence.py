"""Reproduce a pinned PDF text extraction in an isolated pypdf environment."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.training_dataset import checked


def extract(root, pdf_sha):
    import pypdf
    if pypdf.__version__ != '6.7.4':
        raise ValueError('reproduction requires pypdf 6.7.4')
    data = checked(root/'objects'/pdf_sha, pdf_sha)
    pages = [page.extract_text() for page in pypdf.PdfReader(io.BytesIO(data)).pages]
    text = '\n\f\n'.join(pages).encode()
    sha = digest(text)
    (root/'objects'/sha).write_bytes(text)
    report = dict(key='fifa2014-text', sha256=sha, bytes=len(text), source_sha256=pdf_sha,
                  extractor='pypdf', extractor_version=pypdf.__version__, pages=len(pages),
                  implementation_sha256=digest(Path(__file__).read_bytes()),
                  available_at=None, eligible_predeadline=False)
    (root/'extraction.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pdf-sha', required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.root, args.pdf_sha), indent=2))


if __name__ == '__main__':
    main()
