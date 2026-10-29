from bson.errors import InvalidId

class ObjectId(str):
    # imita o comportamento do bson real: texto fora do formato gera InvalidId
    def __new__(cls, valor):
        if not str(valor).startswith("fakeid"):
            raise InvalidId(f"{valor} nao e um ObjectId valido")
        return str.__new__(cls, valor)
