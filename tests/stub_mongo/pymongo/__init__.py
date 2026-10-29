class _FakeCursor(list):
    def sort(self, key=None, direction=1, *a, **k):
        if key:
            list.sort(self, key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

class FakeCollection:
    def __init__(self):
        self._docs = []
        self._next_id = 1

    def _matches(self, doc, query):
        for k, v in (query or {}).items():
            if doc.get(k) != v:
                return False
        return True

    def find(self, query=None, *a, **k):
        return _FakeCursor([d for d in self._docs if self._matches(d, query or {})])

    def find_one(self, query=None):
        for d in self._docs:
            if self._matches(d, query or {}):
                return d
        return None

    def count_documents(self, query=None):
        return len(self.find(query))

    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = f"fakeid{self._next_id}"
        self._next_id += 1
        self._docs.append(doc)
        class R:
            inserted_id = doc["_id"]
        return R()

    def delete_one(self, query):
        doc = self.find_one(query)
        if doc is not None:
            self._docs.remove(doc)

    def update_one(self, query, update):
        doc = self.find_one(query)
        if doc is not None:
            doc.update(update.get("$set", {}))

class FakeDB(dict):
    def __getitem__(self, name):
        if name not in self:
            super().__setitem__(name, FakeCollection())
        return super().__getitem__(name)

class MongoClient:
    def __init__(self, *a, **k):
        self._db = FakeDB()
    def get_default_database(self):
        return self._db
