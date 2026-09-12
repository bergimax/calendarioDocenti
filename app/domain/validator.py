"""
Data validation logic for setup.
Cross-references between entities to ensure coherence.
"""

from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class DataValidator:
    """Validate consistency of parsed setup data."""

    @staticmethod
    def validate_all_data(
        docenti: List[Dict[str, Any]],
        classi: List[Dict[str, Any]],
        materie: List[Dict[str, Any]],
        assegnazioni: List[Dict[str, Any]],
        accoppiamenti: List[Dict[str, Any]],
        calendario: List[Dict[str, Any]],
    ) -> Tuple[bool, List[str]]:
        """
        Cross-validate all entities.
        Returns: (valid: bool, errors: List[str])
        """
        logger.info("Validating data coherence")

        errors = []

        # Build maps for lookups
        docenti_nomi = {d["nome"] for d in docenti}
        classi_nomi = {c["nome"] for c in classi}
        materie_nomi = {m["nome"] for m in materie}

        # Validate assegnazioni
        for idx, asg in enumerate(assegnazioni):
            if asg["docente_nome"] not in docenti_nomi:
                errors.append(
                    f"Assignment {idx}: teacher '{asg['docente_nome']}' not found in teachers list"
                )

            if asg["classe_nome"] not in classi_nomi:
                errors.append(
                    f"Assignment {idx}: class '{asg['classe_nome']}' not found in classes list"
                )

            if asg["materia_nome"] not in materie_nomi:
                errors.append(
                    f"Assignment {idx}: subject '{asg['materia_nome']}' not found in subjects list"
                )

        # Validate accoppiamenti
        for idx, acc in enumerate(accoppiamenti):
            if acc["classe_a"] not in classi_nomi:
                errors.append(
                    f"Pairing {idx}: class_a '{acc['classe_a']}' not found"
                )

            if acc["classe_b"] not in classi_nomi:
                errors.append(
                    f"Pairing {idx}: class_b '{acc['classe_b']}' not found"
                )

            if acc["materia_nome"] not in materie_nomi:
                errors.append(
                    f"Pairing {idx}: subject '{acc['materia_nome']}' not found"
                )

            # Check that both classes have assignment for this subject
            asg_a = next(
                (a for a in assegnazioni
                 if a["classe_nome"] == acc["classe_a"] and a["materia_nome"] == acc["materia_nome"]),
                None
            )
            asg_b = next(
                (a for a in assegnazioni
                 if a["classe_nome"] == acc["classe_b"] and a["materia_nome"] == acc["materia_nome"]),
                None
            )

            if not asg_a or not asg_b:
                errors.append(
                    f"Pairing {idx}: both classes must have assignment for subject '{acc['materia_nome']}'"
                )

        # Validate calendario
        for idx, cal in enumerate(calendario):
            # Check for stage_classe_id
            if cal.get("stage_classe_id"):
                if cal["stage_classe_id"] not in classi_nomi:
                    errors.append(
                        f"Calendar {idx}: stage class '{cal['stage_classe_id']}' not found"
                    )

        # Warnings (not errors, but logged)
        warnings = []

        # Check if any teacher has no assignments
        for docente in docenti:
            if not any(a["docente_nome"] == docente["nome"] for a in assegnazioni):
                warnings.append(
                    f"Teacher '{docente['nome']}' has no assignments"
                )

        # Check if any class has no assignments
        for classe in classi:
            if not any(a["classe_nome"] == classe["nome"] for a in assegnazioni):
                warnings.append(
                    f"Class '{classe['nome']}' has no assignments"
                )

        # Check if any subject is unused
        for materia in materie:
            if not any(a["materia_nome"] == materia["nome"] for a in assegnazioni):
                warnings.append(
                    f"Subject '{materia['nome']}' is not assigned to any class"
                )

        for w in warnings:
            logger.warning(f"Validation warning: {w}")

        if errors:
            for e in errors:
                logger.error(f"Validation error: {e}")
            return False, errors

        logger.info("Data validation passed")
        return True, []

    @staticmethod
    def validate_docente(docente: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate single docente for correction."""
        nome = docente.get("nome", "").strip()
        if not nome:
            return False, "nome is required"

        tipo = docente.get("tipo", "").strip().upper()
        if tipo not in ["ASSUNTO", "CONTRATTO"]:
            return False, f"tipo must be ASSUNTO or CONTRATTO, got {tipo}"

        email = (docente.get("email") or "").strip()
        if email and "@" not in email:
            return False, f"invalid email format: {email}"

        return True, ""

    @staticmethod
    def validate_classe(classe: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate single classe for correction."""
        nome = classe.get("nome", "").strip()
        if not nome:
            return False, "nome is required"

        n_studenti = classe.get("n_studenti", 0)
        try:
            int(n_studenti)
        except (ValueError, TypeError):
            return False, f"n_studenti must be integer, got {n_studenti}"

        return True, ""

    @staticmethod
    def validate_materia(materia: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate single materia for correction."""
        nome = materia.get("nome", "").strip()
        if not nome:
            return False, "nome is required"

        tipo = materia.get("tipo", "").strip().upper()
        if tipo not in ["TEORIA", "PRATICA"]:
            return False, f"tipo must be TEORIA or PRATICA, got {tipo}"

        peso = materia.get("peso_cognitivo", "").strip().upper()
        if peso not in ["ALTO", "MEDIO", "BASSO"]:
            return False, f"peso_cognitivo must be ALTO/MEDIO/BASSO, got {peso}"

        return True, ""
