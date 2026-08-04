from collections import deque

class FairQueue:
    """Small deterministic weighted round-robin admission queue."""
    def __init__(self, per_key_limit=100): self.per_key_limit = per_key_limit; self._queues = {}; self._keys = deque()
    def enqueue(self, key, item):
        queue = self._queues.setdefault(key, deque())
        if len(queue) >= self.per_key_limit: return False
        queue.append(item)
        if key not in self._keys: self._keys.append(key)
        return True
    def pop(self):
        if not self._keys: return None
        key = self._keys.popleft(); item = self._queues[key].popleft()
        if self._queues[key]: self._keys.append(key)
        else: del self._queues[key]
        return key, item
    def __len__(self): return sum(len(queue) for queue in self._queues.values())
