"""
Parsing logic for calendar PDF and CSV files.
Decoupled from routes/DB for testability.
"""

import csv
import io
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

MESI_ITALIANI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# x0-coordinate ranges (in PDF points) for the 5 year-group columns in the
# "CALENDARIO AF" table layout used by this school (see specs.md 3.1). If the
# school changes this template, these ranges - and the < 140 cutoff used to
# isolate the date column in parse_calendario_pdf - may need updating.
# In the school's calendar PDF a day listed with this many hours (vs the usual
# 4-6) means that year-group is out on stage/tirocinio: no lessons at all.
STAGE_ORE_GIORNATA = 8

CALENDARIO_PDF_GRUPPI_COLONNE = [
    ("PRIME", (140, 195)),
    ("SECONDE", (195, 250)),
    ("TERZE", (250, 305)),
    ("QUARTE", (305, 360)),
    ("PRIMA4+2", (360, 410)),
]


class CalendarParser:
    """Parse school calendar from PDF or manual input."""

    @staticmethod
    def parse_calendar_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse calendar from CSV format.
        Expected columns: data (YYYY-MM-DD), ore_max_giornata (4/5/6), flag_chiusura (true/false)
        Optional: stage_classe_id (class in stage on this date), gruppo (year-group this row
        applies to, e.g. "PRIME" - leave empty for a school-wide row that applies to every classe)
        """
        logger.info("Parsing calendar from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            calendar_entries = []

            for row_idx, row in enumerate(reader, start=2):  # start=2 (header is 1)
                try:
                    # Parse date
                    data_str = row.get("data", "").strip()
                    try:
                        data = datetime.strptime(data_str, "%Y-%m-%d").date()
                    except ValueError:
                        raise ValueError(f"Invalid date format: {data_str} (expected YYYY-MM-DD)")

                    # Parse ore_max_giornata
                    ore_max_str = row.get("ore_max_giornata", "6").strip()
                    try:
                        ore_max = int(ore_max_str)
                        if ore_max not in [4, 5, 6]:
                            raise ValueError(f"ore_max_giornata must be 4, 5, or 6, got {ore_max}")
                    except ValueError as e:
                        raise ValueError(f"Invalid ore_max_giornata: {ore_max_str}")

                    # Parse flag_chiusura
                    flag_chiusura_str = row.get("flag_chiusura", "false").strip().lower()
                    flag_chiusura = flag_chiusura_str in ["true", "1", "yes"]

                    # Parse stage_classe_id (optional)
                    stage_classe_id = row.get("stage_classe_id", "").strip() or None

                    # Parse gruppo (optional)
                    gruppo = (row.get("gruppo") or "").strip() or None

                    calendar_entries.append({
                        "data": data,
                        "gruppo": gruppo,
                        "ore_max_giornata": ore_max,
                        "flag_chiusura": flag_chiusura,
                        "stage_classe_id": stage_classe_id,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(calendar_entries)} calendar entries")
            return calendar_entries

        except Exception as e:
            logger.error(f"Error parsing calendar CSV: {e}")
            raise

    @staticmethod
    def _parse_italian_date_words(words: List[str]) -> Optional[date]:
        """Parse a date from loose word tokens like ["mercoledì","9","settembre","2026"]."""
        month = day = year = None
        for w in words:
            lw = w.lower()
            if lw in MESI_ITALIANI:
                month = MESI_ITALIANI[lw]
            elif w.isdigit() and len(w) == 4:
                year = int(w)
            elif w.isdigit():
                day = int(w)
        if month and day and year:
            try:
                return date(year, month, day)
            except ValueError:
                return None
        return None

    @staticmethod
    def parse_calendario_pdf(file_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Parse the annual calendar from a PDF (specs.md 3.1: "Parser Intelligente
        del Calendario Annuale (PDF OCR / AI)").

        This targets the "CALENDARIO AF" table layout actually used by this
        school: one row per school day (weekday name, day, Italian month
        name, year) followed by daily-hours columns for 5 year-groups
        (PRIME/SECONDE/TERZE/QUARTE/PRIMA4+2), with an events table alongside
        that is ignored here.

        Extraction is done by clustering words by their (x, y) position
        rather than relying on pdfplumber's automatic table-grid detection,
        which merges multiple calendar rows together on this file (rows are
        tightly packed and the border grid isn't fully rectilinear). Position
        clustering also survives pages where a naive linear text read jumbles
        adjacent columns' digits together.

        Produces one entry per (data, gruppo) with that year-group's daily
        hours (0 if the cell is blank - e.g. that group is on tirocinio that
        day), plus a school-wide (gruppo=None) flag_chiusura=True entry for
        every weekday within the school-year range that has no data at all
        for any group (inferred closure).

        If this school's calendar template changes, CALENDARIO_PDF_GRUPPI_COLONNE
        and the date-column cutoff below may need to be adjusted to match.
        """
        import pdfplumber

        logger.info("Parsing calendar from PDF")

        entries: List[Dict[str, Any]] = []
        all_dates_seen = set()

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                date_column_max_x = CALENDARIO_PDF_GRUPPI_COLONNE[0][1][0]
                page_crop_width = max(x for _, (_, x) in CALENDARIO_PDF_GRUPPI_COLONNE)

                for page in pdf.pages:
                    left = page.crop((0, 0, min(page_crop_width, page.width), page.height))
                    words = left.extract_words(use_text_flow=False, keep_blank_chars=False)

                    rows: Dict[float, List[dict]] = defaultdict(list)
                    for w in words:
                        rows[round(w["top"], 1)].append(w)

                    for _, ws in rows.items():
                        ws_sorted = sorted(ws, key=lambda w: w["x0"])
                        date_words = [w["text"] for w in ws_sorted if w["x0"] < date_column_max_x]
                        parsed_date = CalendarParser._parse_italian_date_words(date_words)
                        if not parsed_date:
                            continue  # header / blank separator / events-table row

                        all_dates_seen.add(parsed_date)
                        for gruppo, (x_min, x_max) in CALENDARIO_PDF_GRUPPI_COLONNE:
                            val_words = [w["text"] for w in ws_sorted if x_min <= w["x0"] < x_max]
                            ore = 0
                            if val_words:
                                try:
                                    ore = int(val_words[0])
                                except ValueError:
                                    logger.warning(
                                        f"Unparseable hours value {val_words[0]!r} for "
                                        f"{gruppo} on {parsed_date}"
                                    )
                                    continue
                            entries.append({
                                "data": parsed_date,
                                "gruppo": gruppo,
                                "ore_max_giornata": ore,
                                "flag_chiusura": False,
                                "stage_classe_id": None,
                                "flag_stage_gruppo": ore >= STAGE_ORE_GIORNATA,
                            })

            if all_dates_seen:
                start, end = min(all_dates_seen), max(all_dates_seen)
                d = start
                while d <= end:
                    if d.weekday() < 5 and d not in all_dates_seen:
                        entries.append({
                            "data": d,
                            "gruppo": None,
                            "ore_max_giornata": 0,
                            "flag_chiusura": True,
                            "stage_classe_id": None,
                        })
                    d += timedelta(days=1)

            if not all_dates_seen:
                raise ValueError(
                    "No calendar rows recognized in this PDF. The parser expects the "
                    "'CALENDARIO AF' table layout; a different template needs its own parser."
                )

            logger.info(
                f"Parsed {len(entries)} calendar entries from PDF "
                f"({len(all_dates_seen)} school days, range {min(all_dates_seen)}..{max(all_dates_seen)})"
            )
            return entries

        except Exception as e:
            logger.error(f"Error parsing calendar PDF: {e}")
            raise

    @staticmethod
    def parse_docenti_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse teachers from CSV.
        Expected columns: nome, email (optional), tipo (ASSUNTO/CONTRATTO)
        """
        logger.info("Parsing teachers from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            docenti = []

            for row_idx, row in enumerate(reader, start=2):
                try:
                    nome = row.get("nome", "").strip()
                    if not nome:
                        raise ValueError("nome is required")

                    email = row.get("email", "").strip() or None

                    tipo = row.get("tipo", "").strip().upper()
                    if tipo not in ["ASSUNTO", "CONTRATTO"]:
                        raise ValueError(f"tipo must be ASSUNTO or CONTRATTO, got {tipo}")

                    docenti.append({
                        "nome": nome,
                        "email": email,
                        "tipo": tipo,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(docenti)} teachers")
            return docenti

        except Exception as e:
            logger.error(f"Error parsing teachers CSV: {e}")
            raise

    @staticmethod
    def parse_classi_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse classes from CSV.
        Expected columns: nome, n_studenti (optional)
        Optional: gruppo (year-group label matching a PDF calendar's columns,
        e.g. "PRIME" - required only if the calendar was extracted from a
        per-year-group PDF and daily hours should apply to this classe)
        """
        logger.info("Parsing classes from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            classi = []

            for row_idx, row in enumerate(reader, start=2):
                try:
                    nome = row.get("nome", "").strip()
                    if not nome:
                        raise ValueError("nome is required")

                    n_studenti_str = row.get("n_studenti", "0").strip()
                    try:
                        n_studenti = int(n_studenti_str)
                    except ValueError:
                        raise ValueError(f"n_studenti must be integer, got {n_studenti_str}")

                    gruppo = (row.get("gruppo") or "").strip() or None

                    classi.append({
                        "nome": nome,
                        "n_studenti": n_studenti,
                        "gruppo": gruppo,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(classi)} classes")
            return classi

        except Exception as e:
            logger.error(f"Error parsing classes CSV: {e}")
            raise

    @staticmethod
    def parse_materie_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse subjects from CSV.
        Expected columns: nome, tipo (TEORIA/PRATICA), peso_cognitivo (ALTO/MEDIO/BASSO)
        """
        logger.info("Parsing subjects from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            materie = []

            for row_idx, row in enumerate(reader, start=2):
                try:
                    nome = row.get("nome", "").strip()
                    if not nome:
                        raise ValueError("nome is required")

                    tipo = row.get("tipo", "").strip().upper()
                    if tipo not in ["TEORIA", "PRATICA"]:
                        raise ValueError(f"tipo must be TEORIA or PRATICA, got {tipo}")

                    peso_cognitivo = row.get("peso_cognitivo", "MEDIO").strip().upper()
                    if peso_cognitivo not in ["ALTO", "MEDIO", "BASSO"]:
                        raise ValueError(f"peso_cognitivo must be ALTO/MEDIO/BASSO, got {peso_cognitivo}")

                    materie.append({
                        "nome": nome,
                        "tipo": tipo,
                        "peso_cognitivo": peso_cognitivo,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(materie)} subjects")
            return materie

        except Exception as e:
            logger.error(f"Error parsing subjects CSV: {e}")
            raise

    @staticmethod
    def parse_assegnazioni_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse teacher-class-subject assignments from CSV.
        Expected columns: docente_nome, classe_nome, materia_nome, ore_anno
        """
        logger.info("Parsing assignments from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            assegnazioni = []

            for row_idx, row in enumerate(reader, start=2):
                try:
                    docente_nome = row.get("docente_nome", "").strip()
                    if not docente_nome:
                        raise ValueError("docente_nome is required")

                    classe_nome = row.get("classe_nome", "").strip()
                    if not classe_nome:
                        raise ValueError("classe_nome is required")

                    materia_nome = row.get("materia_nome", "").strip()
                    if not materia_nome:
                        raise ValueError("materia_nome is required")

                    ore_anno_str = row.get("ore_anno", "0").strip()
                    try:
                        ore_anno = int(ore_anno_str)
                        if ore_anno <= 0:
                            raise ValueError(f"ore_anno must be > 0, got {ore_anno}")
                    except ValueError as e:
                        raise ValueError(f"Invalid ore_anno: {ore_anno_str}")

                    assegnazioni.append({
                        "docente_nome": docente_nome,
                        "classe_nome": classe_nome,
                        "materia_nome": materia_nome,
                        "ore_anno": ore_anno,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(assegnazioni)} assignments")
            return assegnazioni

        except Exception as e:
            logger.error(f"Error parsing assignments CSV: {e}")
            raise

    @staticmethod
    def parse_accoppiamenti_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse paired classes from CSV.
        Expected columns: classe_a, classe_b, materia_nome, note (optional)
        """
        logger.info("Parsing paired classes from CSV")

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            accoppiamenti = []

            for row_idx, row in enumerate(reader, start=2):
                try:
                    classe_a = row.get("classe_a", "").strip()
                    if not classe_a:
                        raise ValueError("classe_a is required")

                    classe_b = row.get("classe_b", "").strip()
                    if not classe_b:
                        raise ValueError("classe_b is required")

                    materia_nome = row.get("materia_nome", "").strip()
                    if not materia_nome:
                        raise ValueError("materia_nome is required")

                    note = row.get("note", "").strip() or None

                    accoppiamenti.append({
                        "classe_a": classe_a,
                        "classe_b": classe_b,
                        "materia_nome": materia_nome,
                        "note": note,
                    })

                except ValueError as e:
                    logger.warning(f"Row {row_idx}: {e}")
                    raise

            logger.info(f"Parsed {len(accoppiamenti)} paired classes")
            return accoppiamenti

        except Exception as e:
            logger.error(f"Error parsing paired classes CSV: {e}")
            raise


# Italian day names, in app order (0=lunedì..4=venerdì). Index-paired lists:
# the no-accent lowercase form is the app's own convention (see
# DisponibilitaSettimanale.giorni_fasce keys); the accented form is what
# actually appears in these school PDFs.
GIORNI_ORDINE = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
GIORNI_ACCENTATI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì"]

ROMANO_A_GRUPPO = {"I": "PRIME", "II": "SECONDE", "III": "TERZE", "IV": "QUARTE"}


class SchoolRosterParser:
    """
    Parse the two ancillary real-world PDFs used by scripts/import_documenti.py
    to bootstrap docente/classe/assegnazione/disponibilita data for an actual
    school: a "Docente -> Aula assegnata" roster, and a weekly timetable PDF
    (from which classi, docente-classe associations, and docente availability
    are all derived - see that script's module docstring for the reasoning).

    Unlike CalendarParser.parse_calendario_pdf, both of these use clean
    bordered tables that pdfplumber's own table-grid detection extracts
    reliably, so no custom word-position clustering is needed here.
    """

    @staticmethod
    def parse_elenco_docenti_pdf(file_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Parse a "Docente | Aula/Laboratorio | Piano" roster PDF.
        Rows whose first column isn't a "COGNOME NOME" person name (e.g. a
        generic lab label like "LAB. INFORMATICO" used as a placeholder row
        in place of a docente) are skipped.
        """
        import pdfplumber

        logger.info("Parsing docenti roster from PDF")
        entries: List[Dict[str, Any]] = []

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    for table in page.find_tables():
                        for row in table.extract():
                            if not row or not row[0]:
                                continue
                            nome_completo = row[0].strip()
                            if not nome_completo or nome_completo.upper().startswith("LAB."):
                                continue
                            parts = nome_completo.split()
                            if len(parts) < 2:
                                continue
                            entries.append({
                                "nome_completo": nome_completo,
                                "cognome": parts[0].upper(),
                                "aula": (row[1] or "").strip() if len(row) > 1 else None,
                                "piano": (row[2] or "").strip() if len(row) > 2 else None,
                            })

            logger.info(f"Parsed {len(entries)} docenti from roster PDF")
            return entries

        except Exception as e:
            logger.error(f"Error parsing docenti roster PDF: {e}")
            raise

    @staticmethod
    def _normalize_giorno(raw: Optional[str]) -> Optional[str]:
        """
        Match a (possibly garbled) day-name cell against the 5 known Italian
        weekdays. Rotated/vertical text in this PDF's left margin sometimes
        comes out with every letter doubled (e.g. "mmaarrtteeddìì" for
        "martedì") - trying both the raw and de-doubled (every other char)
        forms handles that without depending on it happening consistently.
        """
        if not raw:
            return None
        raw = raw.strip()
        if not raw:
            return None
        candidates = {raw.lower(), raw.lower()[0::2]}
        for candidate in candidates:
            for idx, accentato in enumerate(GIORNI_ACCENTATI):
                if candidate == accentato:
                    return GIORNI_ORDINE[idx]
        return None

    @staticmethod
    def _classe_gruppo(nome_classe: str) -> Optional[str]:
        """
        Infer a classe's year-group (matching the annual calendar's PDF
        columns, see CALENDARIO_PDF_GRUPPI_COLONNE) from its name, which in
        this school's timetable is "<numero romano> <corso>" (e.g. "II
        ELETTRICISTI"). The one exception is "I.T.C." (this school's special
        first-year-only "4+2" track, with no II/III/IV counterpart), mapped
        to the calendar's PRIMA4+2 column rather than PRIME.
        """
        parts = nome_classe.strip().split(" ", 1)
        if len(parts) != 2:
            return None
        romano, resto = parts
        if "I.T.C." in resto.upper():
            return "PRIMA4+2"
        return ROMANO_A_GRUPPO.get(romano.upper())

    @staticmethod
    def parse_orario_settimanale_pdf(file_bytes: bytes) -> Dict[str, Any]:
        """
        Parse a weekly timetable PDF ("Orario scolastico dal X al Y ...":
        one row per hour slot, one column per classe, cell = docente
        surname teaching that classe at that hour) into:
          - classi: [{"nome": str, "gruppo": Optional[str]}, ...]
          - slots: [{"classe_nome", "giorno" (no-accent lowercase), "ora_inizio", "docente_cognome"}, ...]
          - week_label: the raw "dal 14 al 18 Settembre"-style text found on
            the page, if any (no year is printed on this template - the
            caller must confirm/supply it, e.g. by cross-checking the
            annual calendar for a matching week).

        From `slots` a caller can derive both docente-classe associations
        (which classi a docente teaches) and docente availability (the hours
        a docente is observed present that week).
        """
        import pdfplumber
        import re

        logger.info("Parsing weekly timetable from PDF")

        classi: List[Dict[str, Any]] = []
        slots: List[Dict[str, Any]] = []
        week_label: Optional[str] = None

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    if week_label is None:
                        text = page.extract_text() or ""
                        m = re.search(r"dal\s+\d{1,2}\s+al\s+\d{1,2}\s+\w+", text, re.IGNORECASE)
                        if m:
                            week_label = m.group(0)

                    for table in page.find_tables():
                        data = table.extract()
                        if not data:
                            continue

                        # The header row (class-name columns) is usually data[0], but
                        # some PDFs render the page title as an extra leading table row
                        # (a single merged cell, everything else None) - detect the real
                        # header as the first row with several non-empty cells from
                        # column 2 onward, rather than assuming it's always row 0.
                        header_idx = next(
                            (
                                idx for idx, row in enumerate(data)
                                if sum(1 for cell in row[2:] if cell and cell.strip()) >= 2
                            ),
                            0,
                        )
                        header = data[header_idx]
                        classe_columns = [
                            (idx, cell.strip())
                            for idx, cell in enumerate(header)
                            if idx >= 2 and cell and cell.strip()
                        ]
                        if not classi:
                            classi = [
                                {"nome": nome, "gruppo": SchoolRosterParser._classe_gruppo(nome)}
                                for _, nome in classe_columns
                            ]

                        current_giorno: Optional[str] = None
                        for row in data[header_idx + 1:]:
                            giorno = SchoolRosterParser._normalize_giorno(row[0] if row else None)
                            if giorno:
                                current_giorno = giorno

                            ora_label = (row[1] or "").strip() if len(row) > 1 else ""
                            ora_match = re.match(r"(\d{1,2})\s*-\s*\d{1,2}", ora_label)
                            if not current_giorno or not ora_match:
                                continue
                            ora_inizio = int(ora_match.group(1))

                            for idx, nome_classe in classe_columns:
                                docente = (row[idx] or "").strip() if idx < len(row) else ""
                                if not docente:
                                    continue
                                slots.append({
                                    "classe_nome": nome_classe,
                                    "giorno": current_giorno,
                                    "ora_inizio": ora_inizio,
                                    "docente_cognome": docente.upper(),
                                })

            logger.info(
                f"Parsed weekly timetable: {len(classi)} classi, {len(slots)} slot entries"
                + (f", week_label={week_label!r}" if week_label else "")
            )
            return {"classi": classi, "slots": slots, "week_label": week_label}

        except Exception as e:
            logger.error(f"Error parsing weekly timetable PDF: {e}")
            raise
