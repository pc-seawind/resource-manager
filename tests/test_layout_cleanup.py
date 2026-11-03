from pathlib import Path
from types import SimpleNamespace

import pytest

from owned_compute import layout, cleanup


@pytest.mark.parametrize('device',('local','office','wsl','single5090','dual5090'))
def test_device_paths_and_task_cache_are_separated(tmp_path,device):
    roots=layout.roots(device,tmp_path)
    if device in ('single5090','dual5090'):
        assert roots==dict(workspace=tmp_path/'sry/projects',models=tmp_path/'models',data=tmp_path/'sry/data')
    else:
        assert roots==dict(workspace=tmp_path/'work/projects',models=tmp_path/'work/models',data=tmp_path/'work/data')
    assert layout.code('project','revision',tmp_path,device=device).is_relative_to(roots['workspace']/'project')
    env=layout.environment('project','task',tmp_path,device=device)
    assert Path(env['HF_HOME']).is_relative_to(roots['models'])
    assert Path(env['TMPDIR']).is_relative_to(layout.work('project','task',tmp_path,device=device))
    assert layout.receipts(device,tmp_path).is_relative_to(roots['data'])


def test_invalid_namespace_not_silently_normalized(tmp_path):
    with pytest.raises(ValueError):layout.work('../other','task',tmp_path,device='local')
    with pytest.raises(KeyError):layout.roots('unknown',tmp_path)


@pytest.mark.parametrize('active',(True,False))
def test_task_cleanup_requires_physical_exit(tmp_path,monkeypatch,active):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    task=layout.work('project','task',device='local');task.mkdir(parents=True)
    (task/'cache.bin').write_bytes(b'temporary')
    monkeypatch.setattr(cleanup.subprocess,'run',lambda *a,**k:SimpleNamespace(
        stdout='ActiveState=active\nMainPID=123\n' if active else 'ActiveState=inactive\nMainPID=0\n'))
    if active:
        with pytest.raises(ValueError,match='not exited'):cleanup.retire('project','task','local','oc-'+'a'*24+'.service')
        assert task.exists()
    else:
        assert cleanup.retire('project','task','local','oc-'+'a'*24+'.service')['retired'] and not task.exists()
