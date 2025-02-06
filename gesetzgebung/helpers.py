from gesetzgebung.models import *
import copy

bundeslaender = {"Bayern", "Niedersachsen", "Baden-Württemberg", "Nordrhein-Westfalen", "Brandenburg", "Mecklenburg-Vorpommern", 
                 "Hessen", "Sachsen-Anhalt", "Rheinland-Pfalz", "Sachsen", "Thüringen", "Schleswig-Holstein",
                 "Saarland", "Berlin", "Hamburg", "Bremen"}

genera = {"BR": "m",
          "BT": "m",
          "BRg": "w",
          "Bundestag": "m",
          "Bundesrat": "m",
          "Auswärtiger": "m",
          "Ausschuss": "m",
          "Fraktion": "w",
          "Bundesregierung": "w",
          "Bundesministerium": "n",
          "Bayern": "n",
          "Niedersachsen": "n",
          "Baden-Württemberg": "n",
          "Nordrhein-Westfalen": "n",
          "Brandenburg": "n",
          "Mecklenburg-Vorpommern": "n",
          "Hessen": "n",
          "Sachsen-Anhalt": "n",
          "Rheinland-Pfalz": "n",
          "Sachsen": "n",
          "Thüringen": "n",
          "Schleswig-Holstein": "n",
          "Saarland": "n",
          "Berlin": "n",
          "Hamburg": "n",
          "Bremen": "n",
          }

praepositionen_nominativ = { # "DER Bundestag legt ein Gesetz vor"
    "m": "der",
    "w": "die",
    "n": "das",
    "p": "die",
}

praepositionen_genitiv = { # "...ein Gesetz DES Bundestags."
    "m": "des",
    "w": "der",
    "n": "des",
    "p": "der",
}

praepositionen_dativ = { # "...legt DEM Bundesrat ein Gesetz vor"
    "m": "dem",
    "w": "der",
    "n": "dem",
    "p": "den",
}

praepositionen_akkusativ = { # "... bringt ein Gesetz in DEN Bundesrat ein."
    "m": "den",
    "w": "die",
    "n": "das",
    "p": "die",
}


zuordnungen = {"BR": "Bundesrat",
               "BT": "Bundestag",}

# Where multiple options exist for vorgangsposition, list the most normal one first, as that is the one that will be displayed if this event lies in the future (has_happened=False)
gesetzentwurf_bt = {"vorgangsposition": "Gesetzentwurf im Bundestag",
                    "text": "Der Gesetzentwurf muss noch in den Bundestag eingebracht werden."}
gesetzentwurf_br = {"vorgangsposition": "Gesetzentwurf im Bundesrat",
                    "text": "Der Gesetzentwurf muss noch in den Bundesrat eingebracht werden."}
gesetzesantrag_br = {"vorgangsposition": "Gesetzesantrag",
                    "text": "Im Bundesrat muss noch ein Antrag auf Einbringung des Gesetzentwurfs in den Bundestag gestellt werden."}
erste_beratung = {"vorgangsposition": "1. Beratung",
                  "text": "Die erste Beratung im Bundestag und Überweisung an die zuständigen Ausschüsse muss noch stattfinden."}
beschlussempfehlung = {"vorgangsposition": ["Beschlussempfehlung und Bericht", # assumes that the Bericht is not absolutely necessary. Not sure if true.
                                            "Beschlussempfehlung"],
                       "text": "Der federführende Ausschuss muss noch den Bericht und die Beschlussempfehlung der zuständigen Ausschüsse vorlegen."}
zweite_beratung = {"vorgangsposition": "2. Beratung",
                   "text": "Die zweite Beratung und Abstimmung über den Gesetzentwurf und die Beschlussempfehlung der Ausschüsse im Bundestag muss noch stattfinden."}
dritte_beratung = {"vorgangsposition": "3. Beratung",
                    "text": "Die dritte Beratung und Abstimmung über den Gesetzentwurf und die Beschlussempfehlung der Ausschüsse im Bundestag muss noch stattfinden."}
zweite_und_dritte_beratung = {"vorgangsposition": "2. und 3. Beratung",
                              "text": "If this ever gets displayed, it's a bug."} # should never be displayed
entscheidender_durchgang_br = {"vorgangsposition": "Abstimmung im Bundesrat",
                               "text": "Der Bundesrat muss noch über das Gesetz abstimmen."}
erster_durchgang_br = {"vorgangsposition": "1. Durchgang",
                       "text": "Der erste Durchgang mit Stellungnahme des Bundesrats muss noch stattfinden."}
br_einbringungsbeschluss = {"vorgangsposition": "BR-Sitzung",
                            "text": "Der Bundesrat muss noch beschließen, das Gesetz in den Bundestag einzubringen."} # typischerweise gibt es 2x BR-Sitzung: 1x Ausschusszuweisung, 1x Einbringungsbeschluss (oder eben nicht). Ersteres ist aber nicht zwingend
abstimmung_ueber_vermittlungsvorschlag_im_bt = {"vorgangsposition": "Abstimmung über Vermittlungsvorschlag",
                                                "text": "Der Bundestag muss noch über den Vermittlungsvorschlag des Vermittlungsausschusses abstimmen."}
abstimmung_ueber_va_vorschlag_im_br = {"vorgangsposition": "BR-Sitzung",
                                       "text": "Der Bundesrat muss noch über den Vorschlagg des Vermittlungsausschusses abstimmen."}
ueberstimmung_des_br_bei_einspruchsgesetz = {"text": "Der Bundestag muss den vom Bundesrat erhobenen Einspruch noch überstimmen."} # TODO: kann noch nicht ausgefüllt werden mangels Beispielsfall

# TODO: pfad bundestag anders bei bes. Eilbedürftigkeit?
basispfad = [gesetzentwurf_bt, erste_beratung, beschlussempfehlung, zweite_beratung, dritte_beratung, zweite_und_dritte_beratung, entscheidender_durchgang_br]
pfad_bundestag = [gesetzentwurf_br] + basispfad 
pfad_bundesregierung = [erster_durchgang_br] + pfad_bundestag 
pfad_bundesrat = [gesetzesantrag_br, br_einbringungsbeschluss] + basispfad 

pfade = {"Bundestag": pfad_bundestag,
         "Bundesregierung": pfad_bundesregierung,
         "Bundesrat": pfad_bundesrat,
}

def parse_actors(actors, kasus, capitalize=False, iterable=False):
    """ Parses a list of actors into a string, applying prepositions according to the rules of German grammar as per the kasus provided, 
    and adding 'und' in front of the last actor. Optionally, capitalizes first letter. Optionally, outputs a list instead of a string, 
    with each actor as an item in the list."""
    
    result = "" if not iterable else []

    if type(actors) != list:
        actors = [actors]

    for actor in actors:
        first_word = actor.split(" ")[0]

        if first_word.endswith("ausschuss"):
            first_word = "Ausschuss"

        praeposition = kasus.get(genera.get(first_word, ""), "")

        if kasus == praepositionen_genitiv:
            if first_word in bundeslaender: # "des LANDES Bayern"
                praeposition += " Landes"
            elif genera[first_word] == 'm': 
                if actor.startswith("Ausschuss"):
                    actor = actor[:9] + "es" + actor[9:] # "des AusschussES für Familie, Bildung..."
                else:
                    actor += "es" # "des BundestagES"
            elif genera[first_word] == 'n': # "des BundesministeriumS"
                actor += "s"
        else:
            if first_word in bundeslaender: # "das LAND Bayern"
                praeposition += " Land"

        result += f"{praeposition} {actor}, " if not iterable else [f"{praeposition} {actor}"]
    
    if not iterable:
        result = result[:-2] 
    
    if capitalize:
        if not iterable:
            result = "D" + result[1:]
        else:
            result[0] = "D" + result[0][1:]

    if len(actors) > 1 and not iterable:
        last_comma = result.rfind(",", 0, len(result) - 1 - len(actor))
        result = result[:last_comma] + " und" + result[last_comma+1:]

    return result

def parse_beschluesse(law, beschluesse:List[Beschlussfassung]) -> str:#
    """ Parses a Beschlussfassung in the Bundestag. """

    text = "<ul>"

    for beschluss in beschluesse:
        text += "<li>"
        text += f"<strong>{beschluss.beschlusstenor}</strong>"

        if beschluss.dokumentnummer:
            text += " in Bezug auf: "
            dokumentnummern = [dokumentnummer.strip() for dokumentnummer in beschluss.dokumentnummer.split(",")]

            if len(dokumentnummern) > 1:
                text += "<ul>"

            for dokumentnummer in dokumentnummern:
                fundstellen_infos = db.session.query(Fundstelle.drucksachetyp, Fundstelle.pdf_url, Fundstelle.urheber).join(
                    Vorgangsposition).filter(Vorgangsposition.vorgangs_id == law.id, Fundstelle.dokumentnummer == dokumentnummer).all()
                
                for drucksachetyp, pdf_url, urheber in fundstellen_infos:
                    
                    if not drucksachetyp:
                        drucksachetyp = "Dokument"
                    
                    anmerkung = beschluss.abstimm_ergebnis_bemerkung if beschluss.abstimm_ergebnis_bemerkung and beschluss.abstimm_ergebnis_bemerkung.startswith(", Anmerkung") \
                    else f", Anmerkung: {beschluss.abstimm_ergebnis_bemerkung}" if beschluss.abstimm_ergebnis_bemerkung else ""

                    text += f' <a href="{pdf_url}">{drucksachetyp}</a> (Urheber: {", ".join(urh for urh in urheber)}, Dokumentnummer: {dokumentnummer}{anmerkung})' \
                    if len(dokumentnummern) == 1 else \
                    f'<li><a href="{pdf_url}">{drucksachetyp}</a> (Urheber: {", ".join(urh for urh in urheber)}, Dokumentnummer: {dokumentnummer}{anmerkung})</li>'
            
            if len(dokumentnummern) > 1:
                text += "</ul>"
        
        else:
            text += f" (Anmerkung: {beschluss.abstimm_ergebnis_bemerkung})" if beschluss.abstimm_ergebnis_bemerkung else ""
        
        text += "</li>"

    text += "</ul>"
    text += "\n"
    return text

def merge_beschluesse(beschluesse : List[Beschlussfassung], zweite_und_dritte_beratung=False, needs_copy=True) -> List[Beschlussfassung]:
    """ Merge Beschlüsse which differ only in their .abstimm_ergebnis_bemerkung by concatenating their abstimm_ergebnis_bemerkung.
    Can merge Beschlüsse from a single Beratung or from a second and third Beratung. In the latter case, assumes that all beschluesse from
    the second beratung come first, followed by all from the third beratung, and takes a dict zweite_und_dritte_beratung to indicates which 
    beschluesse belong to which beratung."""
    
    merged_beschluesse = {"2. Beratung": [],
                          "3. Beratung": [],
                          "2. und 3. Beratung": [],} if zweite_und_dritte_beratung else []
    
    merged_indices = set()
    
    if zweite_und_dritte_beratung:
        zweite, dritte = zweite_und_dritte_beratung.keys()
    
    for i in range(len(beschluesse)):
        if i in merged_indices:
            continue

        contains_beschluesse_from = {beschluesse[i].positions_id}
        merged = copy.deepcopy(beschluesse[i]) if needs_copy else beschluesse[i]
        first_beschluss_from_dritte_beratung = True

        for j in range(i+1, len(beschluesse)):
            if j in merged_indices:
                continue

            if (beschluesse[i].dokumentnummer == beschluesse[j].dokumentnummer and
                beschluesse[i].beschlusstenor == beschluesse[j].beschlusstenor):
                
                if beschluesse[i].abstimm_ergebnis_bemerkung != beschluesse[j].abstimm_ergebnis_bemerkung:
                    contains_beschluesse_from.add(beschluesse[j].positions_id)

                    if not merged.abstimm_ergebnis_bemerkung:
                        merged.abstimm_ergebnis_bemerkung = ""

                    if not zweite_und_dritte_beratung:
                        merged.abstimm_ergebnis_bemerkung += f" // {beschluesse[j].abstimm_ergebnis_bemerkung}"
                    else:
                        if beschluesse[j].positions_id != beschluesse[i].positions_id:
                            
                            if first_beschluss_from_dritte_beratung:
                                merged.abstimm_ergebnis_bemerkung = ", Anmerkung aus der zweiten Beratung: " + merged.abstimm_ergebnis_bemerkung if merged.abstimm_ergebnis_bemerkung else ""

                            merged.abstimm_ergebnis_bemerkung += ", Anmerkung aus der dritten Beratung: " + beschluesse[j].abstimm_ergebnis_bemerkung if beschluesse[j].abstimm_ergebnis_bemerkung else ""
                            
                            first_beschluss_from_dritte_beratung = False
                        else:
                            merged.abstimm_ergebnis_bemerkung += f" // {beschluesse[j].abstimm_ergebnis_bemerkung}" if beschluesse[j].abstimm_ergebnis_bemerkung else ""

                merged_indices.add(j)
                contains_beschluesse_from.add(beschluesse[j].positions_id)    

        if zweite_und_dritte_beratung:
            if zweite in contains_beschluesse_from and dritte in contains_beschluesse_from:
                merged_beschluesse["2. und 3. Beratung"].append(merged)
            elif zweite in contains_beschluesse_from:
                merged_beschluesse['2. Beratung'].append(merged)
            else:
                merged_beschluesse['3. Beratung'].append(merged)
        else:
            merged_beschluesse.append(merged)
            
        merged_indices.add(i)

    return merged_beschluesse  

# def analyze_beschluesse(beschluesse : List[Beschlussfassung], actor) -> bool:
#     for beschluss in beschluesse:
#         if beschluss.beschlusstenor