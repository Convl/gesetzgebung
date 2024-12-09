from gesetzgebung.database import db
from typing import List, ClassVar
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func
import copy

class AppMetadata(db.Model):
    __tablename__ = 'app_metadata'
    key = db.Column(db.String, primary_key=True)
    value = db.Column(db.Text, nullable=False)

class Beschlussfassung(db.Model):
    __tablename__ = 'beschlussfassungen'

    id = db.Column(db.Integer, primary_key=True)
    beschlusstenor = db.Column(db.String(250), nullable=True)
    dokumentnummer = db.Column(db.String(250), nullable=True)
    abstimm_ergebnis_bemerkung = db.Column(db.String(250), nullable=True)
    seite = db.Column(db.String(100), nullable=True)
    positions_id = db.Column(db.Integer, db.ForeignKey('positionen.id'), nullable=False)
    position = db.relationship('Vorgangsposition', back_populates='beschluesse', lazy='select')

class Fundstelle(db.Model):
    __tablename__ = 'fundstellen'

    id = db.Column(db.Integer, primary_key=True)
    dip_id = db.Column(db.String(250), nullable=True)
    dokumentnummer = db.Column(db.String(250), nullable=True)
    drucksachetyp = db.Column(db.String(250), nullable=True)
    herausgeber = db.Column(db.String(250), nullable=True)
    pdf_url = db.Column(db.String(2048), nullable=True)
    urheber = db.Column(db.ARRAY(db.String(250)), nullable=True)
    anfangsseite = db.Column(db.String(250), nullable=True)
    endseite = db.Column(db.String(250), nullable=True)
    anfangsquadrant = db.Column(db.String(250), nullable=True)
    endquadrant = db.Column(db.String(250), nullable=True)
    positions_id = db.Column(db.Integer, db.ForeignKey('positionen.id'), nullable=False)
    position = db.relationship('Vorgangsposition', back_populates='fundstelle', lazy='select')

class Ueberweisung(db.Model):
    __tablename__ = 'ueberweisungen'

    id = db.Column(db.Integer, primary_key=True)
    ausschuss = db.Column(db.String(250), nullable=True)
    ausschuss_kuerzel = db.Column(db.String(250), nullable=True)
    federfuehrung = db.Column(db.Boolean, nullable=True)
    positions_id = db.Column(db.Integer, db.ForeignKey('positionen.id'), nullable=False)
    position = db.relationship('Vorgangsposition', back_populates='ueberweisungen', lazy='select')

class Vorgangsposition(db.Model):
    __tablename__ = 'positionen'

    id = db.Column(db.Integer, primary_key=True)
    dip_id = db.Column(db.Integer, nullable=True)
    vorgangsposition = db.Column(db.String(250), nullable=True)
    zuordnung = db.Column(db.String(250), nullable=True) 
    gang = db.Column(db.Boolean, nullable=True)
    fortsetzung = db.Column(db.Boolean, nullable=True)
    nachtrag = db.Column(db.Boolean, nullable=True)
    dokumentart = db.Column(db.String(100), nullable=True)
    urheber_titel = db.Column(db.ARRAY(db.String(250)), nullable=True) 
    abstract = db.Column(db.Text, nullable=True) 
    datum = db.Column(db.Date, nullable=True)
    aktualisiert = db.Column(db.DateTime, nullable=True)
    
    ueberweisungen : ClassVar[List[Ueberweisung]] = db.relationship('Ueberweisung', back_populates='position', lazy='select')
    fundstelle : ClassVar[Fundstelle] = db.relationship('Fundstelle', back_populates='position', lazy='select', uselist=False)
    beschluesse : ClassVar[List[Beschlussfassung]] = db.relationship('Beschlussfassung', back_populates='position', lazy='select')
    
    vorgangs_id = db.Column(db.Integer, db.ForeignKey('vorhaben.id'), nullable=False)
    gesetz = db.relationship('GesetzesVorhaben', back_populates='vorgangspositionen', lazy='select')

class Verkuendung(db.Model):
    __tablename__ = 'verkuendungen'

    id = db.Column(db.Integer, primary_key=True)
    seite = db.Column(db.String(250), nullable=True)
    verkuendungsdatum = db.Column(db.Date, nullable=True)
    ausfertigungsdatum = db.Column(db.Date, nullable=True)
    pdf_url = db.Column(db.String(2048), nullable=True)
    fundstelle = db.Column(db.String(250), nullable=True)

    vorgangs_id = db.Column(db.Integer, db.ForeignKey('vorhaben.id'), nullable=False)
    vorhaben = db.relationship('GesetzesVorhaben', back_populates='verkuendung', lazy='select') # TODO rename these, always to the form of verkuendung_vorhaben

class Inkrafttreten(db.Model):
    __tablename__ = 'inkrafttreten'

    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, nullable=True)
    erlaeuterung = db.Column(db.Text)

    vorgangs_id = db.Column(db.Integer, db.ForeignKey('vorhaben.id'), nullable=False)
    inkrafttreten_vorhaben = db.relationship('GesetzesVorhaben', back_populates='inkrafttreten', lazy='select')


class GesetzesVorhaben(db.Model):
    __tablename__ = 'vorhaben'

    id = db.Column(db.Integer, primary_key=True)
    dip_id = db.Column(db.Integer, nullable=True)
    abstract = db.Column(db.Text, nullable=True)
    beratungsstand = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[]) # TODO: change to a string, change daily_update and routes accordingly
    sachgebiet = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    wahlperiode = db.Column(db.SmallInteger, nullable=True)
    zustimmungsbeduerftigkeit = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    initiative = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    aktualisiert = db.Column(db.DateTime, nullable=True)
    inkrafttreten = db.Column(db.ARRAY(db.Date), nullable=True)
    titel = db.Column(db.Text, nullable=True)
    datum = db.Column(db.Date, nullable=True)
    vorgangspositionen : ClassVar[List[Vorgangsposition]] = db.relationship('Vorgangsposition', back_populates='gesetz', lazy='select')
    verkuendung : ClassVar[List[Verkuendung]] = db.relationship('Verkuendung', back_populates='vorhaben', lazy='select') 
    inkrafttreten: ClassVar[List[Inkrafttreten]] = db.relationship('Inkrafttreten', back_populates='inkrafttreten_vorhaben', lazy='select')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.beratungsstand = self.beratungsstand or []

def get_all_laws() -> List[GesetzesVorhaben]:
    return GesetzesVorhaben.query.all()

def get_law_by_id(id) -> GesetzesVorhaben:
    id = int(id)
    # return db.session.query(GesetzesVorhaben).options(joinedload(GesetzesVorhaben.vorgangspositionen)).filter(GesetzesVorhaben.id == id).first()
    return db.session.query(GesetzesVorhaben).options(
        joinedload(GesetzesVorhaben.vorgangspositionen).joinedload(Vorgangsposition.beschluesse),
        joinedload(GesetzesVorhaben.vorgangspositionen).joinedload(Vorgangsposition.fundstelle),
        joinedload(GesetzesVorhaben.vorgangspositionen).joinedload(Vorgangsposition.ueberweisungen),
        joinedload(GesetzesVorhaben.verkuendung),
        joinedload(GesetzesVorhaben.inkrafttreten)
        ).filter(GesetzesVorhaben.id == id).first()

def get_law_by_dip_id(id) -> GesetzesVorhaben:
    id = int(id)
    return db.session.query(GesetzesVorhaben).filter(GesetzesVorhaben.dip_id == id).one_or_none()


def get_position_by_dip_id(id) -> Vorgangsposition:
    id = int(id)
    return db.session.query(Vorgangsposition).options(
        joinedload(Vorgangsposition.beschluesse), 
        joinedload(Vorgangsposition.fundstelle), 
        joinedload(Vorgangsposition.ueberweisungen)).filter(Vorgangsposition.dip_id == id).first()   

def get_last_update():
    # return db.session.query(AppMetadata).filter_by(key="last_update").one_or_none()
    return "2024-12-01T20:00:00"

def set_last_update(update):
    if (last_update := db.session.query(AppMetadata).filter_by(key='last_update').one_or_none()):
        last_update.value = update
    else:
        last_update = AppMetadata(key="last_update", value=update)
        db.session.add(last_update)
    db.session.commit()