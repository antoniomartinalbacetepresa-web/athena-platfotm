"""Resource preflight must remain read-only and never authorize trading."""
from unittest.mock import patch

from scripts.runtime_resource_preflight import collect_resources, main


def test_preflight_never_claims_production_or_trading_ready(tmp_path):
    report = collect_resources(storage_path=tmp_path, memory_bytes=16 * 1024 ** 3, cpu_count=4)
    assert report["productionReady"] is False
    assert report["tradingEnabled"] is False
    assert report["logicalCpuCount"] == 4
    assert report["physicalMemoryBytes"] == 16 * 1024 ** 3


def test_low_resources_and_unknown_capacity_report_explicit_warnings(tmp_path):
    with patch("scripts.runtime_resource_preflight.shutil.disk_usage") as disk:
        disk.return_value.free = 1
        disk.return_value.total = 100
        low = collect_resources(storage_path=tmp_path, memory_bytes=1, cpu_count=1)
        unknown = collect_resources(storage_path=tmp_path, memory_bytes=0, cpu_count=0)
    assert set(low["warnings"]) == {
        "limited_cpu_capacity", "limited_memory_capacity", "limited_free_disk"
    }
    assert "limited_free_disk" in unknown["warnings"]


def test_json_cli_does_not_require_network_or_broker(tmp_path, capsys):
    assert main(["--storage-path", str(tmp_path), "--json"]) == 0
    output = capsys.readouterr().out
    assert '"tradingEnabled": false' in output
    assert '"productionReady": false' in output


def test_vps_cgroup_cap_is_used_instead_of_host_ram(tmp_path):
    with patch("scripts.runtime_resource_preflight.sys.platform", "linux"), \\
         patch("scripts.runtime_resource_preflight._linux_cgroup_memory_limit", return_value=2 * 1024 ** 3):
        report = collect_resources(storage_path=tmp_path, memory_bytes=32 * 1024 ** 3, cpu_count=8)
    assert report["physicalMemoryBytes"] == 32 * 1024 ** 3
    assert report["effectiveMemoryBytes"] == 2 * 1024 ** 3
    assert report["containerMemoryLimitBytes"] == 2 * 1024 ** 3
    assert "container_memory_limited" in report["warnings"]
    assert "limited_memory_capacity" in report["warnings"]
    assert report["productionReady"] is False


def test_unlimited_cgroup_does_not_reduce_memory(tmp_path):
    with patch("scripts.runtime_resource_preflight.sys.platform", "linux"), \\
         patch("scripts.runtime_resource_preflight._linux_cgroup_memory_limit", return_value=None):
        report = collect_resources(storage_path=tmp_path, memory_bytes=16 * 1024 ** 3)
    assert report["effectiveMemoryBytes"] == 16 * 1024 ** 3
    assert "container_memory_limited" not in report["warnings"]
