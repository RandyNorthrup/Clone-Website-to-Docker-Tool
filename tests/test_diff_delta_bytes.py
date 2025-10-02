import os, tempfile, shutil, json
from cw2dt_core import _snapshot_file_hashes, _compute_diff

def test_diff_delta_bytes_and_changed_alias():
    tmp = tempfile.mkdtemp(prefix='cw2dt_diff_')
    try:
        # v1
        with open(os.path.join(tmp,'a.txt'),'w',encoding='utf-8') as f: f.write('AAAA')
        with open(os.path.join(tmp,'b.txt'),'w',encoding='utf-8') as f: f.write('BBBB')
        snap1={'files': _snapshot_file_hashes(tmp)}
        # modify a, remove b, add c
        with open(os.path.join(tmp,'a.txt'),'w',encoding='utf-8') as f: f.write('AAAAXXXX')
        os.remove(os.path.join(tmp,'b.txt'))
        with open(os.path.join(tmp,'c.txt'),'w',encoding='utf-8') as f: f.write('C')
        snap2={'files': _snapshot_file_hashes(tmp)}
        diff=_compute_diff(snap1,snap2)
        # Assertions
        assert 'c.txt' in diff['added']
        assert 'b.txt' in diff['removed']
        mod_paths=[m['path'] for m in diff['modified']]
        assert 'a.txt' in mod_paths
        # delta_bytes should equal new - old size
        mod_entry=[m for m in diff['modified'] if m['path']=='a.txt'][0]
        assert mod_entry['delta_bytes'] == (mod_entry['new_size'] - mod_entry['old_size'])
        # changed alias includes modified paths
        assert 'a.txt' in diff['changed']
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
