"""Testes do LogStore: sobretudo a política de retenção em memória (deque com maxlen), que
antes tinha um vazamento — o dict de entradas nunca descartava o que o deque já tinha esquecido."""
import pytest

from proxy_manager.core import logstore as logstore_module
from proxy_manager.core.logstore import LogEntry, LogStore


@pytest.fixture()
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logstore_module, "data_dir", lambda: tmp_path)
    return tmp_path


def test_entries_dict_does_not_leak_beyond_memory_cap(isolated_data_dir):
    store = LogStore(retention_days=1, max_memory_entries=10)

    for i in range(100):
        store.add(LogEntry(dst_host=f"host{i}.example.com"))

    # nunca deve guardar mais entradas "vivas" em memória do que o cap configurado
    assert len(store._entries) == 10
    assert len(store._order) == 10

    # e as entradas restantes devem ser exatamente as mais recentes
    recent = store.recent(limit=10)
    assert [e.dst_host for e in recent] == [f"host{i}.example.com" for i in range(90, 100)]


def test_update_after_eviction_does_not_resurrect_entry(isolated_data_dir):
    store = LogStore(retention_days=1, max_memory_entries=2)

    first = store.add(LogEntry(dst_host="a.example.com"))
    store.add(LogEntry(dst_host="b.example.com"))
    store.add(LogEntry(dst_host="c.example.com"))  # empurra "first" pra fora do cap

    assert first.id not in store._entries
    assert store.update(first.id, status="concluida") is None
