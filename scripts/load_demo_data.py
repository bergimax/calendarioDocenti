"""
Load a small synthetic school into a running stack and generate one timetable, so the
UI and the observability dashboards have something to show. No real data involved.

Usage: python scripts/load_demo_data.py [base_url] [email] [password]
       (defaults: http://localhost:8080 admin@example.com admin1234; `make demo-data`)
"""

import sys
from datetime import date, timedelta

import httpx


def next_monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def main(base: str = "http://localhost:8080", email: str = "admin@example.com", password: str = "admin1234") -> None:
    week = next_monday(date.today())
    calendar = "data,ore_max_giornata,flag_chiusura,stage_classe_id\n" + "".join(
        f"{week + timedelta(days=d)},6,false,\n" for d in range(5)
    )
    data = {
        "docenti": "nome,email,tipo\nProf Alfa,alfa@example.com,ASSUNTO\nProf Beta,beta@example.com,ASSUNTO\n",
        "classi": "nome,n_studenti\n1A,20\n1B,22\n",
        "materie": "nome,tipo,peso_cognitivo\nMatematica,TEORIA,ALTO\nLab,PRATICA,MEDIO\n",
        "assegnazioni": (
            "docente_nome,classe_nome,materia_nome,ore_anno\n"
            "Prof Alfa,1A,Matematica,300\nProf Alfa,1B,Matematica,300\n"
            "Prof Beta,1A,Lab,300\nProf Beta,1B,Lab,300\n"
        ),
        "accoppiamenti": "classe_a,classe_b,materia_nome,note\n1A,1B,Matematica,congiunta\n",
        "calendario": calendar,
    }
    with httpx.Client(base_url=base, timeout=120) as c:
        token = c.post("/api/auth/login", json={"email": email, "password": password}).raise_for_status().json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        v = c.post("/api/setup/validate", json=data).raise_for_status().json()
        assert v["can_proceed"], v
        c.post("/api/setup/save", json={
            "file_ids": [], "school_name": "Scuola Demo", "school_year": f"{week.year}-{week.year + 1}",
            "data_inizio": f"{week.year}-01-01", "data_fine": f"{week.year + 1}-06-30",
        }).raise_for_status()
        r = c.post("/api/schedule/generate", json={"week_start": str(week)}).raise_for_status().json()
        print(f"week {week}: status={r['status']} quality={r.get('quality_level')} slots={len(r.get('slots', []))}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
