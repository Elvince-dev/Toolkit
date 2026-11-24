from api.supabase import _safe_endpoint


def test_safe_endpoint_omits_storage_object_path():
    assert (
        _safe_endpoint("/storage/v1/object/datasets/user-id/file.csv")
        == "/storage/v1/object/datasets"
    )


def test_safe_endpoint_keeps_database_table_without_query_values():
    assert _safe_endpoint("/rest/v1/messages?select=content") == "/rest/v1/messages"
