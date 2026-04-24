"""DB Query Skill：資料庫查詢（SQLite + MongoDB）。"""

import os
import sqlite3
from pathlib import Path

from pydantic import Field

from ark_agent_core.skills.base import BaseSkill, SkillParam, SkillResult, SkillType


class DbQueryInput(SkillParam):
    """DB Query 輸入參數。"""
    query_type: str = Field(default="vip", description="查詢類型：vip（VIP>=5 大客）/ all（全部玩家）")
    vip_level: int = Field(default=5, description="最低 VIP 等級，預設 5")
    limit: int = Field(default=10, description="回傳筆數，預設 10")


class DbQuerySkill(BaseSkill):
    skill_id = "db_query"
    skill_type = SkillType.PYTHON
    description = "查詢玩家資料庫。預設查詢 VIP>=5 大客的消費狀況（按 LTV 排序 Top 10）。不需要額外參數即可直接呼叫。"
    input_schema = DbQueryInput

    async def execute(self, params: dict) -> SkillResult:
        query_type = params.get("query_type", "vip")
        try:
            # 根據 query_type 建構 MongoDB 查詢
            if query_type == "vip":
                vip_level = int(params.get("vip_level", 5))
                mongo_filter = {"vip_level": {"$gte": vip_level}}
                sort_spec = [("ltv.total_spend", -1)]
            elif query_type == "all":
                mongo_filter = {}
                sort_spec = [("vip_level", -1)]
            else:
                mongo_filter = params.get("filter", {})
                sort_spec = params.get("sort", [])

            limit = int(params.get("limit", 10))

            # 如果有 sql 參數，走 SQLite
            if params.get("sql"):
                return await self._query_sqlite(params)

            # 預設走 MongoDB
            mongo_params = {
                "db_path": params.get("db_path", f"{os.environ.get('MONGO_HOST', 'localhost:27017')}/player_profile"),
                "username": params.get("username", os.environ.get("MONGO_USER", "")),
                "password": params.get("password", os.environ.get("MONGO_PASS", "")),
                "auth_source": params.get("auth_source", "admin"),
                "collection": params.get("collection", "player_profiles"),
                "filter": mongo_filter,
                "sort": sort_spec,
                "limit": limit,
            }
            return await self._query_mongo(mongo_params)
        except Exception as e:
            return SkillResult(success=False, error=f"Query failed: {e}")

    async def _query_sqlite(self, params: dict) -> SkillResult:
        """SQLite 查詢。"""
        sql = params.get("sql", "")
        db_path = params.get("db_path", "./data/app.db")
        query_params = params.get("params", [])

        if not sql:
            return SkillResult(success=False, error="SQL 查詢語句不可為空")

        db_file = Path(db_path)
        if not db_file.exists():
            return SkillResult(success=False, error=f"Database not found: {db_path}")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, query_params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return SkillResult(
            success=True,
            data={"rows": rows, "count": len(rows)},
            metadata={"db_type": "sqlite", "sql": sql},
        )

    async def _query_mongo(self, params: dict) -> SkillResult:
        """MongoDB 文件查詢。"""
        from pymongo import MongoClient

        db_path = params.get("db_path", "")
        collection_name = params.get("collection", "")
        query_filter = params.get("filter", {})
        projection = params.get("projection", {})
        sort_spec = params.get("sort", [])
        limit = int(params.get("limit", 50))

        if not db_path or not collection_name:
            return SkillResult(success=False, error="MongoDB 需要 db_path（URI）和 collection")

        # 解析 URI：mongodb://user:pass@host:port/dbname
        # 或簡易格式：host:port/dbname
        if db_path.startswith("mongodb://"):
            uri = db_path
            db_name = uri.rsplit("/", 1)[-1].split("?")[0]
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        else:
            # 簡易格式：host/dbname 或 host:port/dbname
            parts = db_path.split("/")
            host_port = parts[0]
            db_name = parts[1] if len(parts) > 1 else "test"
            host = host_port.split(":")[0]
            port = int(host_port.split(":")[1]) if ":" in host_port else 27017
            auth_user = params.get("username", "")
            auth_pass = params.get("password", "")
            auth_source = params.get("auth_source", "admin")
            kwargs = {"serverSelectionTimeoutMS": 5000}
            if auth_user:
                kwargs.update(username=auth_user, password=auth_pass, authSource=auth_source)
            client = MongoClient(host, port, **kwargs)

        db = client[db_name]
        coll = db[collection_name]

        cursor = coll.find(query_filter, projection or None)
        if sort_spec:
            cursor = cursor.sort(sort_spec)
        cursor = cursor.limit(limit)

        rows = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            rows.append(doc)

        client.close()
        return SkillResult(
            success=True,
            data={"rows": rows, "count": len(rows)},
            metadata={"db_type": "mongodb", "collection": collection_name, "filter": str(query_filter)},
        )
