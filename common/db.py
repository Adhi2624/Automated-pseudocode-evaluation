"""MongoDB helpers shared by the web app and the grader."""
from pymongo import MongoClient
from pymongo.collection import Collection

from .config import Settings, get_settings


def get_client(settings: Settings = None) -> MongoClient:
    settings = settings or get_settings()
    return MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)


def get_collection(settings: Settings = None, client: MongoClient = None) -> Collection:
    settings = settings or get_settings()
    client = client or get_client(settings)
    return client[settings.mongo_db][settings.mongo_collection]
