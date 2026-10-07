from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from datetime import date, timedelta
from typing import Optional, List
from app.models import (
    ConflittoGestito,
    OrarioSettimanale, SlotLezione, Assegnazione, Docente, Classe, Materia,
    DisponibilitaSettimanale, CalendarioAnnuale, MonteOreAnnuale, ClasseAccoppiata, Scuola
)
from app.domain.solver import ScheduleContext, AssegnazioneDati, DisponibilitaDati, CalendarioDati
import logging

logger = logging.getLogger(__name__)


class ScheduleRepository:
    """Repository for schedule operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_week_context(self, scuola_id: str, week_start: date) -> ScheduleContext:
        """
        Extract all data needed for solver into ScheduleContext.
        This decouples solver from database layer.
        """
        logger.info(f"Building context for school {scuola_id} week {week_start}")

        week_end = week_start + timedelta(days=7)

        scuola = self.db.query(Scuola).filter_by(id=scuola_id).first()
        anno_fine = scuola.data_fine_anno if scuola else week_end

        # 1. Get all assegnazioni with related entities
        assegnazioni = self.db.query(Assegnazione).filter_by(scuola_id=scuola_id).all()

        if not assegnazioni:
            logger.warning(f"No assegnazioni found for school {scuola_id}")

        assegnazioni_dati = []
        docenti_set = set()
        classi_set = set()

        visti = set()
        for asg in assegnazioni:
            # Stesso docente, classe e tipo = la stessa entità: una copia non deve diventare una
            # seconda variabile (la lezione salvata non saprebbe a quale delle due appartiene).
            trio = (asg.docente_id, asg.classe_id, asg.materia_id)
            if trio in visti:
                logger.warning(f"Assegnazione duplicata ignorata: {asg.id}")
                continue
            visti.add(trio)
            docente = self.db.query(Docente).filter_by(id=asg.docente_id).first()
            classe = self.db.query(Classe).filter_by(id=asg.classe_id).first()
            materia = self.db.query(Materia).filter_by(id=asg.materia_id).first()

            if not (docente and classe and materia):
                logger.warning(f"Incomplete assegnazione: {asg.id}")
                continue

            # Get residual hours
            monte = self.db.query(MonteOreAnnuale).filter_by(
                scuola_id=scuola_id,
                classe_id=asg.classe_id,
                materia_id=asg.materia_id,
                docente_id=asg.docente_id,
            ).first()

            ore_residue = monte.ore_totali - monte.ore_erogate if monte else 0

            asg_data = AssegnazioneDati(
                assegnazione_id=asg.id,
                docente_id=docente.id,
                docente_nome=docente.nome,
                docente_tipo=docente.tipo,
                classe_id=classe.id,
                classe_nome=classe.nome,
                materia_id=materia.id,
                materia_nome=materia.nome,
                materia_tipo=materia.tipo,
                peso_cognitivo=materia.peso_cognitivo,
                ore_residue=ore_residue,
                singola=bool(asg.singola),
            )

            assegnazioni_dati.append(asg_data)
            docenti_set.add(docente.id)
            classi_set.add(classe.id)

        # 2. Get availability for this week
        disponibilita_list = self.db.query(DisponibilitaSettimanale).filter(
            and_(
                DisponibilitaSettimanale.scuola_id == scuola_id,
                DisponibilitaSettimanale.settimana_inizio == week_start,
            )
        ).all()

        disponibilita_map = {}
        for disp in disponibilita_list:
            disponibilita_map[disp.docente_id] = DisponibilitaDati(
                docente_id=disp.docente_id,
                giorni_fasce=disp.giorni_fasce,
            )

        # Same fallback the Disponibilita page applies for a docente with no
        # record this week (AvailabilityService.get_or_create_availability):
        # inherit their most recent earlier week, else the default 8-14 grid.
        # Read-only - nothing is persisted, and recorded weeks are never touched.
        for docente_id in docenti_set:
            if docente_id in disponibilita_map:
                continue
            previous = self.db.query(DisponibilitaSettimanale).filter(
                and_(
                    DisponibilitaSettimanale.scuola_id == scuola_id,
                    DisponibilitaSettimanale.docente_id == docente_id,
                    DisponibilitaSettimanale.settimana_inizio < week_start,
                )
            ).order_by(DisponibilitaSettimanale.settimana_inizio.desc()).first()
            giorni_fasce = previous.giorni_fasce if previous else {
                giorno: [
                    {"ora_inizio": f"{h:02d}:00", "ora_fine": f"{h + 1:02d}:00", "disponibile": True}
                    for h in range(8, 14)
                ]
                for giorno in ("lunedi", "martedi", "mercoledi", "giovedi", "venerdi")
            }
            disponibilita_map[docente_id] = DisponibilitaDati(
                docente_id=docente_id, giorni_fasce=giorni_fasce,
            )

        # 3. Get calendar for week
        calendario_list = self.db.query(CalendarioAnnuale).filter(
            and_(
                CalendarioAnnuale.scuola_id == scuola_id,
                CalendarioAnnuale.data >= week_start,
                CalendarioAnnuale.data < week_end,
            )
        ).all()

        calendario = []
        stage_resolver = self._stage_classe_resolver(scuola_id)
        for cal in calendario_list:
            # Convert date to giorno (0-4)
            giorno = (cal.data - week_start).days
            if 0 <= giorno < 5:
                cal_data = CalendarioDati(
                    data=cal.data,
                    giorno=giorno,
                    ore_max_giornata=cal.ore_max_giornata,
                    gruppo=cal.gruppo,
                    flag_stage_classe_id=stage_resolver(cal.flag_stage_classe_id),
                    flag_stage_gruppo=cal.flag_stage_gruppo,
                    flag_chiusura=cal.flag_chiusura,
                    ora_inizio_min=cal.ora_inizio_min,
                )
                calendario.append(cal_data)

        # Fill missing days
        for giorno in range(5):
            if not any(c.giorno == giorno for c in calendario):
                data = week_start + timedelta(days=giorno)
                calendario.append(CalendarioDati(
                    data=data,
                    giorno=giorno,
                    ore_max_giornata=6,  # default
                ))

        # 4. Get paired classes
        classi_accoppiate_list = self.db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id).all()
        classi_accoppiate = [
            (ca.classe_a_id, ca.classe_b_id, ca.materia_id, ca.docente_id)
            for ca in classi_accoppiate_list
        ]

        # 5. Build docenti map
        docenti_map = {}
        for docente_id in docenti_set:
            docente = self.db.query(Docente).filter_by(id=docente_id).first()
            if docente:
                docenti_map[docente_id] = docente.tipo

        # 6. Build materie map
        materie_map = {}
        for asg_data in assegnazioni_dati:
            materie_map[asg_data.materia_id] = asg_data.materia_tipo

        # 7. Build classi -> gruppo map (year-group label, for per-group PDF calendars)
        classi_gruppo = {}
        for classe_id in classi_set:
            classe = self.db.query(Classe).filter_by(id=classe_id).first()
            if classe:
                classi_gruppo[classe_id] = classe.gruppo

        logger.info(f"Context built: {len(assegnazioni_dati)} asgs, {len(docenti_map)} teachers, {len(classi_set)} classes")

        return ScheduleContext(
            scuola_id=scuola_id,
            week_start=week_start,
            week_end=week_end,
            anno_fine=anno_fine,
            assegnazioni=assegnazioni_dati,
            disponibilita_map=disponibilita_map,
            calendario=calendario,
            classi_accoppiate=classi_accoppiate,
            docenti_map=docenti_map,
            classi_set=classi_set,
            materie_map=materie_map,
            classi_gruppo=classi_gruppo,
        )

    def save_generated_schedule(
        self,
        scuola_id: str,
        week_start: date,
        slots: List[dict],
        quality_score: float,
        quality_level: str,
        n_soft_conflicts: int,
    ) -> str:
        """
        Save generated schedule to database.
        Returns: schedule_id
        """
        logger.info(f"Saving schedule: {len(slots)} slots, score {quality_score:.1f}")

        try:
            # Regenerating a week that already has a schedule replaces its
            # slots in place (same id) instead of inserting a second
            # OrarioSettimanale row for the same scuola_id/week_start, which
            # would make get_schedule_by_week's lookup pick an arbitrary one.
            orario = self.db.query(OrarioSettimanale).filter(
                OrarioSettimanale.scuola_id == scuola_id,
                OrarioSettimanale.settimana_inizio == week_start,
            ).first()

            if orario:
                self.db.query(SlotLezione).filter(
                    SlotLezione.orario_settimanale_id == orario.id
                ).delete(synchronize_session=False)
                # a new solution: earlier approve/reject decisions no longer apply
                self.db.query(ConflittoGestito).filter(
                    ConflittoGestito.orario_settimanale_id == orario.id
                ).delete(synchronize_session=False)
                orario.stato = "BOZZA"
                orario.quality_score = quality_score
                orario.quality_level = quality_level
                orario.n_conflitti_soft = n_soft_conflicts
                orario.approved_at = None
            else:
                orario = OrarioSettimanale(
                    scuola_id=scuola_id,
                    settimana_inizio=week_start,
                    stato="BOZZA",
                    quality_score=quality_score,
                    quality_level=quality_level,
                    n_conflitti_soft=n_soft_conflicts,
                )
                self.db.add(orario)
                self.db.flush()  # Get orario.id

            # Bulk insert SlotLezione records
            for slot in slots:
                slot_obj = SlotLezione(
                    orario_settimanale_id=orario.id,
                    classe_id=slot["classe_id"],
                    docente_id=slot["docente_id"],
                    materia_id=slot["materia_id"],
                    giorno=slot["giorno"],
                    ora_inizio=slot["ora_inizio"],
                    ora_fine=slot["ora_fine"],
                    accoppiata=slot.get("accoppiata", False),
                    classe_accoppiata_id=slot.get("classe_accoppiata_id"),
                )
                self.db.add(slot_obj)

            self.db.commit()
            logger.info(f"Schedule saved: {orario.id}")
            return orario.id

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving schedule: {e}")
            raise

    _GIORNI_NOMI = ["LUNEDI", "MARTEDI", "MERCOLEDI", "GIOVEDI", "VENERDI"]

    def _stage_classe_resolver(self, scuola_id: str):
        """
        Callable mapping a stored flag_stage_classe_id to a real classe id.
        The admin may have typed the classe *name* (e.g. "I OP. INFORM.")
        instead of its UUID; accept either, case-insensitively, so a stage
        entry is never silently ignored. Unknown values are returned as-is.
        """
        classi = self.db.query(Classe).filter_by(scuola_id=scuola_id).all()
        ids = {c.id for c in classi}
        by_nome = {c.nome.strip().lower(): c.id for c in classi if c.nome}

        def resolve(value):
            if not value or value in ids:
                return value
            return by_nome.get(value.strip().lower(), value)

        return resolve

    def _stage_cells_for_week(self, scuola_id: str, week_start: date) -> List[dict]:
        """
        {classe_id, classe_nome, giorno} entries on stage this week - a
        whole gruppo via flag_stage_gruppo, or a single classe via
        flag_stage_classe_id - so schedule renderers can label them "STAGE"
        instead of "Libera" (they carry no SlotLezione at all, same as any
        other empty hour) and so a classe on stage every day this week
        still gets a column (classi_sorted elsewhere is otherwise built
        only from classi that have >=1 actual slot).
        """
        week_end = week_start + timedelta(days=7)
        calendario = self.db.query(CalendarioAnnuale).filter(
            and_(
                CalendarioAnnuale.scuola_id == scuola_id,
                CalendarioAnnuale.data >= week_start,
                CalendarioAnnuale.data < week_end,
            )
        ).all()

        classi = self.db.query(Classe).filter_by(scuola_id=scuola_id).all()
        classi_gruppo = {c.id: c.gruppo for c in classi}
        classi_nome = {c.id: c.nome for c in classi}
        stage_resolver = self._stage_classe_resolver(scuola_id)

        cells = set()
        for cal in calendario:
            giorno_idx = (cal.data - week_start).days
            if not (0 <= giorno_idx < 5):
                continue
            giorno_nome = self._GIORNI_NOMI[giorno_idx]

            stage_id = stage_resolver(cal.flag_stage_classe_id)
            if stage_id:
                cells.add((stage_id, giorno_nome))
            elif cal.flag_stage_gruppo and cal.gruppo:
                for classe_id, gruppo in classi_gruppo.items():
                    if gruppo == cal.gruppo:
                        cells.add((classe_id, giorno_nome))

        return [
            {"classe_id": cid, "classe_nome": classi_nome.get(cid, cid), "giorno": g}
            for cid, g in cells
        ]

    def get_schedule_by_week(self, scuola_id: str, week_start: date) -> Optional[dict]:
        """
        Retrieve schedule for week with all related entities.
        Returns dict or None if not found.
        """
        orario = self.db.query(OrarioSettimanale).filter(
            and_(
                OrarioSettimanale.scuola_id == scuola_id,
                OrarioSettimanale.settimana_inizio == week_start,
            )
        ).options(
            joinedload(OrarioSettimanale.slot_lezioni).joinedload(SlotLezione.docente),
            joinedload(OrarioSettimanale.slot_lezioni).joinedload(SlotLezione.classe),
            joinedload(OrarioSettimanale.slot_lezioni).joinedload(SlotLezione.materia),
        ).first()

        if not orario:
            return None

        slots = []
        for slot in orario.slot_lezioni:
            slot_dict = {
                "slot_id": slot.id,
                "classe_id": slot.classe_id,
                "classe_nome": slot.classe.nome if slot.classe else None,
                "docente_id": slot.docente_id,
                "docente_nome": slot.docente.nome if slot.docente else None,
                "materia_id": slot.materia_id,
                "materia_nome": slot.materia.nome if slot.materia else None,
                "materia_tipo": slot.materia.tipo if slot.materia else None,
                "giorno": slot.giorno,
                "ora_inizio": slot.ora_inizio,
                "ora_fine": slot.ora_fine,
                "accoppiata": slot.accoppiata,
                "classe_accoppiata_id": slot.classe_accoppiata_id,
            }
            slots.append(slot_dict)

        return {
            "schedule_id": orario.id,
            "week_start": orario.settimana_inizio,
            "stato": orario.stato,
            "quality_score": orario.quality_score,
            "quality_level": orario.quality_level,
            "n_soft_conflicts": orario.n_conflitti_soft,
            "created_at": orario.created_at,
            "approved_at": orario.approved_at,
            "slots": slots,
            "stage_cells": self._stage_cells_for_week(scuola_id, week_start),
        }
