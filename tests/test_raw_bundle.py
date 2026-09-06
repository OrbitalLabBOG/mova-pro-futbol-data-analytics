import pytest

from experiments.data_ground_truth.raw import digest
from experiments.data_ground_truth.raw_bundle import build, canonical, restore, verify_bundle


def bundle(tmp_path, paths=('raw-a/objects/x', 'raw-b/objects/x')):
    package = tmp_path / 'bundle'; package.mkdir(); (package / 'objects').mkdir()
    payload = b'original raw bytes'; sha = digest(payload)
    (package / 'objects' / sha).write_bytes(payload)
    descriptor = dict(version='test', files=[dict(path=p, sha256=sha, bytes=len(payload)) for p in paths])
    (package / 'manifest.json').write_bytes(canonical(dict(descriptor, bundle_id=digest(canonical(descriptor)))))
    return package, sha


def test_restored_copies_are_independent_and_destination_is_not_overwritten(tmp_path):
    package, sha = bundle(tmp_path)
    out = tmp_path / 'restored'
    assert restore(package, out)['restored_files'] == 2
    (out / 'raw-a/objects/x').write_bytes(b'changed')
    assert (out / 'raw-b/objects/x').read_bytes() == (package / 'objects' / sha).read_bytes()
    with pytest.raises(ValueError, match='new destination'):
        restore(package, out)


def test_same_size_corruption_is_rejected_before_restoration(tmp_path):
    package, sha = bundle(tmp_path)
    original = (package / 'objects' / sha).read_bytes()
    (package / 'objects' / sha).write_bytes(b'x' * len(original))
    out = tmp_path / 'restored'
    with pytest.raises(ValueError, match='corruption'):
        restore(package, out)
    assert not out.exists()


@pytest.mark.parametrize('path', ['../escaped', '/absolute', 'a/../escaped', 'a\\escaped'])
def test_rehashed_manifest_cannot_escape_restore_root(tmp_path, path):
    package, _ = bundle(tmp_path, (path,))
    with pytest.raises(ValueError, match='unsafe'):
        verify_bundle(package)


def test_output_cannot_contaminate_raw_inventory(tmp_path):
    with pytest.raises(ValueError, match="raw acquisition namespace"):
        build(tmp_path, tmp_path / "raw-bundles")
