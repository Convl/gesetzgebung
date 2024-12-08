import copy

class GGVorgang:
    def __init__(self, id=None, abstract=None, beratungsstand=None, sachgebiet=[], wahlperiode=None, zustimmungsbeduerftigkeit=[], initiative=[], aktualisiert=None, titel=None, datum=None):
        self.id = id
        self.abstract = abstract
        self.beratungsstand = beratungsstand
        self.sachgebiet = sachgebiet
        self.wahlperiode = wahlperiode
        self.zustimmungsbeduerftigkeit = zustimmungsbeduerftigkeit
        self.initiative = initiative
        self.aktualisiert = aktualisiert
        self.titel = titel
        self.datum = datum
    
    @classmethod
    def from_iterable(cls, iterable):
        attributes = [attr for attr in vars(cls()) if not attr.startswith("__")]
        values = [copy.deepcopy(value) if isinstance(value, (list, dict)) else value for value in iterable]
        return GGVorgang(**dict(zip(attributes, values)))