"""Academic document shapes, independent of the Firestore SDK."""
from copy import deepcopy
from dataclasses import dataclass, field

COLLECTIONS = ("users", "courses", "enrollments", "attendance", "grades", "notices", "timetable")


@dataclass
class AcademicState:
    records: dict = field(default_factory=lambda: {name: {} for name in COLLECTIONS})
    counters: dict = field(default_factory=dict)

    def rows(self, collection):
        return list(self.records[collection].values())

    def get(self, collection, record_id):
        return self.records[collection].get(str(record_id))

    def add(self, collection, values):
        next_id = self.counters.get(collection, 0) + 1
        self.counters[collection] = next_id
        record = {**deepcopy(values), "id": next_id}
        self.records[collection][str(next_id)] = record
        return record

    def remove(self, collection, record_id):
        return self.records[collection].pop(str(record_id), None)
