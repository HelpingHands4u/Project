"""Firestore document repository for a small academic project.

Academic mutations read a consistent snapshot and update a shared revision in
the same transaction. This serializes conflict checks across Vercel instances.
Transaction callbacks must not call external services (Firebase Auth, email).
"""
from copy import deepcopy

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from backend.app.models.state import AcademicState, COLLECTIONS


class FirestoreStore:
    def __init__(self, client):
        self.client = client
        self.root = client.collection("uams").document("data")

    def collection(self, name):
        return self.root.collection(name)

    def _read(self, transaction):
        meta = self.collection("meta").document("state").get(transaction=transaction).to_dict() or {}
        records = {
            name: {doc.id: doc.to_dict() for doc in self.collection(name).stream(transaction=transaction)}
            for name in COLLECTIONS
        }
        return AcademicState(records, meta.get("counters", {})), meta

    def snapshot(self):
        @firestore.transactional
        def read(transaction):
            return self._read(transaction)[0]
        return read(self.client.transaction())

    def mutate(self, callback):
        @firestore.transactional
        def write(transaction):
            state, meta = self._read(transaction)
            previous = deepcopy(state.records)
            result = callback(state)
            for name in COLLECTIONS:
                for key, record in state.records[name].items():
                    if previous[name].get(key) != record:
                        transaction.set(self.collection(name).document(key), record)
                for key in previous[name].keys() - state.records[name].keys():
                    transaction.delete(self.collection(name).document(key))
            transaction.set(self.collection("meta").document("state"), {
                "counters": state.counters, "revision": meta.get("revision", 0) + 1,
            })
            return deepcopy(result)
        return write(self.client.transaction())

    def get_user(self, user_id):
        return self.collection("users").document(str(user_id)).get().to_dict()

    def user_for_uid(self, uid):
        documents = list(self.collection("users").where(
            filter=FieldFilter("firebase_uid", "==", uid)).limit(1).stream())
        return documents[0].to_dict() if documents else None

    def save_session(self, token_hash, session):
        self.collection("sessions").document(token_hash).set(session)

    def get_session(self, token_hash):
        return self.collection("sessions").document(token_hash).get().to_dict()

    def delete_session(self, token_hash):
        self.collection("sessions").document(token_hash).delete()

    def health(self):
        self.collection("meta").document("state").get()
