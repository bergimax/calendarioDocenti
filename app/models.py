from sqlalchemy import Column, String, Integer, Float, Boolean, Date, DateTime, ForeignKey, JSON, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from app.database import Base


class Scuola(Base):
    """School entity."""
    __tablename__ = "scuola"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    nome = Column(String(255), nullable=False)
    anno_formativo = Column(String(50), nullable=False)  # e.g., "2026-2027"
    data_inizio_anno = Column(Date, nullable=False)
    data_fine_anno = Column(Date, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    classi = relationship("Classe", back_populates="scuola")
    docenti = relationship("Docente", back_populates="scuola")
    materie = relationship("Materia", back_populates="scuola")
    assegnazioni = relationship("Assegnazione", back_populates="scuola")
    calendario = relationship("CalendarioAnnuale", back_populates="scuola")
    monte_ore = relationship("MonteOreAnnuale", back_populates="scuola")
    disponibilita = relationship("DisponibilitaSettimanale", back_populates="scuola")
    orari = relationship("OrarioSettimanale", back_populates="scuola")


class Classe(Base):
    """Class entity."""
    __tablename__ = "classe"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    nome = Column(String(50), nullable=False)  # e.g., "1A", "2B"
    n_studenti = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="classi")
    assegnazioni = relationship("Assegnazione", back_populates="classe")
    monte_ore = relationship("MonteOreAnnuale", back_populates="classe")
    slot_lezioni = relationship(
        "SlotLezione", back_populates="classe", foreign_keys="[SlotLezione.classe_id]"
    )


class Docente(Base):
    """Teacher entity."""
    __tablename__ = "docente"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    nome = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    tipo = Column(Enum("ASSUNTO", "CONTRATTO", name="docente_tipo"), nullable=False)
    active = Column(Boolean, default=True)
    first_time_this_year = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="docenti")
    assegnazioni = relationship("Assegnazione", back_populates="docente")
    monte_ore = relationship("MonteOreAnnuale", back_populates="docente")
    disponibilita = relationship("DisponibilitaSettimanale", back_populates="docente")
    slot_lezioni = relationship("SlotLezione", back_populates="docente")


class Materia(Base):
    """Subject entity."""
    __tablename__ = "materia"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    nome = Column(String(255), nullable=False)
    tipo = Column(Enum("TEORIA", "PRATICA", name="materia_tipo"), nullable=False)
    peso_cognitivo = Column(Enum("ALTO", "MEDIO", "BASSO", name="peso_cognitivo"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="materie")
    assegnazioni = relationship("Assegnazione", back_populates="materia")
    monte_ore = relationship("MonteOreAnnuale", back_populates="materia")
    slot_lezioni = relationship("SlotLezione", back_populates="materia")


class Assegnazione(Base):
    """Teacher-Class-Subject assignment."""
    __tablename__ = "assegnazione"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    docente_id = Column(String, ForeignKey("docente.id"), nullable=False)
    classe_id = Column(String, ForeignKey("classe.id"), nullable=False)
    materia_id = Column(String, ForeignKey("materia.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="assegnazioni")
    docente = relationship("Docente", back_populates="assegnazioni")
    classe = relationship("Classe", back_populates="assegnazioni")
    materia = relationship("Materia", back_populates="assegnazioni")


class CalendarioAnnuale(Base):
    """Annual calendar (dates, closures, stages)."""
    __tablename__ = "calendario_annuale"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    data = Column(Date, nullable=False)
    ore_max_giornata = Column(Integer, default=6)  # 4, 5, or 6
    flag_chiusura = Column(Boolean, default=False)
    flag_stage_classe_id = Column(String, ForeignKey("classe.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="calendario")


class MonteOreAnnuale(Base):
    """Annual hours budget per class-subject-teacher."""
    __tablename__ = "monte_ore_annuale"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    classe_id = Column(String, ForeignKey("classe.id"), nullable=False)
    materia_id = Column(String, ForeignKey("materia.id"), nullable=False)
    docente_id = Column(String, ForeignKey("docente.id"), nullable=False)
    ore_totali = Column(Integer, nullable=False)
    ore_erogate = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="monte_ore")
    classe = relationship("Classe", back_populates="monte_ore")
    materia = relationship("Materia", back_populates="monte_ore")
    docente = relationship("Docente", back_populates="monte_ore")


class DisponibilitaSettimanale(Base):
    """Weekly availability per teacher (hour slots)."""
    __tablename__ = "disponibilita_settimanale"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    docente_id = Column(String, ForeignKey("docente.id"), nullable=False)
    settimana_inizio = Column(Date, nullable=False)
    giorni_fasce = Column(JSON, nullable=False)  # {"lunedi": [{ora_inizio, ora_fine, disponibile}], ...}
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    scuola = relationship("Scuola", back_populates="disponibilita")
    docente = relationship("Docente", back_populates="disponibilita")


class ClasseAccoppiata(Base):
    """Paired classes for joint lessons."""
    __tablename__ = "classe_accoppiata"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    classe_a_id = Column(String, ForeignKey("classe.id"), nullable=False)
    classe_b_id = Column(String, ForeignKey("classe.id"), nullable=False)
    materia_id = Column(String, ForeignKey("materia.id"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class OrarioSettimanale(Base):
    """Weekly schedule (container for slots)."""
    __tablename__ = "orario_settimanale"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    settimana_inizio = Column(Date, nullable=False)
    stato = Column(Enum("BOZZA", "APPROVATO", name="orario_stato"), default="BOZZA")
    quality_score = Column(Float, nullable=True)  # 0-100
    quality_level = Column(Enum("A", "B", "C", name="quality_level"), nullable=True)
    n_conflitti_soft = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    approved_at = Column(DateTime, nullable=True)

    # Relationships
    scuola = relationship("Scuola", back_populates="orari")
    slot_lezioni = relationship("SlotLezione", back_populates="orario")
    chat_messages = relationship("ChatMessage", back_populates="orario")


class SlotLezione(Base):
    """Individual lesson slot."""
    __tablename__ = "slot_lezione"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    orario_settimanale_id = Column(String, ForeignKey("orario_settimanale.id"), nullable=False)
    classe_id = Column(String, ForeignKey("classe.id"), nullable=False)
    docente_id = Column(String, ForeignKey("docente.id"), nullable=False)
    materia_id = Column(String, ForeignKey("materia.id"), nullable=False)
    giorno = Column(Enum("LUNEDI", "MARTEDI", "MERCOLEDI", "GIOVEDI", "VENERDI", name="giorno"), nullable=False)
    ora_inizio = Column(Integer, nullable=False)  # 8, 9, 10, ..., 13
    ora_fine = Column(Integer, nullable=False)    # 9, 10, 11, ..., 14
    accoppiata = Column(Boolean, default=False)
    classe_accoppiata_id = Column(String, ForeignKey("classe.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    orario = relationship("OrarioSettimanale", back_populates="slot_lezioni")
    # foreign_keys is required: classe_id and classe_accoppiata_id are both FKs
    # to classe.id, so SQLAlchemy can't otherwise tell which one this join uses.
    classe = relationship("Classe", back_populates="slot_lezioni", foreign_keys=[classe_id])
    docente = relationship("Docente", back_populates="slot_lezioni")
    materia = relationship("Materia", back_populates="slot_lezioni")


class ChatMessage(Base):
    """Chat message history."""
    __tablename__ = "chat_message"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    orario_settimanale_id = Column(String, ForeignKey("orario_settimanale.id"), nullable=False)
    ruolo = Column(Enum("ADMIN", "AI", name="chat_ruolo"), nullable=False)
    messaggio = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

    # Relationships
    orario = relationship("OrarioSettimanale", back_populates="chat_messages")


class PreferenzeAIMemory(Base):
    """AI memory for preferences (in v1: session only, v2: persistent)."""
    __tablename__ = "preferenze_ai_memory"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    regola = Column(Text, nullable=False)  # e.g., "Prof. Neri non lunedì 1ª ora"
    peso = Column(Float, default=1.0)  # weight for soft constraint
    created_at = Column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Audit log for all actions."""
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    scuola_id = Column(String, ForeignKey("scuola.id"), nullable=False)
    orario_settimanale_id = Column(String, ForeignKey("orario_settimanale.id"), nullable=True)
    azione = Column(String(100), nullable=False)  # GENERATE, MODIFY_SLOT, APPROVE, etc
    admin_id = Column(String, nullable=True)  # Admin who performed action
    dettagli = Column(JSON, nullable=True)
    timestamp = Column(DateTime, server_default=func.now())
