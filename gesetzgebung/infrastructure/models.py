import datetime
from typing import ClassVar, List

from gesetzgebung.infrastructure.config import db


class AppMetadata(db.Model):
    __tablename__ = "app_metadata"
    key = db.Column(db.String, primary_key=True)
    value = db.Column(db.Text, nullable=False)


class Beschlussfassung(db.Model):
    __tablename__ = "beschlussfassungen"

    id = db.Column(db.Integer, primary_key=True)
    beschlusstenor = db.Column(db.String(250), nullable=True)
    dokumentnummer = db.Column(db.String(250), nullable=True)
    abstimm_ergebnis_bemerkung = db.Column(db.String(250), nullable=True)
    seite = db.Column(db.String(100), nullable=True)
    positions_id = db.Column(db.Integer, db.ForeignKey("positionen.id"), nullable=False)
    position = db.relationship("Vorgangsposition", back_populates="beschluesse", lazy=True)


class BeschlussfassungDisplay:  # not an actual database class, used for modifications before display
    def __init__(self, beschluss):
        self.beschlusstenor = beschluss.beschlusstenor
        self.dokumentnummer = beschluss.dokumentnummer
        self.abstimm_ergebnis_bemerkung = beschluss.abstimm_ergebnis_bemerkung
        self.seite = beschluss.seite
        self.positions_id = beschluss.positions_id


class Dokument(db.Model):
    __tablename__ = "dokumente"
    id = db.Column(db.Integer, primary_key=True)
    pdf_url = db.Column(db.Text, nullable=False)
    markdown = db.Column(db.Text, nullable=True)
    conversion_date = db.Column(db.DateTime, nullable=True)
    vorgangsposition = db.Column(db.String(250), nullable=True)
    herausgeber = db.Column(db.String(250), nullable=True)
    anfangsseite = db.Column(db.Integer, nullable=True)
    endseite = db.Column(db.Integer, nullable=True)

    fundstelle_id = db.Column(db.Integer, db.ForeignKey("fundstellen.id"), nullable=False, unique=True)
    fundstelle = db.relationship(
        "Fundstelle",
        back_populates="dokument",
        lazy=True,
    )


class Fundstelle(db.Model):
    __tablename__ = "fundstellen"

    id = db.Column(db.Integer, primary_key=True)
    dip_id = db.Column(db.String(250), nullable=True)
    dokumentnummer = db.Column(db.String(250), nullable=True)
    drucksachetyp = db.Column(db.String(250), nullable=True)
    herausgeber = db.Column(db.String(250), nullable=True)
    pdf_url = db.Column(db.String(2048), nullable=True)
    mapped_pdf_url = db.Column(db.String(2048), nullable=True)
    urheber = db.Column(db.ARRAY(db.String(250)), nullable=True)
    anfangsseite = db.Column(db.Integer, nullable=True)
    endseite = db.Column(db.Integer, nullable=True)
    anfangsseite_mapped = db.Column(db.Integer, nullable=True)
    endseite_mapped = db.Column(db.Integer, nullable=True)
    anfangsquadrant = db.Column(db.String(250), nullable=True)
    endquadrant = db.Column(db.String(250), nullable=True)

    positions_id = db.Column(db.Integer, db.ForeignKey("positionen.id"), nullable=False)

    dokument: ClassVar[Dokument] = db.relationship(
        "Dokument",
        back_populates="fundstelle",
        lazy=True,
        uselist=False,
        cascade="all, delete-orphan",
    )
    position = db.relationship("Vorgangsposition", back_populates="fundstelle", lazy=True)


class Ueberweisung(db.Model):
    __tablename__ = "ueberweisungen"

    id = db.Column(db.Integer, primary_key=True)
    ausschuss = db.Column(db.String(250), nullable=True)
    ausschuss_kuerzel = db.Column(db.String(250), nullable=True)
    federfuehrung = db.Column(db.Boolean, nullable=True)
    positions_id = db.Column(db.Integer, db.ForeignKey("positionen.id"), nullable=False)
    position = db.relationship("Vorgangsposition", back_populates="ueberweisungen", lazy=True)


class NewsArticle(db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    published_date = db.Column(db.Text, nullable=True)
    url = db.Column(db.Text, nullable=True)
    publisher = db.Column(db.Text, nullable=True)
    summary_id = db.Column(db.Integer, db.ForeignKey("summaries.id"), nullable=False)
    summary = db.relationship("NewsSummary", back_populates="articles", lazy=True)


class NewsSummary(db.Model):
    __tablename__ = "summaries"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=True)
    articles_found = db.Column(db.Integer, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    articles: ClassVar[List[NewsArticle]] = db.relationship(
        "NewsArticle",
        back_populates="summary",
        lazy=True,
        cascade="all, delete-orphan",
    )
    positions_id = db.Column(db.Integer, db.ForeignKey("positionen.id"), nullable=False)
    position = db.relationship("Vorgangsposition", back_populates="summary", lazy=True)


class NewsUpdateCandidate(db.Model):
    __tablename__ = "news_update_candidates"

    id = db.Column(db.Integer, primary_key=True)
    last_update = db.Column(db.Date, nullable=True)
    next_update = db.Column(db.Date, nullable=True)
    update_count = db.Column(db.Integer, nullable=True, default=0)
    positions_id = db.Column(db.Integer, db.ForeignKey("positionen.id"), nullable=False)
    position = db.relationship("Vorgangsposition", back_populates="update_candidate", lazy=True)


class SavedNewsUpdateCandidate:  # not an actual database class, used to roll back changes in case of gnews error
    def __init__(self, candidate):
        self.id = candidate.id or None
        self.last_update = candidate.last_update or None
        self.next_update = candidate.next_update or None
        self.update_count = candidate.update_count or 0
        self.positions_id = candidate.positions_id or None
        self.position = candidate.position or None


class Vorgangsposition(db.Model):
    __tablename__ = "positionen"

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

    ueberweisungen: ClassVar[List[Ueberweisung]] = db.relationship(
        "Ueberweisung",
        back_populates="position",
        lazy=True,
        cascade="all, delete-orphan",
    )
    fundstelle: ClassVar[Fundstelle] = db.relationship(
        "Fundstelle",
        back_populates="position",
        lazy=True,
        uselist=False,
        cascade="all, delete-orphan",
    )
    beschluesse: ClassVar[List[Beschlussfassung]] = db.relationship(
        "Beschlussfassung",
        back_populates="position",
        lazy=True,
        cascade="all, delete-orphan",
    )
    summary: ClassVar[Fundstelle] = db.relationship(
        "NewsSummary",
        back_populates="position",
        lazy=True,
        uselist=False,
        cascade="all, delete-orphan",
    )
    update_candidate: ClassVar[NewsUpdateCandidate] = db.relationship(
        "NewsUpdateCandidate",
        back_populates="position",
        lazy=True,
        uselist=False,
        cascade="all, delete-orphan",
    )

    vorgangs_id = db.Column(db.Integer, db.ForeignKey("vorhaben.id"), nullable=False)
    gesetz = db.relationship("GesetzesVorhaben", back_populates="vorgangspositionen", lazy=True)


class Verkuendung(db.Model):
    __tablename__ = "verkuendungen"

    id = db.Column(db.Integer, primary_key=True)
    seite = db.Column(db.String(250), nullable=True)
    verkuendungsdatum = db.Column(db.Date, nullable=True)
    ausfertigungsdatum = db.Column(db.Date, nullable=True)
    pdf_url = db.Column(db.String(2048), nullable=True)
    fundstelle = db.Column(db.String(250), nullable=True)

    vorgangs_id = db.Column(db.Integer, db.ForeignKey("vorhaben.id"), nullable=False)
    vorhaben = db.relationship("GesetzesVorhaben", back_populates="verkuendung", lazy=True)


class Inkrafttreten(db.Model):
    __tablename__ = "inkrafttreten"

    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, nullable=True)
    erlaeuterung = db.Column(db.Text)

    vorgangs_id = db.Column(db.Integer, db.ForeignKey("vorhaben.id"), nullable=False)
    vorhaben = db.relationship("GesetzesVorhaben", back_populates="inkrafttreten", lazy=True)


class GesetzesVorhaben(db.Model):
    __tablename__ = "vorhaben"

    id = db.Column(db.Integer, primary_key=True)
    dip_id = db.Column(db.Integer, nullable=True)
    abstract = db.Column(db.Text, nullable=True)
    beratungsstand = db.Column(
        db.ARRAY(db.String(250)), nullable=True, default=[]
    )  # TODO: change to a string, change daily_update and routes accordingly
    sachgebiet = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    wahlperiode = db.Column(db.SmallInteger, nullable=True)
    zustimmungsbeduerftigkeit = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    initiative = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    aktualisiert = db.Column(db.DateTime, nullable=True)
    inkrafttreten = db.Column(db.ARRAY(db.Date), nullable=True)
    titel = db.Column(db.Text, nullable=True)
    datum = db.Column(db.Date, nullable=True)
    vorgangspositionen: ClassVar[List[Vorgangsposition]] = db.relationship(
        "Vorgangsposition",
        back_populates="gesetz",
        lazy=True,
        cascade="all, delete-orphan",
    )
    verkuendung: ClassVar[List[Verkuendung]] = db.relationship(
        "Verkuendung",
        back_populates="vorhaben",
        lazy=True,
        cascade="all, delete-orphan",
    )
    inkrafttreten: ClassVar[List[Inkrafttreten]] = db.relationship(
        "Inkrafttreten",
        back_populates="vorhaben",
        lazy=True,
        cascade="all, delete-orphan",
    )
    queries = db.Column(db.ARRAY(db.String(250)), nullable=True, default=[])
    queries_last_updated = db.Column(db.Date, nullable=True, default=datetime.date(1900, 1, 1))
    query_update_counter = db.Column(db.Integer, nullable=True, default=0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.beratungsstand = self.beratungsstand or []
        self.queries = self.queries or []


def get_all_laws() -> List[GesetzesVorhaben]:
    return GesetzesVorhaben.query.all()


def get_law_by_id(id) -> GesetzesVorhaben:
    id = int(id)
    return db.session.query(GesetzesVorhaben).filter(GesetzesVorhaben.id == id).first()


def get_law_by_dip_id(id) -> GesetzesVorhaben:
    id = int(id)
    return db.session.query(GesetzesVorhaben).filter(GesetzesVorhaben.dip_id == id).one_or_none()


def get_position_by_dip_id(id) -> Vorgangsposition:
    id = int(id)
    return db.session.query(Vorgangsposition).filter(Vorgangsposition.dip_id == id).first()


def get_last_update():
    return (
        last_update.value
        if (last_update := db.session.query(AppMetadata).filter_by(key="last_update").one_or_none())
        else None
    )


def set_last_update(update):
    if last_update := db.session.query(AppMetadata).filter_by(key="last_update").one_or_none():
        last_update.value = update
    else:
        last_update = AppMetadata(key="last_update", value=update)
        db.session.add(last_update)
    db.session.commit()


def is_update_active():
    if update_status := db.session.query(AppMetadata).filter_by(key="update_active").one_or_none():
        return update_status.value == "True"
    else:
        return False


def set_update_active(status):
    status = "True" if status else "False"
    if update_status := db.session.query(AppMetadata).filter_by(key="update_active").one_or_none():
        update_status.value = status
    else:
        update_status = AppMetadata(key="update_active", value=status)
        db.session.add(update_status)
    db.session.commit()
