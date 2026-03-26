from __future__ import annotations

from atb_cli.registry import latest_version, load_registry, ordered_versions, resolve_release


def test_load_registry_from_osf_source(monkeypatch) -> None:
    responses = {
        "https://api.osf.io/v2/nodes/h7wzy/files/osfstorage/": {
            "data": [
                {
                    "attributes": {
                        "kind": "file",
                        "name": "atb_2026-03-01.parquet",
                        "date_modified": "2026-03-02T12:34:56Z",
                    },
                    "links": {
                        "download": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-1"
                    },
                },
                {
                    "attributes": {
                        "kind": "file",
                        "name": "atb_2026-02-01.parquet",
                        "date_modified": "2026-02-02T12:34:56Z",
                    },
                    "links": {
                        "download": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-2"
                    },
                },
            ],
            "links": {"next": None},
        }
    }

    def fake_fetch_json(url: str, *, timeout: int = 60):
        return responses[url]

    monkeypatch.setattr("atb_cli.registry.fetch_json", fake_fetch_json)

    registry = load_registry("https://osf.io/h7wzy/files/osfstorage")

    assert latest_version(registry) == "2026-03-01"
    release = resolve_release(registry, "2026-02-01")
    assert release.parquet_url.endswith("file-2")
    assert registry["source"] == "osf"
    assert registry["node_id"] == "h7wzy"



def test_load_registry_from_osf_folder_relationship(monkeypatch) -> None:
    responses = {
        "https://api.osf.io/v2/nodes/h7wzy/files/osfstorage/": {
            "data": [
                {
                    "attributes": {"kind": "folder", "name": "nested"},
                    "relationships": {
                        "files": {
                            "links": {
                                "related": {
                                    "href": "https://api.osf.io/v2/nodes/h7wzy/files/osfstorage/abcdef/"
                                }
                            }
                        }
                    },
                }
            ],
            "links": {"next": None},
        },
        "https://api.osf.io/v2/nodes/h7wzy/files/osfstorage/abcdef/": {
            "data": [
                {
                    "attributes": {
                        "kind": "file",
                        "name": "release_v1.2.3.parquet",
                        "date_modified": "2026-03-02T12:34:56Z",
                    },
                    "links": {
                        "download": {
                            "href": "https://files.osf.io/v1/resources/h7wzy/providers/osfstorage/file-3"
                        }
                    },
                }
            ],
            "links": {"next": None},
        },
    }

    def fake_fetch_json(url: str, *, timeout: int = 60):
        return responses[url]

    monkeypatch.setattr("atb_cli.registry.fetch_json", fake_fetch_json)

    registry = load_registry("osf://h7wzy")

    assert latest_version(registry) == "v1.2.3"
    release = resolve_release(registry)
    assert release.parquet_url.endswith("file-3")


def test_ordered_versions_keeps_latest_last() -> None:
    registry = {
        "latest": "2026-03-01",
        "versions": {
            "2026-03-01": {"release_date": "2026-03-02T12:34:56Z"},
            "2026-02-01": {"release_date": "2026-02-02T12:34:56Z"},
            "2026-01-01": {"release_date": "2026-01-02T12:34:56Z"},
        },
    }

    assert ordered_versions(registry) == ["2026-01-01", "2026-02-01", "2026-03-01"]
