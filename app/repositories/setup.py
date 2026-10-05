from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime
from app.models import (
    Scuola, Classe, Docente, Materia, Assegnazione,
    CalendarioAnnuale, MonteOreAnnuale, ClasseAccoppiata
)
from typing import List, Dict, Any, Optional


class SetupRepository:
    """Repository for setup/onboarding operations."""

    def __init__(self, db: Session):
        self.db = db

    def create_school(
        self,
        nome: str,
        anno_formativo: str,
        data_inizio_anno: datetime,
        data_fine_anno: datetime,
        scuola_id: Optional[str] = None,
    ) -> Scuola:
        """
        Create new school, or update it in place if scuola_id already exists.
        v1 is single-tenant: the caller passes a fixed scuola_id (e.g. "sch_1") so
        every other endpoint (hardcoded to that id) can find the data afterwards.
        """
        scuola = None
        if scuola_id:
            scuola = self.db.query(Scuola).filter_by(id=scuola_id).first()

        if scuola:
            scuola.nome = nome
            scuola.anno_formativo = anno_formativo
            scuola.data_inizio_anno = data_inizio_anno
            scuola.data_fine_anno = data_fine_anno
        else:
            scuola = Scuola(
                nome=nome,
                anno_formativo=anno_formativo,
                data_inizio_anno=data_inizio_anno,
                data_fine_anno=data_fine_anno,
            )
            if scuola_id:
                scuola.id = scuola_id
            self.db.add(scuola)

        self.db.flush()
        return scuola

    def bulk_create_classes(self, scuola_id: str, classi_data: List[Dict[str, Any]]) -> Dict[str, str]:
        """Bulk create classes. Returns mapping nome -> id."""
        classe_map = {}
        for data in classi_data:
            classe = Classe(
                scuola_id=scuola_id,
                nome=data["nome"],
                n_studenti=data.get("n_studenti", 0),
                gruppo=data.get("gruppo"),
            )
            self.db.add(classe)
            self.db.flush()
            classe_map[data["nome"]] = classe.id

        return classe_map

    def bulk_create_teachers(
        self, scuola_id: str, docenti_data: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Bulk create teachers. Returns mapping nome -> id."""
        docenti_map = {}
        for data in docenti_data:
            docente = Docente(
                scuola_id=scuola_id,
                nome=data["nome"],
                email=data.get("email"),
                tipo=data["tipo"],
                first_time_this_year=True,
            )
            self.db.add(docente)
            self.db.flush()
            docenti_map[data["nome"]] = docente.id

        return docenti_map

    def bulk_create_subjects(
        self, scuola_id: str, materie_data: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Bulk create subjects. Returns mapping nome -> id."""
        materie_map = {}
        for data in materie_data:
            materia = Materia(
                scuola_id=scuola_id,
                nome=data["nome"],
                tipo=data["tipo"],
                peso_cognitivo=data["peso_cognitivo"],
            )
            self.db.add(materia)
            self.db.flush()
            materie_map[data["nome"]] = materia.id

        return materie_map

    def bulk_create_calendar(
        self, scuola_id: str, calendario_data: List[Dict[str, Any]]
    ) -> None:
        """Bulk create calendar dates."""
        for data in calendario_data:
            cal = CalendarioAnnuale(
                scuola_id=scuola_id,
                data=data["data"],
                gruppo=data.get("gruppo"),
                ore_max_giornata=data.get("ore_max_giornata", 6),
                flag_chiusura=data.get("flag_chiusura", False),
                flag_stage_classe_id=data.get("flag_stage_classe_id") or data.get("stage_classe_id"),
                flag_stage_gruppo=bool(data.get("flag_stage_gruppo", False)),
            )
            self.db.add(cal)

    def bulk_create_assignments(
        self,
        scuola_id: str,
        assegnazioni_data: List[Dict[str, Any]],
        docenti_map: Dict[str, str],
        classi_map: Dict[str, str],
        materie_map: Dict[str, str],
    ) -> None:
        """Bulk create assignments."""
        for data in assegnazioni_data:
            docente_id = docenti_map.get(data["docente_nome"])
            classe_id = classi_map.get(data["classe_nome"])
            materia_id = materie_map.get(data["materia_nome"])

            if docente_id and classe_id and materia_id:
                assegnazione = Assegnazione(
                    scuola_id=scuola_id,
                    docente_id=docente_id,
                    classe_id=classe_id,
                    materia_id=materia_id,
                )
                self.db.add(assegnazione)

                # Also create monte ore record
                monte_ore = MonteOreAnnuale(
                    scuola_id=scuola_id,
                    classe_id=classe_id,
                    materia_id=materia_id,
                    docente_id=docente_id,
                    ore_totali=data.get("ore_anno", 0),
                    ore_erogate=0,
                )
                self.db.add(monte_ore)

    def bulk_create_paired_classes(
        self,
        scuola_id: str,
        accoppiamenti_data: List[Dict[str, Any]],
        classi_map: Dict[str, str],
        materie_map: Dict[str, str],
    ) -> None:
        """Bulk create paired classes."""
        for data in accoppiamenti_data:
            classe_a_id = classi_map.get(data["classe_a"])
            classe_b_id = classi_map.get(data["classe_b"])
            materia_id = materie_map.get(data["materia_nome"])

            if classe_a_id and classe_b_id and materia_id:
                accoppiamento = ClasseAccoppiata(
                    scuola_id=scuola_id,
                    classe_a_id=classe_a_id,
                    classe_b_id=classe_b_id,
                    materia_id=materia_id,
                    note=data.get("note"),
                )
                self.db.add(accoppiamento)

    def commit(self) -> None:
        """Commit transaction."""
        self.db.commit()

    def rollback(self) -> None:
        """Rollback transaction."""
        self.db.rollback()
