from app import toolchains
from app.config import settings


def test_go_paths_are_per_employee_and_outside_the_shared_toolchain():
    first, second = toolchains.agent_env(1), toolchains.agent_env(2)
    assert first["GOPATH"] != second["GOPATH"]
    assert first["GOMODCACHE"] == f"{first['GOPATH']}/pkg/mod"
    assert toolchains.gopath(1).parent == settings.toolchains_dir / "gopath"
    assert toolchains.bin_dir() not in toolchains.gopath(1).parents
