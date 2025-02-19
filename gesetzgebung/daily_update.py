import requests
from dotenv import load_dotenv
import datetime
import time
import os
from gesetzgebung.models import *
from gesetzgebung.flask_file import app
from gesetzgebung.es_file import es, ES_LAWS_INDEX
from gesetzgebung.routes import submit
# from elasticsearch.exceptions import NotFoundError
from elasticsearch7.exceptions import NotFoundError

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

DIP_API_KEY = "I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21"
DIP_ENDPOINT_VORGANGLISTE = "https://search.dip.bundestag.de/api/v1/vorgang"
DIP_ENDPOINT_VORGANG = "https://search.dip.bundestag.de/api/v1/vorgang/"
DIP_ENDPOINT_VORGANGSPOSITIONENLISTE = "https://search.dip.bundestag.de/api/v1/vorgangsposition"
DIP_ENDPOINT_VORGANGSPOSITION = "https://search.dip.bundestag.de/api/v1/vorgangsposition/"
FIRST_DATE_TO_CHECK = "2021-10-26"
LAST_DATE_TO_CHECK = datetime.datetime.now().strftime("%Y-%m-%d")

headers = {"Authorization": "ApiKey " + DIP_API_KEY}

def daily_update(): 
    with app.app_context():
        params =    {"f.vorgangstyp": "Gesetzgebung",
                     "f.datum.start": FIRST_DATE_TO_CHECK,
                     "f.aktualisiert.start": last_update
                    } \
                        if (last_update := get_last_update()) else \
                    {"f.vorgangstyp": "Gesetzgebung", 
                    "f.datum.start": FIRST_DATE_TO_CHECK, 
                    "f.datum.end": LAST_DATE_TO_CHECK
                    }

        cursor = ""
        response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)
        
        print("Starting daily update")
        
        while response.ok and cursor != response.json().get("cursor", None):
            for item in response.json().get("documents", []):
                law = get_law_by_dip_id(item.get("id", None)) or GesetzesVorhaben() 
                print(f"Processing Item id: {item.get("id", None)}, item id type: {type(item.get("id", None))}, law dip id: {law.dip_id}, law dip id type: {type(law.dip_id)}")

                #if not law.aktualisiert or law.aktualisiert != item.get("aktualisiert", None):
                law.dip_id = item.get("id", None)
                law.abstract = item.get("abstract", None)
                if not law.beratungsstand or law.beratungsstand[-1] != item.get("beratungsstand", None):
                    law.beratungsstand.append(item.get("beratungsstand", None))
                law.sachgebiet = [sg for sg in item.get("sachgebiet", [])]
                law.wahlperiode = int(item.get("wahlperiode", None))
                law.zustimmungsbeduerftigkeit = [zb for zb in item.get("zustimmungsbeduerftigkeit", [])]
                law.initiative  = [ini for ini in item.get("initiative", [])]
                law.aktualisiert = item.get("aktualisiert", None)
                law.titel = item.get("titel", None)
                law.datum = item.get("datum", None)

                update_positionen(item.get("id", None), law)

                db.session.add(law)
                db.session.commit()
                
                if item.get("verkuendung", []):
                    update_verkuendung(item.get("verkuendung", []), law)

                if item.get("inkrafttreten", []):
                    update_inkrafttreten(item.get("inkrafttreten", []), law)

                db.session.commit()
                
                update_law_in_es(law)
                
                print(f"Entered into database: law dip id: {law.dip_id}, law dip id type: {type(law.dip_id)}, law id: {law.id}")

                time.sleep(1)
            
            print(f"old cursor: {cursor}")
            params["cursor"] = cursor = response.json().get("cursor", None)
            print(f"new cursor: {cursor}")
            response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)
            print(f"next cursor: {response.json().get("cursor", None)}")

        set_last_update(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        # TODO: define cases when add_news should be called, other than when a new position is added

def update_inkrafttreten(inkrafttreten, law):
    existing_inkrafttreten = db.session.query(Inkrafttreten).filter_by(vorgangs_id=law.id).all()
    for inkraft in existing_inkrafttreten:
        db.session.delete(inkraft)

    for item in inkrafttreten:
        inkraft = Inkrafttreten()
        inkraft.datum = item.get("datum", None)
        inkraft.erlaeuterung = item.get("erlaeuterung", None)

        inkraft.inkrafttreten_vorhaben = law
        db.session.add(inkraft)

def update_verkuendung(verkuendungen, law):
    existing_verkuendungen = db.session.query(Verkuendung).filter_by(vorgangs_id=law.id).all()
    for verkuendung in existing_verkuendungen:
        db.session.delete(verkuendung)
    
    for item in verkuendungen:
        verkuendung = Verkuendung()
        verkuendung.ausfertigungsdatum = item.get("ausfertigungsdatum", None)
        verkuendung.verkuendungsdatum = item.get("verkuendungsdatum", None)
        verkuendung.pdf_url = item.get("pdf_url", None)
        verkuendung.fundstelle = item.get("fundstelle", None)

        verkuendung.vorhaben = law
        db.session.add(verkuendung) 

def update_positionen(dip_id, law):
    params = {"f.vorgang": dip_id}

    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    while response.ok and cursor != response.json().get("cursor", None):
        for item in response.json().get("documents", []):
            new_position = (position := get_position_by_dip_id(item.get("id", None))) is None
            position = position or Vorgangsposition()
            if not position.aktualisiert or position.aktualisiert != item.get("aktualisiert", None): # may wanna check item.get("gang", False) here
                position.dip_id = item.get("id", None)
                position.vorgangsposition = item.get("vorgangsposition", None)
                position.zuordnung = item.get("zuordnung", None)
                position.gang = item.get("gang", None)
                position.fortsetzung = item.get("fortsetzung", None)
                position.nachtrag = item.get("nachtrag", None)
                position.dokumentart = item.get("dokumentart", None)
                urheber = item.get("urheber", [])
                position.urheber_titel = [urh.get("titel", None) for urh in urheber]
                position.abstract = item.get("abstract", None)
                position.datum = item.get("datum", None)
                position.aktualisiert = item.get("aktualisiert", None)

                position.gesetz = law
                db.session.add(position)
                db.session.commit()

                ueberweisungen = item.get("ueberweisung", [])
                update_ueberweisungen(position, ueberweisungen)

                fundstelle = item.get("fundstelle", [])
                update_fundstelle(position, fundstelle)

                beschlussfassungen = item.get("beschlussfassung", [])
                update_beschluesse(position, beschlussfassungen)

                if new_position:
                    add_news(position)
        
        time.sleep(1)
        params["cursor"] = cursor = response.json().get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)

def update_beschluesse(position, beschlussfassungen):
    # position.beschluesse.clear()
    existing_beschluesse = db.session.query(Beschlussfassung).filter_by(positions_id=position.id).all()
    if existing_beschluesse:
        for beschluss in existing_beschluesse:
            db.session.delete(beschluss)

    for item in beschlussfassungen:
        beschluss = Beschlussfassung()
        beschluss.beschlusstenor = item.get("beschlusstenor", None)
        beschluss.dokumentnummer = item.get("dokumentnummer", None)
        beschluss.seite = item.get("seite", None)
        beschluss.abstimm_ergebnis_bemerkung = item.get("abstimm_ergebnis_bemerkung", None)
        
        beschluss.position = position
        db.session.add(beschluss)


def update_fundstelle(position, dip_fundstelle):
    # position.fundstelle.clear()
    existing_fundstellen = db.session.query(Fundstelle).filter_by(positions_id=position.id).all()
    if existing_fundstellen:
        for fundstelle in existing_fundstellen:
            db.session.delete(fundstelle)

    fundstelle = Fundstelle()
    fundstelle.dip_id = dip_fundstelle.get("id", None)
    fundstelle.dokumentnummer = dip_fundstelle.get("dokumentnummer", None)
    fundstelle.drucksachetyp = dip_fundstelle.get("drucksachetyp", None)
    fundstelle.herausgeber = dip_fundstelle.get("herausgeber", None)
    fundstelle.pdf_url = dip_fundstelle.get("pdf_url", None)
    fundstelle.urheber = [urheber for urheber in dip_fundstelle.get("urheber", [])]
    fundstelle.anfangsseite = dip_fundstelle.get("anfangsseite", None)
    fundstelle.endseite = dip_fundstelle.get("endseite", None)
    fundstelle.anfangsquadrant = dip_fundstelle.get("anfangsquadrant", None)
    fundstelle.endquadrant = dip_fundstelle.get("endquadrant", None)

    fundstelle.position = position
    db.session.add(fundstelle)

def update_ueberweisungen(position, ueberweisungen):
    # position.ueberweisungen.clear()
    existing_ueberweisungen = db.session.query(Ueberweisung).filter_by(positions_id=position.id).all()
    if existing_ueberweisungen:
        for ueberweisung in existing_ueberweisungen:
            db.session.delete(ueberweisung)

    for item in ueberweisungen:
        ueberweisung = Ueberweisung()
        ueberweisung.ausschuss = item.get("ausschuss", None)
        ueberweisung.ausschuss_kuerzel = item.get("ausschuss_kuerzel", None)
        ueberweisung.federfuehrung = item.get("federfuehrung", None)

        ueberweisung.position = position
        db.session.add(ueberweisung)

def add_news(position):
    pass

def update_law_in_es(law):
    try:
        es_law = es.get(index=ES_LAWS_INDEX, id=law.id)
        if law.titel == es_law['_source'].get('titel') and law.abstract == es_law["_source"].get('abstract'):
            return
        
    except NotFoundError:
        pass
    
    es.index(index=ES_LAWS_INDEX, id=law.id, body={
        'titel': law.titel,
        'abstract': law.abstract
    })

if __name__ == "__main__":
    daily_update()