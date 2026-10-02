"""Cihaz erişim yönlendirme katmanı — yerel mi, fabrika ajanı mı?

Mikro ERP / PDKS / yayıcı gibi fabrika-yerel op'lar buradan geçer:
- AGENT_MODE='local' (varsayılan): op doğrudan bu makinede çalışır (agent_ops.OPS) — mevcut davranış, değişmez.
- AGENT_MODE='remote' (merkez buluta taşınınca): op, fabrikadaki ajana WS ile iletilir ve sonucu beklenir.

call_sync: senkron cihaz kodu için (çoğu kod threadpool/thread'de senkron çalışır).
"""
from . import config, agent_ops


def online():
    """Yerel modda her zaman True; uzak modda ajan bağlıysa True."""
    if config.AGENT_MODE != 'remote':
        return True
    from . import agent_hub
    return agent_hub.online()


def call_sync(op, args=None, timeout=25):
    if config.AGENT_MODE == 'remote':
        from . import agent_hub
        return agent_hub.call_sync(op, args, timeout)
    fn = agent_ops.OPS.get(op)
    if not fn:
        raise RuntimeError(f'Bilinmeyen cihaz op: {op}')
    return fn(args or {})
