import pytest

from fma.corpus import CorpusMissing, default_index


@pytest.fixture(scope="session")
def index():
    try:
        return default_index()
    except CorpusMissing as e:
        pytest.skip(f"corpus not built: {e}")
