"""Conexão com MongoDB e coleções usadas pelo AdControl."""

import os

from pymongo import MongoClient


MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/adcontrol_web")
cliente = MongoClient(MONGO_URI)
banco = cliente.get_default_database()

campanhas_collection = banco["campanhas"]
produtos_collection = banco["produtos"]
anuncios_collection = banco["anuncios"]
investimentos_collection = banco["investimentos"]
metricas_collection = banco["metricas"]
usuarios_collection = banco["usuarios"]
