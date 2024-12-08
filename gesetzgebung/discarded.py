# Algo for consolidating beschlüsse from 2. and dritte beratung
for d in beschluesse_dritte_beratung:
    matched = False

    for b in position.beschluesse:

        if d.beschlusstenor == b.beschlusstenor and d.dokumentnummer == b.dokumentnummer:
            matched = True

            if d.abstimm_ergebnis_bemerkung != b.abstimm_ergebnis_bemerkung:
                bemerkung = f"Anmerkung (<u>aus der zweiten Beratung</u>): {b.abstimm_ergebnis_bemerkung}, " if \
                b.abstimm_ergebnis_bemerkung and d.abstimm_ergebnis_bemerkung else \
                f" <u>aus der zweiten Beratung:</u>{b.abstimm_ergebnis_bemerkung}" if b.abstimm_ergebnis_bemerkung \
                else ""
                bemerkung += f"Anmerkung (<u>aus der dritten Beratung</u>): {d.abstimm_ergebnis_bemerkung}" if \
                d.abstimm_ergebnis_bemerkung else ""
                bemerkung = ", " + bemerkung

                beschluss = copy.deepcopy(d)
                beschluss.abstimm_ergebnis_bemerkung = bemerkung
                beschluesse["2. und 3. Beratung"].add(beschluss)

            else:
                beschluesse["2. und 3. Beratung"].add(beschluss)
    
    if not matched:
        beschluesse["3. Beratung"].add(d)

for b in position.beschluesse:
    if not any(b.beschlusstenor == beschluss.beschlusstenor and 
            b.dokumentnummer == beschluss.dokumentnummer
            for beschluss in beschluesse["2. und 3. Beratung"]):
        beschluesse["2. Beratung"].add(b)

# The check for daten_dritte_beratung below was discarded, assuming it to be superfluous as per the TODO
case "2. Beratung" | "2. Beratung und Schlussabstimmung":                
                daten_dritte_beratung = db.session.execute(db.select(Vorgangsposition.datum).filter(
                    Vorgangsposition.vorgangs_id == law.id, Vorgangsposition.vorgangsposition == "3. Beratung", Vorgangsposition.nachtrag == False)).scalars().all()

                # TODO: Check if this if condition is superfluous. The next one should suffice, because if there is a 3. Beratung on the same day, there should also
                # be beschluesse from that 3. Beratung. Is there any case in which the first would be True but the second wouldn't?
                if any(datum == position.datum for datum in daten_dritte_beratung): 
                    info["vorgangsposition"] = "2. und 3. Beratung"
                    for nachtrag in nachtraege:
                        if nachtrag["vorgangsposition"] == "3. Beratung":
                            info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'
        
                    text = "Die 2. und 3. Lesung im Bundestag finden am selben Tag statt."
                    if (beschluesse_dritte_beratung := db.session.query(Beschlussfassung).filter(
                        Beschlussfassung.positions_id == Vorgangsposition.id, Vorgangsposition.vorgangs_id == law.id, 
                        Vorgangsposition.vorgangsposition == "3. Beratung", Vorgangsposition.nachtrag == False, Vorgangsposition.datum == position.datum).all()):

                        position_beschluesse = copy.deepcopy(position.beschluesse)
                        beschluesse_dritte_beratung = copy.deepcopy(beschluesse_dritte_beratung)
                        position_beschluesse.extend(beschluesse_dritte_beratung)
                        beschluesse = merge_beschluesse(position_beschluesse,
                                                            {position.id : position.vorgangsposition, 
                                                             beschluesse_dritte_beratung[0].positions_id : "3. Beratung"}, False)
                        text += f" Die Beschlüsse des Bundestags werden nachfolgend gemeinsam dargestellt, sofern sie in beiden Beratungen gleich lauten, andernfalls getrennt: \n\n"
                    
                else:
                    beschluesse = {"2. Beratung": [],
                                   "3. Beratung": [],
                                   "2. und 3. Beratung": [],
                                   "alle": [],}
                    position_beschluesse = merge_beschluesse(position.beschluesse) if len(position.beschluesse) > 1 else position.beschluesse