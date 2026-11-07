import subprocess

import pytest

import deploy


def test_pinned_deployment_resolves_an_existing_commit():
    revision='156aa1468082eed9ee62f052e8a6ff96650e9df9'
    assert deploy.resolve_revision(revision)==revision


def test_nonexistent_revision_cannot_be_deployed():
    with pytest.raises(subprocess.CalledProcessError):
        deploy.resolve_revision('not-an-existing-deployment-revision')
