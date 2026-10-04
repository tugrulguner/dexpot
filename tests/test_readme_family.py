"""Guard consistent family presentation in the README."""

import re
from pathlib import Path


def test_readme_family_presentation():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    hero = re.search(r"<img\b[^>]+>", readme)
    assert hero is not None
    assert 'width="600"' in hero.group()
    resource = re.search(r'<p align="center">(Part of .*?)</p>', readme)
    assert resource is not None
    assert 'Part of <a href="https://modepot.io/">ModePot</a>.' in resource.group(1)
    assert '<a href="https://dexpot.modepot.io/">Project website</a>' in resource.group(1)
    assert '<a href="https://tugrul.modepot.io/">Created by Tugrul Guner</a>' in resource.group(1)
    assert 'href="https://dexpot.modepot.io/quick-start/"' in readme[:2500]
    assert 'href="https://dexpot.modepot.io/playground/"' in readme[:2500]
    assert 'href="https://dexpot.modepot.io/current-boundaries/"' in readme[:2500]
    assert "Synchronous APIs. GIL or free-threaded." in readme[:2500]
