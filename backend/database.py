import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

logger = logging.getLogger("database")
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.getenv("DATABASE_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "appdb")

_client = MongoClient(DATABASE_URL)
db = _client[DATABASE_NAME]


def _collection(name: str) -> Collection:
    return db[name]


def create_document(collection_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        now = datetime.utcnow()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        res = _collection(collection_name).insert_one(data)
        data["_id"] = str(res.inserted_id)
        return data
    except PyMongoError as e:
        logger.exception("Mongo insert failed: %s", e)
        raise


def get_documents(
    collection_name: str,
    filter_dict: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    sort: Optional[List] = None,
) -> List[Dict[str, Any]]:
    try:
        cursor = _collection(collection_name).find(filter_dict or {})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        items = []
        for doc in cursor:
            doc["_id"] = str(doc.get("_id"))
            items.append(doc)
        return items
    except PyMongoError as e:
        logger.exception("Mongo query failed: %s", e)
        raise


def update_document(collection_name: str, filter_dict: Dict[str, Any], update: Dict[str, Any]) -> int:
    try:
        update.setdefault("$set", {})
        update["$set"]["updated_at"] = datetime.utcnow()
        res = _collection(collection_name).update_many(filter_dict, update)
        return res.modified_count
    except PyMongoError as e:
        logger.exception("Mongo update failed: %s", e)
        raise


def get_one(collection_name: str, filter_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    doc = _collection(collection_name).find_one(filter_dict)
    if doc:
        doc["_id"] = str(doc.get("_id"))
    return doc
