from app.infrastructure.json_utils import json_loads_dict_list, json_loads_list


class TestJsonLoadsList:
    def test_none_returns_empty(self) -> None:
        assert json_loads_list(None) == []

    def test_empty_string_returns_empty(self) -> None:
        assert json_loads_list("") == []

    def test_invalid_json_returns_empty(self) -> None:
        assert json_loads_list("[1, 2") == []

    def test_non_list_returns_empty(self) -> None:
        assert json_loads_list("{}") == []

    def test_valid_list_returned(self) -> None:
        assert json_loads_list("[1, 2]") == [1, 2]


class TestJsonLoadsDictList:
    def test_filters_non_dict_items(self) -> None:
        assert json_loads_dict_list('[{"a": 1}, 2, "x"]') == [{"a": 1}]

    def test_none_returns_empty(self) -> None:
        assert json_loads_dict_list(None) == []

    def test_all_dicts_preserved(self) -> None:
        assert json_loads_dict_list('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]
