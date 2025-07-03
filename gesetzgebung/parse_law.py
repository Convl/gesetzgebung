from gesetzgebung.helpers import (
    abstimmung_ueber_va_vorschlag_im_br,
    abstimmung_ueber_vermittlungsvorschlag_im_bt,
    create_link,
    dritte_beratung,
    merge_beschluesse,
    parse_actors,
    parse_beschluesse,
    pfade,
    praepositionen_akkusativ,
    praepositionen_genitiv,
    praepositionen_nominativ,
    ueberstimmung_des_br_bei_einspruchsgesetz,
    zuordnungen,
    zweite_beratung,
    zweite_beratung_und_schlussabstimmung,
    zweite_und_dritte_beratung,
)
from gesetzgebung.models import (
    Beschlussfassung,
    BeschlussfassungDisplay,
    Dokument,
    Fundstelle,
    GesetzesVorhaben,
    Vorgangsposition,
    datetime,
    db,
    or_,
)


from flask import render_template, session


import copy
import datetime


def parse_law(law: GesetzesVorhaben, display=True, use_session=True):
    # ------------------ Phase 0: Gather preliminary information ----------------- #

    nachtraege = db.session.execute(
        db.select(Vorgangsposition.vorgangsposition, Fundstelle.pdf_url, Dokument.id).filter(
            Fundstelle.positions_id == Vorgangsposition.id,
            Vorgangsposition.vorgangs_id == law.id,
            Vorgangsposition.nachtrag == True,
            Dokument.fundstelle_id == Fundstelle.id,
        )
    ).all()
    nachtraege = [{"vorgangsposition": v, "pdf_url": p, "dokument_id": d} for v, p, d in nachtraege]

    beratungsstand = (
        law.beratungsstand[-1] if law.beratungsstand else "Zu diesem Gesetz liegt leider noch kein Beratungsstand vor."
    )
    law_abstract = law.abstract if law.abstract else "Zu diesem Gesetz liegt leider noch keine Zusammenfassung vor."
    zustimmungsbeduerftigkeit = (
        [
            ("<strong>Ja</strong>" + z[2:] if z.startswith("Ja") else "<strong>Nein</strong>" + z[4:])
            for z in law.zustimmungsbeduerftigkeit
        ]
        if law.zustimmungsbeduerftigkeit
        else "Zur Zustimmungsbedürftigkeit dieses Gesetzes liegen leider noch keine Zusammenfassung vor."
    )
    zustimmungsbeduerftig = (
        False if any("Nein" in z for z in law.zustimmungsbeduerftigkeit) else True
    )  # bei widerspruch setzen sich BRg / BT wohl durch. Falls das Nein vom BR kommt, eh egal.
    va_angerufen = False

    initiative = (
        "Bundestag"
        if not law.initiative
        or not law.initiative[0]
        or "Fraktion" in law.initiative[0]
        or "Gruppe" in law.initiative[0]
        or "ausschuss" in law.initiative[0].lower()
        else ("Bundesregierung" if law.initiative[0] == "Bundesregierung" else "Bundesrat")
    )  # law.initiative is None if a random group of Abgeordnete initiates the law, which effectively equates to "Bundestag"
    pfad = copy.deepcopy(pfade[initiative])

    law.vorgangspositionen.sort(
        key=lambda vp: vp.datum
    )  # TODO: Find out why this is even necessary (in rare cases, like dip_id 315332)

    infos = []

    # Handle session access based on whether we're in Flask or daily_update context
    session_storage = {} if not use_session else session
    session_storage["titel"] = law.titel

    # ---- Phase I: Parse all Vorgangspositionen (what has happened thus far) ---- #
    for position in law.vorgangspositionen:

        if not position.gang:
            continue

        info = {
            "id": position.id,
            "datum": position.datum.strftime("%d. %B %Y"),
            "datetime": position.datum,
            "urheber": position.urheber_titel,
            "vorgangsposition": position.vorgangsposition,
            "link": f'<a href="{position.fundstelle.mapped_pdf_url if position.fundstelle.mapped_pdf_url else position.fundstelle.pdf_url}">Originaldokument</a>',
            "ai_info": "",
            "has_happened": True,
            "passed": True,
            "marks_failure": False,
            "marks_success": False,
            "dokument_ids": [position.fundstelle.dokument.id] if position.fundstelle.dokument else [],
        }

        for nachtrag in nachtraege:
            if nachtrag["vorgangsposition"] == position.vorgangsposition:
                info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'
                info["dokument_ids"].append(nachtrag["dokument_id"])

        match position.vorgangsposition:

            case "Gesetzentwurf":
                if position.urheber_titel:
                    text = parse_actors(
                        position.urheber_titel,
                        praepositionen_nominativ,
                        capitalize=True,
                    )
                    text += " legt" if len(position.urheber_titel) == 1 else " legen"
                    text += f" dem {zuordnungen[position.zuordnung]} den Gesetzentwurf vor."
                else:
                    text = f"Der Gesetzentwurf wird im {zuordnungen[position.zuordnung]} eingebracht."
                ai_info = text
                info["vorgangsposition"] = (
                    "Gesetzentwurf im Bundestag" if position.zuordnung == "BT" else "Gesetzentwurf im Bundesrat"
                )

            case "1. Beratung" | "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                ausschuesse = sorted(
                    [
                        (
                            ueberweisung.ausschuss + " (federführend)"
                            if ueberweisung.federfuehrung
                            else ueberweisung.ausschuss
                        )
                        for ueberweisung in position.ueberweisungen
                    ],
                    key=lambda x: " (federführend)" not in x,
                )

                ausschuesse = parse_actors(ausschuesse, praepositionen_akkusativ, iterable=True)
                if position.vorgangsposition == "1. Beratung":
                    text = "Die 1. Lesung im Bundestag findet statt. Das Gesetz wird überwiesen an\n\n<ul>"
                    ai_info = "Die 1. Lesung im Bundestag findet statt."
                else:
                    text = "Das Gesetz wird in der 2./3. Lesung zurückverwiesen an\n\n<ul>"
                    ai_info = "Das Gesetz wird in der 2./3. Lesung zurückverwiesen."

                for ausschuss in ausschuesse:
                    text += f"<li>{ausschuss}</li>"
                text += "</ul>"

                # if Zurückverweisung, reset passed Flag on previous Beschlussempfehlung
                if position.vorgangsposition == "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                    for inf in infos:
                        if inf["vorgangsposition"] in [
                            "Beschlussempfehlung und Bericht",
                            "Beschlussempfehlung",
                        ]:
                            inf["passed"] = False

                # TODO: Possibility of "Zusammengeführt mit" here, like in 2. / 3. Beratung?

            case "Beschlussempfehlung und Bericht" | "Beschlussempfehlung":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text = "Die Empfehlung " + text + f" lautet: \n<strong>{abstract}</strong>."
                ai_info = f"Die Bundestagsausschüsse legen {position.vorgangsposition} vor."

            case "Bericht":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                text = "Der Bericht " + text + " liegt vor."
                ai_info = text

            case "2. Beratung" | "2. Beratung und Schlussabstimmung":
                if position.abstract and position.abstract.startswith("Zusammengeführt mit"):
                    info["marks_failure"] = True
                    text = create_link(position)

                elif (
                    beschluesse_dritte_beratung := db.session.query(Beschlussfassung)
                    .filter(
                        Beschlussfassung.positions_id == Vorgangsposition.id,
                        Vorgangsposition.vorgangs_id == law.id,
                        Vorgangsposition.vorgangsposition == "3. Beratung",
                        Vorgangsposition.nachtrag == False,
                        Vorgangsposition.datum == position.datum,
                    )
                    .all()
                ):
                    dokument_ids_dritte_beratung = (
                        db.session.execute(
                            db.select(Dokument.id).filter(
                                Dokument.fundstelle_id == Fundstelle.id,
                                Fundstelle.positions_id == Vorgangsposition.id,
                                Vorgangsposition.vorgangs_id == law.id,
                                Vorgangsposition.vorgangsposition == "3. Beratung",
                                Vorgangsposition.nachtrag == False,
                                Vorgangsposition.datum == position.datum,
                            )
                        )
                        .scalars()
                        .all()
                    )
                    info["dokument_ids"].extend(dokument_ids_dritte_beratung)

                    # some modifications to info because we are merging two vorgangspositionen into one
                    info["vorgangsposition"] = "2. und 3. Beratung"
                    for nachtrag in nachtraege:
                        if nachtrag["vorgangsposition"] == "3. Beratung":
                            info["dokument_ids"].append(nachtrag["dokument_id"])
                            info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'

                    ai_info = text = "Die 2. und 3. Lesung im Bundestag finden am selben Tag statt."

                    position_beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                    beschluesse_dritte_beratung = [BeschlussfassungDisplay(b) for b in beschluesse_dritte_beratung]
                    position_beschluesse.extend(beschluesse_dritte_beratung)

                    gemeinsame_beschluesse = merge_beschluesse(
                        position_beschluesse,
                        {
                            position.id: position.vorgangsposition,
                            beschluesse_dritte_beratung[0].positions_id: "3. Beratung",
                        },
                    )

                    text += f" Die Beschlüsse des Bundestags werden nachfolgend gemeinsam dargestellt, sofern sie in beiden Beratungen gleich lauten, andernfalls getrennt: \n\n"
                    text += "".join(
                        (
                            parse_beschluesse(law, gemeinsame_beschluesse[k])
                            if gemeinsame_beschluesse[k] and k == "2. und 3. Beratung"
                            else (
                                f"<u>Nur {k}:</u> {parse_beschluesse(law, gemeinsame_beschluesse[k])}"
                                if gemeinsame_beschluesse[k]
                                else ""
                            )
                        )
                        for k in ["2. und 3. Beratung", "2. Beratung", "3. Beratung"]
                    )

                else:
                    beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                    beschluesse = merge_beschluesse(beschluesse) if len(beschluesse) > 1 else beschluesse
                    ai_info = text = (
                        "Die 2. Lesung im Bundestag findet statt."
                        if position.vorgangsposition == "2. Beratung"
                        else "Die 2. Lesung und Schlussabstimmung im Bundestag findet statt."
                    )
                    text += (
                        " Der Beschluss des Bundestags lautet: \n\n"
                        if len(beschluesse) == 1
                        else " Die Beschlüsse des Bundestags lauten: \n\n"
                    )
                    text += parse_beschluesse(law, beschluesse)

                for beschluss in position.beschluesse:
                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False
                    if beschluss.beschlusstenor in [
                        "Ablehnung der Vorlage",
                        "Ablehnung der Vorlagen",
                    ]:
                        info["marks_failure"] = True
                        text += "\n\nDamit ist das Gesetz gescheitert."

            case "3. Beratung":
                daten_zweite_beratung = (
                    db.session.execute(
                        db.select(Vorgangsposition.datum).filter(
                            Vorgangsposition.vorgangs_id == law.id,
                            Vorgangsposition.nachtrag == False,
                            or_(
                                Vorgangsposition.vorgangsposition == "2. Beratung",
                                Vorgangsposition.vorgangsposition == "2. Beratung und Schlussabstimmung",
                            ),
                        )
                    )
                    .scalars()
                    .all()
                )

                if any(datum == position.datum for datum in daten_zweite_beratung):
                    continue

                if position.abstract and position.abstract.startswith("Zusammengeführt mit"):
                    info["marks_failure"] = True
                    text = create_link(position)
                else:
                    beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                    beschluesse = merge_beschluesse(beschluesse)
                    ai_info = text = "Die 3. Lesung im Bundestag findet statt."
                    text += (
                        " Der Beschluss des Bundestags lautet: \n\n"
                        if len(beschluesse) == 1
                        else " Die Beschlüsse des Bundestags lauten: \n\n"
                    )
                    text += parse_beschluesse(law, beschluesse)

                    for beschluss in position.beschluesse:
                        if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                            info["passed"] = False
                        if beschluss.beschlusstenor in [
                            "Ablehnung der Vorlage",
                            "Ablehnung der Vorlagen",
                        ]:
                            info["marks_failure"] = True

            case "1. Durchgang":
                ai_info = text = "Der 1. Durchgang im Bundesrat findet statt."
                beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                beschluesse = merge_beschluesse(beschluesse)
                text += (
                    " Der Beschluss des Bundesrats lautet: \n\n"
                    if len(beschluesse) == 1
                    else " Die Beschlüsse des Bundesrats lauten: \n\n"
                )
                text += parse_beschluesse(law, beschluesse)

                if any(
                    beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit" for beschluss in beschluesse
                ):
                    info["passed"] = False

            case (
                "2. Durchgang" | "Durchgang"
            ):  # Durchgang, wenn initiative = Bundestag, weil es dann keinen 1. Durchgang gab
                ai_info = text = "Die Beratung und Abstimmung im Bundesrat finden statt."
                info["vorgangsposition"] = "Abstimmung im Bundesrat"

                beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                beschluesse = merge_beschluesse(beschluesse)
                text += (
                    " Der Beschluss des Bundesrats lautet: \n\n"
                    if len(beschluesse) == 1
                    else " Die Beschlüsse des Bundesrats lauten: \n\n"
                )
                text += parse_beschluesse(law, beschluesse)

                for beschluss in beschluesse:
                    if beschluss.beschlusstenor.startswith(
                        "kein Antrag auf Einberufung des Vermittlungsausschusses"
                    ) or beschluss.beschlusstenor.startswith("Zustimmung"):
                        text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                        info["marks_success"] = True

                    # BT-Sitzung nach Vermittlungsvorschlag offenbar nicht unbedingt nötig, jedenfalls nicht wenn nicht zustimmungsbedürftig, vgl
                    # https://search.dip.bundestag.de/api/v1/vorgangsposition?f.vorgang=303742&apikey=I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21

                    # We still pass this stage if va is called, as further sessions of the BR will be BR-Sitzung, not Durchgang / 2. Durchgang
                    if beschluss.beschlusstenor.startswith("Anrufung des Vermittlungsausschusses"):
                        va_angerufen = True
                        pfad.append(copy.deepcopy(abstimmung_ueber_va_vorschlag_im_br))

                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False

            case "Gesetzesantrag":
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += " beantragt," if len(position.urheber_titel) == 1 else " beantragen,"
                text += " der Bundesrat möge beschließen, das Gesetz im Bundestag einzubringen."
                ai_info = text

            case "Plenarantrag":
                text = "Im Plenum " + parse_actors(zuordnungen[position.zuordnung], praepositionen_genitiv)
                text += f" wird folgender Antrag gestellt: \n\n<strong>{position.abstract}</strong>."
                ai_info = text

            case (
                "BR-Sitzung"
            ):  # kommt bei initiative von Land (typischerweise 2x) oder bei ini von BT/BRg (nach Anrufung d. Vermittlungsausschusses)
                beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                beschluesse = merge_beschluesse(beschluesse)
                text = "Der Bundesrat befasst sich mit dem Gesetz und beschließt:\n\n"
                text += parse_beschluesse(law, beschluesse)
                ai_info = "Beschlussfassung zu dem Gesetz im Bundesrat."

                gebilligt = False
                einspruch = True

                for beschluss in beschluesse:
                    if initiative == "Bundesrat" and beschluss.beschlusstenor in [
                        "Ablehnung der Einbringung",
                        "Ablehnung der erneuten Einbringung",
                        "für erledigt erklärt",
                    ]:
                        text += "\n\nDamit ist das Gesetz gescheitert; das Gesetzgebungsverfahren ist am Ende."
                        info["passed"] = False
                        info["marks_failure"] = True

                    if initiative == "Bundesrat" and not (
                        beschluss.beschlusstenor.startswith("Einbringung")
                        or beschluss.beschlusstenor.startswith("erneute Einbringung")
                    ):  # postponement etc
                        info["passed"] = False

                    if va_angerufen:
                        if zustimmungsbeduerftig:
                            if "Versagung der Zustimmung" in beschluss.beschlusstenor:
                                text += "\n\nDamit ist das Gesetz gescheitert; das Gesetzgebungsverfahren ist am Ende."
                                info["passed"] = False
                                info["marks_failure"] = True
                            elif "Zustimmung" in beschluss.beschlusstenor:
                                gebilligt = True
                                text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                                info["marks_success"] = True
                        else:
                            if "kein Einspruch" in beschluss.beschlusstenor:
                                einspruch = False
                                text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                                info["marks_success"] = True
                            elif "Einspruch" in beschluss.beschlusstenor:  # speculating, need example
                                einspruch = True
                                pfad.append(copy.deepcopy(ueberstimmung_des_br_bei_einspruchsgesetz))

                # Most likely, if either of these conditions trigger, passes is already False and the law has failed.
                # But, maybe, the Beschlüsse were just formal stuff / a postponement so that another BR-Sitzung is coming.
                if va_angerufen and zustimmungsbeduerftig and not gebilligt:
                    info["passed"] = False
                if va_angerufen and not zustimmungsbeduerftig and not einspruch:
                    info["passed"] = False

            case "Berichtigung zum Gesetzesbeschluss":
                ai_info = text = (
                    f"Im {zuordnungen[position.zuordnung]} wird eine Berichtigung (meist eine Korrektur redaktioneller Fehler) beschlossen."
                )

            # case "...BR" included only as a fallback, likely won't match for the BR as gang tends to be False, VA-Anrufung by BR is instead handled in Durchgang.
            case (
                "Unterrichtung über Anrufung des Vermittlungsausschusses durch die BRg"
                | "Unterrichtung über Anrufung des Vermittlungsausschusses durch den BR"
            ):
                info["vorgangsposition"] = (
                    "Unterrichtung über Anrufung des Vermittlungsausschusses durch die Bundesregierung"
                    if position.vorgangsposition.endswith("BRg")
                    else "Unterrichtung über Anrufung des Vermittlungsausschusses durch den Bundesrat"
                )
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} darüber, dass sie den Vermittlungsausschuss angerufen hat."
                ai_info = text
                va_angerufen = True

            case "Unterrichtung über Stellungnahme des BR und Gegenäußerung der BRg":
                info["vorgangsposition"] = (
                    "Unterrichtung über Stellungnahme des Bundesrats und Gegenäußerung der Bundesregierung"
                )
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} über die Stellungnahme des Bundesrats und die Gegenäußerung der Bundesregierung."
                ai_info = text

            case "Unterrichtung über Zustimmungsversagung durch den BR":
                info["vorgangsposition"] = "Unterrichtung über Zustimmungsversagung durch den Bundesrat."
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += (
                    f" unterrichtet den {zuordnungen[position.zuordnung]} über die Zustimmungsversagung des Bundesrats."
                )
                ai_info = text

            case "Vermittlungsvorschlag" | "Einigungsvorschlag":
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" legt dem {zuordnungen[position.zuordnung]} den {position.vorgangsposition} des Vermittlungsausschusses vor."
                ai_info = text
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text += f" Seine Empfehlung lautet: \n<strong>{abstract}</strong>"

                if position.vorgangsposition == "Vermittlungsvorschlag":
                    pfad.append(copy.deepcopy(abstimmung_ueber_vermittlungsvorschlag_im_bt))

            case "Abstimmung über Vermittlungsvorschlag":
                text = f"Im {zuordnungen[position.zuordnung]} wird über den Vermittlungsvorschlag abgestimmt. Das Abstimmungsergebnis lautet: \n\n"
                ai_info = f"Im {zuordnungen[position.zuordnung]} wird über den Vermittlungsvorschlag abgestimmt."
                beschluesse = [BeschlussfassungDisplay(b) for b in position.beschluesse]
                beschluesse = merge_beschluesse(beschluesse)
                text += parse_beschluesse(law, beschluesse)

                if not any(
                    beschluss.beschlusstenor == "Annahme" for beschluss in beschluesse
                ):  # possibly refine with more examples?
                    info["passed"] = False
                    text += "\n\n Damit ist das Gesetz gescheitert. Das Gesetzgebungsverfahren ist am Ende."
                    info["marks_failure"] = True

            case "Protokollerklärung/Begleiterklärung zum Vermittlungsverfahren":
                abstract = position.abstract if position.abstract else ""
                ai_info = text = (
                    f"Im {zuordnungen[position.zuordnung]} wird eine Erklärung zum Vermittlungsverfahren abgegeben: {abstract}."
                )

            case "Rücknahme der Vorlage" | "Rücknahme des Antrags":
                typ = "die Vorlage" if position.vorgangsposition == "Rücknahme der Vorlage" else "der Antrag"
                ai_info = text = (
                    f"Im {zuordnungen[position.zuordnung]} wird {typ} zurückgenommen. Damit ist das Gesetzgebungsverfahren beendet."
                )
                info["marks_failure"] = True

            case "Unterrichtung":
                ai_info = text = (
                    f"Im {zuordnungen[position.zuordnung]} findet folgende Unterrichtung statt: \n{position.abstract}."
                )

        info["text"] = text
        info["ai_info"] = ai_info
        infos.append(info)

    # -------------------- Phase 2: Check how far we have come ------------------- #
    # ------------------- add what remains to be done to infos ------------------- #

    # add news summaries
    if display:
        i = 0
        while i < len(infos):
            # TODO: awful hack. Used to just store vorgangspositionen in info["position"], but then info was no longer serializable. Re-querying them one at a time is really inefficient and stupid, but I'm leaving it for now until I get around to doing more major re-factoring.
            if (
                position := db.session.query(Vorgangsposition)
                .filter(Vorgangsposition.id == infos[i].get("id"))
                .one_or_none()
            ) and position.summary:
                sources = "<strong>Quellen:</strong> " + ", ".join(
                    f'<a href="{article.url}">{article.publisher}</a>' for article in position.summary.articles
                )
                # text = f'{position.summary.summary}\n\n{sources}'

                if i + 1 < len(infos):
                    fstring = (
                        "%d. %B %Y"
                        if infos[i]["datetime"].year != infos[i + 1]["datetime"].year
                        else ("%d. %B" if infos[i]["datetime"].month != infos[i + 1]["datetime"].month else "%d.")
                    )
                    date = infos[i]["datetime"].strftime(fstring)
                else:
                    date = infos[i]["datum"]

                news_info = {
                    "datum": date,
                    "next_date": (infos[i + 1]["datum"] if i + 1 < len(infos) else "Gegenwart"),
                    "vorgangsposition": "Nachrichtenartikel",
                    "text": position.summary.summary,
                    "link": sources,
                }
                infos.insert(i + 1, news_info)
            i += 1

    # No need to process remaing if law has already failed or succeeded
    for info in infos:
        if info.get("marks_failure", None):
            if display:
                session_storage["infos"] = [inf for inf in infos if inf["vorgangsposition"] != "Nachrichtenartikel"]
                return render_template(
                    "results.html",
                    titel=law.titel,
                    beratungsstand=beratungsstand,
                    abstract=law_abstract,
                    zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit,
                    infos=infos,
                )
            else:
                return infos

        if info.get("marks_success", None):
            if beratungsstand == "Nicht ausgefertigt wegen Zustimmungsverweigerung des Bundespräsidenten":
                info[
                    "text"
                ] += "\n\n<strong>Der Bundespräsident hat sich jedoch wegen verfassungsrechtlicher Bedenken geweigert, das Gesetz auszufertigen. Es wird somit nicht in Kraft treten</strong>."
                if display:
                    session_storage["infos"] = [inf for inf in infos if inf["vorgangsposition"] != "Nachrichtenartikel"]
                    return render_template(
                        "results.html",
                        titel=law.titel,
                        beratungsstand=beratungsstand,
                        abstract=law_abstract,
                        zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit,
                        infos=infos,
                    )
                else:
                    return infos

            if law.verkuendung:
                for verkuendung in law.verkuendung:
                    info[
                        "text"
                    ] += f'\n\nDas Gesetz wurde <strong>am {verkuendung.verkuendungsdatum.strftime("%d. %B %Y")} verkündet</strong>'
                    info["text"] += (
                        f' (<a href="{verkuendung.pdf_url}">Link zur Verkündung</a>).' if verkuendung.pdf_url else "."
                    )
            else:
                info[
                    "text"
                ] += "\n\nDas Gesetz <strong>muss allerdings noch verkündet werden, um in Kraft zu treten.</strong>"

            if law.inkrafttreten:
                for inkraft in law.inkrafttreten:
                    erlaeuterung = f" ({inkraft.erlaeuterung})" if inkraft.erlaeuterung else " "
                    info["text"] += (
                        f"\n\nDas Gesetz{erlaeuterung} ist <strong>am {inkraft.datum.strftime("%d. %B %Y")} in Kraft getreten</strong>."
                        if inkraft.datum <= datetime.datetime.now().date()
                        else f"\n\nDas Gesetz{erlaeuterung} <strong>wird am {inkraft.datum.strftime("%d. %B %Y")} in Kraft treten</strong>."
                    )
            else:
                info["text"] += "\n\nZum <strong>Datum des Inkrafttretens</strong> ist noch nichts bekannt."

            if beratungsstand in {
                "Teile des Gesetzes für nichtig erklärt",
                "Für nichtig erklärt",
                "Für mit dem Grundgesetz unvereinbar erklärt",
            }:
                entscheidung_bverfg = (
                    "teilweise für nichtig erklärt"
                    if beratungsstand == "Teile des Gesetzes für nichtig erklärt"
                    else "f" + beratungsstand[1:]
                )
                info[
                    "text"
                ] += f"\n\n<strong>Das Gesetz wurde durch das Bundesverfassungsgericht jedoch {entscheidung_bverfg}.</strong>"

    if not display:
        return infos

    remaining = []
    used_info_indices = set()
    for station in pfad:
        found = False
        for i, info in enumerate(infos):
            if (
                all(info.get(k) in v for k, v in station.items() if k != "text")
                and info["passed"]
                and i not in used_info_indices
            ):
                used_info_indices.add(i)
                found = True
                break
        if not found:
            remaining.append(station)

    # Have to do this manually because 2. and 3. Beratung may or may not have been merged. Likewise, 2. Beratung und Schlussabstimmung may replace 2. Beratung and 3. Beratung
    for hack in [zweite_und_dritte_beratung, zweite_beratung_und_schlussabstimmung]:
        if hack not in remaining:
            for b in [zweite_beratung, dritte_beratung]:
                if b in remaining:
                    remaining.remove(b)
        else:
            remaining.remove(hack)

    for station in remaining:
        station["has_happened"] = False
        # check for cases where I introduced ambiguity, currently only "Beschlussempfehlung und Bericht", may simplify later
        if type(station["vorgangsposition"]) == list and len(station["vorgangsposition"]) > 1:
            station["vorgangsposition"] = station["vorgangsposition"][0]
        infos.append(station)

    session_storage["infos"] = [inf for inf in infos if inf["vorgangsposition"] != "Nachrichtenartikel"]
    return render_template(
        "results.html",
        titel=law.titel,
        beratungsstand=beratungsstand,
        abstract=law_abstract,
        zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit,
        infos=infos,
    )
