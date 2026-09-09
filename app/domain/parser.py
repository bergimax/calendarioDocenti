"""
Parsing logic for calendar PDF and CSV files.
Decoupled from routes/DB for testability.
"""

import csv
import io
from datetime import datetime, date
from typing import List, Dict, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CalendarParser:
    """Parse school calendar from PDF or manual input."""

    @staticmethod
    def parse_calendar_csv(csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse calendar from CSV format.
        Expected columns: data (YYYY-MM-DD), ore_max_giornata (4/5/6), flag_chiusura (true/false)
        Optional: stage_classe_id (class in stage on this date)
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

                    calendar_entries.append({
                        "data": data,
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

                    classi.append({
                        "nome": nome,
                        "n_studenti": n_studenti,
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
