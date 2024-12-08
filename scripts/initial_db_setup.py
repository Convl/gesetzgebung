import requests
import psycopg2
import dotenv
import os
import datetime
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import GGVorgang

dotenv.load_dotenv()

DIP_API_KEY = "I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21"
DIP_ENDPOINT_VORGANGLISTE = "https://search.dip.bundestag.de/api/v1/vorgang"
DIP_ENDPOINT_VORGANG = "https://search.dip.bundestag.de/api/v1/vorgang/"
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")
POSTGRES_HOST = "localhost"
LAST_DATE_TO_CHECK = datetime.datetime.now().strftime("%Y-%m-%d")

params = {"f.vorgangstyp": "Gesetzgebung",
          "f.datum.start": "2021-10-26",
          "f.datum.end": LAST_DATE_TO_CHECK
          }

headers = {"Authorization": "ApiKey " + DIP_API_KEY}

conn = psycopg2.connect(dbname="gesetze", user="postgres", password=POSTGRES_PASSWORD, host=POSTGRES_HOST, port=5432)
cur = conn.cursor()
cur.execute(""" 
            CREATE TABLE IF NOT EXISTS vorhaben_alle (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dip_id INT,
            abstract TEXT,
            beratungsstand VARCHAR(250),
            sachgebiet VARCHAR(250)[],
            wahlperiode SMALLINT,
            zustimmungsbeduerftigkeit VARCHAR(250)[],
            initiative VARCHAR(250)[],
            aktualisiert TIMESTAMP,
            titel TEXT,
            datum DATE);
        """)
        

gesetze = []
cursor = ""
response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params, headers=headers)
while cursor != response.json().get("cursor", ""):
    for item in response.json().get("documents", []):
        gesetz = GGVorgang(id=item.get("id", None),
                           abstract=item.get("abstract", None),
                           beratungsstand=item.get("beratungsstand", None),
                           sachgebiet=[sg for sg in item.get("sachgebiet", [])],
                           wahlperiode=item.get("wahlperiode", None),
                           zustimmungsbeduerftigkeit=[zb for zb in item.get("zustimmungsbeduerftigkeit", [])],
                           initiative=[ini for ini in item.get("initiative", [])],
                           aktualisiert=item.get("aktualisiert", None),
                           titel=item.get("titel", None),
                           datum=item.get("datum", None))
        gesetze.append(gesetz)
        cur.execute("""INSERT INTO vorhaben_alle (dip_id, abstract, beratungsstand, sachgebiet, wahlperiode, zustimmungsbeduerftigkeit, initiative, aktualisiert, titel, datum) VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (item.get("id", None), 
                    item.get("abstract", None), 
                    item.get("beratungsstand", None),
                    [sg for sg in item.get("sachgebiet", [])],
                    int(item.get("wahlperiode", None)),
                    [zb for zb in item.get("zustimmungsbeduerftigkeit", [])],
                    [ini for ini in item.get("initiative", [])],
                    item.get("aktualisiert", None),
                    item.get("titel", None),
                    item.get("datum", None)))
    params["cursor"] = cursor = response.json().get("cursor", None)
    response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)
        

conn.commit()
cur.close()
conn.close()